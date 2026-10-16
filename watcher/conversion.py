"""Conversion: how many viewers SAVE a format's videos (user's rule, 16 Oct 2026 - same idea as the Memo AI watcher).

The lists must hold formats that convert best AND still go viral - not formats that only go viral. A save means a
viewer kept the video to use it later (the best free signal of real interest in the app); a like or a view does not.
In our data (574 JobStep / competitor CV videos with 10k+ views, 16 Oct 2026) the typical video was saved by 1.6% of
viewers - Spain 2.7%, France 1.7%, DACH 0.6% - hacks / HR secrets with a real app demo by 3-9%, skits and POVs by
0.3%. X01 (user removed it for low signups) was saved by ~0.8%: saves follow signups here too.

- save rate of a video = saves / views (only videos with min_views+ views, a known save count and no sign of a paid
  ad). Each market saves at its own level, so a video counts against the typical rate of ITS market (the creator's
  language): index = rate / that market's typical rate (1.0 = a typical video there). A market with fewer than
  min_market_videos measured videos (Slovenia today) uses the typical rate of all markets.
- paid ads: a video whose likes are below ad_like_rate of its views (JobStep's own brand accounts boost videos to
  1M views with 0.1-0.3% likes and saves) is left out of the measurements and never builds a format.
- conversion of a format = its videos' average index (recent weeks count most), pulled towards 1.0 when it has few
  videos; score = conv x reach ** reach_weight, reach = rank.form (how well it goes viral right now, 1.0 = average).
  Conversion decides, reach still counts: a format that only goes viral cannot win on views alone.
- a video builds a new format (or brings one back) only when viewers save it: viral / rising AND saved by at least
  min_rel x its market's typical rate, or "converting": convert_views+ views, convert_min_saves+ saves and saved by
  convert_save_rate+ AND convert_rel x its market's typical rate (so 30k views saved by 3% in Spain count below 100k).
- hot (5+ viral in 7 days) needs conv >= hot_min_conv as well.
- weekly clean-up (lineup.py): a format with judge_min_videos+ measured videos whose score is below remove_below
  leaves the list, also when it still goes viral or is new.
- our own creators (own.tiers): "proven for us" also needs our videos of it to be saved at least like a typical video
  of that market (when their saves are known - Instagram hides saves, so those count as unknown).
"""
import statistics
import time

DAY = 86400

DEFAULTS = {
    'min_views': 10_000,          # a video's save rate counts from this many views on
    'min_rel': 0.5,               # viral / rising videos saved by less than this x their market's typical rate never build
    'convert_views': 30_000,      # "converting" trigger (below the viral bar)
    'convert_save_rate': 0.02,
    'convert_rel': 1.2,           # ... and at least this x the market's typical rate (Spain: ~3.2%)
    'convert_min_saves': 300,
    'prior_rate': 0.016,          # typical save rate when there are too few videos to measure it
    'min_market_videos': 10,      # a market's own typical rate from this many measured videos on
    'prior_videos': 3,            # smoothing: a format's index counts like this many typical videos more
    'half_life_days': 30,
    'window_days': 120,
    'reach_weight': 0.5,
    'hot_min_conv': 1.0,
    'judge_min_videos': 2,        # the clean-up judges a format on saves from this many measured videos on
    'remove_below': 0.9,          # ... and takes it out below this score (1.0 = an average format)
    'rate_cap': 0.12,             # one odd video cannot carry a format
    'ad_like_rate': 0.007,        # likes below this share of views = probably a paid ad
    'own_min_views': 3_000,       # our creators' videos: their save rate counts from this many views on
    'backfill_per_run': 60,
    'classify_per_run': 40,
}


def conf(cfg):
    return {**DEFAULTS, **(cfg or {}).get('conversion', {})}


def known(v):
    """True when the video's save count was really read. A views-only check (detail_missing) is unknown: a new
    watchlist video starts with saves 0, and its newer views would not match older saves anyway."""
    return v.get('saves') is not None and not v.get('saves_unknown') and not v.get('detail_missing')


def save_rate(v):
    """saves / views (None when the save count is unknown or there are no views)."""
    if not known(v) or not v.get('views'):
        return None
    return v['saves'] / v['views']


def looks_paid(v, cfg=None):
    """Likes far below a normal video's (paid reach): its saves and views say nothing about the format."""
    c = conf(cfg)
    if not known(v) or v.get('likes') is None or v.get('views', 0) < c['min_views']:
        return False
    return v['likes'] / v['views'] < c['ad_like_rate']


def measured_rate(v, c):
    r = save_rate(v)
    if r is None or v['views'] < c['min_views'] or looks_paid(v, {'conversion': c}):
        return None
    return min(r, c['rate_cap'])


def record(entry, v, old=None):
    """Copies likes/saves/shares into a history entry - only when they were really read (a views-only check keeps the
    last real numbers)."""
    old = old or {}
    if v.get('detail_missing') or v.get('saves') is None:
        for k in ('likes', 'saves', 'shares'):
            if k in old:
                entry[k] = old[k]
        return entry
    for k in ('likes', 'saves', 'shares'):
        entry[k] = int(v.get(k) or 0)
    entry['saves_unknown'] = False  # read now (an older failed read must not stick when entries are merged)
    return entry


def market_map():
    """{handle: market} of the JobStep accounts (their language: accounts.json, then the language localize found)."""
    from . import state
    out = dict((state.load('meta.json', {}) or {}).get('handle_lang') or {})
    for h, a in (state.load('accounts.json', {}) or {}).items():
        if a.get('lang'):
            out[h] = a['lang']
    return {h: m for h, m in out.items() if m}


