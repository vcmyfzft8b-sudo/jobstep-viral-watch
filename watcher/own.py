"""Our own creators (Parakeet AI): their TikTok videos and which of our formats each one is.

The list ranking uses this to see how a format does for US, not only for JobStep (see rank.scores).

- Accounts: every run read live from Megasheet (DACH, France, Spain campaigns - see megasheet.py; the export in
  registry/own_seed.json is the fallback), completed every few days via Lightreel (any market) and checked on TikTok:
  posted in the last 30 days AND Parakeet AI in captions or videos.
- Videos: every run the creator embed gives the latest ~10 videos with views (free). Videos up to 10 days old that
  dropped out of the embed get one full check per day, so their views keep growing.
- Formats: once a video is 48h old it is sorted into our formats by Claude (same batch sorting as the JobStep videos).
  Videos without Parakeet AI in caption, on-screen text or speech are ignored (not a campaign video).
  registry/own_formats.json holds hand-checked formats (12 Oct 2026, Spain + France): they always win over the
  automatic sorting (apply_hand_tags, on every load).

state/own_accounts.json  {handle: {status, market, since, source}}
state/own.json           {video_id: {handle, market, created, views, desc, format, checked, ours, platform, creator}}
                         Instagram videos (from Megasheet only) use the key 'ig_<shortcode>'.
"""
import difflib
import json
import os
import re
import time

from . import classify, discover, state, tiktok

BRAND = re.compile(r'parakeet', re.I)
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'own_seed.json')
HAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'own_formats.json')
TRACK_DAYS = 10
MAX_DETAILS = 60  # full video checks per run (old videos after the seed, missing views)


def load():
    """State + anything in the seed that the state does not have yet (a newer export adds creators and videos;
    entries already in the state are left alone - the live Megasheet sync keeps those up to date)."""
    accounts = state.load('own_accounts.json', None) or {}
    videos = state.load('own.json', None) or {}
    with open(SEED) as f:
        seed = json.load(f)
    for h, a in seed['accounts'].items():
        accounts.setdefault(h, {'status': 'active', 'since': int(time.time()), **a})
    for vid, v in seed['videos'].items():
        videos.setdefault(vid, {**v, 'ours': True})
    apply_hand_tags(videos)
    return accounts, videos


def hand_tags():
    try:
        with open(HAND) as f:
            return json.load(f).get('videos', {})
    except FileNotFoundError:
        return {}


def apply_hand_tags(videos, tags=None):
    """Hand-checked formats (registry/own_formats.json) override the automatic sorting. Returns how many changed."""
    changed = 0
    for vid, t in (hand_tags() if tags is None else tags).items():
        v = videos.get(vid)
        if v is None:
            continue
        fmt = aliases().get(t['format'], t['format'])  # a format merged into another (dupes) counts for that one
        if v.get('format') != fmt:
            changed += 1
        v.update({'format': fmt, 'checked': True, 'ours': True, 'format_by': 'hand'})
    return changed


def aliases():
    """{format id: id it was merged into} - formats archived as "duplicate of X" (lineup.merge_duplicates)."""
    import re as _re
    out = {}
    for f in state.load('formats.json', None) or []:
        m = _re.match(r'duplicate of (\S+)', f.get('archived_reason') or '')
        if m:
            out[f['id']] = m.group(1)
    return out


def videos_now():
    """state/own.json with the hand-checked formats applied (for readers that skip load())."""
    videos = state.load('own.json', {})
    apply_hand_tags(videos)
    return videos


