"""Read-only health check of the format pages in Megasheet (mode verify): prints one line per problem. Nothing is changed.

Per market:
- the list: its published ideas are exactly the live (active) formats' pages (Megasheet shows them in list order);
- every format page (live, waiting, archived): no bracketed stage directions / acting tips in the script (only the
  link cues and 📎 material cues - brands.NO_DIRECTIONS), and the ⚠️ note under the inspiration video has the current
  text;
- every live page also: example video, original TikTok link, script section with the Parakeet AI link, no JobStep in
  the script, visual hook section = one hook line (+ the 🚨 line and the Visual Hook Lab link), and the tidy rules
  (watcher/tidy.py: few link cues, hook names the title, bold title, page name = title).
"""
import re

from . import pages, reword
from .brands import SOURCE_RE, speaker_changed
from .markets import TEXT


def _plain(b):
    return ''.join(x.get('plain_text', '') for x in (b.get(b['type']) or {}).get('rich_text', []) or [])


def _title(page_id):
    p = pages.api('GET', f'/pages/{page_id}')
    return ''.join(x['plain_text'] for x in next(v for v in p['properties'].values() if v['type'] == 'title')['title'])


def note_problem(blocks, lang):
    """The ⚠️ note right under the inspiration video must have the current text (either kind); None if fine."""
    i = next((k for k, b in enumerate(blocks) if b['type'] == 'video'), None)
    if i is None:
        return None  # no inspiration video (old archived pages) -> no note to check
    b = next((x for x in blocks[i + 1:i + 4] if x['type'] == 'callout'), None)
    if not b:
        return 'no note under the inspiration video'
    note = _plain(b).replace('**', '').strip()
    want = ['\n'.join(pages.inspo_note(lang, same, own)).replace('**', '').strip()
            for same, own in ((False, False), (True, False), (True, True))]
    if note not in want or b.get('has_children') and any(
            c['type'] == 'paragraph' and re.search(r'JobStep|Parakeet AI', _plain(c)) for c in pages.children(b['id'])):
        return 'note under the inspiration video is not the current text'
    return None


def layout_problems(blocks, script, links):
    """Problems that mean "old hand-written layout": such a page is rebuilt from its example video (main.ready_page),
    never patched (tidy leaves it alone)."""
    urls = [((x.get('text') or {}).get('link') or {}).get('url', '') or '' for b in blocks
            for x in (b.get(b['type']) or {}).get('rich_text', []) or []]
    out = []
    if not any(b['type'] == 'video' for b in blocks):
        out.append('no example video')
    if not any('tiktok.com/@' in u for u in urls):
        out.append('no link to the original TikTok')
    if not script:
        out.append('no script section')
    elif not any(((x.get('text') or {}).get('link') or {}).get('url') == links['parakeet']
                 for b in script for x in b[b['type']].get('rich_text', [])):
        out.append('no Parakeet AI link in the script')
    return out


def check_page(pid, lang, links, live=True, ref_text='', fmt_id=None):
    """Problems of one format page. ref_text: the format's original words (formats.json 'script') - the speaker
    must stay the same (brands.speaker_changed)."""
    blocks = pages.children(pid)
    out = []
    left = reword.directions_left(pid)
    if left:
        out.append(f'stage directions in the script: {left[0][:60]}' + (f' (+{len(left) - 1})' if len(left) > 1 else ''))
    bad_note = note_problem(blocks, lang)
    if bad_note:
        out.append(bad_note)
    if not live:
        return out
    script = reword.script_blocks(pid)
    out += layout_problems(blocks, script, links)
    if ref_text:
        from .crosscheck import page_title
        if speaker_changed(ref_text, page_title(pid)) or speaker_changed(ref_text, ' '.join(_plain(b) for b in script)):
            out.append('the speaker changed (the original\'s "I" became "someone" / "a friend") - mode example '
                       'FORMAT:market:rebuild')
    if SOURCE_RE.search(reword.spoken_text(script)):
        out.append('JobStep (or the other app) named in the script')
    from . import tidy
    out += tidy.problems(pid, links, fmt_id)
    hook = reword.direction_blocks(pid)
    lab = ' '.join(_plain(b) + (b.get('child_page') or {}).get('title', '') for b in blocks)  # link or sub-page
    if len(hook) != 1 or 'Visual Hook Lab' not in lab:
        out.append(f'visual hook section is not "one hook line + Visual Hook Lab" ({len(hook)} lines)')
    return out


def run(cfg, fmts, page_of):
    from . import markets as M
    problems, ok = [], []
    for m in M.load(cfg):
        key = m['key']
        T = TEXT[m['lang']]
        flag = T['flag']
        entries, _ = pages.list_entries(m['list_page'])
        listed = [p.replace('-', '') for _, p in entries]
        out_here = lambda f: f['id'] in (m.get('skip_formats') or ()) or key in (f.get('off_markets') or ())
        live = {(page_of(f, key) or '').replace('-', '') for f in fmts if f.get('status') == 'active' and page_of(f, key)
                and not out_here(f)}
        if set(listed) != live or len(listed) != len(set(listed)):
            problems.append(f'{flag} list differs from the live formats: listed {len(listed)}, live {len(live)}')
        else:
            ok.append(f'{flag} list: {len(listed)} live formats')
        hand = [pid for pid in listed if pages.is_hand(pid)]
        if hand:
            ok.append(f'{flag} edited by hand in Megasheet (kept, never changed by the watcher): ' +
                      ', '.join(_title(p)[:40] for p in hand))
        for f in fmts:
            if f['id'] in (m.get('skip_formats') or ()):
                continue  # not a format of this market (Slovenia: the study-app format 'hardest schools')
            pid = page_of(f, key)
            if not pid:
                if f.get('status') == 'active':
                    problems.append(f"{flag} {f['title']}: no page")
                continue
            if pages.is_hand(pid):
                ok.append(f"{flag} {f['title']} ({f.get('status')}): edited by hand in Megasheet - not checked")
                continue
            try:  # a format off this market's list (lineup off_markets) is checked like an archived page
                bad = check_page(pid, m['lang'], cfg['links'], live=f.get('status') == 'active' and not out_here(f),
                                 ref_text=f.get('script', ''), fmt_id=f['id'])
            except Exception as e:  # e.g. a page moved to the trash
                bad = [f'page unreadable: {str(e)[:100]}']
            problems += [f"{flag} {f['title']} ({f.get('status')}): {x}" for x in bad]
            if not bad:
                ok.append(f"{flag} {f['title']} ({f.get('status')}): ok")
    try:  # the same format twice on a list (16 Oct 2026): merged on Monday / mode dedupe
        from . import dupes
        for a, b, m, ta, tb in dupes.find(fmts, M.load(cfg), page_of):
            problems.append(f'{TEXT[cfg["markets"][m]["lang"]]["flag"]} the same format twice: {a} "{ta}" and {b} "{tb}"')
    except Exception as e:
        problems.append(f'duplicate check failed: {str(e)[:100]}')
    print('\n'.join(['VERIFY OK:'] + ['  ' + x for x in ok] + ['VERIFY PROBLEMS:'] + ['  ' + x for x in problems or ['none']]),
          flush=True)
    return problems
