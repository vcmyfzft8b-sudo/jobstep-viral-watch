"""Order of the formats on a market's list.

1. What is going viral RIGHT NOW: most confirmed viral videos (100k+) posted in the last 7 days first.
   (Hot formats - 5+ JobStep videos - always stay on top; our own creators' viral videos count here too.)
2. Tie-breaker / formats without viral videos this week: current form (see form() - recent weeks count most).
   The older long-term score below is still computed for the weekly report: long-term score = smoothed share of videos with 100k+
   views + weight_20k * smoothed share with 20k+ views. Smoothing pulls small samples towards the network average,
   and new formats (< 5 videos) are capped below the three strongest proven formats.
0. Before all of this (each market on its own, see order()): our own creators' results in THAT market put every
   format in a tier (own.tiers): 1 proven for us -> top, 2 solid, 3 not tested enough (JobStep decides),
   4 weak for us -> bottom, even when JobStep goes viral with it. The tiers come from a weekly snapshot
   (main.own_tiers), so the list does not reshuffle every 6 hours.
3. Our own creators (own.py): the JobStep score is multiplied by how the format does for OUR creators compared with
   their usual views: factor = 2 ** (sum of lifts / (our videos + own_prior_weight)), lift = log2(views / creator's
   median). A format that reliably gets our creators 2x their usual moves towards x2; with only a few videos of ours
   the factor stays close to 1 (JobStep decides), and a format that keeps flopping for us sinks.
"""
import time

from .markets import fkey


def scores(history, formats, cfg, m='de', local=(), own_stats=None):
    r = cfg['ranking']
    own_stats = own_stats or {}
    k_own = r.get('own_prior_weight', 8)
    fk = fkey(m)
    local = set(local)
    out = {}
    for f in formats:
        if f.get('status') != 'active':
            continue
        n = hits = hits20 = 0.0
        for v in history.values():
            if v.get(fk) != f['id']:
                continue
            w = r['german_weight'] if v['handle'] in local else 1
            n += w
            hits += w * (v['views'] >= 100_000)
            hits20 += w * (v['views'] >= 20_000)
        k = r['prior_weight']
        p100 = (hits + r['prior_hit_rate'] * k) / (n + k)
        p20 = (hits20 + r['prior_20k_rate'] * k) / (n + k)
        js_score = p100 + r['weight_20k'] * p20
        o = own_stats.get(f['id'], {})
        factor = 2 ** (o.get('lift_sum', 0.0) / (o.get('n', 0) + k_own))
        out[f['id']] = {'score': js_score * factor, 'js_score': js_score, 'own_factor': factor, 'videos': n,
                        'hits_100k': hits, 'hits_20k': hits20, 'own_videos': o.get('n', 0),
                        'own_hits_100k': o.get('hits_100k', 0), 'own_lift': o.get('lift', 0.0)}
    proven = sorted((v['score'] for v in out.values() if v['videos'] + v['own_videos'] >= 5), reverse=True)
    if len(proven) >= 3:
        cap = proven[2] - 1e-6
        for v in out.values():
            if v['videos'] + v['own_videos'] < 5:
                v['score'] = min(v['score'], cap)
    return out


def recent_viral(history, formats, cfg, m='de'):
    from . import hot
    return hot.counts(history, {}, formats, cfg['thresholds']['viral_views'], m)


def form(history, formats, cfg, own_stats=None, now=None):
    """Current form of EVERY format (list and archive): how likely one video of it does well right now. 1.0 = an
    average format at the moment.

    JobStep part: share of its videos with 100k+ (80%) and 20k+ (20%) views compared with all formats, where recent
    weeks count most (a video's weight halves every half_life_days). Few videos -> pulled towards 1.0, so a format
    with 6 tries is not judged like one with 30. Our part: x the factor from our own creators (see scores)."""
    lc = cfg.get('lineup', {})
    hl = lc.get('half_life_days', 21)
    k = cfg['ranking']['prior_weight'] * 0.5
    k_own = cfg['ranking'].get('own_prior_weight', 8)
    now = now or time.time()
    weight = lambda v: 0.5 ** ((now - v['created']) / 86400 / hl)
    tagged = [v for v in history.values() if v.get('format')]
    total = sum(weight(v) for v in tagged) or 1.0
    base = max(sum(weight(v) for v in tagged if v['views'] >= 100_000) / total, 1e-3)
    base20 = max(sum(weight(v) for v in tagged if v['views'] >= 20_000) / total, 1e-3)
    per = {}
    for v in tagged:
        per.setdefault(v['format'], []).append(v)
    out = {}
    for f in formats:
        vs = per.get(f['id'], [])
        n = sum(weight(v) for v in vs)
        p100 = (sum(weight(v) for v in vs if v['views'] >= 100_000) + base * k) / (n + k)
        p20 = (sum(weight(v) for v in vs if v['views'] >= 20_000) + base20 * k) / (n + k)
        js = 0.8 * p100 / base + 0.2 * p20 / base20
        o = (own_stats or {}).get(f['id'], {})
        factor = 2 ** (o.get('lift_sum', 0.0) / (o.get('n', 0) + k_own))
        out[f['id']] = {'form': js * factor, 'js_form': js, 'own_factor': factor, 'tries': n, 'all_videos': len(vs),
                        'own_videos': o.get('n', 0), 'own_lift': o.get('lift', 0.0)}
    return out


def own_stats(formats, market=None):
    from . import own, state
    return own.stats(state.load('own.json', {}), formats, time.time(), market=market)


def section(tier, hot_now):
    """0 = top card (proven for us, or hot for JobStep and not weak for us), 1 = the rest of the list."""
    return 0 if tier == 1 or (hot_now and tier != 4) else 1


def order(history, formats, cfg, m='de', local=(), tiers=None, market=None):
    """List order. Without tiers: the JobStep order (hot first, then what goes viral, then form). With tiers (one
    market's own.tiers): top card = formats proven for us, then the JobStep-hot ones that are not weak for us; then
    tier 2, 3, 4 - inside each part the JobStep order. market: only our creators of that market count."""
    from . import hot
    o = own_stats(formats, market)
    s = scores(history, formats, cfg, m, local, o)
    fo = form(history, formats, cfg, o)
    recent = recent_viral(history, formats, cfg, m)
    tiers = tiers if tiers is not None else {}
    use_tiers = bool(tiers)
    for fid in s:
        s[fid]['recent_viral'] = recent.get(fid, 0)
        s[fid]['recent_own'] = o.get(fid, {}).get('recent_viral', 0)
        s[fid]['form'] = fo[fid]['form']
        s[fid]['tier'] = tiers.get(fid, {}).get('tier', 3)
        s[fid]['hot'] = s[fid]['recent_viral'] >= hot.MIN_VIRAL
        s[fid]['top'] = section(s[fid]['tier'], s[fid]['hot']) == 0 if use_tiers else s[fid]['hot']

    def key(fid):
        x = s[fid]
        jobstep = (-x['hot'], -(x['recent_viral'] + x['recent_own']), -x['form'])
        if not use_tiers:
            return jobstep
        return (section(x['tier'], x['hot']), x['tier'] if x['tier'] != 1 else 0, *jobstep)
    return sorted(s, key=key), s
