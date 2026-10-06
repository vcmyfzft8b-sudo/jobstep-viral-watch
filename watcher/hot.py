"""Hot formats (per market): 5+ viral JobStep videos (100k+) of the same format posted within the last 7 days,
each confirmed by the strict Claude check as that market's format.

While a format is hot it gets a 🚀 callout at the top of that market's list; once per hot period an @everyone
announcement in the market's language goes to its Discord #announcements (webhook from discord_env) plus a Slack
message listing the videos. When it cools down (< 5), the callout is removed.
"""
import os
import time

import requests

from . import notify, notion, state
from .markets import fkey, jkey

MIN_VIRAL = 5
WINDOW_DAYS = 7


def viral_videos(history, videos, formats, viral_views, m='de'):
    """{format_id: [video, ...]} - confirmed viral videos posted in the last 7 days, for active formats."""
    now = time.time()
    active = {f['id'] for f in formats if f.get('status') == 'active'}
    fk, jk = fkey(m), jkey(m)
    seen, out = set(), {}
    for vid, v in list(videos.items()) + list(history.items()):
        if vid in seen:
            continue
        seen.add(vid)
        fid = v.get(fk)
        if (fid in active and v.get(jk) and v.get('views', 0) >= viral_views
                and now - v.get('created', 0) <= WINDOW_DAYS * 86400):
            out.setdefault(fid, []).append({'id': vid, **v})
    return out


def counts(history, videos, formats, viral_views, m='de'):
    return {fid: len(vs) for fid, vs in viral_videos(history, videos, formats, viral_views, m).items()}


def public_link(page_id):
    return f"https://parakeetai.notion.site/{page_id.replace('-', '')}"


def discord(url, text):
    if not url:
        return False
    try:
        r = requests.post(url, json={'content': text, 'username': 'Parakeet AI', 'allowed_mentions': {'parse': ['everyone']}},
                          timeout=20)
        return r.ok
    except requests.RequestException:
        return False


def update(history, videos, formats, cfg, meta, mkts, dry_run=False):
    """Recompute hot formats (shared list, creators of all markets) and show them in every market:
    🚀 callout at the top of each list + one @everyone Discord post per market in its language."""
    viral = cfg['thresholds']['viral_views']
    proof = viral_videos(history, videos, formats, viral)
    hot_now = {fid: len(vs) for fid, vs in proof.items() if len(vs) >= MIN_VIRAL}
    before = meta.get('hot', {})
    by_id = {f['id']: f for f in formats}
    print('hot formats:', {by_id[f]['title'][:40]: n for f, n in hot_now.items()} or 'none')
    if dry_run:
        return

    def page(f, m):
        return f.get('page_id') if m == 'de' else (f.get('pages') or {}).get(m)

    new = [fid for fid in hot_now if fid not in before]
    cooled = [fid for fid in before if fid not in hot_now]
    meta_hot = {}
    for fid, n in hot_now.items():
        old = before.get(fid, {})
        announced = old.get('announced', {})
        if not isinstance(announced, dict):  # older state: True/False meant DACH
            announced = {'de': bool(announced)}
        meta_hot[fid] = {'count': n, 'since': old.get('since', int(time.time())), 'announced': announced}
    # The hot formats themselves move up into the 🚀 section of every list (done by the re-sort in main.rerank).
    for mk in mkts:
        m, T = mk['key'], mk['T']
        url = os.environ.get(mk.get('discord_env', ''), '')
        for fid in [f for f in hot_now if not meta_hot[f]['announced'].get(m) and url and page(by_id[f], m)]:
            f, n = by_id[fid], hot_now[fid]
            title = notion_title(page(f, m)) or f['title']
            if discord(url, T['discord'].format(title=title, n=n)):
                meta_hot[fid]['announced'][m] = True
                state.log({'type': 'hot_announced', 'market': m, 'format': fid, 'count': n})
    for fid in new:
        f, n = by_id[fid], hot_now[fid]
        links = '\n'.join(f"• @{x['handle']} – {x['views'] // 1000}k – <https://www.tiktok.com/@{x['handle']}/video/{x['id']}|video>"
                          for x in sorted(proof.get(fid, []), key=lambda x: -x['views']))
        done = [mk['T']['flag'] for mk in mkts if meta_hot[fid]['announced'].get(mk['key'])]
        notify.push('🚀 HOT format',
                    f"*{f['title']}* – {n} viral videos in 7 days (each confirmed by Claude as this format):\n{links}\n\n"
                    f"Moved into the 🚀 section at the top of every list. Discord announcement: {' '.join(done) if done else 'none sent (no webhook)'}",
                    click=f"https://app.notion.com/p/{f['page_id'].replace('-', '')}")
        state.log({'type': 'hot', 'format': fid, 'count': n})
    for fid in cooled:
        notify.push('Hot format cooled down', f"*{by_id[fid]['title'] if fid in by_id else fid}* – fewer than {MIN_VIRAL} "
                    'viral videos in the last 7 days, back in the normal list.')
        state.log({'type': 'hot_cooled', 'format': fid})
    meta['hot'] = meta_hot


def notion_title(page_id):
    """The page's current title without the list number (e.g. the French title on the French page)."""
    import re
    try:
        p = notion.api('GET', f'/pages/{page_id}')
        t = ''.join(x['plain_text'] for x in next(v for v in p['properties'].values() if v['type'] == 'title')['title'])
        return re.sub(r'^\d+\.\s*', '', t)
    except Exception:
        return None
