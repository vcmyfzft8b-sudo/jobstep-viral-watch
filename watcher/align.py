"""Sentence-aligned scripts: every page's script mirrors its example video sentence by sentence.

Rules (agreed 2026-10-07):
- one sentence of ours per sentence of the original, about the same length; the whole script at most 110% of the
  original (and at least 80%) - nothing added;
- same meaning, but built differently (other word order, question instead of statement, other words);
- "Parakeet AI" is said/written exactly where the original says/writes JobStep (same number of times). If the original
  only SHOWS the app without naming it, we only show it too ("this tool here");
- a website / call to action only where the original has one (jobstep.io -> parakeet-ai.com/resume-maker);
- the app (link cue) appears at the same moments as in the original; scores are X/Y; no promises nobody can keep.
Only the script section is replaced (old text backed up in state/script_backup.json); the filming directions are
then matched to the new script.
"""
import re

from . import llm, localize, notion, reword, state
from .builder import PARAKEET_FACTS
from .markets import TEXT

JOBSTEP = re.compile(r'job\s*-?\s*st[ae]p|jopstep|jobset|jobster|job stay|jobs beget', re.I)


def _words(t):
    return len(re.findall(r'\w+', t))


APPROVED = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', 'registry', 'approved_scripts.json')


def approved(fid, lang, url):
    """A script the user approved word for word (only while the page still shows the example it was written for)."""
    import json
    try:
        with open(APPROVED) as f:
            x = json.load(f).get(lang, {}).get(fid)
    except FileNotFoundError:
        return None
    return x if x and url and x['example'].split('?')[0] == url.split('?')[0] else None


def align_page(fmt, page_id, lang, cfg, links):
    """Returns (status, why)."""
    T = TEXT[lang]
    src = localize.current_source(page_id)
    url = src['url'] if src else None
    ok = approved(fmt['id'], lang, url)
    if ok:
        return _write(fmt, page_id, lang, cfg, links, {'voiceover': ok['voiceover'], 'script': ok['script']}, 'approved script')
    example = localize.example_text(url) if url else ''
    if not example:
        return 'skipped', 'example video could not be read'
    blocks = reword.script_blocks(page_id)
    if not blocks:
        return 'skipped', 'no script section'
    old_script = '\n'.join(reword._plain(b) for b in blocks)
    speech = example.split('SPEECH:', 1)[-1].strip()
    screen = example.split('SPEECH:', 1)[0].replace('ON-SCREEN:', '').strip()
    base = speech if _words(speech) >= 15 else screen  # text-only videos: the on-screen texts are the script
    voiceover = _words(speech) >= 15
    n_orig = _words(base)
    prompt = f"""ORIGINAL JobStep video ({'speech' if voiceover else 'on-screen texts, no speech'}):
{base[:4000]}
{('On-screen texts of the original: ' + screen[:800]) if voiceover and screen else ''}

Our current {T['lang_name']} script for this format (for the cues: where the app, LinkedIn or an asset like a Gmail
recording is shown, and the asset names):
{old_script[:3000]}

{PARAKEET_FACTS}

Write our new {T['lang_name']} script ({T['style']}) that mirrors the ORIGINAL sentence by sentence:
1. Exactly one sentence of ours for each sentence of the original, in the same order, about the same length.
   The whole script must have {int(n_orig * 0.85)}-{int(n_orig * 1.1)} words (the original has {n_orig}). Add nothing.
2. Same meaning, but build every sentence differently: other word order, a question instead of a statement (or the
   other way round), other words. A native viewer must not recognise the original's sentences.
3. Where the original says or writes JobStep / jobstep.io, write "Parakeet AI" / parakeet-ai.com/resume-maker -
   exactly as often and at the same spots. Where the original only shows the app without naming it (e.g. "this tool
   here"), do the same: do NOT name it. Never mention JobStep.
4. A website / call to action at the end only if the original has one.
5. Scores/percentages the app shows are X (before) and Y (after). No promises nobody can keep ("you will get the
   job", "passes every filter") - say "better chances" instead. Address the viewer as
   { {'de': 'du', 'fr': 'tu', 'es': 'tú (never vosotros)'}[lang] } consistently (or "ihr/vous" if the original speaks to a
   group - but then consistently).
6. Cues: put cue "parakeet" on the sentence where the original shows the app/site, "linkedin" where it shows LinkedIn
   job search, "asset" (with asset_name exactly as in our current script) where it shows something like a Gmail
   inbox, "direction" (asset_name = short stage direction) for important acting moments, else null.
Return JSON {{"jobstep_mentions_in_original": <number>, "voiceover": {str(voiceover).lower()},
"script": [{{"cue": "parakeet|linkedin|asset|direction|null", "asset_name": "", "text": "<one sentence>",
"new_paragraph": false}}]}}"""
    why = ''
    for attempt in range(3):
        extra = f'\n\nYour previous attempt was rejected: {why}. Fix exactly that.' if why else ''
        spec = llm.chat_json(cfg['models']['build'], 'You are a senior UGC script writer. Reply with JSON only.',
                             prompt + extra, timeout=1200)
        why = _validate(spec, n_orig)
        if not why:
            break
    else:
        return 'skipped', why
    return _write(fmt, page_id, lang, cfg, links, spec,
                  f"{sum(_words(s['text']) for s in spec['script'])} words (original {n_orig})")


