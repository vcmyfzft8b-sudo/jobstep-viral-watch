"""Inspiration videos in the creators' language: every market's format page gets a JobStep video of THAT format in
the market's language (DE page -> German video, FR -> French, ES -> Spanish).

For each active format and market:
1. The page's current inspiration video is kept if it already comes from a creator in that language.
2. Otherwise our best JobStep videos of the format from creators in that language are checked by Claude (right
   language? same format? promotes JobStep?) and the first that passes replaces the video on the page; the
   "Original on TikTok" link next to it is updated. Nothing else on the page changes.
3. Formats/markets without a suitable video are reported (Slack + printed).

Done formats are remembered in formats.json (fmt['inspo'][market]); the Monday run retries the missing ones.
"""
import re
import shutil
import tempfile
import time

from . import discover, llm, media, notion, tiktok
from .markets import TEXT

LANG_NAME = {'de': 'German', 'fr': 'French', 'es': 'Spanish'}


def _handle(url):
    m = re.search(r'@([^/?]+)/video', url or '')
    return m.group(1).lower() if m else None


def current_source(page_id):
    """The page's inspiration video block and the TikTok link right after it (or None if the page has no video)."""
    blocks = notion.children(page_id)
    i = next((k for k, b in enumerate(blocks) if b['type'] == 'video'), None)
    if i is None:
        return None
    for b in blocks[i + 1:i + 4]:
        for x in (b.get(b['type'], {}) or {}).get('rich_text', []) or []:
            url = ((x.get('text') or {}).get('link') or {}).get('url', '')
            if 'tiktok.com/@' in url:
                return {'video': blocks[i]['id'], 'link_block': b, 'url': url}
    return {'video': blocks[i]['id'], 'link_block': None, 'url': None}


def confirm(d, fmt, lang, model):
    prompt = f"""Our format: {fmt['title']} - {fmt.get('description', '')}
Script on our page (excerpt): {(fmt.get('script') or '')[:700]}

TikTok video by @{d['handle']}:
CAPTION: {d.get('desc') or '-'}
ON-SCREEN TEXT: {d.get('sticker') or '-'}
SPEECH: {(d.get('subtitles') or '-')[:1500]}

1) Which language is the video in (speech, else on-screen text)?
2) Is it the SAME format as ours (same premise / hook idea and structure - same topic alone is not enough)?
3) Does it promote JobStep (the CV app)?
Return JSON {{"language": "<English name of the language>", "same_format": true, "jobstep": true, "reason": "<short>"}}"""
    return llm.chat_json(model, 'You check TikTok videos for a marketing team. Reply with JSON only.', prompt, timeout=600)


def _relink(block, url):
    """Same text, every TikTok link pointing to the new video."""
    rich = []
    for x in block[block['type']].get('rich_text', []):
        link = ((x.get('text') or {}).get('link') or {}).get('url')
        if link and 'tiktok.com/@' in link:
            link = url
        rich.append({'type': 'text', 'text': {'content': x.get('plain_text', ''), 'link': {'url': link} if link else None},
                     'annotations': x.get('annotations', {})})
    notion.api('PATCH', f"/blocks/{block['id']}", {block['type']: {'rich_text': rich}})


def replace_video(page_id, src, d, lang):
    work = tempfile.mkdtemp(prefix='inspo-')
    try:
        upload = notion.upload_video(media.for_notion(media.download(d['url'], work), work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    r = notion.api('PATCH', f'/blocks/{page_id}/children', {
        'children': [notion.block('video', type='file_upload', file_upload={'id': upload})], 'after': src['video']})
    new_video = r['results'][-1]['id']
    notion.api('DELETE', f"/blocks/{src['video']}")
    if src['link_block']:
        _relink(src['link_block'], d['url'])
    else:
        notion.api('PATCH', f'/blocks/{page_id}/children', {
            'children': [notion.para([notion.rt(TEXT[lang]['source'], link=d['url'])])], 'after': new_video})


def run(fmts, mkts, history, accounts, meta, cfg, page_of, now=None, tries=4):
    """Returns [(format title, market, status, detail)]. status: kept | replaced | missing | no page | error."""
    now = now or time.time()
    langs = meta.setdefault('handle_lang', {})
    for h, a in accounts.items():
        if a.get('lang'):
            langs.setdefault(h, a['lang'])
    report = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        ranked = sorted(((vid, v) for vid, v in history.items() if v.get('format') == f['id']), key=lambda x: -x[1]['views'])[:60]
        for h in {v['handle'] for _, v in ranked} - set(langs):
            langs[h] = discover.language(h)
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            pid = page_of(f, m)
            if not pid:
                report.append((f['title'], m, 'no page', ''))
                continue
            if (f.get('inspo') or {}).get(m):
                report.append((f['title'], m, 'kept', f['inspo'][m]['url']))
                continue
            try:
                src = current_source(pid)
                if src is None:
                    report.append((f['title'], m, 'error', 'page has no video block'))
                    continue
                if src['url'] and langs.get(_handle(src['url'])) == lang:
                    f.setdefault('inspo', {})[m] = {'url': src['url'], 'at': int(now)}
                    report.append((f['title'], m, 'kept', src['url']))
                    continue
                found = None
                for vid, v in [(vid, v) for vid, v in ranked if langs.get(v['handle']) == lang][:tries]:
                    d = tiktok.video_detail(v['handle'], vid)
                    if not d:
                        continue
                    c = confirm(d, f, lang, cfg['models']['classify'])
                    if c.get('same_format') and c.get('jobstep') and LANG_NAME[lang].lower() in str(c.get('language', '')).lower():
                        found = d
                        break
                if not found:
                    report.append((f['title'], m, 'missing', f'no {LANG_NAME[lang]} JobStep video of this format yet'))
                    continue
                replace_video(pid, src, found, lang)
                f.setdefault('inspo', {})[m] = {'url': found['url'], 'views': found['views'], 'at': int(now)}
                report.append((f['title'], m, 'replaced', f"{found['url']} ({found['views'] // 1000}k views)"))
            except Exception as e:
                report.append((f['title'], m, 'error', str(e)[:150]))
    return report
