"""Transcribed scripts: every page's script is its example video's own words (rule since 2026-10-10 - no rewording).

Rules:
- original in the page's language: its transcript word for word; other language: a faithful, close translation;
  same sentences in the same order, nothing added (at most 110% of the original, 125% for a translation);
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
from .builder import COUNTRY, PARAKEET_FACTS, TRANSCRIBE
from .markets import TEXT

from .brands import SOURCE_RE as JOBSTEP  # JobStep and the apps of hand-added formats


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

Write our {T['lang_name']} script for this video: the original's own words, NOT reworded.
{TRANSCRIBE.format(lang=T['lang_name'], style=T['style'], country=COUNTRY[lang])}
The whole script must have {int(n_orig * 0.8)}-{max_words(n_orig, translated=True)} words (the original has {n_orig};
a word-for-word transcript in the same language stays within {max_words(n_orig)}). Address the viewer exactly as the
original does.
Cues: put cue "parakeet" on the sentence where the original shows the app/site, "linkedin" where it shows LinkedIn
job search, "asset" (with asset_name exactly as in our current script) where it shows something like a Gmail
inbox, "direction" (asset_name = short stage direction) for important acting moments, else null.
Return JSON {{"original_language": "<English name>", "jobstep_mentions_in_original": <number>,
"voiceover": {str(voiceover).lower()},
"script": [{{"cue": "parakeet|linkedin|asset|direction|null", "asset_name": "", "text": "<one sentence>",
"new_paragraph": false}}]}}"""
    why = feedback
    for attempt in range(5):
        extra = f'\n\nA reviewer rejected the current/previous version: {why}. Fix exactly that.' if why else ''
        spec = llm.chat_json(cfg['models']['build'], 'You are a precise transcriber and translator of UGC videos. '
                             'Reply with JSON only.', prompt + extra, timeout=1200)
        same = T['lang_name'].lower() in str(spec.get('original_language', '')).lower()
        why = _validate(spec, n_orig, base, translated=not same)
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


def max_words(n_orig, translated=False):
    """110% of the original (125% for a translation); very short on-screen scripts get a few words more (articles in
    FR/ES/DE)."""
    k = 1.25 if translated else 1.1
    return int(n_orig * k) if n_orig >= 60 else max(int(n_orig * k), n_orig + 8)


def _validate(spec, n_orig, source=None, translated=False):
    script = spec.get('script') or []
    if not script:
        return 'empty script'
    text = ' '.join(s.get('text', '') for s in script)
    n = _words(text)
    if not 0.8 * n_orig <= n <= max_words(n_orig, translated):
        return f'the script has {n} words, it must have {int(n_orig * 0.8)}-{max_words(n_orig, translated)}'
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
        pid = page_of(f, mk['key'])
        try:
            status, why = align_page(f, pid, mk['lang'], cfg, cfg['links'])
            if status != 'ok' or why == 'approved script unchanged':  # script untouched -> the hook still gets short
                reword.fix_directions(f, pid, mk['lang'], cfg['models']['classify'])
            localize.refresh_note(pid, mk['lang'])
        except Exception as e:
            status, why = 'error', str(e)[:200]
        if status == 'ok':
            f.setdefault('reworded', {})[mk['key']] = True
        print(f"{f['title'][:45]} | {mk['key']} | {status} | {why}", flush=True)
        return f['title'], mk['key'], status, why
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, jobs))
