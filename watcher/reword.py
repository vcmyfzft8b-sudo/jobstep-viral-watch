"""Reword the scripts on the existing format pages: very similar to the JobStep original (same beats, same order,
same length, same hook idea), but not a 1:1 transcription / literal translation.

Only the script section of a page changes (from the 💬 heading to the next divider/heading). Every link cue in it
(Parakeet AI, LinkedIn, Gmail, ...) and every bold on-screen line stays where it is: the text is sent to Claude with
the links as numbered tokens, and a reworded paragraph is only written back if all tokens come back unchanged and
in the same order and the length stays within ±20%. The old text of every changed block is kept in
state/script_backup.json, so a page can be restored.
"""
import json
import re

from . import llm, notion, state
from .markets import TEXT

TOKEN = re.compile(r'⟦(\d+)⟧(.*?)⟦/\1⟧', re.S)


def _plain(b):
    return ''.join(x.get('plain_text', '') for x in b[b['type']].get('rich_text', []))


def script_blocks(page_id):
    """The blocks of the page's script section (between the 💬 heading and the next divider/heading)."""
    blocks = notion.children(page_id)
    start = next((i for i, b in enumerate(blocks) if b['type'].startswith('heading') and
                  re.search(r'💬|SKRIPT|SCRIPT|GUION', _plain(b), re.I)), None)
    if start is None:
        return []
    out = []
    for b in blocks[start + 1:]:
        if b['type'] == 'divider' or b['type'].startswith('heading'):
            break
        if b['type'] in ('paragraph', 'bulleted_list_item', 'numbered_list_item', 'quote') and _plain(b).strip():
            out.append(b)
    return out


def encode(b):
    """Block text with links as ⟦n⟧label⟦/n⟧ tokens and bold as **...**; None if it has things we must not touch."""
    parts, links = [], []
    for x in b[b['type']].get('rich_text', []):
        if x['type'] != 'text':
            return None, None
        t = x['plain_text']
        link = ((x.get('text') or {}).get('link') or {}).get('url')
        if link:
            links.append((link, t, x.get('annotations', {})))
            parts.append(f'⟦{len(links)}⟧{t}⟦/{len(links)}⟧')
        elif x.get('annotations', {}).get('bold') and t.strip():
            parts.append(f'**{t}**')
        else:
            parts.append(t)
    return ''.join(parts), links


def decode(text, links):
    rich, pos = [], 0
    def plain(seg):
        for k, piece in enumerate(re.split(r'\*\*', seg)):
            if piece:
                rich.append({'type': 'text', 'text': {'content': piece}, 'annotations': {'bold': k % 2 == 1}})
    for m in TOKEN.finditer(text):
        plain(text[pos:m.start()])
        url, label, ann = links[int(m.group(1)) - 1]
        rich.append({'type': 'text', 'text': {'content': label, 'link': {'url': url}}, 'annotations': ann})
        pos = m.end()
    plain(text[pos:])
    return rich


