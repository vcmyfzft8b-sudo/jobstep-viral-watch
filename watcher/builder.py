"""Turn a viral JobStep video into a German Parakeet format page spec (same structure as our existing pages)."""
import os
import re

from . import llm

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, '..', 'registry', 'examples')

APP_LINE = ('Sobald Parakeet AI ins Spiel kommt, filmst du dich selbst, wie du die App am Laptop nutzt – an jeder Stelle '
            'mit Link im Skript. Ladezeiten schneidest du raus.')
LINKEDIN_LINE = 'Beim LinkedIn-Link filmst du, wie du eine Stellenanzeige kopierst. '
RETURN_LINE = 'Für den letzten Satz wieder zurück in die Kamera.'
SCORES_LINE = 'X und Y im Skript: Lies die Punktzahl vor, die dir die App anzeigt.'
REQUIRED_LINE = '🚨👇 Ein visueller Hook ist für jedes Video Pflicht!'
INSPO_NOTE = [
    '**Wichtig:** Dreh dein Video nach dem deutschen Skript unten. Das Inspirationsvideo zeigt dir nur Tempo, Vibe, '
    'Licht und Kamerawinkel – und was du auf dem Bildschirm zeigst und wie du die App zeigst.',
    'Im Video wird JobStep genutzt. Mach es genau gleich, nur mit Parakeet AI: Zeig alles, was im Inspirationsvideo '
    'gezeigt wird – öffne Parakeet AI an den Stellen, an denen JobStep geöffnet wird, und zeig es genauso. JobStep darf '
    'in deinem Video nirgends zu sehen oder zu hören sein.',
]

SYSTEM = """You write German creator instructions for Parakeet AI (an AI CV maker, https://www.parakeet-ai.com/resume-maker)
UGC campaigns in Germany/Austria/Switzerland. You adapt viral videos made by JobStep creators (a competing CV app)
into the same format for Parakeet AI. Reply with JSON only."""

RULES = """RULES
- Script language: casual spoken German like a real TikTok creator (du-Form, natural, not formal, not a literal
  translation). Same meaning, same beats, same order, roughly the same length as the original speech (±25%).
  If the original is already German, keep the wording close and only change what is needed for Parakeet AI.
- Replace JobStep with Parakeet AI everywhere (jobstep.io -> parakeet-ai.com/resume-maker). The words "JobStep" or
  "Job Step" must not appear anywhere in your output.
- Concrete scores/percentages the app shows become X (before) and Y (after) - creators read their own numbers.
- Tone down promises nobody can guarantee (e.g. "guaranteed job in 24h").
- Every moment where the original video SHOWS the CV app on screen gets cue "parakeet". Where it shows LinkedIn job
  search, cue "linkedin". Where it shows something else that the creator cannot film in Parakeet AI (an email inbox,
  a document, a website, a prop) use cue "asset" and describe it in asset_name (short German name). Plain stage
  directions (e.g. "überraschte Reaktion, Musik") use cue "direction" with the direction as text in asset_name.
  Otherwise cue null. Put the cue on the segment where that screen starts.
- CVs are NEVER assets: creators show their own old CV and the CV they make in Parakeet AI (cue "parakeet").
- Public websites/apps the creator can simply open and film (a discount page, a job board, Google) are NOT assets:
  use cue "direction" with a short German direction like "Prime-Student-Seite am Laptop zeigen" and add one
  extra_hook_lines entry with the exact page to open.
- Only things a creator cannot make or open themselves count as assets (e.g. an email inbox full of interview
  invites). For every asset, add one extra_hook_lines entry that says how to show it (German).
- Address creators neutrally (du / "Creator"), never "Creatorin".
- No voiceover videos (only on-screen text + music): set voiceover=false; each script segment is one text overlay.
- title_hook: the on-screen hook/title of the original, adapted to punchy German (keep caps/emojis style).
- page_title: short German hook for the Notion page name + one emoji at the end (like the examples' style:
  "Niemand liest deinen Lebenslauf? Schau hier hin 👀").
- visual_hook_first: one German sentence telling the creator what to do in the first seconds, based on what the
  original creator does in the first 3 seconds (action/prop + speaking to camera + title on screen).
- return_to_camera: true if the original goes back to talking to the camera for the last line(s).
- extra_hook_lines: 0-2 extra German lines only if the original needs special filming instructions."""

