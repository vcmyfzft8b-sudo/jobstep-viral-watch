"""Order of the formats on a market's list.

1. What is going viral RIGHT NOW: most confirmed viral videos (100k+) posted in the last 7 days first.
2. Tie-breaker / formats without viral videos this week: long-term score = smoothed share of videos with 100k+
   views + weight_20k * smoothed share with 20k+ views. Smoothing pulls small samples towards the network average,
   creators of the market's own language count double, and new formats (< 5 videos) are capped below the three
   strongest proven formats.
"""
from .markets import fkey


def scores(history, formats, cfg, m='de', local=()):
    r = cfg['ranking']
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
        out[f['id']] = {'score': p100 + r['weight_20k'] * p20, 'videos': n, 'hits_100k': hits, 'hits_20k': hits20}
    proven = sorted((v['score'] for v in out.values() if v['videos'] >= 5), reverse=True)
    if len(proven) >= 3:
        cap = proven[2] - 1e-6
        for v in out.values():
            if v['videos'] < 5:
                v['score'] = min(v['score'], cap)
    return out


def recent_viral(history, formats, cfg, m='de'):
    from . import hot
    return hot.counts(history, {}, formats, cfg['thresholds']['viral_views'], m)


def order(history, formats, cfg, m='de', local=()):
    s = scores(history, formats, cfg, m, local)
    recent = recent_viral(history, formats, cfg, m)
    for fid in s:
        s[fid]['recent_viral'] = recent.get(fid, 0)
    return sorted(s, key=lambda fid: (-s[fid]['recent_viral'], -s[fid]['score'])), s
