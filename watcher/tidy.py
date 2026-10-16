"""Page tidy (user's request, 13 Oct 2026): every live format page follows the same simple rules, checked by verify and
fixed on every normal run (mode tidy does it at once). Nothing is reworded - only these mechanical things:

1. Link cues: at most ONE cue of a kind per paragraph (consecutive sentences of the same app moment share it) and at
   most MAX_CUES Parakeet AI cues per script. Scripts had up to 15 - unreadable while filming. The renderer
   (pages.script_paragraphs) uses the same rule, so new scripts are born that way.
2. The on-screen text named in the visual hook is the 📲 title. A quoted text in the hook that is neither the title
   nor a line of the script is replaced by the title (creators saw two different texts).
3. The 📲 title is bold.
4. The idea name is the title (names drifted from the content, e.g. "Carrefour…" when the script never says it).
5. Reported only: a sub-page above the page content (e.g. a stray copy of the Visual Hook Lab).
"""
import re

from . import pages, reword

MAX_CUES = 3
QUOTE_RE = re.compile(r'«\s*([^»]+?)\s*»|»\s*([^«]+?)\s*«|“([^”]+)”|„([^“”]+)[“”]|"([^"]+)"')  # »…« = Slovenian


def _url(x):
    return ((x.get('text') or {}).get('link') or {}).get('url') or ''


def _content(x):
    return x.get('text', {}).get('content', x.get('plain_text', ''))


def trim_cues(paragraphs, links):
    """paragraphs: lists of rich-text items. Keeps the first cue of each kind per paragraph and at most MAX_CUES
    Parakeet AI cues overall; a removed cue takes its brackets with it. Returns (new paragraphs, removed count)."""
    kinds = {links['parakeet']: 'parakeet', links['linkedin']: 'linkedin'}
    total, removed, out = 0, 0, []
    for items in paragraphs:
        items = [dict(x, text=dict(x.get('text') or {'content': x.get('plain_text', '')})) for x in items]
        seen, keep = set(), []
        for i, x in enumerate(items):
            kind = kinds.get(_url(x))
            if not kind:
                keep.append(x)
                continue
            if kind not in seen and (kind != 'parakeet' or total < MAX_CUES):
                seen.add(kind)
                total += kind == 'parakeet'
                keep.append(x)
                continue
            removed += 1  # drop the label and its "(" before / ") " after
            if keep and _content(keep[-1]).rstrip().endswith('('):
                t = _content(keep[-1]).rstrip()[:-1]
                keep[-1]['text']['content'] = t
            if i + 1 < len(items):
                nxt = items[i + 1]
                nxt['text']['content'] = re.sub(r'^\)\s?', '', _content(nxt))
        keep = [x for x in keep if _content(x) or _url(x)]
        if keep and not _url(keep[0]):
            keep[0]['text']['content'] = _content(keep[0]).lstrip()
        out.append(keep)
    return out, removed


def _norm(t):
    return ' '.join(re.findall(r'\w+', (t or '').lower()))


def hook_fixes(hook_text, title, script_text):
    """[(quoted text, replacement)] for on-screen texts in the hook that are neither the title nor a script line."""
    fixes = []
    for m in QUOTE_RE.finditer(hook_text or ''):
        q = next(g for g in m.groups() if g)
        nq = _norm(q)
        if not nq or nq == _norm(title) or nq in _norm(script_text):
            continue
        fixes.append((q, title))
    return fixes


def _rich_payload(items):
    return [{'type': 'text', 'text': {'content': _content(x), 'link': ({'url': _url(x)} if _url(x) else None)},
             'annotations': x.get('annotations', {})} for x in items if _content(x)]


def page_name(page_id):
    p = pages.api('GET', f'/pages/{page_id}')
    return ''.join(x['plain_text'] for x in next(v for v in p['properties'].values() if v['type'] == 'title')['title'])


def wanted_name(current, title):
    m = re.match(r'^(\d+)\.\s*', current or '')
    return (f'{m.group(1)}. ' if m else '') + title


def problems(page_id, links):
    """What tidy would change on this page (verify uses it read-only)."""
    return tidy_page(page_id, links, write=False)


@pages.one_save(0)
def tidy_page(page_id, links, write=True):
    """Applies the rules above to one page. Returns the list of changes (or, with write=False, of problems)."""
    from .crosscheck import _title_block
    from .verify import layout_problems
    changes = []
    if pages.is_hand(page_id):  # edited by hand in Megasheet: the user's version stays as it is
        return changes
    script = reword.script_blocks(page_id)
    blocks = pages.children(page_id)
    if layout_problems(blocks, script, links):  # old hand-written page: its "title" may be any bold line - rebuilt, not tidied
        return ['old layout - not tidied (rebuilt from its example video: mode standardize)']
    paras = [b[b['type']].get('rich_text', []) for b in script]
    trimmed, removed = trim_cues(paras, links)
    if removed:
        changes.append(f'{removed} extra link cues')
        if write:
            for b, items in zip(script, trimmed):
                if [_content(x) for x in items] != [x.get('plain_text', '') for x in b[b['type']].get('rich_text', [])]:
                    pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': _rich_payload(items)}})
    tb = _title_block(page_id)
    title = reword._plain(tb).strip() if tb else ''
    if not title:
        return changes
    if not all((x.get('annotations') or {}).get('bold') for x in tb['paragraph']['rich_text'] if _content(x).strip()):
        changes.append('title not bold')
        if write:
            pages.api('PATCH', f"/blocks/{tb['id']}", {'paragraph': {'rich_text': [pages.rt(title, bold=True)]}})
    script_text = ' '.join(reword._plain(b) for b in script)
    for b in reword.direction_blocks(page_id):
        fixes = hook_fixes(reword._plain(b), title, script_text)
        if not fixes:
            continue
        changes += [f'hook names «{q[:40]}» instead of the title' for q, _ in fixes]
        if write:
            items = b[b['type']].get('rich_text', [])
            for x in items:
                for q, new in fixes:
                    x.setdefault('text', {'content': x.get('plain_text', '')})
                    x['text']['content'] = _content(x).replace(q, new)
            pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': _rich_payload(items)}})
    first_heading = next((k for k, b in enumerate(blocks) if b['type'].startswith('heading')), len(blocks))
    if any(b['type'] == 'child_page' for b in blocks[:first_heading]):
        changes.append('a sub-page sits at the top of the page (move it away by hand - sub-pages are never moved '
                       'automatically)')
    name = page_name(page_id)
    want = wanted_name(name, title)
    if name.strip() != want.strip():
        changes.append(f'page name "{name[:40]}" is not the title')
        if write:
            pages.api('PATCH', f'/pages/{page_id}', {'properties': {'title': {'title': [pages.rt(want)]}}})
    return changes


def run(fmts, mkts, cfg, page_of, write=True):
    """Every live page of every running market. Returns [(format title, market, changes)]."""
    report = []
    from .markets import for_format
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in for_format(mkts, f):  # not a market's off-list pages (lineup off_markets)
            pid = page_of(f, mk['key'])
            if not pid:
                continue
            try:
                ch = tidy_page(pid, cfg['links'], write=write)
            except Exception as e:
                ch = [f'error: {str(e)[:120]}']
            if ch:
                report.append((f['title'], mk['key'], ch))
    return report
