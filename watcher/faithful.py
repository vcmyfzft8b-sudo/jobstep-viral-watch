"""Independent check that every live script is its example video, 1:1 (user, 16 Oct 2026: "double-check that it is
actually like this, also when it runs automatically").

A script may differ from its example video ONLY by: the translation into the page's language (the market's variant),
JobStep -> Parakeet AI (and jobstep.io -> the Parakeet link), a JobStep feature Parakeet AI lacks -> the closest real
one, scores the app shows -> X / Y, job sites / companies of the market, and dates / months left out or made timeless.
Everything else - every sentence, the order, the creator's story, numbers, claims and promises - must be there.

Claude lines the original up with the script sentence by sentence and lists every other change. Read-only:
`mode=faithful-check` prints every page; the Monday run sends the problems to Slack (the page audit, which uses the
same rules, re-transcribes failing pages).
"""
import concurrent.futures as cf

from . import llm, localize, reword
from .brands import LOCALISE
from .builder import PARAKEET_FACTS
from .markets import TEXT, for_format

SYSTEM = 'You check translations of UGC video scripts sentence by sentence. Reply with JSON only.'


def check_page(fmt, page_id, lang, model):
    """{'ok': bool, 'problems': [...], 'sentences': n, 'words': (script, original)} or {'ok': None, 'why': ...}."""
    src = localize.current_source(page_id)
    url = src['url'] if src else None
    example = localize.example_text(url, page_id=page_id) if url else ''
    if not example:
        return {'ok': None, 'why': 'example video could not be read'}
    speech = example.split('SPEECH:', 1)[-1].strip()
    screen = example.split('SPEECH:', 1)[0].replace('ON-SCREEN:', '').strip()
    base = speech if len(speech.split()) >= 15 else screen
    script = reword.spoken_text(reword.script_blocks(page_id))
    if not script.strip():
        return {'ok': None, 'why': 'no script on the page'}
    T = TEXT[lang]
    prompt = f"""ORIGINAL video ({'speech' if base is speech else 'on-screen texts'}):
{base[:5000]}

OUR {T['lang_name']} SCRIPT (what the creator says; link labels removed):
{script[:5000]}

The script must be the original, 1:1: its transcript if the original is in {T['lang_name']}, else a faithful close
translation - every sentence, in the same order, not shortened, not summarised, not softened. The ONLY allowed
differences:
- the translation itself (natural {T['lang_name']}, the market's variant of the language);
- JobStep (or another CV app) -> Parakeet AI, its website -> the Parakeet AI link;
- a feature of that app Parakeet AI does not have -> the closest Parakeet AI feature (e.g. "here are the jobs you
  applied to, click 'New job'" -> "here you upload your CV"; "and even a cover letter" -> "and even another template")
  - this is REQUIRED, never report it as reworded or dropped;
- scores / percentages the app shows -> X / Y;
- this localisation: {LOCALISE}
- filler words ("ähm", "like") may go; obvious speech-to-text errors may be fixed.
{PARAKEET_FACTS}
Go through the original sentence by sentence. List every OTHER difference: a sentence dropped, shortened or merged
away, something added, a sentence reworded or retold, a claim / promise / number / personal detail of the creator
changed or softened, the speaker changed - and (kind "feature") a feature Parakeet AI does not have that is still in
the script.
Return JSON {{"problems": [{{"kind": "dropped|added|reworded|softened|speaker|feature|other", "original": "<the original
sentence>", "script": "<what the script says instead, empty if missing>"}}]}} - an empty list when the script is 1:1."""
    r = llm.chat_json(model, SYSTEM, prompt, timeout=900)
    probs = [p for p in (r.get('problems') or []) if isinstance(p, dict)]
    return {'ok': not probs, 'problems': probs, 'words': (len(script.split()), len(base.split())), 'url': url}


def run(fmts, mkts, cfg, page_of, workers=6):
    """Every live page of every running market: [(format title, market, result)]."""
    from . import pages
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in for_format(mkts, f) if page_of(f, mk['key'])
            and not pages.is_hand(page_of(f, mk['key']))]  # edited by hand in Megasheet: the user's text stays

    def one(job):
        f, mk = job
        try:
            res = check_page(f, page_of(f, mk['key']), mk['lang'], cfg['models']['build'])
        except Exception as e:
            res = {'ok': None, 'why': f'check failed: {str(e)[:120]}'}
        mark = '✅' if res['ok'] else '❓' if res['ok'] is None else '❌'
        detail = res.get('why') or '; '.join(f"{p.get('kind')}: «{(p.get('original') or '')[:70]}» → «{(p.get('script') or '')[:70]}»"
                                             for p in res.get('problems', []))
        print(f"{mark} {f['title'][:45]} | {mk['key']} | words {res.get('words')} | {detail}", flush=True)
        return f['title'], mk['key'], res
    with cf.ThreadPoolExecutor(workers) as ex:
        out = list(ex.map(one, jobs))
    bad = [x for x in out if x[2]['ok'] is False]
    unknown = [x for x in out if x[2]['ok'] is None]
    print(f'FAITHFUL: {len(out) - len(bad) - len(unknown)}/{len(out)} pages 1:1, {len(bad)} with changes, '
          f'{len(unknown)} not checkable', flush=True)
    return out


def fix(results, fmts, mkts, cfg, page_of):
    """Pages with changes are transcribed again from their example, told exactly what was off, then checked again.
    Returns [(title, market, result after the fix)] for the pages that were fixed or still have changes."""
    from . import align, reword as _reword
    by_title = {}
    for f in fmts:
        by_title.setdefault(f['title'], f)
    mk_by = {mk['key']: mk for mk in mkts}
    out = []
    for title, m, res in results:
        if res.get('ok') is not False:
            continue
        f, mk = by_title.get(title), mk_by.get(m)
        if not f or not mk:
            continue
        pid = page_of(f, m)
        why = 'not 1:1 with the original: ' + '; '.join(
            f"{p.get('kind')}: original «{p.get('original', '')}» -> script «{p.get('script', '')}»" for p in res['problems'])[:1500]
        st, info = align.align_page(f, pid, mk['lang'], cfg, cfg['links'], feedback=why)
        if st == 'ok':
            _reword.fix_directions(f, pid, mk['lang'], cfg['models']['classify'])
        after = check_page(f, pid, mk['lang'], cfg['models']['build'])
        print(f"{'✅' if after['ok'] else '❌'} fixed? {title[:45]} | {m} | {st}: {info} | still: "
              f"{len(after.get('problems', []))} changes", flush=True)
        out.append((title, m, after))
    return out
