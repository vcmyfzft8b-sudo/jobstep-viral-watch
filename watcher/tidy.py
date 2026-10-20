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
6. Markets with demo recordings (watcher/demo.py, Slovenia): the script's only app cue is ONE plain "(🎥 …)" recording
   cue where the app first appears (the Parakeet AI cues go; the app link and the page's Drive folder are resources -
   links in a script are not clickable for creators).
"""
import re

from . import demo, pages, reword

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
            _drop_cue(keep, items, i)
        keep = [x for x in keep if _content(x) or _url(x)]
        if keep and not _url(keep[0]):
            keep[0]['text']['content'] = _content(keep[0]).lstrip()
        out.append(keep)
    return out, removed


def _drop_cue(keep, items, i):
    """A removed cue at items[i] takes its brackets with it ('(' at the end of the kept text before, ')' after)."""
    if keep and _content(keep[-1]).rstrip().endswith('('):
        keep[-1]['text']['content'] = _content(keep[-1]).rstrip()[:-1]
    if i + 1 < len(items):
        nxt = items[i + 1]
        nxt['text']['content'] = re.sub(r'^\)\s?', '', _content(nxt))


DEMO_CUE_RE = re.compile(r'\(\s*🎥[^()]*\)\s?')  # the plain-text demo cue (its link sits in the resources)


def _first_app(paragraphs, links):
    return next(((j, i) for j, items in enumerate(paragraphs) for i, x in enumerate(items)
                 if _url(x) == links['parakeet']), None)


def _demo_ok(paragraphs, links, cue):
    """The script holds exactly one cue: the plain recording cue (this text). No app link cues and no linked demo cue
    (user, 20 Oct 2026: "play the recording from here only once per video, just the recording")."""
    if any(_url(x) == links['parakeet'] or demo.is_demo_url(_url(x)) or ('🎥' in _content(x) and _url(x))
           for p in paragraphs for x in p):
        return False
    found = [m for p in paragraphs for x in p if not _url(x) for m in DEMO_CUE_RE.findall(_content(x))]
    return len(found) == 1 and found[0].strip() == cue


def place_demo(paragraphs, links, cue):
    """paragraphs with exactly one plain recording cue, where the app first appears (the first Parakeet AI cue, else
    where a recording cue already stands), and no Parakeet AI cues: the app link is in the resources, the creator plays
    the recording from that one point. Script links are not clickable for creators (user, 19 Oct 2026). Returns
    (paragraphs, changed). Neither cue in the script -> unchanged (verify reports it)."""
    if _demo_ok(paragraphs, links, cue):
        return paragraphs, False
    out, anchor = [], None
    for j, items in enumerate(paragraphs):  # every app cue and old recording cue out; the first one's place is kept
        items = [dict(x, text=dict(x.get('text') or {'content': x.get('plain_text', '')})) for x in items]
        keep = []
        for i, x in enumerate(items):
            app = _url(x) == links['parakeet']
            if app or demo.is_demo_url(_url(x)) or ('🎥' in _content(x) and _url(x)):
                _drop_cue(keep, items, i)
                if anchor is None and (app or '🎥' in _content(x)):
                    anchor = (j, len(keep))
                continue
            if not _url(x) and DEMO_CUE_RE.search(_content(x)):
                if anchor is None:  # an earlier plain recording cue: the recording starts here
                    t = _content(x)
                    m = DEMO_CUE_RE.search(t)
                    x['text']['content'] = t[:m.start()]
                    keep.append(x)
                    anchor = (j, len(keep))
                    keep.append(dict(x, text=dict(x['text'], content=t[m.end():])))
                    keep[-1]['text']['content'] = re.sub(r' {2,}', ' ', DEMO_CUE_RE.sub('', keep[-1]['text']['content']))
                    continue
                x['text']['content'] = re.sub(r' {2,}', ' ', DEMO_CUE_RE.sub('', _content(x)))
            keep.append(x)
        out.append(keep)
    if anchor is None:
        return paragraphs, False
    j, k = anchor
    out[j].insert(k, pages.rt(cue + ' '))
    out = [[x for x in items if _content(x) or _url(x)] for items in out]
    # no double spaces and no space at the start of a paragraph around the cue
    for items in out:
        for x in items:
            x['text']['content'] = re.sub(r' {2,}', ' ', _content(x))
        if items and not _url(items[0]):
            items[0]['text']['content'] = _content(items[0]).lstrip()
    return out, True


def resources_block(blocks):
    """The callout of the 🔧 resources section (its links are the idea's resources in Megasheet)."""
    inside = False
    for b in blocks:
        if b['type'].startswith('heading'):
            inside = '🔧' in reword._plain(b)
            continue
        if inside and b['type'] == 'callout':
            return b
    return None


def place_demo_resource(rich, links, label, url):
    """The resources callout's rich text with exactly one demo link (label, url) right after the Parakeet AI link (else
    after the last link before any text line). Returns (rich, changed)."""
    demos = [x for x in rich if demo.is_demo_url(_url(x))]
    if len(demos) == 1 and _url(demos[0]) == url and _content(demos[0]).strip() == label:
        return rich, False
    items = [dict(x, text=dict(x.get('text') or {'content': x.get('plain_text', '')})) for x in rich]
    keep = []
    for i, x in enumerate(items):
        if demo.is_demo_url(_url(x)):
            if keep and _content(keep[-1]) == '\n':
                keep.pop()
            elif not keep and i + 1 < len(items) and _content(items[i + 1]) == '\n':
                items[i + 1]['text']['content'] = ''
            continue
        keep.append(x)
    keep = [x for x in keep if _content(x)]
    at = next((i + 1 for i, x in enumerate(keep) if _url(x) == links['parakeet']), None)
    if at is None:
        at = 0
        while at < len(keep) and (_url(keep[at]) or _content(keep[at]) == '\n'):
            at += 1
        while at and _content(keep[at - 1]) == '\n':
            at -= 1
    add = ([pages.rt('\n')] if at else []) + [pages.rt(label, link=url)] + ([pages.rt('\n')] if not at and keep else [])
    return keep[:at] + add + keep[at:], True


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


def problems(page_id, links, fmt_id=None):
    """What tidy would change on this page (verify uses it read-only)."""
    return tidy_page(page_id, links, write=False, fmt_id=fmt_id)


@pages.one_save(0)
def tidy_page(page_id, links, write=True, fmt_id=None):
    """Applies the rules above to one page. Returns the list of changes (or, with write=False, of problems).
    fmt_id: the page's format (finds its demo folder when the idea is not in demo/drive_folders.json)."""
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
    cue, moved = demo.cue_for(page_id, fmt_id), False
    if cue and cue['url']:
        trimmed, moved = place_demo(trimmed, links, cue['cue'])
        if moved:
            changes.append('demo recording cue missing or not at the first app moment')
        res = resources_block(blocks)
        if res:
            rich, res_moved = place_demo_resource(res['callout'].get('rich_text', []), links, cue['res'], cue['url'])
            if res_moved:
                changes.append('demo recording folder missing in the resources')
                if write:
                    pages.api('PATCH', f"/blocks/{res['id']}", {'callout': {'rich_text': _rich_payload(rich)}})
    elif cue and not write:
        changes.append('no demo recording folder for this page (demo/drive_folders.json - run demo/drive_sync.py)')
    if write and (removed or moved):
        for b, items in zip(script, trimmed):
            if [(_content(x), _url(x)) for x in items] != [(x.get('plain_text', ''), _url(x))
                                                            for x in b[b['type']].get('rich_text', [])]:
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
                ch = tidy_page(pid, cfg['links'], write=write, fmt_id=f['id'])
            except Exception as e:
                ch = [f'error: {str(e)[:120]}']
            if ch:
                report.append((f['title'], mk['key'], ch))
    return report
