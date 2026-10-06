"""Hot formats: 5+ viral videos (100k+) of the same format posted within the last 7 days, from creators of all
markets, each confirmed by the strict Claude check as that format.

While a format is hot it moves into the "going viral" section at the top of every list (main.rerank); once per hot period an
@everyone announcement in each market's language goes to its Discord #announcements (webhook from discord_env), the
same message goes into every creator's private channel (our bot, markets with creator_channels), plus a Slack message
listing the videos. When it cools down (< 5), it drops back into the normal order.
"""
import os
import time

import requests

from . import discord_bot, notify, notion, state
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
    """Posts via the webhook; returns the Discord message id ('' if it failed)."""
    if not url:
        return ''
    try:
        r = requests.post(url, params={'wait': 'true'}, json={'content': text, 'username': 'Parakeet AI',
                                                              'allowed_mentions': {'parse': ['everyone']}}, timeout=20)
        return r.json().get('id', 'sent') if r.ok else ''
    except (requests.RequestException, ValueError):
        return ''


def edit_discord(url, message_id, text):
    """Rewrites an announcement the webhook posted earlier (no new ping)."""
    r = requests.patch(f'{url}/messages/{message_id}', json={'content': text, 'allowed_mentions': {'parse': []}}, timeout=20)
    r.raise_for_status()


def announcement(T, f, n, page_id):
    """Discord text for format f: the exact title creators see in their list (with its number), never a Notion link."""
    import re
    title = notion_title(page_id, keep_number=True) or f['title']
    return T['discord'].format(title=re.sub(r'^(\d+)\.', r'\1\\.', title), n=n)  # "1\." - no Discord list


def update(history, videos, formats, cfg, meta, mkts, dry_run=False):
    """Recompute hot formats (shared list, creators of all markets) and show them in every market:
    "going viral" section at the top of each list + one @everyone Discord post per market in its language."""
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
        meta_hot[fid] = {'count': n, 'since': old.get('since', int(time.time())), 'announced': announced,
                         'creators': old.get('creators', {}), 'messages': old.get('messages', {})}
    # The hot formats themselves move up into the 🚀 section of every list (done by the re-sort in main.rerank).
    for mk in mkts:
        m, T = mk['key'], mk['T']
        url = os.environ.get(mk.get('discord_env', ''), '') if mk.get('discord_announce', True) else ''
        for fid in [f for f in hot_now if not meta_hot[f]['announced'].get(m) and url and page(by_id[f], m)]:
            f, n = by_id[fid], hot_now[fid]
            msg = discord(url, announcement(T, f, n, page(f, m)))
            if msg:
                meta_hot[fid]['announced'][m] = True
                meta_hot[fid]['messages'][m] = msg
                state.log({'type': 'hot_announced', 'market': m, 'format': fid, 'count': n})
        if mk.get('creator_channels') and discord_bot.token() and hot_now:
            try:
                chans = discord_bot.creator_channels(mk['discord_server'], cfg)
            except Exception as e:
                print(m, 'creator channels failed:', str(e)[:200])
                chans = []
            for fid in [f for f in hot_now if page(by_id[f], m)]:
                done = meta_hot[fid]['creators'].setdefault(m, [])
                text = announcement(T, by_id[fid], hot_now[fid], page(by_id[fid], m)).replace('@everyone ', '', 1)
                for c in [c for c in chans if c['id'] not in done]:
                    try:
                        discord_bot.send(c['id'], text, c['members'])
                        done.append(c['id'])
                    except Exception as e:
                        print(m, 'creator channel', c['name'], 'failed:', str(e)[:200])
                if done:
                    state.log({'type': 'hot_creators', 'market': m, 'format': fid, 'channels': len(done)})
    for fid in new:
        f, n = by_id[fid], hot_now[fid]
        links = '\n'.join(f"• @{x['handle']} – {x['views'] // 1000}k – <https://www.tiktok.com/@{x['handle']}/video/{x['id']}|video>"
                          for x in sorted(proof.get(fid, []), key=lambda x: -x['views']))
        done = [mk['T']['flag'] for mk in mkts if meta_hot[fid]['announced'].get(mk['key'])]
        notify.push('🚀 HOT format',
                    f"*{f['title']}* – {n} viral videos in 7 days (each confirmed by Claude as this format):\n{links}\n\n"
                    f"Moved into the going-viral section at the top of every list. Discord announcement: {' '.join(done) if done else 'none sent (no webhook)'}"
                    f" · creator channels: {sum(len(v) for v in meta_hot[fid]['creators'].values())}",
                    click=f"https://app.notion.com/p/{f['page_id'].replace('-', '')}")
        state.log({'type': 'hot', 'format': fid, 'count': n})
    for fid in cooled:
        notify.push('Hot format cooled down', f"*{by_id[fid]['title'] if fid in by_id else fid}* – fewer than {MIN_VIRAL} "
                    'viral videos in the last 7 days, back in the normal list.')
        state.log({'type': 'hot_cooled', 'format': fid})
    meta['hot'] = meta_hot


def notion_title(page_id, keep_number=False):
    """The page's current title (e.g. the French title on the French page), by default without the list number."""
    import re
    try:
        p = notion.api('GET', f'/pages/{page_id}')
        t = ''.join(x['plain_text'] for x in next(v for v in p['properties'].values() if v['type'] == 'title')['title'])
        return t if keep_number else re.sub(r'^\d+\.\s*', '', t)
    except Exception:
        return None
