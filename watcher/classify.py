"""Which of our formats is this video? Or is it a new one?"""

from . import llm

SYSTEM = """You sort short-form TikTok videos (CV / job-search app promotions by JobStep creators, any language)
into content FORMATS. A format = the hook + premise + structure, independent of language and wording.
Reply with JSON only."""


def _listing(formats):
    """Every format we have in Notion: the active list AND the archive."""
    return '\n'.join(f"- {f['id']}{' (archived)' if f.get('status') != 'active' else ''}: {f['description']}"
                     for f in formats if f.get('description'))


def classify(video, formats, model, transcript=''):
    listing = _listing(formats)
    prompt = f"""All formats we already have in Notion (active list + archive):
{listing}

Video (@{video['handle']}, {video['views']} views):
ON-SCREEN TEXT: {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH: {(transcript or video.get('subtitles') or '-')[:2500]}

Does this video use one of our formats? Match when the CORE MESSAGE / premise is the same as a format, even if the
hook is worded differently (e.g. "HR hates these CVs" and "nobody reads your CV" are both the ATS-rejects-pretty-CVs
format). Only call it new when the premise itself is different - not just because many videos mention ATS or CVs in
passing.
Return JSON:
{{"match": "<format id or null>", "confidence": "high|med|low",
  "hook_en": "<the video's hook in English, short>",
  "new_format_description": "<if no match: one-sentence description of this format, in the same style as the list>"}}"""
    result = llm.chat_json(model, SYSTEM, prompt, max_tokens=800, temperature=0)
    if result.get('match') in ('null', '', 'None'):
        result['match'] = None
    return result


def confirm_new(video, formats, model, transcript=''):
    """Second, stricter check with the strong model right before a page is built: is this format really not in
    Notion yet (neither in the list nor in the archive)? Returns the id of the existing format, or None."""
    prompt = f"""All formats we already have in Notion (active list + archive):
{_listing(formats)}

Viral video (@{video['handle']}):
ON-SCREEN TEXT: {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH: {(transcript or video.get('subtitles') or '-')[:3000]}

Is this video's format already one of the formats above (same core premise / hook idea and structure, even if
worded differently or in another language)? Same topic (CVs, ATS) alone is NOT enough.
Return JSON {{"duplicate_of": "<format id or null>", "reason": "<short>"}}"""
    r = llm.chat_json(model, SYSTEM, prompt, max_tokens=600, temperature=0)
    dup = r.get('duplicate_of')
    return None if dup in (None, '', 'null', 'None') else dup
