"""Which of our formats is this video? Or is it a new one?"""

from . import llm

SYSTEM = """You sort short-form TikTok videos (CV / job-search app promotions by JobStep creators, any language)
into content FORMATS. A format = the hook + premise + structure, independent of language and wording.
Reply with JSON only."""


def _listing(formats, with_script=False):
    """Every format we have in Notion: the active list AND the archive (optionally with its script text)."""
    lines = []
    for f in formats:
        if not f.get('description'):
            continue
        line = f"- {f['id']}{' (archived)' if f.get('status') != 'active' else ''}: {f['description']}"
        if with_script and f.get('script'):
            line += f"\n    Script on our page: {f['script'][:700]}"
        lines.append(line)
    return '\n'.join(lines)


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
    prompt = f"""All formats we already have in Notion (active list + archive), with the script from each page:
{_listing(formats, with_script=True)}

Viral video (@{video['handle']}):
ON-SCREEN TEXT: {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH: {(transcript or video.get('subtitles') or '-')[:3000]}

Is this video's format already one of the formats above (same core premise / hook idea and structure, even if
worded differently or in another language)? Compare the story/premise, the hook and how the video is built.
Same topic (CVs, ATS) alone is NOT enough - but if the video tells the same story as one of our pages (e.g.
"months/a whole summer of rejections -> changed my CV -> now lots of interview invites"), it IS that format.
We never want duplicates: when you are unsure, answer with the closest existing format.
Return JSON {{"duplicate_of": "<format id or null>", "reason": "<short>"}}"""
    r = llm.chat_json(model, SYSTEM, prompt, max_tokens=600, temperature=0)
    dup = r.get('duplicate_of')
    return None if dup in (None, '', 'null', 'None') else dup


def classify_many(videos, formats, model, batch=25):
    """Sort many videos in few requests (25 per request). Returns {video_id: {'match', 'hook_en'}}."""
    out = {}
    for i in range(0, len(videos), batch):
        chunk = videos[i:i + batch]
        items = '\n\n'.join(f"VIDEO {v['id']} (@{v['handle']}):\nON-SCREEN TEXT: {v.get('sticker') or '-'}\n"
                              f"CAPTION: {(v.get('desc') or '-')[:300]}\nSPEECH: {(v.get('subtitles') or '-')[:900]}"
                              for v in chunk)
        prompt = f"""All formats we already have in Notion (active list + archive):
{_listing(formats)}

Sort each of these videos. Match a format when the CORE premise is the same (even if worded differently);
same topic (CVs/ATS) alone is not enough. Use null when it is none of them.

{items}

Return JSON {{"results": [{{"id": "<video id>", "match": "<format id or null>", "hook_en": "<short English hook>"}}]}}"""
        try:
            r = llm.chat_json(model, SYSTEM, prompt, timeout=900)
        except Exception as e:
            print('batch classify failed:', str(e)[:200])
            continue
        for x in r.get('results', []):
            m = x.get('match')
            out[str(x.get('id'))] = {'match': None if m in (None, '', 'null', 'None') else m, 'hook_en': x.get('hook_en', '')}
    return out


def judge(video, formats, model, transcript='', translate=True):
    """The definitive check for a viral video (strong model): is its format already in Notion (list or archive)?
    Also translates the script to English for the Slack message.
    Returns {'duplicate_of', 'reason', 'english_script', 'hook_en', 'new_format_description'}."""
    translate_task = ('2) Translate the full script into natural English (spoken lines; if there is no speech, the on-screen '
                      'texts), keeping the line order. Replace nothing - translate what is said.') if translate else ''
    translate_field = ',\n"english_script": "<the translated script, line breaks between sentences>"' if translate else ''
    prompt = f"""All formats we already have in Notion (active list + archive), with the script from each page:
{_listing(formats, with_script=True)}

Viral TikTok video (@{video['handle']}):
ON-SCREEN TEXT: {video.get('sticker') or '-'}
CAPTION: {video.get('desc') or '-'}
SPEECH (transcript): {(transcript or video.get('subtitles') or '-')[:6000]}

1) Is this video's format already one of the formats above? Compare the story/premise, the hook and how the video
   is built - not just the topic (CVs/ATS alone is NOT enough). If it tells the same story as one of our pages, it
   IS that format, even if worded differently or in another language. We never want duplicates: if you are unsure,
   answer with the closest existing format.
{translate_task}
Return JSON {{"duplicate_of": "<format id or null>", "reason": "<one sentence why>",
"hook_en": "<the hook in English>", "new_format_description": "<if new: one English sentence describing the format>"{translate_field}}}"""
    r = llm.chat_json(model, SYSTEM, prompt, timeout=1200)
    if r.get('duplicate_of') in (None, '', 'null', 'None'):
        r['duplicate_of'] = None
    return r