def _write(fmt, page_id, lang, cfg, links, spec, info):
    blocks = reword.script_blocks(page_id)
    if not blocks:
        return 'skipped', 'no script section'
    T = TEXT[lang]
    sub = T['sub_voice'] if spec.get('voiceover', True) else T['sub_silent']
    for b in notion.children(page_id):  # the subtitle line under the title must match (voiceover or not)
        if b['type'] == 'bulleted_list_item' and reword._plain(b).strip() in (T['sub_voice'], T['sub_silent']):
            if reword._plain(b).strip() != sub:
                notion.api('PATCH', f"/blocks/{b['id']}", {'bulleted_list_item': {'rich_text': [notion.rt(sub)]}})
            break
    for seg in spec['script']:
        if seg.get('cue') in ('null', 'None', ''):
            seg['cue'] = None
    new_blocks = notion.script_paragraphs(spec, links, lang)
    with state.LOCK:
        backup = state.load('script_backup.json', {})
        backup.setdefault('page:' + page_id, [b[b['type']]['rich_text'] for b in blocks])
        state.save('script_backup.json', backup)
    notion.api('PATCH', f'/blocks/{page_id}/children', {'children': new_blocks, 'after': blocks[-1]['id']})
    for b in blocks:
        notion.api('DELETE', f"/blocks/{b['id']}")
    reword.fix_directions(fmt, page_id, lang, cfg['models']['classify'])
    return 'ok', info


def _validate(spec, n_orig):
    script = spec.get('script') or []
    if not script:
        return 'empty script'
    text = ' '.join(s.get('text', '') for s in script)
    n = _words(text)
    if not 0.8 * n_orig <= n <= 1.12 * n_orig:
        return f'the script has {n} words, it must have {int(n_orig * 0.85)}-{int(n_orig * 1.1)}'
    if JOBSTEP.search(text):
        return 'JobStep is mentioned'
    want = int(spec.get('jobstep_mentions_in_original') or 0)
    have = len(re.findall(r'parakeet', text, re.I))
    if have != want:
        return f'"Parakeet AI"/the website appears {have} times, but the original names JobStep {want} times'
    if not any(s.get('cue') == 'parakeet' for s in script):
        return 'no sentence shows the app (cue "parakeet")'
    return ''


def run(fmts, mkts, cfg, page_of, workers=8):
    import concurrent.futures as cf
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in mkts if page_of(f, mk['key'])]

    def one(job):
        f, mk = job
        try:
            status, why = align_page(f, page_of(f, mk['key']), mk['lang'], cfg, cfg['links'])
        except Exception as e:
            status, why = 'error', str(e)[:200]
        if status == 'ok':
            f.setdefault('reworded', {})[mk['key']] = True
        print(f"{f['title'][:45]} | {mk['key']} | {status} | {why}", flush=True)
        return f['title'], mk['key'], status, why
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, jobs))