def sync_megasheet(accounts, videos, now, full=False, markets=None):
    """Live creator + video list from Megasheet (see megasheet.py) for the given markets (the enabled ones).
    Never raises: the rest of the run goes on, but every failure is pushed to Slack (at most once a day)."""
    from . import megasheet, notify
    try:
        s = megasheet.sync(accounts, videos, now, full=full, markets=markets)
    except megasheet.LoginError as e:
        print('megasheet:', e)
        if megasheet.should_warn(now):
            notify.push('🔑 Megasheet login needed', f'{e}. Our creators are not refreshed from Megasheet until then.')
        return None
    except Exception as e:
        print('megasheet sync failed:', str(e)[:200])
        if megasheet.should_warn(now):
            notify.push('⚠️ Megasheet sync failed', f'{str(e)[:300]}\nOur creators\' videos and views are not refreshed '
                        'until this works again, so the list order is based on old numbers.')
        return None
    print('megasheet:', 'no login saved - skipped' if s is None else s)
    if s:
        state.save('own.json', videos)
        state.save('own_accounts.json', accounts)
    return s


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
        if v.get('platform') == 'instagram':
            continue  # no TikTok page: views come from Megasheet
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
        if v['views'] == d['views']:  # saves read with the same views (the save rate decides "proven", 16 Oct 2026)
            v['bookmarks'], v['likes'] = d['saves'], d['likes']
    todo = []
    for vid, v in videos.items():
        if v.get('checked') or now - v['created'] < 48 * 3600 or ('sticker' not in v and v.get('tries', 0) < 2):
            continue  # sorted once the full text (on-screen text + speech) is there
        if not v.get('ours') and not BRAND.search(' '.join([v.get('desc', ''), v.get('sticker', ''), v.get('subtitles', '')])):
            v.update({'checked': True, 'ours': False})  # not a Parakeet AI campaign video
            continue
        v['ours'] = True
        if v.get('platform') == 'instagram':
            twin = tiktok_twin(videos, v)
            if twin == WAIT and now - v['created'] < IG_WAIT_DAYS * 86400:
                continue  # the creator's TikTok post of it is not sorted yet - take its format then
            if twin and twin != WAIT:
                tid, t = twin
                v.update({'format': t.get('format'), 'checked': True, 'twin': tid, 'hook_en': t.get('hook_en', '')})
                continue
        todo.append({'id': vid, **v})
    if todo:
        results = classify.classify_many(todo, fmts, cfg['models']['classify'])
        for x in todo:
            c = results.get(x['id'])
            if c:
                videos[x['id']].update({'format': c['match'], 'checked': True, 'hook_en': c['hook_en']})
    return {'accounts': sum(1 for a in accounts.values() if a.get('status') == 'active'), 'new_videos': fresh,
            'details': details, 'sorted': len(todo)}


WAIT = 'wait'
IG_WAIT_DAYS = 5  # an Instagram video waits this long for its TikTok twin to be sorted, then is sorted on its own


def _norm(text):
    return re.sub(r'#\S+|@\S+|https?://\S+|[^\w ]+', ' ', (text or '').lower()).split()


def tiktok_twin(videos, v, max_days=2):
    """The same video posted on TikTok by the same creator (Megasheet creator id, else handle) within 2 days:
    (id, video), WAIT when that TikTok post is not sorted yet, None when there is none. Several candidates ->
    the one whose caption matches best, then the closest in time."""
    def same_creator(t):
        return t.get('creator') == v['creator'] if v.get('creator') else t.get('handle') == v.get('handle')
    cands = [(tid, t) for tid, t in videos.items() if t.get('platform', 'tiktok') == 'tiktok' and t.get('ours')
             and same_creator(t) and abs(t['created'] - v['created']) <= max_days * 86400]
    if not cands:
        return None
    words = ' '.join(_norm(v.get('desc')))
    ratio = lambda c: difflib.SequenceMatcher(None, words, ' '.join(_norm(c[1].get('desc')))).ratio()
    best = max(cands, key=lambda c: (ratio(c), -abs(c[1]['created'] - v['created'])))
    if ratio(best) < 0.5 and not (len(cands) == 1 and abs(best[1]['created'] - v['created']) <= 86400):
        return None  # captions too different: probably another video - sorted on its own
    return best if best[1].get('checked') else WAIT


def stats(videos, fmts, now, min_age_days=3, market=None):
    """How each format does for OUR creators: {format_id: {'n', 'lift', 'hits_100k', 'views', 'recent_viral',
    'week_videos', 'week_views'}}.

    Our creators get far fewer views than JobStep's, so fixed thresholds (100k / 20k) would call almost every video
    of ours a flop. Instead each video is compared with its creator's usual: lift = log2(views / creator's median),
    clipped to -2..+2 (a quarter to 4x the usual). Only videos at least 3 days old count (young ones are not flops)."""
    import math
    import statistics
    videos = {k: v for k, v in videos.items() if not market or v.get('market') == market}
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


