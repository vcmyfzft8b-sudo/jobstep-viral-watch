"""Script-section helpers (blocks, link tokens, spoken text) and the short visual hook section.

Rewording is OFF since 2026-10-10: scripts are the example video's own words (align.align_page transcribes them).
reword_page is kept as a no-op so old callers do nothing.

Link cues travel as numbered tokens ⟦n⟧label⟦/n⟧ (encode/decode). The old text of every changed block is kept in
state/script_backup.json, so a page can be restored.
"""
import json
import re

from . import llm, pages, state
from .brands import SOURCE_RE
from .markets import TEXT

TOKEN = re.compile(r'⟦(\d+)⟧(.*?)⟦/\1⟧', re.S)


def _plain(b):
    return ''.join(x.get('plain_text', '') for x in b[b['type']].get('rich_text', []))


def script_blocks(page_id):
    """The blocks of the page's script section (between the 💬 heading and the next divider/heading)."""
    blocks = pages.children(page_id)
    start = next((i for i, b in enumerate(blocks) if b['type'].startswith('heading') and
                  re.search(r'💬|SKRIPT|SCRIPT|GUION|SCENARIJ', _plain(b), re.I)), None)
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
    return 'skipped', 'rewording is off - scripts are transcribed from the example video', []


def _validate(enc, new, original=''):
    if len(new) != len(enc):
        return f'returned {len(new)} paragraphs instead of {len(enc)}', []
    changes = []
    for i, ((b, old, links), text) in enumerate(zip(enc, new)):
        if [m.group(1) for m in TOKEN.finditer(old)] != [m.group(1) for m in TOKEN.finditer(text)]:
            return f'paragraph {i}: the link tokens must stay exactly the same and in the same order', []
        if SOURCE_RE.search(text):
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
    with state.LOCK:  # backup first (so the original text is never lost), then write to Megasheet
        backup = state.load('script_backup.json', {})
        for b, old, text, links in changes:
            backup.setdefault(b['id'], b[b['type']]['rich_text'])
        state.save('script_backup.json', backup)
    for b, old, text, links in changes:
        pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': decode(text, links)}})


def direction_blocks(page_id):
    """Blocks of the 🎬 filming-directions section (without the mandatory 🚨 line and the Visual Hook Lab link)."""
    blocks = pages.children(page_id)
    out, inside = [], False
    for b in blocks:  # 🎬 = directions; older German pages also keep them under 👀 VISUELLER EINSTIEG
        if b['type'].startswith('heading'):
            inside = '🎬' in _plain(b) or '👀' in _plain(b)
            continue
        if b['type'] == 'divider':
            inside = False
            continue
        t = _plain(b)
        has_link = any(((x.get('text') or {}).get('link') or {}).get('url', '').startswith(('http', '/')) and
                       'parakeet-ai.com' not in ((x.get('text') or {}).get('link') or {}).get('url', '')
                       for x in b.get(b['type'], {}).get('rich_text', []))
        # the Visual Hook Lab / example TikTok links are never directions; a plain line that only MENTIONS the lab is one
        # ('/<page id>' = a Notion link inside the workspace, e.g. the Visual Hook Lab on the copied Slovenian pages)
        if inside and b['type'] in ('paragraph', 'bulleted_list_item') and t.strip() and '🚨' not in t and not has_link:
            out.append(b)
    return out


@pages.one_save(1)
def fix_directions(fmt, page_id, lang, model, issues=''):
    """Shrink the 🎬 section to the short visual hook: ONE line of 1-2 sentences (copy what the example video does in
    its first seconds, or pick a hook from the Visual Hook Lab), followed by the 🚨 line and the Visual Hook Lab link.
    All other direction lines are removed (backed up first). Returns (status, why)."""
    from .builder import VISUAL_HOOK
    T = TEXT[lang]
    enc = [(b, *encode(b)) for b in direction_blocks(page_id)]
    enc = [(b, t, l) for b, t, l in enc if t is not None]
    if not enc:
        return 'skipped', 'no directions found'
    from . import crosscheck
    filming = (crosscheck.reference(fmt['id']) or {}).get('filming', '')
    lines = '\n'.join(re.sub(r'⟦/?\d+⟧', '', t) for _, t, _ in enc)
    prompt = f"""These are the filming directions ({T['lang_name']}) of a UGC format page ("{fmt.get('title', '')}").
They are far too long. Keep only the visual hook, written as {VISUAL_HOOK}
CURRENT DIRECTIONS:
{lines[:3000]}
{('How the example video is filmed: ' + filming) if filming else ''}
{('A reviewer found: ' + issues) if issues else ''}
Write it in {T['lang_name']}, address the creator informally ({ {'de': 'du', 'fr': 'tu', 'es': 'tú', 'sl': 'ti'}[lang] }), no links,
no X/Y scores, nothing about filming the app (the script's links already say that).
Return JSON {{"hook": "<1-2 short sentences>"}}"""
    from .builder import sentences
    why = ''
    for _ in range(3):
        extra = f'\n\nYour previous answer was rejected: {why}. Fix exactly that.' if why else ''
        r = llm.chat_json(model, 'You are a precise editor of creator instructions. Reply with JSON only.', prompt + extra,
                          timeout=900)
        hook = str(r.get('hook') or '').strip().replace('⟦', '').replace('⟧', '')
        n = sentences(hook)
        why = ('empty' if not hook else f'it has {n} sentences, at most 2 are allowed' if n > 2
               else 'it names JobStep - never mention it' if SOURCE_RE.search(hook) else '')
        if not why:
            break
    else:
        return 'skipped', f'no usable short hook ({why}): {hook[:120]}'
    if len(enc) == 1 and enc[0][1] == hook:
        return 'ok', 'unchanged'
    with state.LOCK:
        backup = state.load('script_backup.json', {})
        for b, _, _ in enc:
            backup.setdefault(b['id'], b[b['type']]['rich_text'])
        state.save('script_backup.json', backup)
    first = enc[0][0]
    pages.api('PATCH', f"/blocks/{first['id']}", {first['type']: {'rich_text': [pages.rt(hook)]}})
    for b, _, _ in enc[1:]:
        pages.api('DELETE', f"/blocks/{b['id']}")
    return 'ok', ''