SCHEMA = """Return JSON:
{"page_title": "...", "icon": "<one emoji>", "title_hook": "...", "voiceover": true,
 "script": [{"cue": "parakeet|linkedin|asset|direction|null", "asset_name": "", "text": "...", "new_paragraph": false}],
 "visual_hook_first": "...", "return_to_camera": true, "extra_hook_lines": [],
 "has_scores": false, "assets_needed": [{"name": "<German>", "description": "<German: what it must show>"}],
 "registry_description": "<one English sentence describing the format, for matching future videos>",
 "summary_en": "<2 sentences: what the original video does and why it works>"}"""


def _examples():
    out = []
    for name in sorted(os.listdir(EXAMPLES)):
        with open(os.path.join(EXAMPLES, name)) as f:
            out.append(f'--- EXAMPLE PAGE {name} ---\n' + f.read())
    return '\n'.join(out)


def build_spec(video, transcript, frames, model):
    """video: tiktok.video_detail dict; transcript: soniox result; frames: [(seconds, path)]."""
    timed = '\n'.join(f"[{s['start']:.1f}-{s['end']:.1f}s] {s['text']}" for s in transcript.get('segments', [])) or '(no speech)'
    content = [{'type': 'text', 'text': f"""Our existing German pages (follow this style exactly):
{_examples()}

{RULES}

ORIGINAL VIDEO (@{video['handle']}, {video['views']} views, {video['duration']}s, language: {transcript.get('language') or '?'})
ON-SCREEN TEXT (TikTok text stickers): {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH WITH TIMESTAMPS (Soniox):
{timed}

The following images are frames from the video; each is preceded by its timestamp. Use them to see the visual hook,
what is shown on screen and when the app appears.

{SCHEMA}"""}]
    for t, path in frames:
        content.append({'type': 'text', 'text': f'Frame at {t:.1f}s:'})
        content.append(llm.image_part(path))
    spec = llm.chat_json(model, SYSTEM, content, max_tokens=8000, temperature=0.4)
    for seg in spec.get('script', []):
        if seg.get('cue') in ('null', 'None', ''):
            seg['cue'] = None
    return spec


def hook_lines(spec):
    cues = {s.get('cue') for s in spec.get('script', [])}
    lines = [spec['visual_hook_first']]
    app = APP_LINE if 'parakeet' in cues else ''
    if 'linkedin' in cues:
        app = LINKEDIN_LINE + app
    if app.strip():
        lines.append(app.strip())
    lines += spec.get('extra_hook_lines', [])
    if spec.get('return_to_camera'):
        lines.append(RETURN_LINE)
    if spec.get('has_scores') or any(re.search(r'\b[XY]\b', s['text']) for s in spec.get('script', [])):
        lines.append(SCORES_LINE)
    return lines


GERMAN_WORDS = set('der die das und ist ich du nicht ein eine zu mit auf für den dem es sie wir ihr mein dein '
                   'was wie hab habe hat sind auch noch dann so aber wenn schon mal einfach jetzt hier da'.split())


def validate(spec, transcript):
    """Problems that block publishing (page goes to drafts instead)."""
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
    words = re.findall(r'[a-zäöüß]+', ' '.join(s.get('text', '') for s in spec.get('script', [])).lower())
    if words and sum(w in GERMAN_WORDS for w in words) / len(words) < 0.08:
        problems.append('script does not look German')
    if re.search(r'[čćđšłąęńśźżř]', blob.lower()):
        problems.append('non-German characters left in the text')
    orig_words = len(transcript.get('text', '').split())
    new_words = sum(len(s.get('text', '').split()) for s in spec.get('script', []))
    if spec.get('voiceover', True) and orig_words >= 20:
        ratio = new_words / orig_words
        if not 0.75 <= ratio <= 1.25:
            problems.append(f'script length is {ratio:.0%} of the original (allowed 75–125%)')
    if not any(s.get('cue') == 'parakeet' for s in spec.get('script', [])):
        problems.append('no Parakeet AI moment in the script')
    return problems
