"""Weekly clean-up: formats that perform badly leave the list (Monday, first run of the week).

There is no fixed number of spots. Every format in the list has a current-form score (rank.form: how likely one
video of it does well right now, JobStep + our own creators; 1.0 = an average format at the moment).

A format leaves the list when ALL of this is true:
- its current form is below lineup.remove_below (1.0 = below an average format right now),
- it had no viral video (100k+) in the last 21 days and is not hot,
- it came into the list more than lineup.protect_days ago (new formats get time).
The list never shrinks below lineup.min_formats (the weakest leave first).

Leaving = every market's page moves to that market's archive (nothing is deleted). Formats only come INTO the list
when they go viral: new ones are built, archived ones come back automatically (main.handle_viral).
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
    """Which formats would leave: {'out': [(format, form, reason)], 'board': {...}, 'protected': {...}}."""
    lc = cfg['lineup']
    now = now or time.time()
    board = rank.form(history, formats, cfg, own.stats(own_videos, formats, now), now)
    recent = rank.recent_viral(history, formats, cfg)
    viral21 = {}
    for v in history.values():
        if v.get('format') and v['views'] >= cfg['thresholds']['viral_views'] and now - v['created'] <= 21 * DAY:
            viral21[v['format']] = viral21.get(v['format'], 0) + 1

    def protected(f):
        if recent.get(f['id'], 0) >= hot.MIN_VIRAL:
            return 'hot'
        if viral21.get(f['id']):
            return f"{viral21[f['id']]} viral in the last 21 days"
        if now - listed_at(f) < lc['protect_days'] * DAY:
            return f"in the list for less than {lc['protect_days']} days"
        return None

    active = [f for f in formats if f.get('status') == 'active']
    form = lambda f: board[f['id']]['form']
    bad = sorted([f for f in active if not protected(f) and form(f) < lc['remove_below']], key=form)
    room = max(0, len(active) - lc['min_formats'])
    out = [(f, form(f), f"current form {form(f):.2f} (below average) and no viral video in the last 21 days")
           for f in bad[:room]]
    return {'out': out, 'board': board, 'protected': {f['id']: protected(f) for f in active}}


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
            '\n\n_Form 1.0 = an average format right now. Nothing is deleted – they sit in the archive and come back '
            'on their own if they go viral again._')
    return p


def due(meta, now):
    """First run of the week on Monday (UTC)."""
    week = time.strftime('%G-W%V', time.gmtime(now))
    return time.gmtime(now).tm_wday == 0 and meta.get('lineup') != week, week
