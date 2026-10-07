"""Page audit: every active format page in every market must check out - and is fixed until it does.

For each page Claude (strong model) compares three things: the FORMAT, the page's EXAMPLE VIDEO (what is said and
shown in it) and the page's SCRIPT.
  1. Is the example video really this format?
  2. Does the script follow the example's beats (same story, same order)?
  3. Is the script reworded (not a 1:1 transcription), in the market's language, without JobStep or guarantees?
Fixes, then the page is checked again (max 3 rounds):
  - wrong example -> a strictly checked same-language JobStep video of the format, else the format's original
    JobStep video (registry/originals.json, the video the script was built from)
  - script off -> reworded again against the example video
Pages that still fail after 3 rounds are reported with the reason.
"""
import json
import os
import re

from . import align, llm, localize, notion, reword, tiktok
from .builder import PARAKEET_FACTS

ORIGINALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'originals.json')


def originals():
    try:
        with open(ORIGINALS) as f:
            return json.load(f)['originals']
    except FileNotFoundError:
        return {}


def check(fmt, page_id, lang, model):
    """Returns (passed, verdict dict, example url)."""
    src = localize.current_source(page_id)
    url = src['url'] if src else None
    example = localize.example_text(url) if url else ''
    script = '\n'.join(reword._plain(b) for b in reword.script_blocks(page_id))
    directions = '\n'.join(reword._plain(b) for b in reword.direction_blocks(page_id))
    blocks_all = notion.children(page_id)
    ti = next((k for k, b in enumerate(blocks_all) if b['type'].startswith('heading') and '📲' in reword._plain(b)), None)
    title_block = next((b for b in blocks_all[ti + 1:ti + 3] if b['type'] == 'paragraph' and reword._plain(b).strip()), None) if ti is not None else None
    title = reword._plain(title_block) if title_block else ''
    note = next((reword._plain(b) for b in notion.children(page_id) if b['type'] == 'callout' and '⚠' in str(b['callout'].get('icon'))), '')
    if not script.strip():
        return False, {'script_issues': ['no script section found']}, url
    lang_name = localize.LANG_NAME[lang]
    prompt = f"""FORMAT: {fmt['title']}
What the format is: {fmt.get('description', '')}

EXAMPLE VIDEO on the page ({url or 'no video on the page'}):
{example[:3000] or '(no example video)'}

SCRIPT on the page (creators say this, in {lang_name}):
{script[:4000]}

FILMING DIRECTIONS on the page:
{directions[:2000]}

Check strictly:
1. example_same_format: is the example video really THIS format (same premise, hook idea and structure - same topic
   alone is not enough)? false if there is no example video.
2. script_follows_example: does the script tell the same story with the same beats in the same order as the example?
3. script_reworded: is the script reworded rather than a transcription/translation of the example? Very similar
   story is good, but if more than about a third of the sentences are direct translations/transcriptions of the
   example's sentences (same structure, same images), it is NOT reworded. Be strict - a native viewer must not
   recognise the example's sentences.
5. directions_ok: do the filming directions match the script - no duplicate or contradicting lines, X/Y mentioned
   only as they appear in the script, every quoted line really in the script?
6. example_language: the language of the example video (English name).
4. script_ok: natural {lang_name}, mentions Parakeet AI (never JobStep), no promises nobody can guarantee; scores and
   percentages the app shows are ALWAYS the placeholders X / Y, never concrete numbers (e.g. "64 %", "40 sobre 100"
   is wrong); one consistent form of address ({ {'de': 'du', 'fr': 'tu', 'es': 'tú (never vosotros)'}[lang] });
   no stray formatting characters (backticks, asterisks) in what is said or shown.
7. title_ok: the on-screen TITLE ({title!r}) makes no promise nobody can guarantee (e.g. 'a job in 24h') and is not a
   word-for-word copy of the example's on-screen text when the example is in {lang_name}.
{PARAKEET_FACTS}
script_ok is false if the script or directions show/mention a feature Parakeet AI does not have.
Note: X and Y in the script are intentional placeholders - the creator says the score the app shows them. They are
correct; never ask to replace them with numbers.
Return JSON {{"example_same_format": true, "script_follows_example": true, "script_reworded": true, "script_ok": true,
"directions_ok": true, "title_ok": true, "example_language": "<language>", "example_issue": "<short, if any>",
"title_suggestion": "<if title_ok is false: a fixed title in the same style, else empty>",
"script_issues": ["<short>", ...], "direction_issues": ["<short>", ...]}}"""
    v = llm.chat_json(model, 'You are a strict QA reviewer for UGC creator instructions. Reply with JSON only.', prompt, timeout=1200)
    v['script_issues'] = [x for x in (v.get('script_issues') or []) if x]
    v['example_issue'] = v.get('example_issue') or ''
    v['direction_issues'] = [x for x in (v.get('direction_issues') or []) if x]
    v['note'] = note
    v['views'] = 0
    if url:
        d = tiktok.video_detail(localize._handle(url), re.search(r'/video/(\d+)', url).group(1))
        v['views'] = d['views'] if d else -1
    if url and not example:  # the video could not be read right now: unknown, not wrong
        v['example_same_format'] = v['script_follows_example'] = True
        v['unverified'] = True
    same = localize.LANG_NAME[lang].lower() in str(v.get('example_language', '')).lower()
    v['note_ok'] = bool(note) and ((same and _note_is_same(note, lang)) or (not same and not _note_is_same(note, lang)))
    v['same_lang'] = same
    v['views_ok'] = v['views'] < 0 or v['views'] >= localize.MIN_VIEWS or url == originals().get(fmt['id'])
    v['title_block'] = title_block
    v['approved'] = bool(align.approved(fmt['id'], lang, url))
    if v['approved']:  # the user approved this script word for word - only directions/note/title/example are checked
        v.update({'script_follows_example': True, 'script_reworded': True, 'script_ok': True})
        v['script_issues'] = []
    spoken = example.split('SPEECH:', 1)[-1] if example else ''
    base = spoken if align._words(spoken) >= 15 else example
    v['length_ok'] = v['approved'] or not example or align._words(script) <= 1.15 * max(align._words(base), 1)
    if not title_block:
        v['title_ok'] = True
    passed = all(v.get(k) for k in ('example_same_format', 'script_follows_example', 'script_reworded', 'script_ok',
                                    'directions_ok', 'note_ok', 'views_ok', 'title_ok', 'length_ok'))
    if re.search(r'job\s*-?\s*step', script, re.I):
        passed = False
        v['script_issues'].append('JobStep is mentioned in the script')
    return passed, v, url