def reword_page(fmt, page_id, lang, model, original='', feedback=''):
    from . import align
    if align.approved_script(fmt['id'], lang):
        return 'skipped', 'approved script is locked', []
    if not original:
        return 'skipped', 'source evidence required for sentence-aligned rewrite', []
    blocks = script_blocks(page_id)
    enc = [(b, *encode(b)) for b in blocks]
    enc = [(b, t, l) for b, t, l in enc if t is not None]
    if not enc:
        return 'skipped', 'no script section found', []
    T = TEXT[lang]
    numbered = '\n'.join(f'{i}: {t}' for i, (_, t, _) in enumerate(enc))
    prompt = f"""This is the {T['lang_name']} script of a UGC video format ("{fmt['title']}") for Parakeet AI, an AI CV
maker. It was adapted from a viral JobStep video and is currently almost a 1:1 transcription/translation of it.
{('The example video on the page (use it as the reference for the beats - do NOT copy its wording): ' + original[:2500]) if original else ''}

Rewrite EVERY paragraph with exactly one adapted sentence per original sentence, in the same order. Keep the same
story, beats, meaning, hook idea and tone ({T['style']}); add no story beats, examples, filler or CTA. Change each
sentence's wording and structure naturally, without merging or splitting source sentences. The whole script must
be at most 110% of the original word count. Only the hook line may stay close. A native viewer who saw the JobStep
video must NOT recognise its sentences. Keep it natural spoken {T['lang_name']}.
Rules:
- Keep every token ⟦n⟧...⟦/n⟧ exactly as it is (same number, same text inside) and in the same order and paragraph.
- Keep **bold** lines bold (they are on-screen texts). Scores/percentages the app shows are ALWAYS X (before) and Y
  (after) - replace any concrete number like "64 %" or "40 sobre 100" with X or Y.
- Address the viewer consistently as { {'de': 'du', 'fr': 'tu', 'es': 'tú (never vosotros)'}[lang] }. No backticks.
- Mirror the ORIGINAL's spoken brand mentions exactly in count and story position: replace JobStep with Parakeet
  AI, and its spoken URL with parakeet-ai.com/resume-maker, only where present in the source. Zero spoken brand
  mentions in the original means zero in ours. Linked cue labels are filming directions, not spoken words. For
  silent videos compare on-screen text instead. Never add a CTA or website absent from the original.
- The spoken/on-screen script must not exceed 110% of the original word count. Never mention JobStep.
- No promises nobody can guarantee (e.g. "you will definitely get the job") - say "better chances" instead.

{('A reviewer found these problems - fix them: ' + feedback) if feedback else ''}

Paragraphs:
{numbered}

Return JSON {{"paragraphs": ["<reworded paragraph 0>", "<reworded paragraph 1>", ...]}} with exactly {len(enc)} items."""
    why = ''
    for attempt in range(3):
        extra = f'\n\nYour previous attempt was rejected: {why}. Fix exactly that.' if why else ''
        r = llm.chat_json(model, 'You are a senior UGC script writer. Reply with JSON only.', prompt + extra, timeout=1200)
        why, changes = _validate(enc, r.get('paragraphs', []), original)
        if not why:
            return 'ok', '', changes
    return 'skipped', why, []


def _validate(enc, new, original=''):
    if len(new) != len(enc):
        return f'returned {len(new)} paragraphs instead of {len(enc)}', []
    changes = []
    for i, ((b, old, links), text) in enumerate(zip(enc, new)):
        if [m.group(1) for m in TOKEN.finditer(old)] != [m.group(1) for m in TOKEN.finditer(text)]:
            return f'paragraph {i}: the link tokens must stay exactly the same and in the same order', []
        if re.search(r'job\s*-?\s*step', text, re.I):
            return f'paragraph {i}: JobStep appeared', []
        if len(old) > 60 and not 0.75 <= len(text) / len(old) <= 1.25:
            return f'paragraph {i}: length changed too much ({len(text)} vs {len(old)} characters)', []
        changes.append((b, old, text, links))
    if original:
        from . import align
        base = align.source_script(original)
        rendered = [{'type': b['type'], b['type']: {'rich_text': decode(text, links)}} for b, _, text, links in changes]
        spoken = spoken_text(rendered)
        if align._words(spoken) > 1.10 * align._words(base):
            return 'script exceeds 110% of the original word count', []
        want, have = len(align.JOBSTEP.findall(base)), len(re.findall(r'parakeet', spoken, re.I))
        if have != want:
            return f'spoken brand count is {have}; source requires {want}; cue labels do not count', []
    return '', changes


def apply(changes):
    with state.LOCK:  # backup first (so the original text is never lost), then write to Notion
        backup = state.load('script_backup.json', {})
        for b, old, text, links in changes:
            backup.setdefault(b['id'], b[b['type']]['rich_text'])
        state.save('script_backup.json', backup)
    for b, old, text, links in changes:
        notion.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': decode(text, links)}})