TIER_DEFAULTS = {'window_days': 28, 'min_age_days': 2, 'proven_avg': 10000, 'proven_min_videos': 2,
                 'proven_hit': 100000, 'proven_hit_days': 14, 'solid_avg': 2000, 'solid_min_videos': 3,
                 'weak_avg': 1500, 'weak_min_videos': 6, 'weak_vs_median': 1.2}
TIER_NAMES = {1: 'proven for us', 2: 'solid for us', 3: 'not tested enough by us', 4: 'weak for us'}


def tiers(videos, fmts, now, market, cfg, typical_rate=None):
    """How each format does for OUR creators in ONE market, as a tier (the list order starts with it, see rank.order):
    1 proven  - our videos of it average 10k+ (at least 2 videos), or one of them passed 100k in the last 14 days -
                AND (user's rule, 16 Oct 2026) our videos of it are saved at least like a typical video OF OURS in
                this market (conversion.own_rate vs conversion.own_typical - not JobStep's rate, our creators' videos
                are saved less overall). Saved less -> tier 2 ('saves_low'). Saves unknown (only Instagram videos,
                which hide saves) or too few measured videos of ours in the market -> views alone decide.
    2 solid   - at least 3 of our videos, average 2k+
    4 weak    - at least 6 of our videos, average under 1.5k AND under 1.2x a typical video of ours in this market
                (its median) - sinks to the bottom, even when it is viral for JobStep. The median part keeps a market
                where all our creators get few views (DACH) from burying half its list.
    3 the rest (not tested enough by us) - JobStep decides there.
    Averages use our videos of the last 28 days that are at least 2 days old (TikTok and Instagram).
    Thresholds: config ranking.own_tiers. Returns {format_id: {'tier', 'n', 'avg', 'best', 'hit'}} (formats with
    none of our videos are left out = tier 3)."""
    from . import conversion
    c = {**TIER_DEFAULTS, **(cfg.get('ranking', {}).get('own_tiers') or {})}
    known = {f['id'] for f in fmts}
    typical_save = typical_rate if typical_rate is not None else conversion.own_typical(videos, market, cfg, now)
    import statistics
    typical = [v['views'] for v in videos.values() if v.get('ours') and v.get('market') == market
               and c['min_age_days'] * 86400 <= now - v['created'] <= c['window_days'] * 86400]
    median = statistics.median(typical) if typical else 0
    per = {}
    for v in videos.values():
        fid = v.get('format')
        if not v.get('ours') or v.get('market') != market or fid not in known:
            continue
        age = now - v['created']
        x = per.setdefault(fid, {'n': 0, 'views': 0, 'best': 0, 'hit': 0})
        if age <= c['proven_hit_days'] * 86400 and v['views'] >= c['proven_hit']:
            x['hit'] += 1
        if c['min_age_days'] * 86400 <= age <= c['window_days'] * 86400:
            x['n'] += 1
            x['views'] += v['views']
            x['best'] = max(x['best'], v['views'])
    out = {}
    for fid, x in per.items():
        avg = x['views'] / x['n'] if x['n'] else 0
        if x['hit'] or (x['n'] >= c['proven_min_videos'] and avg >= c['proven_avg']):
            tier = 1
        elif x['n'] >= c['weak_min_videos'] and avg < c['weak_avg'] and avg < c['weak_vs_median'] * median:
            tier = 4
        elif x['n'] >= c['solid_min_videos'] and avg >= c['solid_avg']:
            tier = 2
        else:
            tier = 3
        rate, measured = conversion.own_rate(videos, fid, market, cfg, now, c['window_days'], c['min_age_days'])
        saves_low = tier == 1 and rate is not None and typical_save is not None and rate < typical_save
        if saves_low:
            tier = 2  # many views for us, but our viewers do not save it: not "proven" (16 Oct 2026)
        out[fid] = {'tier': tier, 'n': x['n'], 'avg': round(avg), 'best': x['best'], 'hit': x['hit'],
                    'market_median': round(median), 'save_rate': rate, 'saved_videos': measured,
                    'typical_rate': typical_save, 'saves_low': saves_low}
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
