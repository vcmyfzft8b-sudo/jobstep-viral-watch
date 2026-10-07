"""Our own creators (Parakeet AI): their TikTok videos and which of our formats each one is.

The list ranking uses this to see how a format does for US, not only for JobStep (see rank.scores).

- Accounts: seeded from the Megasheet export (registry/own_seed.json, DACH), completed every few days via Lightreel
  (any market) and checked on TikTok: posted in the last 30 days AND Parakeet AI in captions or videos.
- Videos: every run the creator embed gives the latest ~10 videos with views (free). Videos up to 10 days old that
  dropped out of the embed get one full check per day, so their views keep growing.
- Formats: once a video is 48h old it is sorted into our formats by Claude (same batch sorting as the JobStep videos).
  Videos without Parakeet AI in caption, on-screen text or speech are ignored (not a campaign video).

state/own_accounts.json  {handle: {status, market, since, source}}
state/own.json           {video_id: {handle, market, created, views, desc, format, checked, ours}}
"""
import json
import os
import re
import time

from . import classify, discover, state, tiktok

BRAND = re.compile(r'parakeet', re.I)
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'own_seed.json')
TRACK_DAYS = 10
MAX_DETAILS = 60  # full video checks per run (old videos after the seed, missing views)


def load():
    accounts = state.load('own_accounts.json', None)
    videos = state.load('own.json', None)
    if accounts is None or videos is None:
        with open(SEED) as f:
            seed = json.load(f)
        accounts = accounts or {h: {'status': 'active', 'since': int(time.time()), **a} for h, a in seed['accounts'].items()}
        videos = videos or {vid: {**v, 'ours': True} for vid, v in seed['videos'].items()}
    return accounts, videos


def update(accounts, videos, fmts, cfg, now, max_details=MAX_DETAILS):
    """New videos + views from the embeds, view refresh for younger videos, format sorting. Returns a summary dict."""
    seen, fresh = set(), 0
    for handle, a in accounts.items():
        if a.get('status') != 'active':
            continue
        for item in tiktok.latest_videos(handle):
            vid = item['id']
            seen.add(vid)
            v = videos.get(vid)
            if v is None:
                v = videos[vid] = {'handle': handle, 'market': a.get('market', ''), 'created': int(vid) >> 32,
                                   'views': 0, 'desc': item['desc'][:300]}
                fresh += 1
            v['views'] = max(v.get('views', 0), item['views'])
            v['updated'] = int(now)
    details = 0
    for vid, v in sorted(videos.items(), key=lambda x: -x[1]['created']):
        if details >= max_details:
            break
        age = now - v['created']
        needs_text = not v.get('checked') and age >= 48 * 3600 and 'sticker' not in v and v.get('tries', 0) < 2
        needs_views = vid not in seen and age <= TRACK_DAYS * 86400 and now - v.get('updated', 0) >= 20 * 3600
        if not (needs_text or needs_views):
            continue
        d = tiktok.video_detail(v['handle'], vid)
        details += 1
        if not d:
            v['tries'] = v.get('tries', 0) + 1
            continue
        v.update({'views': max(v.get('views', 0), d['views']), 'updated': int(now), 'desc': d['desc'][:300],
                  'sticker': d['sticker'][:400], 'subtitles': d['subtitles'][:900]})
    todo = []
    for vid, v in videos.items():
        if v.get('checked') or now - v['created'] < 48 * 3600 or ('sticker' not in v and v.get('tries', 0) < 2):
            continue  # sorted once the full text (on-screen text + speech) is there
        if not v.get('ours') and not BRAND.search(' '.join([v.get('desc', ''), v.get('sticker', ''), v.get('subtitles', '')])):
            v.update({'checked': True, 'ours': False})  # not a Parakeet AI campaign video
            continue
        v['ours'] = True
        todo.append({'id': vid, **v})
    if todo:
        results = classify.classify_many(todo, fmts, cfg['models']['classify'])
        for x in todo:
            c = results.get(x['id'])
            if c:
                videos[x['id']].update({'format': c['match'], 'checked': True, 'hook_en': c['hook_en']})
    return {'accounts': sum(1 for a in accounts.values() if a.get('status') == 'active'), 'new_videos': fresh,
            'details': details, 'sorted': len(todo)}


