"""Turn a viral JobStep video into a Parakeet format page spec (DE/FR/ES, same structure as our existing pages)."""
import os
import re

from . import llm

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, '..', 'registry', 'examples')

from .brands import OTHER_NOTE, SOURCE_RE
from .markets import TEXT

# Kept for older callers (DACH texts); the per-language texts live in markets.TEXT.
INSPO_NOTE = TEXT['de']['inspo_note']
REQUIRED_LINE = TEXT['de']['required_line']

TRANSCRIBE = """- The SCRIPT IS THE ORIGINAL'S OWN WORDS - never reword it:
  * original in {lang}: the script is the original's transcript, word for word (fix only obvious speech-to-text
    mistakes; filler like "ähm" may go);
  * original in another language: translate it faithfully and closely, sentence by sentence, into natural spoken
    {lang} ({style}) - no rewording beyond what the translation needs; adapt country-specific things (job sites,
    companies, places) to {country}.
  Same sentences, same order, add nothing, drop nothing. The ONLY changes:
  * JobStep -> "Parakeet AI" exactly where (and as often as) the original names it, jobstep.io ->
    parakeet-ai.com/resume-maker. If the original only shows the app ("this tool here"), only show it too. The words
    "JobStep" or "Job Step" must not appear anywhere in your output.
  * a JobStep feature Parakeet AI does not have -> the closest Parakeet AI feature (change as few words as possible);
  * concrete scores/percentages the app shows -> X (before) and Y (after) - creators read their own numbers;
  * a promise nobody can guarantee (e.g. "guaranteed job in 24h") -> the smallest change that makes it honest
    ("better chances")."""

VISUAL_HOOK = """1-2 short sentences (no more) on the visual hook: if the original does something specific in
  its first seconds (an action, a prop, a place, a text on screen), tell the creator to copy exactly that, like in the
  example video; if it does nothing special, tell them to pick a hook from the Visual Hook Lab (linked right below)."""

SYSTEM = """You write creator instructions for Parakeet AI (an AI CV maker, https://www.parakeet-ai.com/resume-maker)
UGC campaigns. You turn viral videos made by JobStep creators (a competing CV app) into the same video for Parakeet AI:
the script is the original's transcript (translated if needed), only with Parakeet AI instead of JobStep. Reply with
JSON only."""

RULES = """RULES
- Output language for ALL creator-facing text (page_title, title_hook, script, visual_hook_first, asset
  names/descriptions, directions): {lang}.
""" + TRANSCRIBE + """
- Every moment where the original video SHOWS the CV app on screen gets cue "parakeet". Where it shows LinkedIn job
  search, cue "linkedin". Plain stage directions (e.g. surprised reaction, music, "open google.com") use cue
  "direction" with the direction as text in asset_name. Otherwise cue null. Put the cue on the segment where that
  screen starts.
- CVs are NEVER assets: creators show their own old CV and the CV they make in Parakeet AI (cue "parakeet").
- Public websites/apps the creator can simply open and film (a discount page, a job board, Google) are NOT assets:
  use cue "direction" with the exact page to open as asset_name.
- Only things a creator cannot make or open themselves count as assets (cue "asset", e.g. an email inbox full of
  interview invites).
- No voiceover videos (only on-screen text + music): set voiceover=false; each script segment is one text overlay.
- title_hook: the original's on-screen hook/title - word for word if it is in {lang}, else translated (keep
  caps/emojis style), JobStep -> Parakeet AI.
- page_title: short {lang} hook for the Notion page name + one emoji at the end.
- Address creators neutrally (informal "you"), never with a gendered word for "creator".
- visual_hook_first: """ + VISUAL_HOOK

PARAKEET_FACTS = """What Parakeet AI's Resume Maker can do (only show/mention these): upload your CV, get a score/analysis,
paste the link (or text) of a job ad, answer questions in a chat, let the AI rewrite/tailor the CV to the job, pick a
template, edit everything yourself, download it. It does NOT have: an overview of your applications, a "New job"
button, cover letters. If the original shows a JobStep feature Parakeet AI doesn't have, replace that sentence with an
equivalent step that exists (keep the sentence count, change as few words as possible).""" + OTHER_NOTE


COUNTRY = {'de': 'Germany/Austria/Switzerland', 'fr': 'France', 'es': 'Spain'}

SCHEMA = """Return JSON:
{"page_title": "...", "icon": "<one emoji>", "title_hook": "...", "voiceover": true,
 "script": [{"cue": "parakeet|linkedin|asset|direction|null", "asset_name": "", "text": "...", "new_paragraph": false}],
 "visual_hook_first": "<1-2 short sentences>",
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
    content = [{'type': 'text', 'text': f"""Our existing pages (German - follow their structure (cues, title, page layout), write in {T['lang_name']}):
{_examples()}

{rules}
{PARAKEET_FACTS}

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
    """The visual hook section: 1-2 short sentences (copy the example's opening, or pick one from the Visual Hook Lab).
    The Visual Hook Lab link itself is added below by the page layout."""
    return [spec['visual_hook_first'].strip()] if spec.get('visual_hook_first', '').strip() else []


ABBREV = re.compile(r'\b(z|d|u|o|v|s|ca|bzw|etc|evtl|ggf|inkl|usw|vs|ex|ej|p|cf|env|aprox)\.\s?(?:[a-zA-Z]{1,2}\.)?', re.I)


def sentences(text):
    """Number of sentences ('z. B.', 'p. ex.', '...', quotes and emojis do not end a sentence)."""
    t = re.sub(r'„[^“”"]*[“”"]|"[^"]*"|«[^»]*»|“[^”]*”',  # a quote from the video is one phrase
               lambda m: 'Q.' if re.search(r'[.!?]\W*$', m.group()) else 'Q', text or '')
    t = ABBREV.sub('', t)
    t = re.sub(r'\.{2,}|…', ',', t)
    return len([x for x in re.split(r'[.!?]+(?:\s|$)', t.strip()) if re.search(r'\w', x)])


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
    blob = ' '.join(texts)
    if SOURCE_RE.search(blob):
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
        same = (transcript.get('language') or '')[:2] == lang  # a translation may need a few more words
        top, allowed = (1.12, '110%') if same else (1.35, '135%')
        if not 0.8 <= ratio <= top:
            problems.append(f'script length is {ratio:.0%} of the original (allowed 80–{allowed})')
    if sentences(spec.get('visual_hook_first', '')) > 2:
        problems.append('visual hook is longer than 2 sentences')
    if not any(s.get('cue') == 'parakeet' for s in spec.get('script', [])):
        problems.append('no Parakeet AI moment in the script')
    return problems
