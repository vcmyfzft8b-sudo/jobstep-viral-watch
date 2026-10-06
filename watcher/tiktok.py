"""Read public TikTok data without a browser: the creator embed (latest videos) and each video's page."""
import json
import re
import time

import requests

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': UA, 'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'})


def _get(url, tries=3):
    for attempt in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200 and r.text:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 4)
    return None


def latest_video_ids(handle):
    """IDs of a creator's latest videos (TikTok's official creator embed returns about 10)."""
    html = _get(f'https://www.tiktok.com/embed/@{handle}')
    if not html:
        return []
    m = re.search(r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', html)
    if not m:
        return []
    data = json.loads(m.group(1))
    for key, value in data.get('source', {}).get('data', {}).items():
        if key.startswith('/embed/@') and isinstance(value, dict) and 'videoList' in value:
            return [v['id'] for v in value['videoList'] if v.get('id')]
    return []


def video_detail(handle, video_id):
    """Stats, on-screen text and TikTok's own subtitles for one video; None if unavailable."""
    url = f'https://www.tiktok.com/@{handle}/video/{video_id}'
    html = _get(url)
    if not html:
        return None
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html)
    if not m:
        return None
    try:
        item = json.loads(m.group(1))['__DEFAULT_SCOPE__']['webapp.video-detail']['itemInfo']['itemStruct']
    except (KeyError, json.JSONDecodeError):
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
