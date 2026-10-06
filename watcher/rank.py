"""Order of the formats on the DACH page, from how every JobStep video of each format performed.

score = smoothed share of videos with 100k+ views + weight_20k * smoothed share with 20k+ views,
counting only views reached within the first 7 days after posting (exact for every video we tracked from the
start; for older videos first seen later, today's total views / 1.2 is used as a cautious estimate).
Smoothing pulls small samples towards the network average (prior), so one lucky video can't top the list
on its own, but a new format with a real hit still ranks high. German creators' videos count double.
"""


def scores(history, formats, cfg):
    r = cfg['ranking']
    german = set(cfg['german_accounts'])
    out = {}
    for f in formats:
        if f.get('status') != 'active':
            continue
        n = hits = hits20 = 0.0
        for v in history.values():
            if v.get('format') != f['id']:
                continue
            w = r['german_weight'] if v['handle'] in german else 1
            v7 = v['views_7d'] if v.get('views_7d') is not None else v['views'] / 1.2
            n += w
            hits += w * (v7 >= 100_000)
            hits20 += w * (v7 >= 20_000)
        k = r['prior_weight']
        p100 = (hits + r['prior_hit_rate'] * k) / (n + k)
        p20 = (hits20 + r['prior_20k_rate'] * k) / (n + k)
        out[f['id']] = {'score': p100 + r['weight_20k'] * p20, 'videos': n, 'hits_100k': hits, 'hits_20k': hits20}
    return out


def order(history, formats, cfg):
    """New formats (fewer than 5 videos) can enter at position 4 at the highest - right after the three
    strongest proven formats - and only climb further once more of their videos prove them."""
    s = scores(history, formats, cfg)
    proven = sorted((v['score'] for v in s.values() if v['videos'] >= 5), reverse=True)
    if len(proven) >= 3:
        cap = proven[2] - 1e-6
        for v in s.values():
            if v['videos'] < 5:
                v['score'] = min(v['score'], cap)
    return sorted(s, key=lambda fid: -s[fid]['score']), s
