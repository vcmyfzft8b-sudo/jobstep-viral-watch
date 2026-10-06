"""Order of the formats on a market's list.

1. What is going viral RIGHT NOW: most confirmed viral videos (100k+) posted in the last 7 days first.
   (Hot formats - 5+ JobStep videos - always stay on top; our own creators' viral videos count here too.)
2. Tie-breaker / formats without viral videos this week: long-term score = smoothed share of videos with 100k+
   views + weight_20k * smoothed share with 20k+ views. Smoothing pulls small samples towards the network average,
   and new formats (< 5 videos) are capped below the three strongest proven formats.
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


def own_stats(formats):
    from . import own, state
    return own.stats(state.load('own.json', {}), formats, time.time())


def order(history, formats, cfg, m='de', local=()):
    from . import hot
    o = own_stats(formats)
    s = scores(history, formats, cfg, m, local, o)
    recent = recent_viral(history, formats, cfg, m)
    for fid in s:
        s[fid]['recent_viral'] = recent.get(fid, 0)
        s[fid]['recent_own'] = o.get(fid, {}).get('recent_viral', 0)
    return sorted(s, key=lambda fid: (-(s[fid]['recent_viral'] >= hot.MIN_VIRAL),
                                      -(s[fid]['recent_viral'] + s[fid]['recent_own']), -s[fid]['score'])), s