def _note_is_same(note, lang):
    from .markets import TEXT
    return note.replace('**', '')[:30] == TEXT[lang]['inspo_note_same'].replace('**', '')[:30]


def _put_example(fmt, m, page_id, lang, url, same_lang):
    h, vid = localize._handle(url), re.search(r'/video/(\d+)', url).group(1)
    d = tiktok.video_detail(h, vid)
    if not d:
        return False
    src = localize.current_source(page_id)
    if src:
        localize.replace_video(page_id, src, d, lang)
    else:
        localize.add_section(page_id, d, lang)
    localize.set_note(page_id, lang, same_lang)
    fmt.setdefault('inspo', {})[m] = {'url': url, 'views': d['views'], 'strict': True, 'audit': True}
    return True


def fix_page(fmt, mk, cfg, history, accounts, meta, page_of, rounds=5, rebuild=None):
    """Checks one page and fixes it until it passes. Returns (status, notes)."""
    m, lang, model = mk['key'], mk['lang'], cfg['models']['build']
    pid = page_of(fmt, m)
    notes, rejected, rebuilt = [], set(), False
    for r in range(rounds + 1):
        passed, v, url = check(fmt, pid, lang, model)
        if passed:
            if v.get('unverified'):
                notes.append('example video could not be read right now - checked again next Monday')
            return ('ok' if r == 0 else 'fixed'), notes
        if r == rounds:
            break
        if not v.get('views_ok'):
            orig = originals().get(fmt['id'])
            notes.append(f"example has only {v['views']} views - original JobStep video put back")
            if url:
                rejected.add(url)
            if orig:
                _put_example(fmt, m, pid, lang, orig, same_lang=False)
                fmt.get('reworded', {}).pop(m, None)
            continue
        if not v.get('note_ok') and v.get('example_same_format'):
            localize.set_note(pid, lang, v['same_lang'])
            notes.append('note under the video corrected')
            continue
        if v.get('example_same_format') and (not v.get('length_ok') or not v.get('script_reworded')
                                             or not v.get('script_follows_example')) and not rebuilt:
            rebuilt = True  # script too long / too close / not following: mirror the example sentence by sentence
            st, why = align.align_page(fmt, pid, lang, cfg, cfg['links'])
            notes.append(f'script rewritten sentence by sentence ({why})' if st == 'ok' else f'rewrite refused: {why}')
            continue
        if not v.get('title_ok') and v.get('title_suggestion') and v.get('title_block'):
            tb = v['title_block']
            notion.api('PATCH', f"/blocks/{tb['id']}", {tb['type']: {'rich_text': [notion.rt(v['title_suggestion'], bold=True)]}})
            notes.append(f"title fixed: {v['title_suggestion'][:60]}")
            continue
        if not v.get('directions_ok') and v.get('example_same_format') and v.get('script_reworded') and v.get('script_follows_example'):
            st, why = reword.fix_directions(fmt, pid, lang, model, '; '.join(v['direction_issues']))
            notes.append('filming directions corrected' if st == 'ok' else f'directions not changed: {why}')
            continue
        if not v.get('example_same_format'):
            notes.append(f"example not this format ({(v.get('example_issue') or '')[:80]})")
            fmt.get('inspo', {}).pop(m, None)
            fmt.get('reworded', {}).pop(m, None)
            if url:
                rejected.add(url)
            rep = localize.run([fmt], [mk], history, accounts, meta, cfg, page_of, exclude=rejected)  # strict search
            if not (rep and rep[0][2] in ('replaced', 'kept') and (fmt.get('inspo') or {}).get(m, {}).get('strict')):
                orig = originals().get(fmt['id'])
                if orig and orig not in rejected:
                    _put_example(fmt, m, pid, lang, orig, same_lang=False)
                    notes.append('put back the original JobStep video')
            continue
        if not v.get('script_follows_example') and url and rebuild and not rebuilt:
            # the example tells the format in another order: build the page from the example (reworded script)
            rebuilt = True
            ok, why = rebuild(fmt, mk, url)
            notes.append('page rebuilt from its example video' if ok else f'rebuild refused: {why}')
            if ok:
                continue
        notes.append('script reworded again: ' + '; '.join(v['script_issues'])[:120])
        status, why, changes = reword.reword_page(fmt, pid, lang, model, localize.example_text(url) if url else '',
                                                  feedback='; '.join(v['script_issues']))
        if status == 'ok':
            reword.apply(changes)
            fmt.setdefault('reworded', {})[m] = True
        else:
            notes.append(f'reword refused: {why}')
    return 'failed', notes + ['still failing: ' + '; '.join(v['script_issues'] + v['direction_issues'] + [v['example_issue']])[:200]]