def resources_text(page_id):
    """Plain text of the page's 🔧 resources section (what a '📎 … – see resources' cue may point to)."""
    out, inside = [], False
    for b in pages.children(page_id):
        if b['type'].startswith('heading'):
            inside = '🔧' in _plain(b)
            continue
        if inside and b['type'] != 'divider':
            out.append(_plain(b))
            if b.get('has_children'):  # e.g. the Gmail link sits inside the resources callout
                out += [_plain(c) for c in pages.children(b['id']) if c.get(c['type'], {}).get('rich_text') is not None]
    return ' '.join(out).lower()


def in_resources(name, resources):
    """True if the asset is really in the resources section (e.g. 'Gmail inbox' -> 'Gmail recording')."""
    words = [w for w in re.findall(r'\w+', (name or '').lower()) if len(w) >= 4]
    return any(w in resources for w in words)


@pages.one_save(0)
def fix_asset_cues(page_id):
    """Repairs script cues: decorated more than once ('📎 📎 📎 … – ver Recursos – ver Recursos'), or pointing to the
    resources section for something that is not there (then the cue is removed - scripts have no stage directions)."""
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
                name = pages.asset_label(m.group(1))
                if resources is None:
                    resources = resources_text(page_id)
                if not in_resources(name, resources):
                    clean = ''  # nothing in the resources to point to -> no cue (brands.NO_DIRECTIONS)
                elif m.group(1).count('📎') > 1:
                    clean = TEXT[lang]['asset_cue'].format(name=name).strip()
                else:
                    continue
                t = re.sub(r' {2,}', ' ', t.replace(m.group(0), clean))
                changed = True
            x['text']['content'] = t
        if changed:
            pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': [
                {'type': 'text', 'text': x['text'], 'annotations': x.get('annotations', {})} for x in rich if x.get('text')]}})
            fixed += 1
    return fixed


def directions_left(page_id):
    """Bracketed stage directions / acting tips still in the script (not a link cue, not a 📎 material cue)."""
    found = []
    for b in script_blocks(page_id):
        for x in b[b['type']].get('rich_text', []):
            if x.get('type') == 'text' and not ((x.get('text') or {}).get('link') or {}).get('url'):
                found += [m.group(0).strip() for m in pages.DIRECTION_RE.finditer(x.get('plain_text', ''))]
    return found


@pages.one_save(0)
def strip_directions(page_id):
    """Removes bracketed stage directions / acting tips from the script (user's decision, 11 Oct 2026): only the link
    cues (Parakeet AI, LinkedIn) and 📎 material cues stay in brackets. The old text is backed up first; a paragraph
    that was only a direction is deleted. Returns how many paragraphs changed."""
    changed = 0
    for b in script_blocks(page_id):
        rich, out, touched = b[b['type']].get('rich_text', []), [], False
        for x in rich:
            if x.get('type') == 'text' and not ((x.get('text') or {}).get('link') or {}).get('url'):
                t = x.get('plain_text', '')
                new = re.sub(r' {2,}', ' ', pages.DIRECTION_RE.sub('', t))
                if new != t:
                    touched = True
                if new:
                    out.append({'type': 'text', 'text': {'content': new}, 'annotations': x.get('annotations', {})})
            elif x.get('type') == 'text':
                out.append({'type': 'text', 'text': {'content': x['plain_text'], 'link': x['text']['link']},
                            'annotations': x.get('annotations', {})})
            else:
                out.append({k: v for k, v in x.items() if k in ('type', 'mention', 'equation', 'annotations')})
        if not touched:
            continue
        with state.LOCK:
            backup = state.load('script_backup.json', {})
            backup.setdefault('directions:' + b['id'], rich)
            state.save('script_backup.json', backup)
        if out and out[0]['type'] == 'text':
            out[0]['text']['content'] = out[0]['text']['content'].lstrip()
        if not ''.join(o.get('text', {}).get('content', '') for o in out).strip():
            pages.api('DELETE', f"/blocks/{b['id']}")  # the paragraph was only a direction
        else:
            pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': out}})
        changed += 1
    return changed


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


def shorten_hooks(fmts, mkts, cfg, page_of):
    """Every active page whose 🎬 section still has more than one direction line gets the short visual hook.
    Pages that already have one line are not touched (no Claude call). Returns [(title, market, status, why)]."""
    out = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in mkts:
            pid = page_of(f, mk['key'])
            if not pid:
                continue
            try:
                n = len(direction_blocks(pid))
                st, why = fix_directions(f, pid, mk['lang'], cfg['models']['classify']) if n > 1 else ('ok', 'already short')
            except Exception as e:
                st, why = 'error', str(e)[:150]
            print(f"{f['title'][:45]} | {mk['key']} | {st} | {why}", flush=True)
            out.append((f['title'], mk['key'], st, why))
    return out
