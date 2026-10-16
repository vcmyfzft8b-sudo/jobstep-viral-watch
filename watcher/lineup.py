"""Weekly clean-up: formats that do not convert leave the list (Monday, first run of the week).

User's rule (16 Oct 2026, like the Memo AI watcher): the lists hold formats that convert best and still go viral -
not formats that only go viral. Every format has a conversion score (conversion.py / rank.order: how many viewers
save its videos compared with a typical video of their market x how well it goes viral right now; 1.0 = average).

A format leaves the list when it is not protected and
- once conversion.judge_min_videos+ of its videos have a known save count: its score is below conversion.remove_below.
  Then neither going viral nor being new protects it - only being proven for OUR creators in a running market
  (own.tiers tier 1, which needs our viewers to save it too), hot (5+ viral in 7 days that viewers also save) or a
  viral video in the last 21 days while viewers save it at least like an average format;
- with fewer measured videos: its current form (reach) is below lineup.remove_below, no viral video in the last 21
  days and it came into the list more than lineup.protect_days ago (like before).
The list never shrinks below lineup.min_formats (the weakest leave first).

Leaving = every market's page moves to that market's archive (nothing is deleted). Formats come INTO the list when a
video goes viral / rises with enough saves or converts (main.handle_viral): new ones are built, archived ones come
back - and archived formats proven for our creators come back by themselves (main.own_comebacks).
"""
import datetime
import re
import time

from . import hot, notion, notify, own, rank, state

DAY = 86400


def listed_at(f):
    """When the format came into the list (0 = it has been there since before the lineup existed)."""
    if f.get('listed_at'):
        return f['listed_at']
    if (f.get('revived') or {}).get('at'):
        return f['revived']['at']
    m = re.match(r'A(\d{14})$', f['id'])  # formats built by the watcher: A + build time
    if m:
        return int(datetime.datetime.strptime(m.group(1), '%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc).timestamp())
    return 0


def plan(history, formats, cfg, own_videos, now=None):
    """Which formats would leave: {'out': [(format, score, reason)], 'board': {...}, 'protected': {...}}."""
    from . import conversion
    lc = cfg['lineup']
    cc = conversion.conf(cfg)
    now = now or time.time()
    stopped = {k for k, m in cfg['markets'].items() if not m.get('enabled', True)}
    own_videos = {k: v for k, v in own_videos.items() if v.get('market') not in stopped}  # only running campaigns count
    reach = rank.form(history, formats, cfg, own.stats(own_videos, formats, now), now)
    conv, base = conversion.board(history, formats, cfg, now, reach)
    board = {fid: {**reach[fid], **conv[fid]} for fid in reach}
    recent = rank.recent_viral(history, formats, cfg)
    viral21 = {}
    for v in history.values():
        if v.get('format') and v['views'] >= cfg['thresholds']['viral_views'] and now - v['created'] <= 21 * DAY:
            viral21[v['format']] = viral21.get(v['format'], 0) + 1

    running = [k for k, m in cfg['markets'].items() if m.get('enabled', True)]
    proven = {fid for m in running for fid, x in own.tiers(own_videos, formats, now, m, cfg).items() if x['tier'] == 1}

    def measured(f):
        return conv[f['id']]['videos'] >= cc['judge_min_videos']

    def protected(f):
        c = conv[f['id']]
        if f['id'] in proven:
            return 'proven for our creators'
        if recent.get(f['id'], 0) >= hot.MIN_VIRAL and c['conv'] >= cc['hot_min_conv']:
            return 'hot'
        if viral21.get(f['id']) and (not measured(f) or c['conv'] >= cc['hot_min_conv']):
            return f"{viral21[f['id']]} viral in the last 21 days"
        if now - listed_at(f) < lc['protect_days'] * DAY and not measured(f):
            return f"in the list for less than {lc['protect_days']} days"
        return None

    def value(f):
        return conv[f['id']]['score'] if measured(f) else reach[f['id']]['form']

    def limit(f):
        return cc['remove_below'] if measured(f) else lc['remove_below']

    def reason(f):
        c = conv[f['id']]
        if measured(f):
            return (f"saved by {conversion.pct(c['raw_rate'])} of viewers ({c['videos']} videos; typical video "
                    f"{conversion.pct(base['all'])}) - score {c['score']:.2f}, below {cc['remove_below']}")
        return f"current form {reach[f['id']]['form']:.2f} (below average) and no viral video in the last 21 days"

    active = [f for f in formats if f.get('status') == 'active']
    bad = sorted([f for f in active if not protected(f) and value(f) < limit(f)], key=value)
    room = max(0, len(active) - lc['min_formats'])
    out = [(f, value(f), reason(f)) for f in bad[:room]]
    return {'out': out, 'board': board, 'protected': {f['id']: protected(f) for f in active}, 'typical_rate': base['all'],
            'typical': base}


def apply(history, formats, cfg, own_videos, mkts, now=None):
    """Moves the badly performing formats out of the list in every market. Returns the plan."""
    from . import main as watcher  # page helpers live in main
    p = plan(history, formats, cfg, own_videos, now)
    today = time.strftime('%d.%m.%Y')
    for f, score, reason in p['out']:
        for mk in mkts:
            pid = watcher.page_of(f, mk['key'])
            if pid:
                try:
                    notion.move_page(pid, mk['archive_page'])
                except Exception as e:
                    print('clean-up: move to archive failed', mk['key'], f['title'], str(e)[:150])
        f['status'] = 'archived'
        f['archived_reason'] = f'clean-up {today}: {reason}'
        state.log({'type': 'lineup_out', 'format': f['id'], 'form': round(score, 2), 'reason': reason})
    if p['out']:
        notify.push('🧹 Formats taken out of the lists (DE/FR/ES)', '\n'.join(
            f"➖ *{f['title']}* – {r}" for f, _, r in p['out']) +
            '\n\n_Score 1.0 = an average format (how many viewers save it x how well it goes viral). Nothing is deleted '
            '– they sit in the archive and come back on their own if a new video of theirs goes viral AND gets saved._')
    return p


def due(meta, now):
    """First run of the week on Monday (UTC)."""
    week = time.strftime('%G-W%V', time.gmtime(now))
    return time.gmtime(now).tm_wday == 0 and meta.get('lineup') != week, week