def run(fmts, mkts, cfg, page_of, originals=None, dry=False):
    """Returns [(format title, market, status, detail, changes)]."""
    import concurrent.futures as cf
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in mkts
            if page_of(f, mk['key']) and not (f.get('reworded') or {}).get(mk['key'])]

    def one(job):
        f, mk = job
        try:
            from . import localize
            pid = page_of(f, mk['key'])
            src = localize.current_source(pid)
            ref = localize.example_text(src.get('url') if src else None, page_id=pid) or (originals or {}).get(f['id'], '')
            status, why, changes = reword_page(f, pid, mk['lang'], cfg['models']['build'], ref)
            return f, mk, status, why, changes
        except Exception as e:
            return f, mk, 'error', str(e)[:150], []
    out = []
    with cf.ThreadPoolExecutor(3) as ex:
        for f, mk, status, why, changes in ex.map(one, jobs):
            if status == 'ok' and not dry:
                apply(changes)
                f.setdefault('reworded', {})[mk['key']] = True
            out.append((f['title'], mk['key'], status, why, changes))
    return out


def direction_blocks(page_id):
    """Blocks of the 🎬 filming-directions section (without the mandatory 🚨 line and the Visual Hook Lab link)."""
    blocks = notion.children(page_id)
    out, inside = [], False
    for b in blocks:  # 🎬 = directions; older German pages also keep them under 👀 VISUELLER EINSTIEG
        if b['type'].startswith('heading'):
            inside = '🎬' in _plain(b) or '👀' in _plain(b)
            continue
        if b['type'] == 'divider':
            inside = False
            continue
        t = _plain(b)
        has_link = any(((x.get('text') or {}).get('link') or {}).get('url', '').startswith('http') and
                       'parakeet-ai.com' not in ((x.get('text') or {}).get('link') or {}).get('url', '')
                       for x in b.get(b['type'], {}).get('rich_text', []))
        if inside and b['type'] in ('paragraph', 'bulleted_list_item') and t.strip() and '🚨' not in t \
                and 'Visual Hook Lab' not in t and not has_link:  # the example's TikTok link is never a direction
            out.append(b)
    return out


