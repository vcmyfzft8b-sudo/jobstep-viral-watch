"""Turn a viral JobStep video into a Parakeet format page spec (DE/FR/ES, same structure as our existing pages)."""
import os
import re

from . import llm

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, '..', 'registry', 'examples')

from .markets import TEXT

# Kept for older callers (DACH texts); the per-language texts live in markets.TEXT.
INSPO_NOTE = TEXT['de']['inspo_note']
REQUIRED_LINE = TEXT['de']['required_line']

SYSTEM = """You write creator instructions for Parakeet AI (an AI CV maker, https://www.parakeet-ai.com/resume-maker)
UGC campaigns. You adapt viral videos made by JobStep creators (a competing CV app) into the same format for
Parakeet AI, in the creators' language. Reply with JSON only."""

RULES = """RULES
- Output language for ALL creator-facing text (page_title, title_hook, script, visual_hook_first, extra_hook_lines,
  asset names/descriptions, directions): {lang}. Script style: {style}. Same meaning, same beats, same order, roughly
  the same length as the original speech (±25%) - but REWORDED, never a 1:1 transcription or literal translation:
  say each beat in your own words (other phrasing, other sentence structure, other filler words), so the video feels
  very similar but is clearly not a copy of the JobStep creator. This applies even more when the original is already
  in {lang}: then no sentence may match the original word for word. Keep the hook idea and on-screen title punchy
  (they may stay close). The example pages below are German - copy their STYLE and STRUCTURE, but write in {lang}.
- Replace JobStep with Parakeet AI everywhere (jobstep.io -> parakeet-ai.com/resume-maker). The words "JobStep" or
  "Job Step" must not appear anywhere in your output.
- Concrete scores/percentages the app shows become X (before) and Y (after) - creators read their own numbers.
- Adapt country-specific things to {country} (job sites, companies, places) when the original names local ones.
- Tone down promises nobody can guarantee (e.g. "guaranteed job in 24h").
- Every moment where the original video SHOWS the CV app on screen gets cue "parakeet". Where it shows LinkedIn job
  search, cue "linkedin". Plain stage directions (e.g. surprised reaction, music) use cue "direction" with the
  direction as text in asset_name. Otherwise cue null. Put the cue on the segment where that screen starts.
- CVs are NEVER assets: creators show their own old CV and the CV they make in Parakeet AI (cue "parakeet").
- Public websites/apps the creator can simply open and film (a discount page, a job board, Google) are NOT assets:
  use cue "direction" with a short direction and add one extra_hook_lines entry with the exact page to open.
- Only things a creator cannot make or open themselves count as assets (cue "asset", e.g. an email inbox full of
  interview invites). For every asset, add one extra_hook_lines entry that says how to show it.
- Address creators neutrally (informal "you"), never with a gendered word for "creator".
- No voiceover videos (only on-screen text + music): set voiceover=false; each script segment is one text overlay.
- title_hook: the on-screen hook/title of the original, adapted to punchy {lang} (keep caps/emojis style).
- page_title: short {lang} hook for the Notion page name + one emoji at the end.
- visual_hook_first: one sentence telling the creator what to do in the first seconds, based on what the original
  creator does in the first 3 seconds (action/prop + speaking to camera + title on screen).
- return_to_camera: true if the original goes back to talking to the camera for the last line(s).
- extra_hook_lines: 0-2 extra lines only if the original needs special filming instructions. Never mention X/Y scores
  or going back to the camera at the end (both are added automatically). Every direction must refer to a line that is
  really in YOUR script (quote your own wording, not the original's). Never repeat the standard
  line about filming Parakeet AI on the laptop at every link and cutting loading times - it is added automatically."""

COUNTRY = {'de': 'Germany/Austria/Switzerland', 'fr': 'France', 'es': 'Spain'}

SCHEMA = """Return JSON:
{"page_title": "...", "icon": "<one emoji>", "title_hook": "...", "voiceover": true,
 "script": [{"cue": "parakeet|linkedin|asset|direction|null", "asset_name": "", "text": "...", "new_paragraph": false}],
 "visual_hook_first": "...", "return_to_camera": true, "extra_hook_lines": [],
 "has_scores": false, "assets_needed": [{"name": "...", "description": "<what it must show>"}],
 "registry_description": "<one English sentence describing the format, for matching future videos>",
 "summary_en": "<2 sentences: what the original video does and why it works>"}"""


def _examples():
    out = []
    for name in sorted(os.listdir(EXAMPLES)):
        with open(os.path.join(EXAMPLES, name)) as f:
            out.append(f'--- EXAMPLE PAGE {name} ---\n' + f.read())
    return '\n'.join(out)