def stats(videos, fmts, now, min_age_days=3):
    """How each format does for OUR creators: {format_id: {'n', 'lift', 'hits_100k', 'views', 'recent_viral',
    'week_videos', 'week_views'}}.

    Our creators get far fewer views than JobStep's, so fixed thresholds (100k / 20k) would call almost every video
    of ours a flop. Instead each video is compared with its creator's usual: lift = log2(views / creator's median),
    clipped to -2..+2 (a quarter to 4x the usual). Only videos at least 3 days old count (young ones are not flops)."""
    import math
    import statistics
    mature = [v for v in videos.values() if v.get('ours') and now - v['created'] >= min_age_days * 86400]
    by_creator = {}
    for v in mature:
        by_creator.setdefault(v['handle'], []).append(v['views'])
    overall = statistics.median([v['views'] for v in mature]) if mature else 1
    median = {h: statistics.median(vs) if len(vs) >= 3 else overall for h, vs in by_creator.items()}
    out = {}
    for v in videos.values():
        fid = v.get('format')
        if not v.get('ours') or not fid:
            continue
        s = out.setdefault(fid, {'n': 0, 'lift_sum': 0.0, 'hits_100k': 0, 'views': 0, 'recent_viral': 0,
                                 'week_videos': 0, 'week_views': 0})
        age = now - v['created']
        if age >= min_age_days * 86400:
            s['n'] += 1
            s['lift_sum'] += max(-2.0, min(2.0, math.log2(max(v['views'], 1) / max(median.get(v['handle'], overall), 1))))
            s['hits_100k'] += v['views'] >= 100_000
            s['views'] += v['views']
        if age <= 7 * 86400:
            s['week_videos'] += 1
            s['week_views'] += v['views']
            s['recent_viral'] += v['views'] >= 100_000
    for s in out.values():
        s['lift'] = s['lift_sum'] / s['n'] if s['n'] else 0.0
    return out


QUESTION = discover.QUESTION.replace('JobStep (jobstep.io, the AI CV/resume builder)',
                                     'Parakeet AI (parakeet-ai.com, the AI CV/resume maker; hashtags like #parakeetai, '
                                     '#partnerparakeetai, #parakeetaiad)').replace(
    'Many are named like "<name>.jobtipps", "<name>.jobtips",\n"<name>.jobstep.io", "<name>jobstep", "job.by.<name>", '
    '"<name>cvtips", but include normal career/lifestyle creators too.', 'Include normal career/lifestyle creators too.')


def check_account(handle, max_days=30):
    vids = tiktok.latest_videos(handle)
    if not vids:
        return 'invalid'
    recent = (time.time() - max(int(v['id']) >> 32 for v in vids)) / 86400 <= max_days
    ours = any(BRAND.search(v['desc']) for v in vids)
    return 'active' if (recent and ours) else 'inactive'


def refresh_accounts(accounts):
    """Every few days: new Parakeet AI accounts (Lightreel, any market) + pause/revive. Returns (added, paused, revived)."""
    added, paused, revived = [], [], []
    hint = ("\nOnly look at this market: {market}. Search captions, hashtags (#parakeetai, #partnerparakeetai, "
            "#parakeetaiad), on-screen text and spoken mentions. List only accounts NOT in the known list.")
    for h in sorted(discover.lightreel_handles(set(accounts), QUESTION, hint=hint) - set(accounts)):
        if check_account(h) == 'active':
            accounts[h] = {'status': 'active', 'since': int(time.time()), 'source': 'lightreel',
                           'market': discover.language(h)}
            added.append(h)
    for h, a in accounts.items():
        if h in added or a.get('source') == 'megasheet':
            continue  # creators confirmed in Megasheet are always tracked
        status = check_account(h)
        if status == 'invalid':
            continue
        if a['status'] == 'active' and status == 'inactive':
            a['status'] = 'inactive'
            paused.append(h)
        elif a['status'] == 'inactive' and status == 'active':
            a['status'] = 'active'
            revived.append(h)
    return added, paused, revived
