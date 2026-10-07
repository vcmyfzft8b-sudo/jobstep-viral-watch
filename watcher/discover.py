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
    if not jobstep:  # JobStep often only appears on screen or in speech: read up to 8 videos (3 missed real creators)
        for v in vids[:8]:
            d = tiktok.video_detail(handle, v['id'])
            if d and re.search(r'job\s*-?\s*step', ' '.join([d['desc'], d['sticker'], d['subtitles']]), re.I):
                jobstep = True
                break
    return 'active' if (recent and jobstep) else 'inactive'


# One Lightreel question per market finds far more accounts than one global question (7 Oct 2026: +20 accounts).
MARKETS = ['Germany, Austria and Switzerland (German)', 'Serbia, Croatia, Bosnia, Montenegro, Slovenia (Balkans)',
           'Poland', 'France and Belgium (French)', 'Italy', 'Spain and Latin America (Spanish)', 'Portugal and Brazil',
           'Netherlands', 'Sweden, Norway, Denmark, Finland', 'Czechia, Slovakia, Hungary, Romania, Bulgaria',
           'UK, Ireland, US and other English-speaking', 'Turkey and Greece']
MARKET_HINT = ("\nOnly look at this market: {market}. Search captions, hashtags (#jobstep, #jobstepio), on-screen text and "
               "spoken mentions. List only accounts NOT in the known list.")


def _ask(key, q):
    try:
        r = requests.post('https://api.lightreel.ai/v1/chat', json={'question': q}, timeout=1500,
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        return r.json().get('answer', '') if r.ok else ''
    except (requests.RequestException, ValueError):
        return ''


UGC_SYSTEM = "You check TikTok accounts for a marketing team. Reply with JSON only."


def account_text(handle, details=4):
    """The account's latest videos as text: caption for all, plus on-screen text and speech for the newest few."""
    vids = tiktok.latest_videos(handle)[:8]
    lines = []
    for i, v in enumerate(vids):
        line = f"- ({round((time.time() - (int(v['id']) >> 32)) / 86400)}d ago, {v['views']} views) CAPTION: {v['desc'][:220]}"
        if i < details:
            d = tiktok.video_detail(handle, v['id'])
            if d:
                line += f" | ON SCREEN: {d['sticker'][:160]} | SPEECH: {d['subtitles'][:300]}"
        lines.append(line)
    return '\n'.join(lines)


def confirm_ugc(handles, model='sonnet', batch=8, details=4):
    """Claude reads each account's latest videos: is it really a UGC/creator account promoting the JobStep CV app?
    Returns {handle: {'verdict': 'jobstep_ugc'|'other_app'|'not_ugc'|'unclear', 'other_app', 'reason'}}."""
    import concurrent.futures as cf
    from . import llm
    with cf.ThreadPoolExecutor(8) as ex:
        texts = dict(zip(handles, ex.map(lambda h: account_text(h, details), handles)))
    out = {}

    def one(chunk):
        blocks = '\n\n'.join(f"ACCOUNT @{h}\n{texts[h] or '(no videos)'}" for h in chunk)
        prompt = f"""Each block below is a TikTok account with its latest videos (newest first).
Decide for each account: is it a UGC / creator account that currently promotes JobStep (jobstep.io), the AI CV/resume
builder app - i.e. it posts (sponsored, affiliate or creator-program) videos where the JobStep app is shown,
recommended or named? JobStep's own brand account also counts.
- "jobstep_ugc": yes, it promotes the JobStep CV app (at least one recent video clearly does).
- "other_app": a CV/job creator account that now promotes a DIFFERENT app (name it), not JobStep.
- "not_ugc": a random/personal account, or "job step" only appears as normal words, or another company called
  Jobstep (e.g. a staffing agency), not the CV app.
- "unclear": not enough information.

{blocks}

Return JSON {{"results": [{{"handle": "<handle without @>", "verdict": "...", "other_app": "<name or empty>",
"reason": "<short, in English>"}}]}}"""
        try:
            return llm.chat_json(model, UGC_SYSTEM, prompt, timeout=900).get('results', [])
        except Exception as e:
            print('UGC check failed:', str(e)[:200])
            return []

    with cf.ThreadPoolExecutor(3) as ex:
        for results in ex.map(one, [handles[i:i + batch] for i in range(0, len(handles), batch)]):
            for x in results:
                out[str(x.get('handle', '')).lstrip('@').lower()] = x
    return out


def lightreel_handles(known, question=None, hint=None):
    """Handles Lightreel names for every market (asked in parallel), minus nothing - the caller filters known ones."""
    import concurrent.futures as cf
    key = os.environ.get('LIGHTREEL_API_KEY')
    if not key:
        return set()
    q = (question or QUESTION).format(today=time.strftime('%d %B %Y'), known=', '.join('@' + h for h in sorted(known)))
    with cf.ThreadPoolExecutor(6) as ex:
        answers = list(ex.map(lambda m: _ask(key, q + (hint or MARKET_HINT).format(market=m)), MARKETS))
    return {h.lower().rstrip('.') for a in answers for h in re.findall(r'@([A-Za-z0-9._]{2,30})', a)}


def refresh(accounts):
    """accounts: {handle: {'status': 'active'|'inactive'|'manual', 'since': ts, ...}} -> (accounts, added, paused, revived)."""
    added, paused, revived = [], [], []
    new = [h for h in sorted(lightreel_handles(set(accounts)) - set(accounts)) if check_account(h) == 'active']
    verdicts = confirm_ugc(new) if new else {}
    for h in new:  # only real JobStep UGC accounts (Claude read their latest videos)
        if verdicts.get(h, {}).get('verdict') == 'jobstep_ugc':
            accounts[h] = {'status': 'active', 'since': int(time.time()), 'source': 'lightreel', 'checked_ugc': True}
            added.append(h)
    for h, info in accounts.items():
        if info['status'] == 'manual' or h in added or info.get('blocked'):
            continue  # manually confirmed creators are always tracked; blocked = Claude found it is not JobStep UGC
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
