"""Read public TikTok data without a browser: the creator embed (latest videos) and each video's page."""
import json
import os
import re
import time

import requests

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
LAST_ERROR = {}


# Some videos are only available in Europe ("cross_border_violation" from US servers such as GitHub's).
# Those requests are retried through TIKTOK_PROXY (the workflow runs Tor with European exit nodes).
PROXY = os.environ.get('TIKTOK_PROXY', '')


def _new_session(proxy=False):
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'})
    if proxy and PROXY:
        s.proxies = {'http': PROXY, 'https': PROXY}
    return s


SESSION = _new_session()
STATS = {'direct_ok': 0, 'proxy_ok': 0, 'failed': 0}


def _get(url, tries=3, session=None):
    for attempt in range(tries):
        try:
            r = (session or SESSION).get(url, timeout=45)
            if r.status_code == 200 and r.text:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 4)
    return None


def latest_video_ids(handle):
    """IDs of a creator's latest videos (TikTok's official creator embed returns about 10)."""
    return [v['id'] for v in latest_videos(handle)]


def latest_videos(handle):
    """The creator embed's latest videos: [{'id', 'views', 'desc'}] (views also for Europe-only videos)."""
    html = _get(f'https://www.tiktok.com/embed/@{handle}')
    if not html:
        return []
    m = re.search(r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', html)
    if not m:
        return []
    data = json.loads(m.group(1))
    for key, value in data.get('source', {}).get('data', {}).items():
        if key.startswith('/embed/@') and isinstance(value, dict) and 'videoList' in value:
            return [{'id': v['id'], 'views': int(v.get('playCount') or 0), 'desc': v.get('desc', '')}
                    for v in value['videoList'] if v.get('id')]
    return []


def download(handle, video_id, out_path):
    """Download the MP4 from the video page data (same session/cookies as the page request). True on success."""
    url = f'https://www.tiktok.com/@{handle}/video/{video_id}'
    for proxy in ([False, True] if PROXY else [False]):
        for _ in range(2):
            sess = _new_session(proxy=proxy)
            item, _err = _item(url, session=sess)
            if not item:
                continue
            video = item.get('video') or {}
            candidates = [video.get('playAddr'), video.get('downloadAddr')]
            candidates += [b.get('PlayAddr', {}).get('UrlList', [None])[0] for b in (video.get('bitrateInfo') or [])]
            for src in [c for c in candidates if c]:
                try:
                    r = sess.get(src, headers={'Referer': 'https://www.tiktok.com/', 'Range': 'bytes=0-'}, timeout=120)
                except requests.RequestException:
                    continue
                if r.status_code in (200, 206) and len(r.content) > 100_000:
                    with open(out_path, 'wb') as f:
                        f.write(r.content)
                    return True
            time.sleep(3)
    return False


def _item(url, session=None):
    html = _get(url, session=session)
    if not html:
        return None, 'no response'
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html)
    if not m:
        return None, 'no data script (blocked/captcha?)'
    try:
        detail = json.loads(m.group(1))['__DEFAULT_SCOPE__']['webapp.video-detail']
    except (KeyError, json.JSONDecodeError):
        return None, 'no video-detail block'
    item = (detail.get('itemInfo') or {}).get('itemStruct')
    if not item or not item.get('id'):
        return None, f"statusCode {detail.get('statusCode')} {detail.get('statusMsg', '')}".strip()
    return item, None


def video_detail(handle, video_id):
    """Stats, on-screen text and TikTok's own subtitles for one video; None if unavailable."""
    global SESSION
    url = f'https://www.tiktok.com/@{handle}/video/{video_id}'
    time.sleep(0.7)
    item, err = _item(url)
    if not item and err and '10231' not in err:  # second chance with fresh cookies
        time.sleep(5)
        SESSION = _new_session()
        item, err = _item(url)
    if item:
        STATS['direct_ok'] += 1
    elif PROXY:  # Europe-only video (or blocked): go through the European route
        for _ in range(3):
            item, err = _item(url, session=_new_session(proxy=True))
            if item:
                STATS['proxy_ok'] += 1
                break
            time.sleep(3)
    if not item:
        STATS['failed'] += 1
        LAST_ERROR[video_id] = err
        return None
    stats = item.get('statsV2') or item.get('stats') or {}
    sticker = ' / '.join(t for st in (item.get('stickersOnItem') or []) for t in st.get('stickerText', []))
    subtitles = ''
    infos = item.get('video', {}).get('subtitleInfos') or []
    if infos:
        vtt = _get(infos[0]['Url'], tries=1) or ''
        subtitles = ' '.join(line for line in vtt.splitlines()
                             if line and '-->' not in line and not line.startswith('WEBVTT') and not line.isdigit())
    return {
        'id': video_id,
        'handle': handle,
        'url': url,
        'created': int(item.get('createTime') or 0),
        'duration': item.get('video', {}).get('duration', 0),
        'desc': item.get('desc', ''),
        'sticker': sticker,
        'subtitles': subtitles[:3000],
        'views': int(stats.get('playCount', 0)),
        'likes': int(stats.get('diggCount', 0)),
        'comments': int(stats.get('commentCount', 0)),
        'shares': int(stats.get('shareCount', 0)),
        'saves': int(stats.get('collectCount', 0)),
    }


def mentions_jobstep(handle, sample=3):
    """True if any of the creator's latest videos mention JobStep (used to accept discovered accounts)."""
    for vid in latest_video_ids(handle)[:sample]:
        d = video_detail(handle, vid)
        if d and re.search(r'job\s*step', ' '.join([d['desc'], d['sticker'], d['subtitles']]), re.I):
            return True
    return False
