"""Which of our formats is this video? Or is it a new one?"""

from . import llm

SYSTEM = """You sort short-form TikTok videos (CV / job-search app promotions by JobStep creators, any language)
into content FORMATS. A format = the hook + premise + structure, independent of language and wording.
Reply with JSON only."""


def classify(video, formats, model, transcript=''):
    listing = '\n'.join(f"- {f['id']}: {f['description']}" for f in formats if f.get('status') == 'active')
    prompt = f"""Our current formats:
{listing}

Video (@{video['handle']}, {video['views']} views):
ON-SCREEN TEXT: {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH: {(transcript or video.get('subtitles') or '-')[:2500]}

Does this video use one of our formats (same hook/premise and structure)? Only match when the MAIN hook/premise
is the same - many videos mention ATS or CVs in passing.
Return JSON:
{{"match": "<format id or null>", "confidence": "high|med|low",
  "hook_en": "<the video's hook in English, short>",
  "new_format_description": "<if no match: one-sentence description of this format, in the same style as the list>"}}"""
    result = llm.chat_json(model, SYSTEM, prompt, max_tokens=800, temperature=0)
    if result.get('match') in ('null', '', 'None'):
        result['match'] = None
    return result