def build_spec(video, transcript, frames, model, lang='de', feedback=''):
    """video: tiktok.video_detail dict; transcript: soniox result; frames: [(seconds, path)]; lang: de | fr | es."""
    T = TEXT[lang]
    rules = RULES.format(lang=T['lang_name'], style=T['style'], country=COUNTRY[lang])
    timed = '\n'.join(f"[{s['start']:.1f}-{s['end']:.1f}s] {s['text']}" for s in transcript.get('segments', [])) or '(no speech)'
    content = [{'type': 'text', 'text': f"""Our existing pages (German - follow this style and structure, write in {T['lang_name']}):
{_examples()}

{rules}

ORIGINAL VIDEO (@{video['handle']}, {video['views']} views, {video['duration']}s, language: {transcript.get('language') or '?'})
ON-SCREEN TEXT (TikTok text stickers): {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH WITH TIMESTAMPS (Soniox):
{timed}

The following images are contact sheets of frames from the video; every tile is labelled with its timestamp in
seconds (red). Use them to see the visual hook, what is shown on screen and when the app appears.

{SCHEMA}{chr(10) + 'Your previous attempt was rejected: ' + feedback + ' Fix exactly that.' if feedback else ''}"""}]
    from . import media
    for t0, t1, path in media.contact_sheets(frames, os.path.dirname(frames[0][1])):
        content.append({'type': 'text', 'text': f'Frames {t0:.1f}s – {t1:.1f}s:'})
        content.append(llm.image_part(path))
    spec = llm.chat_json(model, SYSTEM, content, max_tokens=8000, temperature=0.4)
    for seg in spec.get('script', []):
        if seg.get('cue') in ('null', 'None', ''):
            seg['cue'] = None
    return spec


def hook_lines(spec, lang='de'):
    T = TEXT[lang]
    cues = {s.get('cue') for s in spec.get('script', [])}
    lines = [spec['visual_hook_first']]
    app = T['app_line'] if 'parakeet' in cues else ''
    if 'linkedin' in cues:
        app = T['linkedin_line'] + app
    if app.strip():
        lines.append(app.strip())
    text = ' '.join(s['text'] for s in spec.get('script', []))
    has_x, has_y = bool(re.search(r'\bX\b', text)), bool(re.search(r'\bY\b', text))
    # the model's own extra lines must not repeat the standard lines (scores / back to camera)
    extra = [l for l in spec.get('extra_hook_lines', [])
             if not re.search(r'\bX\b|\bY\b', l) and not (spec.get('return_to_camera') and _similar(l, T['return_line']))]
    lines += extra
    if spec.get('return_to_camera'):
        lines.append(T['return_line'])
    if has_x or has_y:
        line = T['scores_line']
        if not (has_x and has_y):  # only one score in the script -> only name that one
            line = re.sub(r'X\s+(und|et|e|y)\s+Y', 'X' if has_x else 'Y', line)
        lines.append(line)
    return lines


def _similar(a, b):
    wa, wb = set(re.findall(r'\w{4,}', a.lower())), set(re.findall(r'\w{4,}', b.lower()))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5


# Letters that must not appear in the finished text (leftovers from Balkan/Polish/Czech originals).
FOREIGN = 'čćđšłąęńśźżř'


def validate(spec, transcript, lang='de'):
    """Problems that block publishing (page goes to drafts instead)."""
    T = TEXT[lang]
    problems = []
    for key in ('page_title', 'title_hook', 'visual_hook_first', 'script'):
        if not spec.get(key):
            problems.append(f'missing {key}')
    texts = [spec.get('page_title', ''), spec.get('title_hook', ''), spec.get('visual_hook_first', '')]
    texts += [s.get('text', '') + ' ' + (s.get('asset_name') or '') for s in spec.get('script', [])]
    texts += spec.get('extra_hook_lines', [])
    blob = ' '.join(texts)
    if re.search(r'job\s*-?\s*step', blob, re.I):
        problems.append('"JobStep" appears in the page text')
    stop = set(T['stopwords'].split())
    words = re.findall(r"[a-zäöüßàâçéèêëîïôûùüÿœñáíóú’']+", ' '.join(s.get('text', '') for s in spec.get('script', [])).lower())
    if words and sum(w in stop for w in words) / len(words) < 0.08:
        problems.append(f"script does not look {T['lang_name']}")
    if re.search(f'[{FOREIGN}]', blob.lower()):
        problems.append(f"non-{T['lang_name']} characters left in the text")
    orig_words = len(transcript.get('text', '').split())
    new_words = sum(len(s.get('text', '').split()) for s in spec.get('script', []))
    if spec.get('voiceover', True) and orig_words >= 20:
        ratio = new_words / orig_words
        if not 0.75 <= ratio <= 1.25:
            problems.append(f'script length is {ratio:.0%} of the original (allowed 75–125%)')
    if not any(s.get('cue') == 'parakeet' for s in spec.get('script', [])):
        problems.append('no Parakeet AI moment in the script')
    return problems
