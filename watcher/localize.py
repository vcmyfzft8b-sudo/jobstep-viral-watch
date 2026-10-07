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
MIN_VIEWS = 10_000  # an inspiration video must be proven, not just in the right language


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
    """Strict check with the strong model: the video must be the SAME format as our page (full script compared),
    in the market's language, and promote JobStep. Returns the verdict dict; ok() decides."""
    prompt = f"""OUR FORMAT: {fmt['title']}
What it is: {fmt.get('description', '')}
Full script on our page:
{(fmt.get('script') or '')[:2500]}

CANDIDATE TikTok video by @{d['handle']}:
CAPTION: {d.get('desc') or '-'}
ON-SCREEN TEXT: {d.get('sticker') or '-'}
SPEECH: {(d.get('subtitles') or '-')[:2500]}

Creators will copy this video's pacing, visuals and structure while saying OUR script, so it must really be the
same format: same premise, same hook idea, same story/structure (e.g. same "problem -> reveal -> app" beats). Same
topic alone (CVs, ATS, job search) is NOT enough. Be strict.
Return JSON {{"language": "<English name of the video's language>", "match": "same|similar|different",
"confidence": "high|medium|low", "jobstep": true, "reason": "<one sentence>"}}"""
    return llm.chat_json(model, 'You check TikTok videos for a marketing team. Reply with JSON only.', prompt, timeout=900)


def ok(c, lang):
    return (c.get('match') == 'same' and c.get('confidence') == 'high' and c.get('jobstep')
            and LANG_NAME[lang].lower() in str(c.get('language', '')).lower())


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


def add_section(page_id, d, lang):
    """Page without an inspiration video (older FR/ES pages): add the whole section at the top in its language."""
    T = TEXT[lang]
    work = tempfile.mkdtemp(prefix='inspo-')
    try:
        upload = notion.upload_video(media.for_notion(media.download(d['url'], work), work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    section = [notion.block('heading_1', [notion.rt(T['video_heading'])]),
               notion.block('video', type='file_upload', file_upload={'id': upload}),
               notion.para([notion.rt(T['source'], link=d['url'])]),
               notion.block('callout', notion.md('\n'.join(T['inspo_note'])), icon={'type': 'emoji', 'emoji': '⚠️'},
                            color='gray_background'),
               notion.block('divider')]
    try:
        notion.api('PATCH', f'/blocks/{page_id}/children', {'children': section, 'position': {'type': 'start'}},
                   version='2025-09-03')
    except Exception as e:  # if inserting at the top is refused: put it at the end of the page instead
        print('top insert refused, adding at the end:', str(e)[:150])
        notion.api('PATCH', f'/blocks/{page_id}/children', {'children': section})


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
                if src and src['url'] and langs.get(_handle(src['url'])) == lang:
                    f.setdefault('inspo', {})[m] = {'url': src['url'], 'at': int(now)}
                    report.append((f['title'], m, 'kept', src['url']))
                    continue
                found = None
                for vid, v in [(vid, v) for vid, v in ranked if langs.get(v['handle']) == lang and v['views'] >= MIN_VIEWS][:tries]:
                    d = tiktok.video_detail(v['handle'], vid)
                    if not d:
                        continue
                    c = confirm(d, f, lang, cfg['models']['build'])
                    if ok(c, lang) and d['views'] >= MIN_VIEWS:
                        found = d
                        break
                if not found:
                    report.append((f['title'], m, 'missing', f'no {LANG_NAME[lang]} JobStep video of this format yet'))
                    continue
                if src:
                    replace_video(pid, src, found, lang)
                else:
                    add_section(pid, found, lang)
                f.setdefault('inspo', {})[m] = {'url': found['url'], 'views': found['views'], 'at': int(now),
                                                'prev': src['url'] if src else None, 'strict': True}
                report.append((f['title'], m, 'replaced', f"{found['url']} ({found['views'] // 1000}k views)"))
            except Exception as e:
                report.append((f['title'], m, 'error', str(e)[:150]))
    return report


def recheck(fmts, mkts, history, accounts, meta, cfg, page_of, now=None):
    """Re-checks every video an earlier (less strict) run put on a page. If it does not pass the strict check it is
    replaced by one that does, or - if there is none - the page gets its previous video back (format first,
    language second). Returns the report like run()."""
    now = now or time.time()
    report = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            x = (f.get('inspo') or {}).get(m)
            if not x or x.get('strict') or 'views' not in x:
                continue  # nothing replaced, or already strictly checked
            h = _handle(x['url'])
            vid = re.search(r'/video/(\d+)', x['url']).group(1)
            d = tiktok.video_detail(h, vid)
            c = confirm(d, f, lang, cfg['models']['build']) if d else {}
            if d and ok(c, lang) and d['views'] >= MIN_VIEWS:
                x['strict'] = True
                report.append((f['title'], m, 'confirmed', x['url']))
                continue
            print('failed strict check:', f['title'], m, x['url'], c.get('reason', ''))
            prev = x.get('prev')
            f['inspo'].pop(m)
            r = run([f], [mk], history, accounts, meta, cfg, page_of, now)  # tries the next candidates (strict)
            if r and r[0][2] == 'replaced':
                report.append(r[0])
                continue
            back = prev or f.get('source_video')
            pid = page_of(f, m)
            src = current_source(pid)
            bd = tiktok.video_detail(_handle(back), re.search(r'/video/(\d+)', back).group(1)) if back else None
            if bd and src:
                replace_video(pid, src, bd, lang)
                report.append((f['title'], m, 'restored', f"{back} (no {LANG_NAME[lang]} video passed the strict check)"))
            else:
                report.append((f['title'], m, 'error', 'failed strict check and the previous video could not be restored'))
    return report
