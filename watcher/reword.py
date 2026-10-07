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

Rewrite EVERY paragraph so the video stays VERY similar - same story, same beats, same order, same hook idea, roughly
the same length (±15%), same tone ({T['style']}) - but is clearly reworded: other phrasing, other sentence structure,
other filler words. No sentence may stay word for word. Keep it natural spoken {T['lang_name']}.
Rules:
- Keep every token ⟦n⟧...⟦/n⟧ exactly as it is (same number, same text inside) and in the same order and paragraph.
- Keep **bold** lines bold (they are on-screen texts); keep X and Y (the scores creators read from the app).
- Keep "Parakeet AI" and parakeet-ai.com/resume-maker as they are. Never mention JobStep.
- No promises nobody can guarantee (e.g. "you will definitely get the job") - say "better chances" instead.

{('A reviewer found these problems - fix them: ' + feedback) if feedback else ''}

Paragraphs:
{numbered}

Return JSON {{"paragraphs": ["<reworded paragraph 0>", "<reworded paragraph 1>", ...]}} with exactly {len(enc)} items."""
    why = ''
    for attempt in range(3):
        extra = f'\n\nYour previous attempt was rejected: {why}. Fix exactly that.' if why else ''
        r = llm.chat_json(model, 'You are a senior UGC script writer. Reply with JSON only.', prompt + extra, timeout=1200)
        why, changes = _validate(enc, r.get('paragraphs', []))
        if not why:
            return 'ok', '', changes
    return 'skipped', why, []


def _validate(enc, new):
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
            ref = localize.example_text(src['url']) if src and src.get('url') else (originals or {}).get(f['id'], '')
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
