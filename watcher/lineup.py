"""Weekly clean-up: each market's list keeps only its best formats (Monday, first run of the week).

User's rule (16 Oct 2026): "only the best converting and the most viral ones". Every market's list holds at most
lineup.list_size (12) formats - the best by conversion score (conversion.py: how many viewers save a format's videos
compared with a typical video of their market x sqrt(how well it goes viral right now); 1.0 = average) - PLUS in that
market: formats proven for OUR creators there (own.tiers tier 1: views AND saves like our typical video), hot formats
(5+ viral in 7 days that viewers also save), the lineup.keep_most_viral (3) formats with the most JobStep viral videos in
the last 30 days that viewers save at least like an average format, the lineup.keep_best_converting (3) formats viewers
save the most (with at least lineup.converting_min_videos measured videos) and formats the user pinned
(markets.<m>.pin_formats, e.g. the laptop ad spot in Slovenia). So the most viral AND the best converting formats are
always on every list (user, 16 Oct 2026: "a really bullet proof system").
Going viral in the last weeks or being new no longer protects a format.

- A format kept in no running market leaves completely: every market's page moves to that market's archive, status
  archived (nothing is deleted). It comes back on its own when a new video of it goes viral / converts AND is saved
  like a typical video (main.handle_viral), or when it becomes proven for our creators (main.own_comebacks).
- A format kept in some markets but not in another: only that market's page moves to that market's archive and the
  format gets the market in 'off_markets' (markets.for_format then leaves it out there: not listed, built, audited or
  checked). When it is among a market's best again on a later Monday, its page moves back and it is listed again.
Between Mondays new formats join the lists right away (a list can then be a bit longer than 12 until Monday).
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
    """What Monday does: {'lists': {market: {format_id: why kept}}, 'out': [(format, score, reason)] (leaves every
    list -> archive), 'off': {market: [format]} (leaves that market's list), 'back': {market: [format]} (back on that
    market's list), 'board': {format_id: score data}, 'protected': {format_id: why kept or None}, 'typical'}."""
    from . import conversion
    lc = cfg['lineup']
    cc = conversion.conf(cfg)
    size = lc.get('list_size', 12)
    now = now or time.time()
    running = {k: m for k, m in cfg['markets'].items() if m.get('enabled', True)}
    own_videos = {k: v for k, v in own_videos.items() if v.get('market') in running}  # only running campaigns count
    reach = rank.form(history, formats, cfg, own.stats(own_videos, formats, now), now)
    conv, base = conversion.board(history, formats, cfg, now, reach)
    board = {fid: {**reach[fid], **conv[fid]} for fid in reach}
    recent = rank.recent_viral(history, formats, cfg)
    hot_now = {fid for fid, n in recent.items() if n >= hot.MIN_VIRAL and conv.get(fid, {}).get('conv', 0) >= cc['hot_min_conv']}
    active = [f for f in formats if f.get('status') == 'active']
    score = lambda f: board[f['id']]['score']
    month = rank.viral_30d(history, formats, cfg, now)
    saved = lambda f: board[f['id']]['conv'] >= cc['hot_min_conv']
    most_viral = {f['id'] for f in sorted([f for f in active if month.get(f['id']) and saved(f)],
                                          key=lambda f: (-month[f['id']], -score(f)))[:lc.get('keep_most_viral', 3)]}
    best_conv = {f['id'] for f in sorted([f for f in active if board[f['id']]['videos'] >= lc.get('converting_min_videos', 3)
                                          and saved(f)], key=lambda f: -board[f['id']]['conv'])[:lc.get('keep_best_converting', 3)]}

    lists = {}
    for m, mc in running.items():
        tiers = own.tiers(own_videos, formats, now, m, cfg)
        cands = sorted([f for f in active if f['id'] not in (mc.get('skip_formats') or ())], key=score, reverse=True)
        best = {f['id'] for f in cands[:size]}
        keep = {}
        for f in cands:
            fid = f['id']
            if fid in (mc.get('pin_formats') or ()):
                keep[fid] = 'pinned by you'
            elif tiers.get(fid, {}).get('tier') == 1:
                keep[fid] = 'proven for our creators'
            elif fid in hot_now:
                keep[fid] = 'hot'
            elif fid in most_viral:
                keep[fid] = f'most viral now ({month[fid]} viral in 30 days)'
            elif fid in best_conv:
                keep[fid] = f"best converting (saved by {conversion.pct(board[fid]['raw_rate'])})"
            elif fid in best:
                keep[fid] = f'best {size} by score'
        lists[m] = keep

    order = ('pinned by you', 'proven for our creators', 'hot', 'most viral now', 'best converting')

    def rank_of(r):
        return next((i for i, o in enumerate(order) if r.startswith(o)), len(order))

    def why(f):
        reasons = [lists[m][f['id']] for m in lists if f['id'] in lists[m]]
        return min(reasons, key=rank_of) if reasons else None

    def reason(f):
        c = board[f['id']]
        return (f"not among the best {size} of any list: score {c['score']:.2f} (saved by {conversion.pct(c['raw_rate'])} "
                f"of viewers, {c['videos']} videos; typical video {conversion.pct(base['all'])}), not proven for our "
                f"creators, not hot, not among the most viral or best converting")

    out = [(f, score(f), reason(f)) for f in sorted(active, key=score) if not why(f)]
    gone = {f['id'] for f, _, _ in out}
    off, back = {}, {}
    for m, mc in running.items():
        skip = set(mc.get('skip_formats') or ())
        off[m] = [f for f in active if f['id'] not in gone and f['id'] not in skip and f['id'] not in lists[m]
                  and m not in (f.get('off_markets') or ())]
        back[m] = [f for f in active if f['id'] in lists[m] and m in (f.get('off_markets') or ())]
    return {'lists': lists, 'out': out, 'off': off, 'back': back, 'board': board,
            'protected': {f['id']: why(f) for f in active}, 'typical_rate': base['all'], 'typical': base}


def would_keep(history, formats, cfg, v, fid=None, own_videos=None, now=None):
    """Would a format brought back (fid, archived) or built new (fid None) from video v stay on a list on Monday?
    (user, 16 Oct 2026: no ping-pong - formats came back from 'converting' videos in the afternoon and the clean-up
    took them out again the same day). Returns (True, why kept) or (False, why not). Plays the Monday plan with the
    format live and v counted for it."""
    import copy
    if own_videos is None:
        own_videos = own.load()[1]
    fid = fid or '__new__'
    fmts = [dict(f, status='active') if f['id'] == fid else f for f in formats]
    if fid == '__new__':
        fmts = fmts + [{'id': fid, 'status': 'active', 'title': 'new'}]
    hist = dict(history)
    if v.get('id'):
        hist[v['id']] = {**copy.deepcopy(history.get(v['id'], {})), 'handle': v['handle'], 'created': v['created'],
                         'views': v['views'], 'likes': v.get('likes'), 'saves': v.get('saves'), 'shares': v.get('shares'),
                         'format': fid, 'judged': True}
    p = plan(hist, fmts, cfg, own_videos, now)
    kept = {m: keep[fid] for m, keep in p['lists'].items() if fid in keep}
    if kept:
        return True, '; '.join(f'{m}: {r}' for m, r in kept.items())
    b = p['board'][fid]
    return False, (f"would not stay on any list (score {b['score']:.2f}: not among the best "
                   f"{cfg['lineup'].get('list_size', 12)}, not proven for our creators, not hot, not among the most "
                   f"viral or best converting)")


def merge_duplicates(history, formats, cfg, own_videos, mkts, now=None, pairs=None):
    """Two live formats with near-identical titles in a market (dupes.find): the one with the better score stays,
    the other is archived as "duplicate of <kept>" (main.resolve follows it), its pages go to each market's archive
    and its videos (JobStep history, ours) count for the kept one. Returns [(dup, kept, why)]."""
    from . import conversion, dupes
    from . import main as watcher
    pairs = dupes.find(formats, mkts, watcher.page_of) if pairs is None else pairs
    if not pairs:
        return []
    now = now or time.time()
    reach = rank.form(history, formats, cfg, own.stats(own_videos, formats, now), now)
    conv, _ = conversion.board(history, formats, cfg, now, reach)
    by = {f['id']: f for f in formats}
    merged, today = [], time.strftime('%d.%m.%Y')
    for a, b, m, ta, tb in pairs:
        if by[a].get('status') != 'active' or by[b].get('status') != 'active':
            continue  # one of them was merged already
        keep, dup = (a, b) if conv[a]['score'] >= conv[b]['score'] else (b, a)
        f = by[dup]
        for mk in mkts:
            pid = watcher.page_of(f, mk['key'])
            if pid:
                try:
                    notion.move_page(pid, mk['archive_page'])
                except Exception as e:
                    print('dupes: move to archive failed', mk['key'], f['title'], str(e)[:120])
        why = f"same title in {m}: \"{ta}\" / \"{tb}\""
        f['status'] = 'archived'
        f['archived_reason'] = f"duplicate of {keep} (clean-up {today}: {why})"
        f.pop('off_markets', None)
        for v in history.values():
            if v.get('format') == dup:
                v['format'] = keep
        for v in own_videos.values():
            if v.get('format') == dup:
                v['format'] = keep
        state.log({'type': 'duplicate_merged', 'format': dup, 'into': keep, 'why': why})
        merged.append((f, by[keep], why))
    if merged:
        state.save('history.json', history)
        state.save('own.json', own_videos)
        notify.push('🔁 Same format twice on a list – merged', '\n'.join(
            f"➖ *{d['title']}* → kept *{k['title']}* ({why})" for d, k, why in merged) +
            '\n\n_The one with the better score stays; the other is archived as its duplicate and its videos count '
            'for the one that stays._')
    return merged


def apply(history, formats, cfg, own_videos, mkts, now=None):
    """Cuts every market's list to its best formats (see plan). mkts: the running markets. Returns the plan."""
    from . import main as watcher  # page helpers live in main
    try:  # the same format twice on a list: merged first (user, 16 Oct 2026)
        merge_duplicates(history, formats, cfg, own_videos, mkts, now)
    except Exception as e:
        print('clean-up: duplicate check failed', str(e)[:200])
    p = plan(history, formats, cfg, own_videos, now)
    today = time.strftime('%d.%m.%Y')
    by_key = {mk['key']: mk for mk in mkts}

    def move(f, mk, target, what):
        pid = watcher.page_of(f, mk['key'])
        if not pid:
            return
        try:
            notion.move_page(pid, mk[target])
        except Exception as e:
            print(f'clean-up: {what} failed', mk['key'], f['title'], str(e)[:150])

    for f, score, reason in p['out']:
        for mk in mkts:
            move(f, mk, 'archive_page', 'move to archive')
        f['status'] = 'archived'
        f['archived_reason'] = f'clean-up {today}: {reason}'
        f.pop('off_markets', None)  # a comeback starts in every market again
        state.log({'type': 'lineup_out', 'format': f['id'], 'form': round(score, 2), 'reason': reason})
    for m, fs in p['off'].items():
        if m not in by_key:
            continue
        for f in fs:
            move(f, by_key[m], 'archive_page', 'move off the list')
            f['off_markets'] = sorted(set(f.get('off_markets') or []) | {m})
            state.log({'type': 'lineup_off', 'format': f['id'], 'market': m, 'form': round(p['board'][f['id']]['score'], 2)})
    for m, fs in p['back'].items():
        if m not in by_key:
            continue
        for f in fs:
            move(f, by_key[m], 'holder_page', 'move back to the list')
            f['off_markets'] = [x for x in f.get('off_markets') or [] if x != m]
            if not f['off_markets']:
                f.pop('off_markets')
            state.log({'type': 'lineup_back', 'format': f['id'], 'market': m})
    flags = {mk['key']: mk['T']['flag'] for mk in mkts}
    lines = [f"➖ *{f['title']}* – {r}" for f, _, r in p['out']]
    for m, fs in p['off'].items():
        lines += [f"{flags.get(m, m)} ➖ *{f['title']}* – not among the best {cfg['lineup'].get('list_size', 12)} here "
                  f"(score {p['board'][f['id']]['score']:.2f})" for f in fs]
    for m, fs in p['back'].items():
        lines += [f"{flags.get(m, m)} ➕ *{f['title']}* – back among the best here" for f in fs]
    if lines:
        notify.push('🧹 Weekly list clean-up – only the best formats stay', '\n'.join(lines) +
                    '\n\n_Each list: the best 12 by score (how many viewers save a format x how well it goes viral) + '
                    'formats proven for our creators there + hot ones + pinned ones. Nothing is deleted – they sit in the '
                    'archive and come back on their own if a new video of theirs goes viral AND gets saved._')
    return p


def due(meta, now):
    """First run of the week on Monday (UTC)."""
    week = time.strftime('%G-W%V', time.gmtime(now))
    return time.gmtime(now).tm_wday == 0 and meta.get('lineup') != week, week
