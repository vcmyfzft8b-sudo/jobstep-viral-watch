"""Monday report in Slack (#jobstep-radar): how the formats did last week, for JobStep AND for our own creators."""
import time

from . import notify, rank, state

WEEK = 7 * 86400


def _k(n):
    return f'{n / 1_000_000:.1f}M' if n >= 1_000_000 else f'{n / 1000:.0f}k' if n >= 1000 else str(n)


def report(history, own_videos, own_accounts, fmts, cfg, now):
    by_id = {f['id']: f for f in fmts}
    title = lambda fid: by_id[fid]['title'] if fid in by_id else '(not in our formats)'
    ids, s = rank.order(history, fmts, cfg)
    week = {vid: v for vid, v in history.items() if now - v['created'] <= WEEK}
    ours = {vid: v for vid, v in own_videos.items() if v.get('ours') and now - v['created'] <= WEEK}

    lines = [f"_{time.strftime('%d.%m.', time.gmtime(now - WEEK))}–{time.strftime('%d.%m.%Y', time.gmtime(now))}_", '',
             '*Top 5 formats (current list order)*']
    for n, fid in enumerate(ids[:5], 1):
        js = [v for v in week.values() if v.get('format') == fid]
        us = [v for v in ours.values() if v.get('format') == fid]
        lines.append(f"{n}. *{title(fid)}*\n      JobStep: {len(js)} videos, {sum(v['views'] >= 100_000 for v in js)} viral"
                     f" · Ours: {len(us)} videos, {_k(sum(v['views'] for v in us))} views"
                     + (f", best {_k(max(v['views'] for v in us))}" if us else '')
                     + (f" · for us so far: {2 ** s[fid]['own_lift']:.1f}x our creators' usual views"
                        f" ({s[fid]['own_videos']} videos)" if s[fid]['own_videos'] else ' · no videos of ours yet'))

    log = [e for e in state.load('log.json', []) if now - e['ts'] <= WEEK]
    built = [title(e['format']) for e in log if e['type'] == 'format_built']
    revived = [title(e['format']) for e in log if e['type'] == 'format_revived']
    hot = list(dict.fromkeys(title(e['format']) for e in log if e['type'] == 'hot'))
    gone = [f"{title(e['format'])} ({e['form']})" for e in log if e['type'] == 'lineup_out']
    came = [f"{title(e['format'])} ({e['form']})" for e in log if e['type'] == 'lineup_in']
    lines += ['', f"*Lineup – taken out:* {', '.join(gone) if gone else 'none'}",
              f"*Lineup – brought in:* {', '.join(came) if came else 'none'}"]
    lines += [f"*New formats added:* {', '.join(built) if built else 'none'}",
              f"*Brought back from the archive:* {', '.join(revived) if revived else 'none'}",
              f"*Went hot (5+ viral):* {', '.join(hot) if hot else 'none'}"]

    creators = {}
    for v in week.values():
        c = creators.setdefault(v['handle'], {'views': 0, 'videos': 0, 'viral': 0})
        c['views'] += v['views']
        c['videos'] += 1
        c['viral'] += v['views'] >= 100_000
    top = sorted(creators.items(), key=lambda x: -x[1]['views'])[:5]
    lines += ['', '*JobStep creators blowing up*'] + [
        f"• <https://www.tiktok.com/@{h}|@{h}> – {_k(c['views'])} views, {c['videos']} videos, {c['viral']} viral"
        for h, c in top]

    best = sorted(ours.items(), key=lambda x: -x[1]['views'])[:5]
    lines += ['', f"*Our creators:* {sum(1 for a in own_accounts.values() if a.get('status') == 'active')} accounts tracked · "
                  f"{len(ours)} videos this week · {_k(sum(v['views'] for v in ours.values()))} views",
              '*Our best videos this week*'] + [
        f"• <https://www.tiktok.com/@{v['handle']}/video/{vid}|@{v['handle']}> – {_k(v['views'])} – "
        f"{title(v['format']) if v.get('format') else 'format not sorted yet'}" for vid, v in best]
    if not best:
        lines.append('• none yet')
    return '\n'.join(lines)


def maybe_send(meta, history, own_videos, own_accounts, fmts, cfg, now, force=False):
    """Sends once per week, on the first run on Monday (UTC) - or right away with force=True."""
    week_id = time.strftime('%G-W%V', time.gmtime(now))
    if not force and (time.gmtime(now).tm_wday != 0 or meta.get('weekly') == week_id):
        return False
    notify.push('📊 Weekly format report', report(history, own_videos, own_accounts, fmts, cfg, now))
    if not force:
        meta['weekly'] = week_id
    state.log({'type': 'weekly', 'week': week_id})
    return True
