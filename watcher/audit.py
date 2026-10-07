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

from . import llm, localize, notion, reword, tiktok

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
    if not script.strip():
        return False, {'script_issues': ['no script section found']}, url
    lang_name = localize.LANG_NAME[lang]
    prompt = f"""FORMAT: {fmt['title']}
What the format is: {fmt.get('description', '')}

EXAMPLE VIDEO on the page ({url or 'no video on the page'}):
{example[:3000] or '(no example video)'}

SCRIPT on the page (creators say this, in {lang_name}):
{script[:4000]}

Check strictly:
1. example_same_format: is the example video really THIS format (same premise, hook idea and structure - same topic
   alone is not enough)? false if there is no example video.
2. script_follows_example: does the script tell the same story with the same beats in the same order as the example?
3. script_reworded: is the script reworded rather than a word-for-word transcription/translation of the example?
   (very similar is good; identical sentences are not)
4. script_ok: natural {lang_name}, mentions Parakeet AI (never JobStep), no promises nobody can guarantee.
Return JSON {{"example_same_format": true, "script_follows_example": true, "script_reworded": true, "script_ok": true,
"example_issue": "<short, if any>", "script_issues": ["<short>", ...]}}"""
    v = llm.chat_json(model, 'You are a strict QA reviewer for UGC creator instructions. Reply with JSON only.', prompt, timeout=1200)
    passed = all(v.get(k) for k in ('example_same_format', 'script_follows_example', 'script_reworded', 'script_ok'))
    if re.search(r'job\s*-?\s*step', script, re.I):
        passed = False
        v.setdefault('script_issues', []).append('JobStep is mentioned in the script')
    return passed, v, url


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


def fix_page(fmt, mk, cfg, history, accounts, meta, page_of, rounds=3):
    """Checks one page and fixes it until it passes. Returns (status, notes)."""
    m, lang, model = mk['key'], mk['lang'], cfg['models']['build']
    pid = page_of(fmt, m)
    notes, rejected = [], set()
    for r in range(rounds + 1):
        passed, v, url = check(fmt, pid, lang, model)
        if passed:
            return ('ok' if r == 0 else 'fixed'), notes
        if r == rounds:
            break
        if not v.get('example_same_format'):
            notes.append(f"example not this format ({v.get('example_issue', '')[:80]})")
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
        notes.append('script reworded again: ' + '; '.join(v.get('script_issues', []))[:120])
        status, why, changes = reword.reword_page(fmt, pid, lang, model, localize.example_text(url) if url else '')
        if status == 'ok':
            reword.apply(changes)
            fmt.setdefault('reworded', {})[m] = True
        else:
            notes.append(f'reword refused: {why}')
    return 'failed', notes + ['still failing: ' + '; '.join(v.get('script_issues', []) + [v.get('example_issue', '')])[:200]]


def run(fmts, mkts, cfg, history, accounts, meta, page_of, workers=4):
    import concurrent.futures as cf
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in mkts]

    def one(job):
        f, mk = job
        if not page_of(f, mk['key']):
            return f['title'], mk['key'], 'no page', []
        try:
            status, notes = fix_page(f, mk, cfg, history, accounts, meta, page_of)
        except Exception as e:
            status, notes = 'error', [str(e)[:200]]
        print(f"{f['title'][:45]} | {mk['key']} | {status} | {' / '.join(notes)}", flush=True)
        return f['title'], mk['key'], status, notes
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, jobs))
