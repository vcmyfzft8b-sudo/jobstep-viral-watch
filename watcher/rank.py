"""Order of the formats on the DACH page, from how every JobStep video of each format performed.

score = smoothed share of videos with 100k+ views + weight_20k * smoothed share with 20k+ views
(every video counts with its views, no matter how long it took to get them).
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
            n += w
            hits += w * (v['views'] >= 100_000)
            hits20 += w * (v['views'] >= 20_000)
        k = r['prior_weight']
        p100 = (hits + r['prior_hit_rate'] * k) / (n + k)
        p20 = (hits20 + r['prior_20k_rate'] * k) / (n + k)
        out[f['id']] = {'score': p100 + r['weight_20k'] * p20, 'videos': n, 'hits_100k': hits, 'hits_20k': hits20}
    return out


def recent_viral(history, formats, cfg):
    """{format_id: confirmed viral videos (100k+) posted in the last 7 days} - what is going viral right now."""
    from . import hot
    return hot.counts(history, {}, formats, cfg['thresholds']['viral_views'])


def order(history, formats, cfg):
    """List order = what creators should make RIGHT NOW: most confirmed viral videos in the last 7 days first.
    Ties (and formats without viral videos this week) are ordered by the long-term score below."""
    s = long_term_order_scores(history, formats, cfg)
    recent = recent_viral(history, formats, cfg)
    for fid in s:
        s[fid]['recent_viral'] = recent.get(fid, 0)
    return sorted(s, key=lambda fid: (-s[fid]['recent_viral'], -s[fid]['score'])), s


def long_term_order_scores(history, formats, cfg):
    """Long-term score; new formats (fewer than 5 videos) are capped below the three strongest proven ones."""
    s = scores(history, formats, cfg)
    proven = sorted((v['score'] for v in s.values() if v['videos'] >= 5), reverse=True)
    if len(proven) >= 3:
        cap = proven[2] - 1e-6
        for v in s.values():
            if v['videos'] < 5:
                v['score'] = min(v['score'], cap)
    return s
