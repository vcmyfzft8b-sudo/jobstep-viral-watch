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


def update(history, videos, formats, cfg, meta, market, dry_run=False):
    """Recompute hot formats for one market, update its Notion callouts and announce new ones."""
    m, T = market['key'], market['T']
    viral = cfg['thresholds']['viral_views']
    proof = viral_videos(history, videos, formats, viral, m)
    hot_now = {fid: len(vs) for fid, vs in proof.items() if len(vs) >= MIN_VIRAL}
    mkey = 'hot' if m == 'de' else f'hot_{m}'
    before = meta.get(mkey, {})
    by_id = {f['id']: f for f in formats}
    print(f"{T['flag']} hot formats:", {by_id[f]['title'][:40]: n for f, n in hot_now.items()} or 'none')
    if dry_run:
        return
    new = [fid for fid in hot_now if fid not in before]
    cooled = [fid for fid in before if fid not in hot_now]
    if new or cooled or any(before.get(f, {}).get('count') != n for f, n in hot_now.items()):
        notion.set_hot(market['list_page'], [(by_id[f]['page_id'], n) for f, n in
                                             sorted(hot_now.items(), key=lambda x: -x[1])], lang=market['lang'])
    meta_hot = {fid: {'count': n, 'since': before.get(fid, {}).get('since', int(time.time())),
                      'announced': before.get(fid, {}).get('announced', False)} for fid, n in hot_now.items()}
    url = os.environ.get(market.get('discord_env', ''), '')
    for fid in [f for f in hot_now if not meta_hot[f]['announced'] and url]:
        f, n = by_id[fid], hot_now[fid]
        if discord(url, T['discord'].format(title=f['title'], n=n, link=public_link(f['page_id']))):
            meta_hot[fid]['announced'] = True
            notify.push(f"📣 {T['flag']} Announced in Discord #announcements", f"*{f['title']}* ({n} viral videos in 7 days)")
            state.log({'type': 'hot_announced', 'market': m, 'format': fid, 'count': n})
    for fid in new:
        f, n = by_id[fid], hot_now[fid]
        links = '\n'.join(f"• @{x['handle']} – {x['views'] // 1000}k – <https://www.tiktok.com/@{x['handle']}/video/{x['id']}|video>"
                          for x in sorted(proof.get(fid, []), key=lambda x: -x['views']))
        notify.push(f"🚀 {T['flag']} HOT format ({T['name']})",
                    f"*{f['title']}* – {n} viral JobStep videos in 7 days (each confirmed by Claude as this format):\n{links}\n\n"
                    f"Pinned at the top of the {T['name']} list"
                    f"{' and announced in Discord #announcements' if meta_hot[fid]['announced'] else ' (Discord not connected – no announcement sent)'}.",
                    click=f"https://app.notion.com/p/{f['page_id'].replace('-', '')}")
        state.log({'type': 'hot', 'market': m, 'format': fid, 'count': n})
    for fid in cooled:
        notify.push(f"{T['flag']} Hot format cooled down", f"*{by_id[fid]['title'] if fid in by_id else fid}* – fewer than "
                    f"{MIN_VIRAL} viral videos in the last 7 days, removed from the top of the {T['name']} list.")
        state.log({'type': 'hot_cooled', 'market': m, 'format': fid})
    meta[mkey] = meta_hot
