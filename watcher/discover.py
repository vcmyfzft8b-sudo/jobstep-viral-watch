"""Keep the list of JobStep creator accounts complete (runs every few days).

- Lightreel (LIGHTREEL_API_KEY) is asked for every account promoting JobStep; new handles are verified with
  TikTok's creator embed: posted in the last 30 days AND JobStep in their captions or videos.
- Accounts that stop posting JobStep content for 30 days are paused (not fetched every 6 h) and re-checked
  on every discovery run, so they come back automatically.
"""
import os
import re
import time

import requests

from . import tiktok

QUESTION = """Today is {today}. Give me a COMPLETE list of every TikTok account that posted sponsored, affiliate or
creator-program videos for JobStep (jobstep.io, the AI CV/resume builder) in the last 30 days, in ANY language/market
(Balkans, Germany/Austria/Switzerland, Poland, France, Italy, Spain, Portugal, Netherlands, Nordics, Hungary, Czechia,
Bulgaria, Romania, Turkey, UK, US and others). Many are named like "<name>.jobtipps", "<name>.jobtips",
"<name>.jobstep.io", "<name>jobstep", "job.by.<name>", "<name>cvtips", but include normal career/lifestyle creators too.
Be exhaustive. Already known (you may skip them): {known}
Answer with one line per account exactly like: ACCOUNT | @handle | market"""


def check_account(handle, max_days=30):
    """'active', 'inactive' or 'invalid' for one TikTok account."""
    vids = tiktok.latest_videos(handle)
    if not vids:
        return 'invalid'
    newest = max(int(v['id']) >> 32 for v in vids)
    recent = (time.time() - newest) / 86400 <= max_days
    jobstep = any(re.search(r'job\s*step', v['desc'], re.I) for v in vids)
    if not jobstep:
        for v in vids[:3]:
            d = tiktok.video_detail(handle, v['id'])
            if d and re.search(r'job\s*step', ' '.join([d['desc'], d['sticker'], d['subtitles']]), re.I):
                jobstep = True
                break
    return 'active' if (recent and jobstep) else 'inactive'


def lightreel_handles(known, question=None):
    key = os.environ.get('LIGHTREEL_API_KEY')
    if not key:
        return set()
    q = (question or QUESTION).format(today=time.strftime('%d %B %Y'), known=', '.join('@' + h for h in sorted(known)))
    try:
        r = requests.post('https://api.lightreel.ai/v1/chat', json={'question': q}, timeout=1500,
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        answer = r.json().get('answer', '') if r.ok else ''
    except (requests.RequestException, ValueError):
        return set()
    return {h.lower().rstrip('.') for h in re.findall(r'@([A-Za-z0-9._]{2,30})', answer)}


def refresh(accounts):
    """accounts: {handle: {'status': 'active'|'inactive'|'manual', 'since': ts, ...}} -> (accounts, added, paused, revived)."""
    added, paused, revived = [], [], []
    for h in sorted(lightreel_handles(set(accounts)) - set(accounts)):
        if check_account(h) == 'active':
            accounts[h] = {'status': 'active', 'since': int(time.time()), 'source': 'lightreel'}
            added.append(h)
    for h, info in accounts.items():
        if info['status'] == 'manual' or h in added:
            continue  # manually confirmed JobStep creators are always tracked
        status = check_account(h)
        if status == 'invalid':
            continue
        if info['status'] == 'active' and status == 'inactive':
            info['status'] = 'inactive'
            paused.append(h)
        elif info['status'] == 'inactive' and status == 'active':
            info['status'] = 'active'
            revived.append(h)
        info['checked'] = int(time.time())
    return accounts, added, paused, revived


def language(handle):
    """'de', 'fr' or 'es' if the account's captions are mostly in that language, else ''."""
    from .markets import TEXT
    words = re.findall(r"[a-zäöüßàâçéèêëîïôûùÿœñáíóú’']+", ' '.join(v['desc'] for v in tiktok.latest_videos(handle)).lower())
    if not words:
        return ''
    best, score = '', 0.0
    for lang in ('de', 'fr', 'es'):
        stop = set(TEXT[lang]['stopwords'].split()) - {'job', 'cv'}
        r = sum(w in stop for w in words) / len(words)
        if r > score:
            best, score = lang, r
    return best if score >= 0.08 else ''
