"""Weekly: find new JobStep creator accounts with Lightreel (LIGHTREEL_API_KEY, optional)."""
import os
import re

import requests

from . import tiktok

QUESTION = """List TikTok accounts that currently post sponsored or affiliate videos for JobStep (jobstep.io, the
AI CV / resume builder) in any language. Many are named like "<name>.jobtipps", "<name>.jobstep.io" or are job-tip
creators in the Balkans, Germany, Poland, France, Italy, the Netherlands. Only accounts that posted in the last 30 days.
Answer with one line per account in the form: ACCOUNT | @handle"""


def find_accounts(known):
    key = os.environ.get('LIGHTREEL_API_KEY')
    if not key:
        return []
    try:
        r = requests.post('https://api.lightreel.ai/v1/chat', json={'question': QUESTION}, timeout=1500,
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        answer = r.json().get('answer', '') if r.ok else ''
    except (requests.RequestException, ValueError):
        return []
    handles = {h.lower().rstrip('.') for h in re.findall(r'@([A-Za-z0-9._]{2,30})', answer)}
    new = []
    for h in sorted(handles - {k.lower() for k in known}):
        if tiktok.latest_video_ids(h) and tiktok.mentions_jobstep(h):
            new.append(h)
    return new
