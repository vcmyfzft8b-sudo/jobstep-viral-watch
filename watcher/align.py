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
import json
import re

from . import llm, localize, notion, reword, state
from .builder import PARAKEET_FACTS
from .markets import TEXT

JOBSTEP = re.compile(r'job\s*-?\s*st[ae]p|jopstep|jobset|jobster|job stay|jobs beget', re.I)


def _words(t):
    return len(re.findall(r'\w+', t))


def source_script(example):
    """Use speech for voiced videos, on-screen copy for silent ones; never count both together."""
    speech = example.split('SPEECH:', 1)[-1].strip()
    screen = example.split('SPEECH:', 1)[0].replace('ON-SCREEN:', '').strip()
    return speech if _words(speech) >= 15 else screen


APPROVED = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', 'registry', 'approved_scripts.json')


def approved_script(fid, lang):
    """The approval lock survives changes to the example; automation cannot revoke it."""
    import json
    try:
        with open(APPROVED) as f:
            x = json.load(f).get(lang, {}).get(fid)
    except FileNotFoundError:
        return None
    return x


def approved(fid, lang, url):
    x = approved_script(fid, lang)
    return x if x and url and x['example'].split('?')[0] == url.split('?')[0] else None


def matches_approved(page_id, lang, links, spec):
    """Compare actual text, cue links, emphasis and paragraph boundaries to the approved rendering."""
    def signature(blocks):
        out = []
        for b in blocks:
            # Notion may merge adjacent rich-text fragments; compare characters with their relevant styling.
            chars = []
            for x in b[b['type']].get('rich_text', []):
                t = x.get('text', {})
                style = (x.get('type', 'text'), (t.get('link') or {}).get('url'),
                         bool(x.get('annotations', {}).get('bold')), bool(x.get('annotations', {}).get('code')))
                chars.extend((c, style) for c in t.get('content', x.get('plain_text', '')))
            while chars and chars[-1][0].isspace():
                chars.pop()
            out.append((b['type'], chars))
        return out
    return signature(reword.script_blocks(page_id)) == signature(notion.script_paragraphs(spec, links, lang))


def align_page(fmt, page_id, lang, cfg, links, feedback='', draft_url=None):
    """Returns (status, why). With draft_url: writes NOTHING - returns ('draft', spec) for a replacement script that
    follows that example (used to prepare replacements of approval-locked scripts for the user's approval)."""
    T = TEXT[lang]
    src = localize.current_source(page_id)
    url = draft_url or (src['url'] if src else None)
    ok = None if draft_url else approved(fmt['id'], lang, url)
    if approved_script(fmt['id'], lang) and not ok and not draft_url:
        return 'skipped', 'approved script is locked; example differs from the approved example'
    if ok:
        if matches_approved(page_id, lang, links, ok):
            return 'ok', 'approved script unchanged'
        return _write(fmt, page_id, lang, cfg, links, {'voiceover': ok['voiceover'], 'script': ok['script']}, 'approved script')
    example = localize.example_text(url, page_id=page_id)
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
    from . import crosscheck
    ref = crosscheck.reference(fmt['id'])
    prompt = f"""ORIGINAL JobStep video ({'speech' if voiceover else 'on-screen texts, no speech'}):
{base[:4000]}
{('On-screen texts of the original: ' + screen[:800]) if voiceover and screen else ''}

Our current {T['lang_name']} script for this format (for the cues: where the app, LinkedIn or an asset like a Gmail
recording is shown, and the asset names):
{old_script[:3000]}

{PARAKEET_FACTS}

{('REFERENCE DEFINITION of this format (beats, product moment, brand/CTA rules): ' + json.dumps(ref, ensure_ascii=False)) if ref else ''}

Write our new {T['lang_name']} script ({T['style']}) for the SAME FORMAT, independently worded:
1. Same beats in the same order as the original (and the reference), the product introduced at the same beat, about
   the same length. The whole script must have {int(n_orig * 0.8)}-{max_words(n_orig)} words (the original has
   {n_orig}). Add no new beats, claims or features.
2. Write every beat in your OWN words, as a creator would tell it from scratch: do NOT translate or paraphrase the
   original's sentences one by one, do not keep its sentence structure, images or turns of phrase (only the hook
   idea may stay close). A native viewer who saw the original must not recognise any sentence.
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
    why = feedback
    for attempt in range(5):
        extra = f'\n\nA reviewer rejected the current/previous version: {why}. Fix exactly that.' if why else ''
        spec = llm.chat_json(cfg['models']['build'], 'You are a senior UGC script writer. Reply with JSON only.',
                             prompt + extra, timeout=1200)
        why = _validate(spec, n_orig, base)
        if not why:
            break
    else:
        return 'skipped', why
    if draft_url:
        return 'draft', {**spec, 'example': draft_url, 'n_orig': n_orig}
    return _write(fmt, page_id, lang, cfg, links, spec,
                  f"{sum(_words(s['text']) for s in spec['script'])} words (original {n_orig})")


def _write(fmt, page_id, lang, cfg, links, spec, info):
    locked = approved_script(fmt['id'], lang)
    if locked and (spec.get('script') != locked['script'] or spec.get('voiceover', True) != locked['voiceover']):
        return 'skipped', 'approved script is locked'
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
    resources = None if locked else reword.resources_text(page_id)  # approved scripts are rendered exactly as approved
    for seg in spec['script']:
        if seg.get('cue') in ('null', 'None', ''):
            seg['cue'] = None
        if resources is not None and seg.get('cue') == 'asset' and not reword.in_resources(notion.asset_label(seg.get('asset_name')), resources):
            seg['cue'] = 'direction'  # nothing in the resources to point to -> a plain stage direction
            seg['asset_name'] = notion.asset_label(seg.get('asset_name'))
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


def max_words(n_orig):
    """110% of the original; very short on-screen scripts get a few words more (articles in FR/ES/DE)."""
    return int(n_orig * 1.1) if n_orig >= 60 else max(int(n_orig * 1.1), n_orig + 8)


def _validate(spec, n_orig, source=None):
    script = spec.get('script') or []
    if not script:
        return 'empty script'
    text = ' '.join(s.get('text', '') for s in script)
    n = _words(text)
    if not 0.8 * n_orig <= n <= max_words(n_orig):
        return f'the script has {n} words, it must have {int(n_orig * 0.85)}-{max_words(n_orig)}'
    if JOBSTEP.search(text):
        return 'JobStep is mentioned'
    want = len(JOBSTEP.findall(source)) if source is not None else int(spec.get('jobstep_mentions_in_original') or 0)
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
