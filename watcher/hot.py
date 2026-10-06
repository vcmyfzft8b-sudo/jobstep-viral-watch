"""Hot formats: 5+ viral JobStep videos (100k+) of the same format posted within the last 7 days.

While a format is hot it gets a 🚀 callout at the top of the DACH list ("geht gerade viral – dreh das jetzt"),
and the moment it becomes hot an @everyone announcement goes to the DACH Discord #announcements channel
(DISCORD_WEBHOOK_URL) plus a Slack message. When it cools down (< 5), the callout is removed again.
"""
import os
import time

import requests

from . import notify, notion, state

MIN_VIRAL = 5
WINDOW_DAYS = 7


def counts(history, videos, formats, viral_views):
    """{format_id: number of viral videos posted in the last 7 days} for active formats."""
    now = time.time()
    active = {f['id'] for f in formats if f.get('status') == 'active'}
    seen, out = set(), {}
    for vid, v in list(videos.items()) + list(history.items()):
        if vid in seen:
            continue
        seen.add(vid)
        fid = v.get('format')
        if fid in active and v.get('views', 0) >= viral_views and now - v.get('created', 0) <= WINDOW_DAYS * 86400:
            out[fid] = out.get(fid, 0) + 1
    return out


def public_link(page_id):
    return f"https://parakeetai.notion.site/{page_id.replace('-', '')}"


def discord(text):
    url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not url:
        return False
    try:
        r = requests.post(url, json={'content': text, 'allowed_mentions': {'parse': ['everyone']}}, timeout=20)
        return r.ok
    except requests.RequestException:
        return False


def update(history, videos, formats, cfg, meta, dry_run=False):
    """Recompute hot formats, update the Notion callouts and announce new ones."""
    c = counts(history, videos, formats, cfg['thresholds']['viral_views'])
    hot_now = {fid: n for fid, n in c.items() if n >= MIN_VIRAL}
    before = meta.get('hot', {})
    by_id = {f['id']: f for f in formats}
    print('hot formats:', {by_id[f]['title'][:40]: n for f, n in hot_now.items()} or 'none')
    if dry_run:
        return
    new = [fid for fid in hot_now if fid not in before]
    cooled = [fid for fid in before if fid not in hot_now]
    shown = {fid: n for fid, n in hot_now.items()}
    if new or cooled or any(before.get(f, {}).get('count') != n for f, n in shown.items()):
        notion.set_hot(cfg['notion']['dach_page'], [(by_id[f]['page_id'], n) for f, n in
                                                     sorted(shown.items(), key=lambda x: -x[1])])
    meta_hot = {fid: {'count': n, 'since': before.get(fid, {}).get('since', int(time.time())),
                      'announced': before.get(fid, {}).get('announced', False)} for fid, n in hot_now.items()}
    # Announce in Discord once per hot period - also later, if Discord was not connected yet when it became hot.
    for fid in [f for f in hot_now if not meta_hot[f]['announced'] and os.environ.get('DISCORD_WEBHOOK_URL')]:
        f, n = by_id[fid], hot_now[fid]
        if discord(f"@everyone 🔥 **Dieses Format geht gerade viral!**\n\n**{f['title']}**\n"
                   f"{n} JobStep-Videos mit über 100.000 Aufrufen in den letzten 7 Tagen.\n"
                   f"👉 Dreh es **jetzt als Nächstes** – Skript, Beispielvideo und alle Infos:\n{public_link(f['page_id'])}"):
            meta_hot[fid]['announced'] = True
            notify.push('📣 Announced in Discord #announcements', f"*{f['title']}* ({n} viral videos in 7 days)")
            state.log({'type': 'hot_announced', 'format': fid, 'count': n})
    for fid in new:
        f, n = by_id[fid], hot_now[fid]
        ok = meta_hot[fid]['announced']
        notify.push('🚀 HOT format', f"*{f['title']}* – {n} viral JobStep videos in 7 days.\n"
                    f"Pinned at the top of the DACH list{' and announced in Discord #announcements' if ok else ' (Discord not connected – no announcement sent)'}.",
                    click=f"https://app.notion.com/p/{f['page_id'].replace('-', '')}")
        state.log({'type': 'hot', 'format': fid, 'count': n, 'discord': ok})
    for fid in cooled:
        notify.push('Hot format cooled down', f"*{by_id[fid]['title'] if fid in by_id else fid}* – fewer than {MIN_VIRAL} viral videos "
                    'in the last 7 days, removed from the top of the list.')
        state.log({'type': 'hot_cooled', 'format': fid})
    meta['hot'] = meta_hot