def baselines(history, c, now=None, markets=None):
    """{'all': typical rate of all measured videos, market: typical rate of that market's videos} (medians in the
    window). A market with too few measured videos is left out (typical() falls back to 'all')."""
    now = now or time.time()
    markets = markets or {}
    rates, per = [], {}
    for v in history.values():
        if now - v.get('created', 0) > c['window_days'] * DAY:
            continue
        r = measured_rate(v, c)
        if r is None:
            continue
        rates.append(r)
        m = markets.get(v.get('handle'))
        if m:
            per.setdefault(m, []).append(r)
    out = {'all': statistics.median(rates) if len(rates) >= c['min_market_videos'] else c['prior_rate']}
    for m, rs in per.items():
        if len(rs) >= c['min_market_videos']:
            out[m] = statistics.median(rs)
    return out


def typical(base, market):
    return max(base.get(market) or base['all'], 1e-4)


def board(history, formats, cfg, now=None, reach=None, markets=None):
    """({format_id: {'rate', 'conv', 'reach', 'score', 'videos', 'raw_rate'}}, baselines) for every format (list and
    archive). conv = the format's average index (rate / its video's market typical rate), 1.0 = an average format.
    reach: rank.form() output (None -> 1.0 for everyone). markets: {handle: market} (None -> market_map())."""
    c = conf(cfg)
    now = now or time.time()
    markets = market_map() if markets is None else markets
    base = baselines(history, c, now, markets)
    k = c['prior_videos']
    per = {}
    for v in history.values():
        if not v.get('format') or now - v.get('created', 0) > c['window_days'] * DAY:
            continue
        r = measured_rate(v, c)
        if r is not None:
            w = 0.5 ** ((now - v['created']) / DAY / c['half_life_days'])
            per.setdefault(v['format'], []).append((w, r, r / typical(base, markets.get(v.get('handle')))))
    out = {}
    for f in formats:
        xs = per.get(f['id'], [])
        w = sum(x for x, _, _ in xs)
        conv = (sum(x * i for x, _, i in xs) + k) / (w + k)
        rch = max((reach or {}).get(f['id'], {}).get('form', 1.0), 0.05)
        out[f['id']] = {'conv': conv, 'rate': conv * base['all'], 'reach': rch,
                        'score': conv * rch ** c['reach_weight'], 'videos': len(xs),
                        'raw_rate': (sum(x * r for x, r, _ in xs) / w) if w else None}
    return out, base


def video_typical(v, history, cfg, markets=None, now=None):
    """The typical save rate of the video's market (all markets when its market is unknown or has too few videos)."""
    c = conf(cfg)
    markets = market_map() if markets is None else markets
    return typical(baselines(history, c, now, markets), markets.get(v.get('handle')))


def converting(v, cfg, base_rate=None):
    """A video below the viral bar that viewers save a lot (see module doc). base_rate: its market's typical rate."""
    c = conf(cfg)
    r = save_rate(v)
    need = max(c['convert_save_rate'], c['convert_rel'] * (base_rate or 0))
    return (r is not None and not looks_paid(v, cfg) and v.get('views', 0) >= c['convert_views']
            and v.get('saves', 0) >= c['convert_min_saves'] and r >= need)


def too_few_saves(v, cfg, base_rate=None):
    """Known save rate below min_rel x its market's typical rate, or a paid ad (unknown -> False: never blocked on
    missing data). base_rate: the market's typical rate (None -> the prior)."""
    c = conf(cfg)
    r = save_rate(v)
    if r is None:
        return False
    return looks_paid(v, cfg) or r < c['min_rel'] * (base_rate or c['prior_rate'])


def own_rate(videos, fid, market, cfg, now=None, window_days=28, min_age_days=2):
    """How many viewers save OUR creators' videos of a format in one market: (pooled rate, measured videos) or
    (None, 0). Only TikTok videos with a read save count (Megasheet 'bookmarks' or the TikTok page); Instagram hides
    saves, so those videos are unknown, not zero."""
    c = conf(cfg)
    now = now or time.time()
    saves = views = n = 0
    for v in videos.values():
        if (not v.get('ours') or v.get('market') != market or v.get('format') != fid
                or v.get('platform') == 'instagram' or v.get('bookmarks') is None
                or v.get('views', 0) < c['own_min_views']
                or not min_age_days * DAY <= now - v.get('created', 0) <= window_days * DAY):
            continue
        saves += v['bookmarks']
        views += v['views']
        n += 1
    return (saves / views if views else None), n


def pct(r):
    return '?' if r is None else f'{r * 100:.1f}%'


def backfill(history, limit, now=None, detail=None, min_views=10_000, days=120):
    """Reads likes/saves of older history videos that were stored before saves were kept (newest first, limit per
    run). Returns the fresh details of the updated videos (for sorting them into formats; their text is not kept in
    history). detail: (handle, id) -> video detail or None (tiktok.video_detail)."""
    if detail is None:
        from .tiktok import video_detail as detail
    now = now or time.time()
    todo = sorted([(vid, v) for vid, v in history.items() if 'saves' not in v and not v.get('saves_unknown')
                   and v.get('views', 0) >= min_views and now - v.get('created', 0) <= days * DAY],
                  key=lambda x: -x[1]['created'])[:limit]
    done = []
    for vid, v in todo:
        d = detail(v['handle'], vid)
        if not d:
            v['saves_tries'] = v.get('saves_tries', 0) + 1
            if v['saves_tries'] >= 3:
                v['saves_unknown'] = True
            continue
        v['views'] = max(v.get('views', 0), d['views'])
        record(v, d)
        v.pop('saves_tries', None)
        done.append({**d, 'id': vid})
    return done


def to_sort(history, details):
    """Backfilled videos no check has put into a format yet (judged ones keep their verdict)."""
    return [d for d in details if not history[d['id']].get('format') and not history[d['id']].get('judged')
            and not history[d['id']].get('sorted')]
