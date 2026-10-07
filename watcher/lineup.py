"""Weekly lineup: which formats are in the list at all (Monday, first run of the week).

The list has a fixed number of spots (config lineup.spots). Every format - in the list AND in the archive - has a
current-form score (rank.form: how likely one video of it does well right now, JobStep + our own creators).

- Swap: the weakest format in the list is replaced by the best one on the bench (archive) if that one is clearly
  better (lineup.margin, e.g. 1.2 = 20%). At most lineup.max_swaps per week.
- Protected (never taken out): hot formats, formats that had a viral video in the last 21 days, and formats that came
  into the list less than lineup.protect_days ago.
- The bench only counts formats with real evidence: at least min_own_videos of our creators' videos or min_tries
  (weighted) JobStep videos. Formats archived as duplicates or without a German page never come back this way.
- List too long (new formats came in during the week): the weakest unprotected ones leave. List too short: the best
  bench formats with at least average form (1.0) come in.

Taking out = every market's page moves to that market's archive. Bringing back = pages move back exactly as they
are (hand-made pages keep their audio files etc.); a market without a page gets one, built from our creators' best
video of the format. Nothing is ever deleted, and a format that goes viral later comes back on its own anyway.
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
    """What would change: {'out': [(format, form, reason)], 'in': [(format, form, reason)], 'board': {...}}."""
    lc = cfg['lineup']
    now = now or time.time()
    o = own.stats(own_videos, formats, now)
    board = rank.form(history, formats, cfg, o, now)
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

    def eligible(f):
        b = board[f['id']]
        return (f.get('page_id') and not (f.get('archived_reason') or '').startswith('duplicate')
                and not f.get('market_only')
                and (b['own_videos'] >= lc['min_own_videos'] or b['tries'] >= lc['min_tries']))

    active = [f for f in formats if f.get('status') == 'active']
    weak = sorted([f for f in active if not protected(f)], key=lambda f: board[f['id']]['form'])
    bench = sorted([f for f in formats if f.get('status') != 'active' and eligible(f)], key=lambda f: -board[f['id']]['form'])
    out, inn = [], []
    form = lambda f: board[f['id']]['form']
    # too many formats: the weakest unprotected ones leave
    while len(active) - len(out) > lc['spots'] and weak:
        f = weak.pop(0)
        out.append((f, form(f), f"list is over {lc['spots']} formats and it is the weakest"))
    # swaps
    for _ in range(lc['max_swaps']):
        if not weak or not bench or form(bench[0]) < form(weak[0]) * lc['margin']:
            break
        f, g = weak.pop(0), bench.pop(0)
        out.append((f, form(f), f"form {form(f):.2f} vs {form(g):.2f} for {g['title']}"))
        inn.append((g, form(g), f"form {form(g):.2f} replaces {f['title']}"))
    # too few formats: the best bench formats with at least average form come in
    while len(active) - len(out) + len(inn) < lc['spots'] and bench and form(bench[0]) >= 1.0:
        g = bench.pop(0)
        inn.append((g, form(g), f"list had a free spot, form {form(g):.2f}"))
    return {'out': out, 'in': inn, 'board': board, 'protected': {f['id']: protected(f) for f in active}}


def _best_own_video(fid, own_videos):
    vs = [(vid, v) for vid, v in own_videos.items() if v.get('format') == fid and v.get('ours')]
    return max(vs, key=lambda x: x[1]['views'], default=None)


def apply(history, formats, cfg, own_videos, mkts, now=None):
    """Carries out the plan in every market. Returns the plan."""
    from . import main as watcher  # page building lives in main
    from . import tiktok
    p = plan(history, formats, cfg, own_videos, now)
    today = time.strftime('%d.%m.%Y')
    for f, score, reason in p['out']:
        for mk in mkts:
            pid = watcher.page_of(f, mk['key'])
            if pid:
                try:
                    notion.move_page(pid, mk['archive_page'])
                except Exception as e:
                    print('lineup: move to archive failed', mk['key'], f['title'], str(e)[:150])
        f['status'] = 'archived'
        f['archived_reason'] = f'lineup {today}: {reason}'
        state.log({'type': 'lineup_out', 'format': f['id'], 'form': round(score, 2), 'reason': reason})
    missing_by = {}
    for f, score, reason in p['in']:
        missing = missing_by[f['id']] = []
        for mk in mkts:
            pid = watcher.page_of(f, mk['key'])
            try:
                if pid:
                    notion.move_page(pid, mk['holder_page'])
                    continue
                best = _best_own_video(f['id'], own_videos)
                v = tiktok.video_detail(best[1]['handle'], best[0]) if best else None
                if not v:
                    missing.append(mk['T']['flag'])
                    continue
                v['own'] = True
                new_pid, spec, problems = watcher.make_page(v, mk, cfg, None)
                if problems:
                    missing.append(mk['T']['flag'] + ' (draft on the radar page)')
                else:
                    watcher.set_page(f, mk['key'], new_pid)
            except Exception as e:
                missing.append(mk['T']['flag'])
                print('lineup: bring back failed', mk['key'], f['title'], str(e)[:150])
        f['status'] = 'active'
        f.pop('archived_reason', None)
        f['listed_at'] = int(now or time.time())
        state.log({'type': 'lineup_in', 'format': f['id'], 'form': round(score, 2), 'reason': reason,
                   'missing': missing})
    if p['out'] or p['in']:
        lines = [f"➖ *{f['title']}* ({s:.2f}) – {r}" for f, s, r in p['out']]
        lines += [f"➕ *{f['title']}* ({s:.2f}) – {r}" + (f" · no page yet in {', '.join(missing_by[f['id']])}"
                                                         if missing_by.get(f['id']) else '') for f, s, r in p['in']]
        notify.push('🔄 Weekly lineup change (DE/FR/ES lists)', '\n'.join(lines) +
                    '\n\n_Form 1.0 = an average format right now. Nothing is deleted – taken-out formats sit in the archive '
                    'and come back on their own if they go viral._')
    return p


def due(meta, now):
    """First run of the week on Monday (UTC)."""
    week = time.strftime('%G-W%V', time.gmtime(now))
    return time.gmtime(now).tm_wday == 0 and meta.get('lineup') != week, week