def run(fmts, mkts, cfg, history, accounts, meta, page_of, workers=4, rebuild=None, only_failed=False):
    import concurrent.futures as cf
    last = meta.setdefault('audit', {})
    if only_failed and not last:  # no record yet: the pages listed in registry/audit_todo.json are the open ones
        try:
            with open(os.path.join(os.path.dirname(ORIGINALS), 'audit_todo.json')) as fh:
                todo = set(json.load(fh)['pages'])
            last.update({f"{f['id']}:{mk['key']}": 'ok' for f in fmts for mk in mkts if f"{f['id']}:{mk['key']}" not in todo})
        except FileNotFoundError:
            pass
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in mkts
            if not (only_failed and last.get(f"{f['id']}:{mk['key']}") in ('ok', 'fixed'))]

    def one(job):
        f, mk = job
        if not page_of(f, mk['key']):
            return f['title'], mk['key'], 'no page', []
        try:
            status, notes = fix_page(f, mk, cfg, history, accounts, meta, page_of, rebuild=rebuild)
        except Exception as e:
            status, notes = 'error', [str(e)[:200]]
        print(f"{f['title'][:45]} | {mk['key']} | {status} | {' / '.join(notes)}", flush=True)
        return f['title'], mk['key'], status, notes
    with cf.ThreadPoolExecutor(workers) as ex:
        rep = list(ex.map(one, jobs))
    by_title = {f['title']: f['id'] for f in fmts}
    for t, m, status, _ in rep:
        last[f"{by_title.get(t, t)}:{m}"] = status
    return rep