def fix_directions(fmt, page_id, lang, model, issues=''):
    """Rewrite the filming directions so they match the script: no duplicates, X/Y only as in the script, every quoted
    cue really in the script. Lines may be removed. Returns (status, why)."""
    T = TEXT[lang]
    script = '\n'.join(_plain(b) for b in script_blocks(page_id))
    from . import crosscheck
    filming = (crosscheck.reference(fmt['id']) or {}).get('filming', '')
    enc = [(b, *encode(b)) for b in direction_blocks(page_id)]
    enc = [(b, t, l) for b, t, l in enc if t is not None]
    if not enc:
        return 'skipped', 'no directions found'
    numbered = '\n'.join(f'{i}: {t}' for i, (_, t, _) in enumerate(enc))
    prompt = f"""These are the filming directions ({T['lang_name']}) of a UGC format page, and the script they belong to.
SCRIPT:
{script[:4000]}

DIRECTIONS:
{numbered}
{('How this format is filmed (reference, all countries): ' + filming) if filming else ''}
{('A reviewer found: ' + issues) if issues else ''}
Fix the directions so they match the script exactly: remove duplicate or contradicting lines; mention "X"/"Y" only
if they appear in the script (only X -> only X); a direction that quotes a script line must quote the script's
actual wording; never refer to markers the script does not have; keep everything else as it is (same language, same
tone). Keep tokens ⟦n⟧...⟦/n⟧ unchanged. If a shot of the reference filming sequence or something the reviewer
names is missing, add short new lines for it ("add", in {T['lang_name']}, no links) - only what the script needs.
Return JSON {{"lines": [{{"index": 0, "text": "<fixed line, or null to delete it>"}}, ...],
"add": ["<new direction line>", ...]}} - one item per existing line; "add" may be empty."""
    r = llm.chat_json(model, 'You are a precise editor of creator instructions. Reply with JSON only.', prompt, timeout=900)
    items = {int(x['index']): x.get('text') for x in r.get('lines', []) if str(x.get('index', '')).isdigit()}
    if set(items) != set(range(len(enc))):
        return 'skipped', 'directions answer incomplete'
    with state.LOCK:
        backup = state.load('script_backup.json', {})
        for b, _, _ in enc:
            backup.setdefault(b['id'], b[b['type']]['rich_text'])
        state.save('script_backup.json', backup)
    for i, (b, old, links) in enumerate(enc):
        new = items[i]
        if new is None or not str(new).strip():
            if links:
                continue  # a line with a link is never deleted
            notion.api('DELETE', f"/blocks/{b['id']}")
        elif new != old:
            if [m.group(1) for m in TOKEN.finditer(old)] != [m.group(1) for m in TOKEN.finditer(new)]:
                continue  # keep that line rather than lose a link
            notion.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': decode(new, links)}})
    add = [str(t).strip() for t in (r.get('add') or []) if str(t).strip() and '⟦' not in str(t)][:4]
    if add:
        notion.api('PATCH', f'/blocks/{page_id}/children', {'after': enc[-1][0]['id'], 'children': [
            {'object': 'block', 'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [notion.rt(t)]}}
            for t in add]})
    return 'ok', ''


def resources_text(page_id):
    """Plain text of the page's 🔧 resources section (what a '📎 … – see resources' cue may point to)."""
    out, inside = [], False
    for b in notion.children(page_id):
        if b['type'].startswith('heading'):
            inside = '🔧' in _plain(b)
            continue
        if inside and b['type'] != 'divider':
            out.append(_plain(b))
    return ' '.join(out).lower()


def in_resources(name, resources):
    """True if the asset is really in the resources section (e.g. 'Gmail inbox' -> 'Gmail recording')."""
    words = [w for w in re.findall(r'\w+', (name or '').lower()) if len(w) >= 4]
    return any(w in resources for w in words)


def fix_asset_cues(page_id):
    """Repairs script cues: decorated more than once ('📎 📎 📎 … – ver Recursos – ver Recursos'), or pointing to the
    resources section for something that is not there (then it is a plain stage direction '(InfoJobs)')."""
    suffixes = {l: TEXT[l]['asset_cue'].split('{name}')[1].strip(' )') for l in TEXT}
    resources = None
    fixed = 0
    for b in script_blocks(page_id):
        rich = b[b['type']].get('rich_text', [])
        changed = False
        for x in rich:
            if not x.get('text'):
                continue
            t = x['text'].get('content', '')
            for m in re.finditer(r'\((📎[^()]*)\)', t):
                lang = next((l for l, suf in suffixes.items() if suf in m.group(1)), None)
                if not lang:
                    continue
                name = notion.asset_label(m.group(1))
                if resources is None:
                    resources = resources_text(page_id)
                if not in_resources(name, resources):
                    clean = f'({name})'
                elif m.group(1).count('📎') > 1:
                    clean = TEXT[lang]['asset_cue'].format(name=name).strip()
                else:
                    continue
                t = t.replace(m.group(0), clean)
                changed = True
            x['text']['content'] = t
        if changed:
            notion.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': [
                {'type': 'text', 'text': x['text'], 'annotations': x.get('annotations', {})} for x in rich if x.get('text')]}})
            fixed += 1
    return fixed


def spoken_text(blocks):
    """What is actually said/shown as script text: without link labels, (cue) brackets and the silent label."""
    out = []
    for b in blocks:
        parts = []
        for x in b[b['type']].get('rich_text', []):
            if ((x.get('text') or {}).get('link') or {}).get('url'):
                continue  # cue link label
            parts.append(x.get('plain_text', x.get('text', {}).get('content', '')))
        t = re.sub(r'\([^)]*\)\s*', '', ''.join(parts))
        if any(t.strip().startswith(TEXT[l]['silent_label']) for l in TEXT):
            continue
        out.append(t)
    return '\n'.join(out)
