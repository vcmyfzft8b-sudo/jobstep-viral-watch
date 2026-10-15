"""One watcher run (GitHub Actions every 2 hours: a full run every 6 hours, light runs - new videos, views, alerts - in
between), for all markets (DACH / France / Spain).

1. Pull the latest videos of every JobStep account; new ones go on the watchlist (7 days).
2. Re-check every watchlist video (views, likes, shares, saves).
3. Alerts: taking off (short Slack message) / viral (Slack message with English script + Claude's verdict per market).
4. Viral videos: per market, Claude judges the format against that market's formats (list + archive):
   in the list -> report; in the archive -> bring back; new -> build the page in the market's language.
5. Per market: sort the list by confirmed viral videos in the last 7 days, 🚀 hot spot + Discord for 5+.
6. Every few days: complete the JobStep account list (Lightreel).
"""
import argparse
import datetime
import json
import os
import re
import shutil
import tempfile
import time
import traceback

from . import align, audit, builder, classify, crosscheck, detect, discover, gate, hot, lineup, llm, localize, markets as M, media, notify, notion, own, rank, reword, soniox, state, tidy, tiktok, verify, weekly

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ALL_MARKETS = ('de', 'fr', 'es', 'sl')


CTX = {}  # meta + accounts of the current run (the quality gate needs them)


def _gate(fmt, mkts, fmts, history, cfg, kind):
    """Quality gate for a built/revived format: (published, position, reasons)."""
    mkts = M.for_format(mkts, fmt)
    meta, accounts = CTX.get('meta', {}), CTX.get('accounts') or state.load('accounts.json', {})
    ok, reasons = gate.check(fmt, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild_page)
    if ok:
        checkpoint = lambda: (state.save('formats.json', fmts), state.save('meta.json', meta))
        try:
            gate.publish(fmt, mkts, page_of, checkpoint)
        except Exception as e:
            gate.hold(fmt, [str(e)], kind, count_attempt=False)
            return False, None, [str(e)]
        return gate.finish_listing(fmt, mkts, fmts, history, cfg, rerank, checkpoint)
    gate.hold(fmt, reasons, kind, count_attempt=not gate.has_unknown(fmt, mkts, meta))
    return False, None, reasons


def load_config():
    with open(os.path.join(ROOT, 'config.json')) as f:
        cfg = json.load(f)
    if os.environ.get('NOTION_RADAR_PAGE'):
        cfg['notion']['radar_page'] = os.environ['NOTION_RADAR_PAGE']
    return cfg


def load_formats():
    """One shared format list for all markets. Each format has a page per market: page_id (DACH) + pages{fr, es, sl}."""
    formats = state.load('formats.json', None)
    if formats is None:
        with open(os.path.join(ROOT, 'registry', 'formats.json')) as f:
            formats = json.load(f)
    adopt_market_pages(formats)
    return formats


def adopt_market_pages(formats, adopt=None):
    """A new market whose pages were made by copying another market's pages (registry/market_adopt.json, e.g.
    Slovenia = translated copies of the France pages) gets each copy linked to its format once: pages[market] = copy.
    The example video is not copied over - localize looks for one in the new market's language like for every
    market. 'adopted' remembers it, so a page removed later is never linked again. Returns how many were linked."""
    if adopt is None:
        try:
            with open(os.path.join(ROOT, 'registry', 'market_adopt.json')) as f:
                adopt = json.load(f)
        except FileNotFoundError:
            return 0
    n = 0
    for m, spec in adopt.items():
        if m.startswith('_'):
            continue
        copies = {k.replace('-', ''): v for k, v in spec['pages'].items()}
        for fmt in formats:
            if (fmt.get('adopted') or {}).get(m) or page_of(fmt, m):
                continue
            src = (page_of(fmt, spec['from']) or '').replace('-', '')
            if src in copies:
                fmt.setdefault('pages', {})[m] = copies[src]
                fmt.setdefault('adopted', {})[m] = True
                n += 1
    return n


def page_of(fmt, m):
    return fmt.get('page_id') if m == 'de' else (fmt.get('pages') or {}).get(m)


def local_accounts(account_info, cfg, lang):
    local = {h for h, a in account_info.items() if a.get('lang') == lang}
    return local | set(cfg['german_accounts']) if lang == 'de' else local


def fmt_views(n):
    return f'{n / 1000:.0f}k' if n >= 1000 else str(n)


def page_url(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}"


def to_history(history, v, german, now):
    old = history.get(v['id'], {})
    entry = {'handle': v['handle'], 'created': v['created'], 'views': v['views'], 'hook': v.get('hook_en', ''),
             'german': v['handle'] in german, 'mature': now - v['created'] >= 7 * 86400,
             'format': v.get('format', old.get('format')), 'judged': bool(v.get('judged') or old.get('judged'))}
    if now - v['created'] <= 7.5 * 86400:
        entry['views_7d'] = v['views']
    elif 'views_7d' in old:
        entry['views_7d'] = old['views_7d']
    history[v['id']] = entry


def set_format(v, history, fid, judged=None):
    v['format'] = fid
    h = history.get(v['id'])
    if h is not None:
        h['format'] = fid
    if judged:
        v['judged'] = True
        if h is not None:
            h['judged'] = True


def resolve(formats, fid):
    """Formats archived as duplicates point to the format they duplicate."""
    f = next((x for x in formats if x['id'] == fid), None)
    seen = set()
    while f and f.get('archived_reason', '').startswith('duplicate of ') and f['id'] not in seen:
        seen.add(f['id'])
        target = f['archived_reason'].split()[2]
        f = next((x for x in formats if x['id'] == target), f)
    return f


FULL_EVERY_HOURS = 6  # the 2-hourly schedule makes a full run every 6 hours, light runs in between
LIGHT_DETAIL_VIEWS = 50_000  # light runs: full stats only for videos under 30 h or with this many views
NO_RUN_ALERT_HOURS = 12  # Slack note when GitHub left this long a gap between two runs
FAILED = []  # steps of this run that failed (they do not stop the run) -> one Slack note


def is_light(meta, now, auto):
    """A scheduled (auto) run is light unless the last full run is about FULL_EVERY_HOURS old."""
    return auto and now - meta.get('last_full_run', 0) < (FULL_EVERY_HOURS - 0.5) * 3600


def step_failed(step, e):
    print(f'{step} failed:', str(e)[:200], flush=True)
    FAILED.append(f'{step}: {str(e)[:150]}')


def report_failures(meta, now):
    """One Slack note when steps failed - again only when other steps fail or a day has passed (no ping every 2 h)."""
    if not FAILED:
        meta.pop('failed_steps', None)
        return
    sig = sorted(x.split(':')[0] for x in FAILED)
    last = meta.get('failed_steps') or {}
    if last.get('sig') == sig and now - last.get('at', 0) < 86400:
        return
    notify.push(f'⚠️ JobStep watcher: {len(FAILED)} step(s) failed this run', '\n'.join(FAILED)[:1500] +
                '\nThe rest of the run went on. <https://github.com/vcmyfzft8b-sudo/jobstep-viral-watch/actions|GitHub runs>')
    meta['failed_steps'] = {'sig': sig, 'at': int(now)}


def run(dry_run=False, only_detect=False, auto=False):
    cfg = load_config()
    mkts = M.load(cfg)
    fmts = load_formats()
    videos = state.load('videos.json', {})
    history = state.load('history.json', {})
    meta = state.load('meta.json', {})
    now = time.time()
    th = cfg['thresholds']
    account_info = state.load('accounts.json', None) or {h: {'status': 'manual', 'since': int(now)} for h in cfg['accounts']}
    german = local_accounts(account_info, cfg, 'de')
    accounts = [h for h, a in account_info.items() if a['status'] in ('active', 'manual')]
    radar_page = cfg['notion']['radar_page']

    CTX.update({'meta': meta, 'accounts': account_info})
    FAILED.clear()
    # auto (the 2-hourly schedule): a full run when the last one is FULL_EVERY_HOURS old, else a light one - new
    # videos, views of the young / nearly viral ones and the alerts (incl. building a new format), nothing else.
    light = is_light(meta, now, auto)
    print(f"{'light' if light else 'full'} run (last full run {(now - meta.get('last_full_run', 0)) / 3600:.1f} h ago)",
          flush=True)
    gap = now - meta.get('last_run', now)
    if not dry_run and gap > NO_RUN_ALERT_HOURS * 3600:
        notify.push(f'⚠️ JobStep watcher: no run for {gap / 3600:.0f} hours',
                    'GitHub skipped or delayed the scheduled runs. It is running again now – nothing else to do.')

    # 1. new videos
    fresh, embed_views = 0, {}
    for handle in accounts:
        for item in tiktok.latest_videos(handle):
            vid = item['id']
            embed_views[vid] = item
            if vid not in videos and vid not in history:
                videos[vid] = {'id': vid, 'handle': handle, 'first_seen': int(now), 'snapshots': [], 'notified': [],
                               'url': f'https://www.tiktok.com/@{handle}/video/{vid}',
                               'created': int(vid) >> 32,  # TikTok IDs start with the upload timestamp
                               'desc': item['desc'], 'sticker': '', 'subtitles': '', 'duration': 0,
                               'views': 0, 'likes': 0, 'comments': 0, 'shares': 0, 'saves': 0}
                fresh += 1

    # 2. refresh stats
    failed = 0
    for vid, v in list(videos.items()):
        age_h = (now - v.get('created', now)) / 3600
        last = v['snapshots'][-1][0] if v['snapshots'] else 0
        once_a_day = age_h > 72 and now - last < 20 * 3600 and v.get('views', 0) < th['viral_views']
        light_skip = light and age_h > 30 and v.get('views', 0) < LIGHT_DETAIL_VIEWS
        if once_a_day or light_skip:
            # 3-7 day old videos: full check once a day (light runs: only young or nearly viral videos);
            # in between only the free embed view count
            if vid in embed_views and embed_views[vid]['views'] > v.get('views', 0):
                v['views'] = embed_views[vid]['views']
                to_history(history, v, german, now)
            continue
        d = tiktok.video_detail(v['handle'], vid)
        if not d and vid in embed_views:
            d = {**v, 'views': max(embed_views[vid]['views'], v.get('views', 0)), 'detail_missing': True}
        if not d:
            v['fails'] = v.get('fails', 0) + 1
            failed += 1
            if v['fails'] >= 8 or now - v.get('created', now) > cfg['watch_days'] * 86400:
                videos.pop(vid)
            continue
        v.update({k: d[k] for k in ('url', 'created', 'duration', 'desc', 'sticker', 'subtitles',
                                    'views', 'likes', 'comments', 'shares', 'saves')})
        v['fails'] = 0
        v['detail_missing'] = bool(d.get('detail_missing'))
        v['snapshots'].append([int(now), d['views'], d['likes'], d['shares'], d['saves']])
        to_history(history, v, german, now)
        if now - v['created'] > cfg['watch_days'] * 86400:
            videos.pop(vid)
    print(f'accounts={len(accounts)} new_videos={fresh} watchlist={len(videos)} not_updated={failed} '
          f'page_direct={tiktok.STATS["direct_ok"]} page_via_eu={tiktok.STATS["proxy_ok"]} '
          f'views_only={sum(1 for x in videos.values() if x.get("detail_missing"))} markets={[m["key"] for m in mkts]}')

    # 3./4. alerts
    actions = []
    for vid, v in sorted(videos.items(), key=lambda x: -x[1].get('views', 0)):
        if 'created' not in v:
            continue
        lvl = detect.level(v, now, detect.creator_baseline(history, v['handle']), th)
        if not lvl or 'viral' in v['notified'] or (lvl in ('taking_off', 'rising') and lvl in v['notified']):
            continue
        try:
            result = handle_alert(v, lvl, mkts, fmts, history, cfg, now, dry_run, only_detect)
            actions.append(result)
            if lvl == 'taking_off' and not dry_run:
                v['notified'].append(lvl)
            if not dry_run:  # save right away, so a video is never reported twice (even if the run crashes later)
                state.save('videos.json', videos)
                state.save('history.json', history)
                state.save('formats.json', fmts)
        except Exception as e:  # keep going with the other videos
            traceback.print_exc()
            notify.push('⚠️ JobStep watcher error', f"{v['url']}\n{str(e)[:300]}", click=v.get('url'))
            state.log({'type': 'error', 'video': vid, 'error': str(e)[:500]})
    if not dry_run:  # formats built or brought back in this run: their pages changed -> audited again on Monday
        changed = {e.get('format') for e in state.load('log.json', [])
                   if e.get('ts', 0) >= now and e.get('type') in ('format_built', 'format_revived')}
        for key in [k for k in meta.get('audit', {}) if k.split(':')[0] in changed]:
            meta['audit'].pop(key, None)

    if not dry_run and not light:
        # Sort every video into our formats once it is 48h old (not only the viral ones), so the ranking sees hits AND flops.
        todo = [v for v in videos.values() if 'created' in v and not v.get('format_checked') and now - v['created'] >= 48 * 3600]
        if todo:
            results = classify.classify_many(todo, fmts, cfg['models']['classify'])
            for v in todo:
                c = results.get(v['id'])
                if c:
                    set_format(v, history, c['match'])
                    v['format_checked'] = True
                    v.setdefault('hook_en', c['hook_en'])
            print(f'sorted {len(todo)} videos')

        # Viral videos not yet confirmed by the strict Claude check (e.g. older tags): re-check quietly (max 5 per run).
        for v in [v for v in videos.values() if v.get('views', 0) >= th['viral_views'] and not v.get('judged')
                  and 'created' in v and now - v['created'] <= cfg['watch_days'] * 86400][:5]:
            work = tempfile.mkdtemp(prefix='judge-')
            try:
                try:
                    transcript = soniox.transcribe(media.audio(media.download(v['url'], work), work)).get('text', '')
                except Exception:
                    transcript = v.get('subtitles', '')
                verdict = classify.judge(v, fmts, cfg['models']['build'], transcript, translate=False)
                f = resolve(fmts, verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
                set_format(v, history, f['id'] if f else None, judged=True)
                print('re-judged', v['handle'], v['views'], '->', v.get('format'))
            except Exception as e:
                print('re-judge failed', v['id'], str(e)[:150])
            finally:
                shutil.rmtree(work, ignore_errors=True)

    # 4a. formats waiting at the quality gate: checked again, published once every language page passes
    if not dry_run and not only_detect and not light:
        try:
            gate.retry_pending(fmts, mkts, cfg, history, account_info, meta, page_of, set_page, make_page, rebuild_page, rerank)
            state.save('formats.json', fmts)
        except Exception as e:
            step_failed('gate retry', e)

    # 4b. our own creators: new videos, views, formats (feeds the ranking: how each format does for US)
    own_accounts, own_videos = own.load()
    if not dry_run and not light:
        own.sync_megasheet(own_accounts, own_videos, now, markets=[m['key'] for m in mkts])
        try:
            print('own creators:', own.update(own_accounts, own_videos, fmts, cfg, now))
            state.save('own.json', own_videos)
            state.save('own_accounts.json', own_accounts)
        except Exception as e:
            step_failed('own creators', e)

    # 4c. Monday: weekly clean-up - formats that perform badly leave the list
    if not dry_run and not only_detect and not light:
        is_due, week_id = lineup.due(meta, now)
        if is_due:  # mark the Monday work as done first, so it never repeats (even if a step fails or times out)
            meta['lineup'] = week_id
            state.save('meta.json', meta)
            try:
                p = lineup.apply(history, fmts, cfg, own_videos, mkts, now)
                print('clean-up:', [f['title'] for f, _, _ in p['out']])
                meta['lineup'] = week_id
                state.save('formats.json', fmts)
            except Exception as e:
                traceback.print_exc()
                notify.push('⚠️ Weekly clean-up failed', str(e)[:300])

        if is_due:
            try:  # Monday: every active format gets its missing language pages
                for mk in mkts:
                    if any(f.get('status') == 'active' and not page_of(f, mk['key']) for f in fmts):
                        state.save('formats.json', fmts)
                        fill_market(mk['key'])
                        fmts[:] = load_formats()
            except Exception as e:
                step_failed('fill pages', e)
        if is_due:
            try:  # Monday: inspiration videos in each market's language for formats that still miss one
                localize_report(localize.run(fmts, mkts, history, account_info, meta, cfg, page_of, now), only_changes=True)
                state.save('formats.json', fmts)
            except Exception as e:
                step_failed('localize', e)
            try:  # Monday: every page must check out (example video = format, script = its transcript)
                bad = [r for r in audit.run(fmts, mkts, cfg, history, account_info, meta, page_of, rebuild=rebuild_page, only_failed=True) if r[2] not in ('ok', 'fixed')]
                state.save('formats.json', fmts)
                if bad:
                    notify.push('⚠️ Page audit: pages that need a look', '\n'.join(f"{m} {t} – {' / '.join(n)[:150]}" for t, m, _, n in bad))
            except Exception as e:
                step_failed('audit', e)
            try:  # Monday: every format's three countries TOGETHER against its reference (cached unless anything changed)
                group_report(fmts, mkts, cfg, meta, fix=True)
                state.save('formats.json', fmts)
            except Exception as e:
                step_failed('cross-country check', e)

    # 5. going-viral card + Discord (every market), then sort all lists in the same order (what goes viral right now first)
    if not only_detect and not light:
        try:
            hot.update(history, videos, fmts, cfg, meta, mkts, dry_run=dry_run)
        except Exception as e:
            step_failed('hot update', e)
        if not dry_run:
            try:
                lead = next((m for m in mkts if m['key'] == 'de'), mkts[0])  # the market whose top is reported
                before_top = meta.get('top3', []) if meta.get('top3_market', 'de') == lead['key'] else []
                try:  # archived formats that are proven for OUR creators come back before the lists are drawn
                    if own_comebacks(mkts, fmts, cfg):
                        state.save('formats.json', fmts)
                except Exception as e:
                    step_failed('own comebacks', e)
                ids = rerank(mkts, fmts, history, cfg)
                meta['top3'], meta['top3_market'] = ids[:3], lead['key']
                if before_top and ids[:3] != before_top:
                    by = {f['id']: f for f in fmts}
                    recent = rank.recent_viral(history, fmts, cfg)
                    notify.push(f"🔁 New top of the {lead['T']['flag']} format list", '\n'.join(
                        f"{n}. {by[i]['title']} – {recent.get(i, 0)} viral in 7 days" for n, i in enumerate(ids[:5], 1)))
            except Exception as e:
                step_failed('re-sort', e)

    # 5b. Monday: weekly report in Slack
    if not dry_run and not light:
        try:
            weekly.maybe_send(meta, history, own_videos, own_accounts, fmts, cfg, now)
        except Exception as e:
            step_failed('weekly report', e)

    # 6. every few days: complete the JobStep account list (Lightreel) and pause/revive accounts
    today = datetime.datetime.now(datetime.timezone.utc)
    if not dry_run and not light and meta.get('account_langs') != sorted(M.TEXT):
        try:  # a market language was added (Slovenian, 15 Oct 2026): sort the accounts without a language again
            for h, a in account_info.items():
                if not a.get('lang') and a.get('status') in ('active', 'manual'):
                    a['lang'] = discover.language(h)
            meta['handle_lang'] = {h: l for h, l in meta.get('handle_lang', {}).items() if l}  # localize asks again
            meta['account_langs'] = sorted(M.TEXT)
        except Exception as e:
            step_failed('account languages', e)
    if not dry_run and not light and now - meta.get('discovered_at', 0) >= cfg['discovery_every_days'] * 86400:
        account_info, added, paused, revived = discover.refresh(account_info)
        for h in added:
            account_info[h]['lang'] = discover.language(h)
        meta['discovered_at'] = int(now)
        n_active = sum(1 for a in account_info.values() if a['status'] in ('active', 'manual'))
        summary = (f"{n_active} active JobStep accounts" + (f" · new: {', '.join('@' + h for h in added)}" if added else '')
                   + (f" · paused: {', '.join('@' + h for h in paused)}" if paused else '')
                   + (f" · active again: {', '.join('@' + h for h in revived)}" if revived else ''))
        print('discovery:', summary)
        if added:
            notify.push(f'🔎 {len(added)} new JobStep accounts', summary)
        notify.radar(radar_page, f"{today:%d.%m.%Y} – Account-Check: {summary}")
        state.log({'type': 'discovery', 'added': added, 'paused': paused, 'revived': revived})
        try:  # same for our own creators
            o_added, o_paused, o_revived = own.refresh_accounts(own_accounts)
            state.save('own_accounts.json', own_accounts)
            if o_added:
                notify.push(f'🔎 {len(o_added)} new Parakeet AI creator accounts tracked',
                            ', '.join(f"@{h} ({own_accounts[h].get('market') or '?'})" for h in o_added))
            state.log({'type': 'own_discovery', 'added': o_added, 'paused': o_paused, 'revived': o_revived})
        except Exception as e:
            step_failed('own discovery', e)

    if not dry_run and not only_detect and not light:  # every live page follows the tidy rules (cues, hook text, title, page name)
        try:
            for t, m, ch in tidy.run(fmts, mkts, cfg, page_of):
                print('tidy:', m, t[:40], '-', '; '.join(ch))
        except Exception as e:
            step_failed('tidy', e)

    if not dry_run:
        state.save('videos.json', videos)
        state.save('history.json', history)
        state.save('formats.json', fmts)
        state.save('accounts.json', account_info)
        meta['last_run'] = int(now)
        if not light and not only_detect:
            meta['last_full_run'] = int(now)
        report_failures(meta, now)
        state.save('meta.json', meta)
    print('actions:', json.dumps(actions, ensure_ascii=False))


JUDGE_TRIES = 3  # runs (6 h apart) the Claude check may fail before the basic viral alert goes out


def handle_alert(v, lvl, mkts, fmts, history, cfg, now, dry_run, only_detect):
    """Taking off: a line on the Notion radar page only (no Slack ping - one Slack alert per video, the viral one).
    Viral: see handle_viral."""
    if now - v['created'] > cfg['watch_days'] * 86400:  # never alert on old videos
        return {'video': v['id'], 'level': lvl, 'skipped': 'older than watch window'}
    if dry_run:
        print('DRY', lvl, v['handle'], v['views'], v.get('url'))
        return {'video': v['id'], 'level': lvl, 'views': v['views']}
    if lvl == 'viral':
        return handle_viral(v, mkts, fmts, history, cfg, now, only_detect)
    if lvl == 'rising':
        return handle_viral(v, mkts, fmts, history, cfg, now, only_detect, rising=True)
    if not v.get('format_checked'):
        c = classify.classify(v, fmts, cfg['models']['classify'])
        set_format(v, history, c.get('match'))
        v['format_checked'], v['hook_en'] = True, c.get('hook_en', '')
    known = resolve(fmts, v.get('format'))
    age_h = (now - v['created']) / 3600
    fmt_text = (f"Probably format: {known['title']}" + ('' if known.get('status') == 'active' else ' (archive)')
                if known else f"Possibly new format: {v.get('hook_en') or '?'}")
    msg = (f"@{v['handle']} – {fmt_views(v['views'])} views after {age_h:.0f} h · shares+saves {detect.engagement(v):.1%}\n"
           f"{fmt_text}\n(Full check with script follows if it goes viral.)")
    notify.radar(cfg['notion']['radar_page'], f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🟡 – "
                 f"{msg.replace(chr(10), ' – ')}", link=v['url'], link_label='Video')
    result = {'video': v['id'], 'level': lvl, 'views': v['views']}
    state.log({'type': 'alert', **result})
    return result


def list_position(mk, page_id):
    ids = [pid.replace('-', '') for _, pid in notion.list_entries(mk['list_page'])[0]]
    pid = (page_id or '').replace('-', '')
    return ids.index(pid) + 1 if pid in ids else None


def market_links(fmt, mkts):
    return ' · '.join(f"<{page_url(page_of(fmt, mk['key']))}|{mk['T']['flag']}>" for mk in mkts if page_of(fmt, mk['key']))


RISING_NOTE = '🚀 *Rising fast:* 30k+ views in its first 24 h – in our data 4 of 5 such videos reached 100k.'


def handle_viral(v, mkts, fmts, history, cfg, now, only_detect, test=False, force=False, label=None, rising=False):
    """Every viral video (creators from ALL markets): download + Soniox transcript, Claude (Opus) judges it against
    ALL our formats (list + archive) and translates the script to English. Then for every market (DE/FR/ES):
    in the list -> nothing to build (missing language pages are added); in the archive -> brought back everywhere;
    new -> built in every market's language and added to every list. One Slack message with link, verdict, English
    script. If Claude fails, a basic message still goes out and the full check is retried next run.
    rising (detect 'rising', 30k+ in 24 h): a NEW or archived format is built/brought back now - that is the video's
    one Slack ping (none again at 100k). A video of a live format, or one that cannot be built, only gets a radar line
    now; its Slack ping comes at 100k, with the format check reused (v['verdict'])."""
    age_h = (now - v['created']) / 3600
    eng = detect.engagement(v)
    eng_unknown = v.get('detail_missing') and not v.get('shares') and not v.get('saves')
    weak = (not eng_unknown) and eng < cfg['thresholds']['min_engagement'] and not force  # force: added by hand
    stats = (f"@{v['handle']} – *{fmt_views(v['views'])} views* after {age_h:.0f} h · shares+saves {eng:.1%}"
             f"{' (weak)' if weak else ''}{' (unknown)' if eng_unknown else ''}")
    title = ('🧪 TEST – ' if test else '') + (label or ('🚀 RISING FAST: JobStep video – new format early' if rising
                                                         else '🟢 VIRAL: JobStep video'))
    result = {'video': v['id'], 'level': 'rising' if rising else 'viral', 'views': v['views']}
    work = tempfile.mkdtemp(prefix='viral-')
    try:
        video_file, note = None, ''
        try:
            video_file = media.download(v['url'], work)
            transcript = soniox.transcribe(media.audio(video_file, work))
        except Exception as e:
            note = f'\n_(video download/transcription failed: {str(e)[:80]} – judged from TikTok text)_'
            transcript = {'text': v.get('subtitles', ''), 'segments': [], 'language': ''}
        cached = v.get('verdict') if not (test or force) else None  # the check made when it was rising (a live format)
        try:
            verdict = cached or classify.judge(v, fmts, cfg['models']['build'], transcript.get('text', ''))
        except Exception as e:
            if rising:  # tried again next run while it is still rising, else at 100k
                state.log({'type': 'judge_failed', 'video': v['id'], 'error': str(e)[:300], 'rising': True})
                result['error'] = str(e)[:200]
                return result
            v['judge_fails'] = v.get('judge_fails', 0) + 1
            if v['judge_fails'] >= JUDGE_TRIES and 'viral_basic' not in v['notified'] and not force:
                # added by hand (force): add_format sends its own alert
                notify.push(title, f"{stats}\n⚠️ Claude check failed {v['judge_fails']}x ({str(e)[:120]}) – the watcher "
                            'keeps trying; the result will be on the Notion radar page.', click=v['url'])
                v['notified'].append('viral_basic')
            state.log({'type': 'judge_failed', 'video': v['id'], 'error': str(e)[:300]})
            result['error'] = str(e)[:200]
            return result

        prepared = {'work': work, 'video_file': video_file, 'transcript': transcript} if video_file else None
        blocked = 'weak engagement' if weak else 'only-detect mode' if only_detect else None if prepared else 'video unavailable'
        known = resolve(fmts, verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
        if rising and (blocked or (known and known.get('status') == 'active')):
            # nothing to build now: a radar line; the Slack ping comes at 100k (with this check reused)
            if known:
                set_format(v, history, known['id'], judged=True)
                v['verdict'] = {k: verdict.get(k) for k in ('duplicate_of', 'reason', 'english_script', 'hook_en')}
            what = (f"live format: {known['title']}" if known and known.get('status') == 'active' else
                    f"not built now ({blocked}) – checked again at 100k")
            notify.radar(cfg['notion']['radar_page'], f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🚀 "
                         f"rising – @{v['handle']} {fmt_views(v['views'])} after {age_h:.0f} h – {what}",
                         link=v['url'], link_label='Video')
            v['notified'] += ['rising', 'taking_off']  # no 🟡 line on top of this one
            result['format'] = v.get('format')
            state.log({'type': 'alert', **result})
            return result
        if known:
            set_format(v, history, known['id'], judged=True)
            if known.get('status') == 'active':
                added = [] if blocked else ensure_market_pages(known, v, mkts, fmts, history, cfg, prepared)
                pos = list_position(mkts[0], page_of(known, mkts[0]['key']))
                outcome = (f"✅ *Already in Notion* – in the lists{f' as #{pos}' if pos else ''}: *{known['title']}* "
                           f"({market_links(known, mkts)})" + (f"\n➕ added missing pages: {' '.join(added)}" if added else ''))
            elif blocked:
                outcome = f"📦 *Already in Notion* – in the archive: *{known['title']}* – not brought back ({blocked})"
            else:
                ok, pos, reasons = revive_format(known, v, mkts, fmts, history, cfg, prepared=prepared)
                outcome = (f"♻️ *Was in the archive → checked & brought back as #{pos}* in all lists: *{known['title']}* "
                           f"({market_links(known, mkts)})" if ok else
                           f"♻️ *Was in the archive* – *{known['title']}* – ⏳ *held back until every language page passes "
                           f"the check* (tried again next run):\n" + '\n'.join(reasons))
        else:
            set_format(v, history, None, judged=True)
            if blocked:
                outcome = f"🆕 *NEW format – not in Notion yet*, not added ({blocked})"
            else:
                fmt, problems, position = build_format(v, mkts, fmts, history, cfg, prepared=prepared,
                                                       description=verdict.get('new_format_description', ''))
                result.update({'built': fmt['id'], 'problems': problems, 'position': position})
                outcome = (f"🆕 *NEW format → checked & added as #{position}* in all lists: *{fmt['title']}* ({market_links(fmt, mkts)})"
                           if position else
                           f"🆕 *NEW format* – *{fmt['title']}* – ⏳ *held back until every language page passes the check* "
                           f"(tried again next run):\n" + '\n'.join(problems))
        result['format'] = v.get('format')
        script = (verdict.get('english_script') or '').strip() or '(no speech / text found)'
        quoted = '\n'.join('> ' + line for line in script.splitlines() if line.strip())
        msg = (f"{stats}\n▶ <{v['url']}|Open video on TikTok>{note}\n" + (RISING_NOTE + '\n' if rising else '') +
               f"\n*Format check (Claude):* {outcome}\n"
               f"_{verdict.get('reason', '')}_\n\n*Script (English):*\n{quoted[:3500]}")
        if 'viral_basic' not in v['notified']:  # one Slack alert per video: none if the basic one already went out
            notify.push(title, msg)
        notify.radar(cfg['notion']['radar_page'], f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – "
                     f"{'🚀 RISING' if rising else '🟢 VIRAL'} – @{v['handle']} {fmt_views(v['views'])} – "
                     f"{outcome.split(chr(10))[0]}", link=v['url'], link_label='Video')
        v['notified'] += ['rising', 'viral'] if rising else ['viral']  # one Slack ping per video: none again at 100k
        state.log({'type': 'alert', **result})
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _prepare(v, prepared):
    """Reuse an already downloaded video + transcript (+ frames), or fetch them."""
    if prepared:
        if 'frames' not in prepared:
            prepared['frames'] = media.frames(prepared['video_file'], prepared['work'])
        return prepared['work'], prepared['video_file'], prepared['transcript'], prepared['frames'], False
    work = tempfile.mkdtemp(prefix='fmt-')
    video_file = media.download(v['url'], work)
    transcript = soniox.transcribe(media.audio(video_file, work))
    return work, video_file, transcript, media.frames(video_file, work), True


def make_page(v, mk, cfg, prepared, parent=None, title=None, replace_page=None, attempts=1):
    """Build one market's page (its language, current layout). Returns (page_id_or_url, spec, problems)."""
    if replace_page:
        locked = next((f for f in load_formats() if page_of(f, mk['key']) == replace_page
                       and align.approved_script(f['id'], mk['lang'])), None)
        if locked:
            return None, {}, ['approved script/example locked; full-page rebuild refused']
    work, video_file, transcript, frames, own = _prepare(v, prepared)
    try:
        feedback = ''
        for _ in range(attempts):  # rebuilds may retry with the reason the last attempt was rejected
            spec = builder.build_spec(v, transcript, frames, cfg['models']['build'], lang=mk['lang'], feedback=feedback)
            problems = builder.validate(spec, transcript, lang=mk['lang'], on_screen=v.get('sticker') or '')
            if not problems:
                break
            feedback = '; '.join(problems)
        if replace_page and problems:
            return None, spec, problems
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        blocks = notion.page_blocks(spec, v, upload_id, cfg['links'], lang=mk['lang'], lab_url=mk['visual_hook_lab'],
                                    same_lang=(transcript.get('language') or '')[:2] == mk['lang'])
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)
    if replace_page:
        notion.replace_content(replace_page, blocks)
        return replace_page, spec, []
    if problems:
        page = notion.create_page(cfg['notion']['radar_page'], mk['T']['draft_prefix'] + spec['page_title'], spec.get('icon') or '📝', blocks)
    else:
        page = notion.create_page(parent or mk['holder_page'], title or spec['page_title'], spec.get('icon') or '🎬', blocks)
    return page['id'], spec, problems


def set_page(fmt, m, page_id):
    if m == 'de':
        fmt['page_id'] = page_id
    else:
        fmt.setdefault('pages', {})[m] = page_id


def ensure_market_pages(fmt, v, mkts, fmts, history, cfg, prepared):
    """A listed format missing a market's page gets one - built in the staging page, checked, and only then moved
    into that market's format folder (and list)."""
    added = []
    meta, accounts = CTX.get('meta', {}), CTX.get('accounts') or state.load('accounts.json', {})
    for mk in M.for_format(mkts, fmt):
        if page_of(fmt, mk['key']):
            continue
        pending_pages = fmt.setdefault('pending_pages', {})
        pid = pending_pages.get(mk['key'])
        if not pid:
            pid, spec, problems = make_page(v, mk, cfg, prepared, parent=cfg['notion']['radar_page'], attempts=3)
            if problems:
                continue
            pending_pages[mk['key']] = pid
            state.save('formats.json', fmts)
        staged_page_of = lambda f, m: pid if f['id'] == fmt['id'] and m == mk['key'] else page_of(f, m)
        status, notes = audit.fix_page(fmt, mk, cfg, history, accounts, meta, staged_page_of)
        meta.setdefault('audit', {})[f"{fmt['id']}:{mk['key']}"] = status
        if status in ('ok', 'fixed'):
            notion.move_page(pid, mk['holder_page'])
            set_page(fmt, mk['key'], pid)
            pending_pages.pop(mk['key'], None)
            added.append(mk['T']['flag'])
        state.save('formats.json', fmts)
    if added:
        rerank(mkts, fmts, history, cfg)
    return added


def build_format(v, mkts, fmts, history, cfg, prepared=None, description=''):
    """New format: build its page in every market's language (DE/FR/ES) and add it to every list.
    Returns (format entry, problems, position)."""
    fid = 'A' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    entry = {'id': fid, 'source_video': v['url'], 'created': int(time.time()), 'pages': {}, 'status': 'pending'}
    problems = []
    for mk in mkts:  # built where creators can't see it yet (private staging page) - the gate publishes it
        pid, spec, probs = make_page(v, mk, cfg, prepared, parent=cfg['notion']['radar_page'], attempts=3)
        if probs:
            problems.append(f"{mk['T']['flag']} {'; '.join(probs)}")
            continue
        set_page(entry, mk['key'], pid)
        if mk['key'] == 'de' or 'title' not in entry:
            entry.update({'title': spec['page_title'], 'description': spec.get('registry_description') or description,
                          'script': ' '.join(seg.get('text', '') for seg in spec.get('script', []))[:900]})
        assets = spec.get('assets_needed') or []
        if assets and mk['key'] == mkts[0]['key']:
            notify.push('📎 New format needs a resource', f"{spec['page_title']}: " + ', '.join(a['name'] for a in assets))
    entry.setdefault('title', v.get('hook_en') or 'new format')
    fmts.append(entry)
    set_format(v, history, fid, judged=True)
    published, position, reasons = _gate(entry, mkts, fmts, history, cfg, 'new')
    problems = reasons
    state.log({'type': 'format_built', 'format': fid, 'pages': entry.get('pages'), 'page_de': entry.get('page_id'),
               'problems': problems, 'position': position})
    return entry, problems, position


def revive_format(fmt, v, mkts, fmts, history, cfg, prepared=None):
    """Archived format went viral again: its pages are refreshed where they are (still in the archive, invisible in
    the lists), missing markets are built in the staging page, then the quality gate checks every page. Only if all
    pass do they move into the format folders and the format is listed again. Returns (published, position, reasons)."""
    fmt.pop('pending', None)  # a comeback starts with fresh quality-check attempts (old ones led to the archive)
    for mk in M.for_format(mkts, fmt):
        m = mk['key']
        pid = page_of(fmt, m)
        try:
            if pid:
                make_page(v, mk, cfg, prepared, replace_page=pid, attempts=3)
            else:
                new_pid, spec, problems = make_page(v, mk, cfg, prepared, parent=cfg['notion']['radar_page'], attempts=3)
                if not problems:
                    set_page(fmt, m, new_pid)
        except Exception as e:
            notify.radar(cfg['notion']['radar_page'], f"{mk['T']['flag']} revive issue for {fmt['title']}: {str(e)[:150]}")
    fmt.pop('market_only', None)
    fmt['revived'] = {'at': int(time.time()), 'because': v['url'], 'views': v['views']}
    fmt.setdefault('source_video', v['url'])
    set_format(v, history, fmt['id'], judged=True)
    published, position, reasons = _gate(fmt, mkts, fmts, history, cfg, 'revive')
    state.log({'type': 'format_revived' if published else 'format_held', 'format': fmt['id'], 'video': v['id'],
               'position': position, 'reasons': reasons})
    return published, position, reasons


def own_tiers(mkts, fmts, cfg, force=False, now=None):
    """How each format does for OUR creators, per market (own.tiers). Formats move UP right away (a new hit of ours
    goes to the top on the next run), but only move DOWN on the first re-sort of the week (Monday) or when forced
    (mode relist) - so the lists do not reshuffle every 6 hours and a format is not buried mid-week because its
    newest videos are not sorted yet. Kept in state/own_tiers.json {week, at, markets: {m: {format: {...}}}}."""
    now = now or time.time()
    week = time.strftime('%G-W%V', time.gmtime(now))
    snap = state.load('own_tiers.json', {})
    new_week = force or snap.get('week') != week
    if new_week:
        snap = {'week': week, 'at': int(now), 'markets': {}}
    own_videos = own.videos_now()
    moved = []
    for mk in mkts:
        m = mk['key']
        fresh = own.tiers(own_videos, fmts, now, m, cfg)
        if m not in snap['markets']:
            snap['markets'][m] = fresh
            moved.append(m)
            continue
        kept = snap['markets'][m]
        for fid in set(fresh) | set(kept):
            f_tier, k_tier = fresh.get(fid, {}).get('tier', 3), kept.get(fid, {}).get('tier', 3)
            if f_tier < k_tier:  # up: right away (no videos of ours any more = back to neutral tier 3)
                if fid in fresh:
                    kept[fid] = fresh[fid]
                else:
                    kept.pop(fid)
                moved.append(f'{m}:{fid}^{f_tier}')
            elif fid in fresh and f_tier == k_tier:
                kept[fid] = fresh[fid]  # same tier: newer numbers for the report
    state.save('own_tiers.json', snap)
    if moved:
        state.log({'type': 'own_tiers', 'week': week, 'changes': moved})
    return snap['markets']


COMEBACK_TRIES = 3  # runs a comeback may fail to get its pages ready before it waits for mode relist


def own_comebacks(mkts, fmts, cfg, tiers=None, now=None, force=False):
    """An archived format that is PROVEN for our creators in a running market (own.tiers tier 1: our videos of it
    average 10k+, or one passed 100k in 14 days) comes back into the lists right away - JobStep does not have to go
    viral with it again. First every running market gets a page in the current layout (ready_page: a missing page is
    built and checked, an old hand-written page is rebuilt from its example video). Only when all are ready do the
    pages move from each market's archive back to that market's format folder and the format is listed; else it stays
    archived (a page just built goes back to the archive) and is tried again next run - after COMEBACK_TRIES failed
    runs one Slack note, then only mode relist (force) tries again. lineup.never_revive keeps a format out on purpose.
    Returns the formats that came back."""
    now = now or time.time()
    tiers = tiers if tiers is not None else own_tiers(mkts, fmts, cfg)
    never = set(cfg.get('lineup', {}).get('never_revive', []))
    back, origs = [], None
    for f in fmts:
        if f.get('status') != 'archived' or f['id'] in never:
            continue
        proven = [(mk, tiers.get(mk['key'], {}).get(f['id'])) for mk in mkts
                  if tiers.get(mk['key'], {}).get(f['id'], {}).get('tier') == 1]
        if not proven or (f.get('comeback_tries', 0) >= COMEBACK_TRIES and not force):
            continue
        origs = audit.originals() if origs is None else origs
        ready = {}
        for mk in M.for_format(mkts, f):
            try:
                ready[mk['key']] = ready_page(f, mk, fmts, origs, cfg)
            except Exception as e:
                ready[mk['key']] = ('error', str(e)[:150])
        not_ready = {m: r for m, r in ready.items() if r[0] not in READY}
        if not_ready:
            for mk in mkts:  # a page built for it now (moved into the folder) waits in the archive with the others
                if ready[mk['key']][0] == 'built' and page_of(f, mk['key']):
                    try:
                        notion.move_page(page_of(f, mk['key']), mk['archive_page'])
                    except Exception as e:
                        print('comeback: move back failed', mk['key'], f['title'], str(e)[:150])
            f['comeback_tries'] = f.get('comeback_tries', 0) + 1
            state.log({'type': 'format_comeback_held', 'format': f['id'], 'tries': f['comeback_tries'],
                       'not_ready': {m: f'{st}: {d}' for m, (st, d) in not_ready.items()}})
            print('comeback held:', f['title'], not_ready)
            if f['comeback_tries'] == COMEBACK_TRIES:
                notify.push('⏸️ Format NOT back in the lists – its pages are not ready', f"*{f['title']}*: " + '; '.join(
                    f'{m}: {st} ({d[:80]})' for m, (st, d) in not_ready.items()) + ' – fix the page, then run mode relist')
            continue
        f.pop('comeback_tries', None)
        for mk in mkts:
            pid = page_of(f, mk['key'])
            if pid and ready[mk['key']][0] != 'built':  # a built page is already in the folder
                try:
                    notion.move_page(pid, mk['holder_page'])
                except Exception as e:
                    print('comeback: move failed', mk['key'], f['title'], str(e)[:150])
        why = ', '.join(f"{mk['key']}: our {x['n']} videos average {fmt_views(x['avg'])}, best {fmt_views(x['best'])}"
                        for mk, x in proven)
        f['status'] = 'active'
        f['listed_at'] = int(now)
        f['revived'] = {'at': int(now), 'because': f'proven for our creators ({why})'}
        f.pop('archived_reason', None)
        state.log({'type': 'format_revived_own', 'format': f['id'], 'because': why,
                   'pages': {m: st for m, (st, _) in ready.items()}})
        back.append((f, why))
    if back:
        notify.push('♻️ Formats back in the lists – proven for our creators', '\n'.join(
            f"➕ *{f['title']}* – {why}" for f, why in back))
    return [f for f, _ in back]


def rerank(mkts, fmts, history, cfg, force=False):
    """Every market gets its own order: our creators' results IN THAT MARKET first (own_tiers - proven formats on
    top, weak ones at the bottom), inside that the JobStep order (what goes viral right now). The red "going viral"
    card at the top holds only what goes viral now (rank.going_viral); proven formats follow right under it.
    Returns the DACH order (the first market's when DACH is not in mkts)."""
    tiers = own_tiers(mkts, fmts, cfg, force=force)
    by_id = {f['id']: f for f in fmts}
    first = None
    orders = {}
    for mk in mkts:
        ids, scores = rank.order(history, fmts, cfg, tiers=tiers.get(mk['key'], {}), market=mk['key'])
        if first is None or mk['key'] == 'de':
            first = ids
        page_ids, hot_count = [], 0
        for i in ids:
            pid = page_of(by_id[i], mk['key']) if M.for_format([mk], by_id[i]) else None
            if pid:
                page_ids.append(pid)
                hot_count += bool(scores[i]['top'])
        orders[mk['key']] = ids
        entries, _ = notion.list_entries(mk['list_page'])
        current = [pid.replace('-', '') for _, pid in entries]
        if force or [p.replace('-', '') for p in page_ids] != current or notion.hot_entry_count(mk['list_page']) != hot_count:
            notion.set_order(mk['list_page'], page_ids, hot_count=hot_count, lang=mk['lang'])
    state.log({'type': 'rerank', 'order': first, 'orders': orders})
    return first or []


def check_hot():
    """Strict Claude check of every viral video (100k+) posted in the last 7 days, then report per format."""
    cfg = load_config()
    fmts = load_formats()
    videos, history = state.load('videos.json', {}), state.load('history.json', {})
    now = time.time()
    todo = [v for v in videos.values() if v.get('views', 0) >= cfg['thresholds']['viral_views']
            and 'created' in v and now - v['created'] <= cfg['watch_days'] * 86400]
    print(f'{len(todo)} viral videos from the last 7 days')
    for v in todo:
        if v.get('judged'):
            continue
        work = tempfile.mkdtemp(prefix='judge-')
        try:
            try:
                transcript = soniox.transcribe(media.audio(media.download(v['url'], work), work)).get('text', '')
            except Exception:
                transcript = v.get('subtitles', '')
            verdict = classify.judge(v, fmts, cfg['models']['build'], transcript, translate=False)
            f = resolve(fmts, verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
            set_format(v, history, f['id'] if f else None, judged=True)
            v['hook_en'] = verdict.get('hook_en', v.get('hook_en', ''))
        except Exception as e:
            print('judge failed', v['id'], str(e)[:150])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    state.save('videos.json', videos)
    state.save('history.json', history)
    by = {f['id']: f for f in fmts}
    groups = {}
    for v in todo:
        groups.setdefault(v.get('format') or 'NEW/none', []).append(v)
    print('\nCONFIRMED VIRAL VIDEOS PER FORMAT (last 7 days):')
    for fid, vs in sorted(groups.items(), key=lambda x: -len(x[1])):
        f = by.get(fid)
        name = f['title'] + ('' if f.get('status') == 'active' else ' [archive]') if f else 'not in Notion'
        print(f'{len(vs)} | {fid} | {name}')
        for v in sorted(vs, key=lambda x: -x['views']):
            print(f"    {v['views']:>7} @{v['handle']:22} {v['url']}  | {v.get('hook_en', '')[:70]}")


def _page_text(page_id):
    texts = []
    for c in notion.children(page_id):
        rt = c.get(c['type'], {}).get('rich_text')
        if rt:
            texts.append(''.join(x['plain_text'] for x in rt))
    return ' '.join(texts)


def source_video(fmt):
    """The TikTok inspiration video of a format (stored, or the 'Original auf TikTok' link on its DACH page, or on
    another market's page for formats built after DACH stopped)."""
    if fmt.get('source_video'):
        return fmt['source_video']
    pid = fmt.get('page_id') or next(iter((fmt.get('pages') or {}).values()), None)
    if not pid:
        return None
    for b in notion.children(pid):
        for x in (b.get(b['type'], {}) or {}).get('rich_text', []) or []:
            url = ((x.get('text') or {}).get('link') or {}).get('url', '')
            if 'tiktok.com/@' in url and '/video/' in url:
                return url
    return None


def init_market(m):
    """Connect a market to the shared format list.
    1. Its existing format pages (format folder + archive) are matched by Claude to our formats -> become that
       format's page for this market.
    2. Pages of formats that are not in the active list are moved to the market's archive (nothing is deleted);
       unmatched ones become archived formats (so they are known to the duplicate check).
    3. Every active format still missing a page in this market gets one, built from its inspiration video."""
    cfg = load_config()
    mk = next(x for x in M.load({**cfg, 'markets': {k: {**v, 'enabled': True} for k, v in cfg['markets'].items()}}) if x['key'] == m)
    fmts = load_formats()
    pages = []
    for where, parent in (('folder', mk['holder_page']), ('archive', mk['archive_page'])):
        for b in notion.children(parent):
            if b['type'] == 'child_page':
                pages.append({'page_id': b['id'], 'title': b['child_page']['title'], 'where': where, 'text': _page_text(b['id'])[:1200]})
    listing = '\n'.join(f"- {f['id']} ({f.get('status')}): {f.get('description', f['title'])}" for f in fmts)
    items = '\n'.join(f"{i}: TITLE {p['title']} | TEXT {p['text'][:700]}" for i, p in enumerate(pages))
    r = llm.chat_json(cfg['models']['build'], 'Reply JSON only.', f"""Our formats (one shared list for all markets):
{listing}

These are existing {mk['T']['lang_name']} format pages. For each page, which of our formats is it (same core premise/hook
and structure, even if worded differently)? null if none. Also write one English sentence describing each page's format.
{items}
Return JSON {{"pages": [{{"index": 0, "format": "<format id or null>", "description": "<sentence>"}}]}}""", timeout=1800)
    by = {f['id']: f for f in fmts}
    moved, matched, extra = 0, 0, 0
    for x in r.get('pages', []):
        p = pages[int(x['index'])]
        f = by.get(x.get('format'))
        if f and not page_of(f, m):
            set_page(f, m, p['page_id'])
            matched += 1
            target = mk['holder_page'] if f.get('status') == 'active' else mk['archive_page']
        else:
            fid = f"{m.upper()}X{int(x['index']) + 1:02d}"
            fmts.append({'id': fid, 'title': p['title'], 'status': 'archived', 'description': x.get('description', p['title']),
                         'script': p['text'][:900], 'pages': {m: p['page_id']}, 'market_only': m})
            by[fid] = fmts[-1]
            extra += 1
            target = mk['archive_page']
        if (p['where'] == 'folder') != (target == mk['holder_page']):
            notion.move_page(p['page_id'], target)
            moved += 1
    state.save('formats.json', fmts)
    print(f'{m}: matched {matched}, archived-only {extra}, moved {moved}')
    fill_market(m)


def fill_market(m):
    """Missing language pages stay in staging until their complete audit passes."""
    cfg = load_config()
    mk = next(x for x in M.load({**cfg, 'markets': {k: {**v, 'enabled': True} for k, v in cfg['markets'].items()}}) if x['key'] == m)
    fmts, history = load_formats(), state.load('history.json', {})
    built = 0
    for f in [f for f in fmts if f.get('status') == 'active' and not page_of(f, m) and M.for_format([mk], f)]:
        url = source_video(f)
        if not url:
            print('no inspiration video for', f['title'])
            continue
        import re as _re
        handle, vid = _re.search(r'@([^/]+)/video/(\d+)', url).groups()
        v = tiktok.video_detail(handle, vid)
        if not v:
            print('video unavailable for', f['title'])
            continue
        try:
            added = ensure_market_pages(f, v, [mk], fmts, history, cfg, None)
            built += len(added)
            state.save('formats.json', fmts)
            print('published' if added else 'held in staging', m, f['title'])
        except Exception as e:
            print('build failed', f['title'], str(e)[:200])
    state.save('formats.json', fmts)
    rerank([mk], fmts, history, cfg)
    print(f'{m}: built {built} pages')


def localize_report(rep, only_changes=False):
    for r in rep:
        print(' | '.join(str(x) for x in r))
    flags = {'de': '🇩🇪', 'fr': '🇫🇷', 'es': '🇪🇸', 'sl': '🇸🇮'}
    done = [r for r in rep if r[2] in ('replaced', 'restored')]
    miss = [r for r in rep if r[2] in ('missing', 'error')]
    if done or (miss and not only_changes):
        notify.push('🌍 Inspiration videos in the creators\' language',
                    (f"Replaced {len(done)}:\n" + '\n'.join(f"{flags[m]} {t} – {d}" for t, m, _, d in done) if done else 'Nothing replaced.')
                    + (f"\n\nStill missing ({len(miss)}):\n" + '\n'.join(f"{flags[m]} {t} – {d}" for t, m, _, d in miss) if miss else ''))


def backfill(handles, fmts, history, cfg, now):
    """Older videos (> 7 days) of newly added accounts: into history and sorted into formats, so ranking and the
    language-matched inspiration videos see them. Younger videos are left to the normal watch (alerts)."""
    vids = []
    for h in handles:
        for item in tiktok.latest_videos(h):
            created = int(item['id']) >> 32
            if item['id'] in history or now - created <= cfg['watch_days'] * 86400:
                continue
            d = tiktok.video_detail(h, item['id']) or {'desc': item['desc'], 'sticker': '', 'subtitles': '', 'views': item['views']}
            vids.append({'id': item['id'], 'handle': h, 'created': created, 'views': max(d['views'], item['views']),
                         'desc': d['desc'], 'sticker': d['sticker'], 'subtitles': d['subtitles']})
    res = classify.classify_many(vids, fmts, cfg['models']['classify']) if vids else {}
    for v in vids:
        c = res.get(v['id'], {})
        history[v['id']] = {'handle': v['handle'], 'created': v['created'], 'views': v['views'], 'hook': c.get('hook_en', ''),
                            'german': False, 'mature': True, 'format': c.get('match'), 'judged': False, 'views_7d': v['views'],
                            'backfill': True}
    return len(vids), sum(1 for v in vids if res.get(v['id'], {}).get('match'))


def accounts_add(path):
    """Add accounts that were checked by hand/agent (with evidence): JobStep UGC -> tracked (+ older videos pulled
    in), dead ones paused, our own Parakeet creators -> own tracking."""
    cfg, fmts = load_config(), load_formats()
    history, accounts = state.load('history.json', {}), state.load('accounts.json', {})
    with open(path) as f:
        data = json.load(f)
    now = time.time()
    new = [h for h in data.get('add', {}) if accounts.get(h, {}).get('status') not in ('active', 'manual')]
    for h, evidence in data.get('add', {}).items():
        accounts[h] = {**accounts.get(h, {}), 'status': accounts.get(h, {}).get('status') if accounts.get(h, {}).get('status') == 'manual' else 'active',
                       'since': accounts.get(h, {}).get('since', int(now)), 'source': accounts.get(h, {}).get('source', 'checked-2026-10-07'),
                       'lang': accounts.get(h, {}).get('lang') or discover.language(h), 'checked_ugc': True, 'evidence': evidence}
        accounts[h].pop('blocked', None)
    for h, why in data.get('inactive', {}).items():
        if h in accounts:
            accounts[h].update({'status': 'inactive', 'paused_reason': why})
    state.save('accounts.json', accounts)
    own_accounts, own_videos = own.load()
    for h, market in data.get('own_add', {}).items():
        own_accounts.setdefault(h, {'status': 'active', 'since': int(now), 'source': 'checked-2026-10-07', 'market': market})
    state.save('own_accounts.json', own_accounts)
    n, sorted_n = backfill(new, fmts, history, cfg, now)
    state.save('history.json', history)
    active = sum(1 for a in accounts.values() if a['status'] in ('active', 'manual'))
    print(f'+{len(new)} accounts, {active} active; backfill {n} videos ({sorted_n} matched)')
    notify.push('🔎 JobStep creator list completed', f"+{len(new)} more JobStep UGC accounts (each checked by reading its videos): "
                + ', '.join('@' + h for h in new) + f"\n{active} active JobStep accounts tracked now.")


def accounts_sync(path):
    """Check a candidate list with Claude and update the JobStep account list:
    {"candidates": [handles found by search/Lightreel], "paused": {handle: source}}.
    Every candidate AND every account we already track is read by Claude (latest videos: caption, on-screen text,
    speech). Only real JobStep UGC accounts are tracked; tracked accounts that are not (other app / random) are
    blocked. Then: older videos of the new accounts are pulled in, and the inspiration videos are localized."""
    cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
    history = state.load('history.json', {})
    accounts = state.load('accounts.json', {})
    with open(path) as f:
        data = json.load(f)
    now = time.time()
    tracked = [h for h, a in accounts.items() if a['status'] in ('active', 'manual')]
    cands = [h for h in dict.fromkeys(data.get('candidates', [])) if h not in tracked and not accounts.get(h, {}).get('blocked')]
    cands = [h for h in cands if discover.check_account(h) == 'active']  # posted in 30 days + JobStep in its videos
    verdicts = discover.confirm_ugc(tracked + cands)
    retry = [h for h in tracked + cands if verdicts.get(h, {}).get('verdict') in (None, 'unclear')]
    if retry:  # second look for the undecided ones: all 8 videos with on-screen text and speech
        verdicts.update(discover.confirm_ugc(retry, model=cfg['models']['build'], batch=4, details=8))
    added, blocked, unclear = [], [], []
    for h in cands:
        if verdicts.get(h, {}).get('verdict') == 'jobstep_ugc':
            accounts[h] = {**accounts.get(h, {}), 'status': 'active', 'since': int(now), 'source': 'search-2026-10-07',
                           'lang': discover.language(h), 'checked_ugc': True}
            added.append(h)
    for h in tracked:
        v = verdicts.get(h, {})
        if v.get('verdict') in ('other_app', 'not_ugc') and h != 'jobstep.io' and not accounts[h].get('added_format'):
            accounts[h].update({'status': 'inactive', 'blocked': True,
                                'blocked_reason': f"{v['verdict']}: {v.get('other_app') or ''} {v.get('reason') or ''}".strip()})
            blocked.append((h, v))
        elif v.get('verdict') == 'jobstep_ugc':
            accounts[h]['checked_ugc'] = True
        else:
            unclear.append(h)
    for h, src in data.get('paused', {}).items():
        accounts.setdefault(h, {'status': 'inactive', 'since': int(now), 'source': src})
    state.save('accounts.json', accounts)
    for h, v in verdicts.items():
        print(f"{h:24} {v.get('verdict') or '?':12} {(v.get('other_app') or '')[:18]:18} {(v.get('reason') or '')[:100]}")
    n, sorted_n = backfill(added, fmts, history, cfg, now)
    state.save('history.json', history)
    active = sum(1 for a in accounts.values() if a['status'] in ('active', 'manual'))
    summary = (f"{active} active JobStep UGC accounts now tracked – every one checked by Claude (latest videos: caption, "
               f"on-screen text, speech).\n+{len(added)} new: {', '.join('@' + h for h in added) or '-'}\n"
               + (f"Removed {len(blocked)} (not JobStep UGC):\n" + '\n'.join(
                   f"• @{h} – {v.get('other_app') or v['verdict']}: {(v.get('reason') or '')[:90]}" for h, v in blocked) + '\n' if blocked else '')
               + (f"Could not decide (kept): {', '.join('@' + h for h in unclear)}\n" if unclear else '')
               + f"Pulled in {n} older videos of the new accounts ({sorted_n} match one of our formats).")
    print(summary)
    notify.push('🔎 JobStep creator list checked', summary)
    state.log({'type': 'accounts_sync', 'added': added, 'blocked': [h for h, _ in blocked], 'unclear': unclear})
    rep = localize.run(fmts, M.load(cfg), history, accounts, meta, cfg, page_of)
    state.save('formats.json', fmts)
    state.save('meta.json', meta)
    localize_report(rep)


def _plain_text(b):
    return ''.join(x.get('plain_text', '') for x in (b.get(b['type'], {}) or {}).get('rich_text', []) or []).strip()


def rebuild_page(fmt, mk, url):
    """Rebuild one market page (current layout, transcribed script) from the given example video. -> (ok, reason)"""
    cfg = load_config()
    m = re.search(r'@([^/]+)/video/(\d+)', url)
    v = tiktok.video_detail(*m.groups()) if m else None
    if not v:
        return False, 'example video unavailable'
    page, spec, problems = make_page(v, mk, cfg, None, replace_page=page_of(fmt, mk['key']), attempts=3)
    if problems:
        return False, '; '.join(problems)[:150]
    fmt.setdefault('reworded', {})[mk['key']] = True
    return True, ''


READY = ('ok', 'built', 'rebuilt')  # ready_page results that leave a page in the current layout


def own_example(fid, m):
    """Our creators' best TikTok video of this format (hand-checked tags): this market's if it is proven
    (localize.MIN_VIEWS), else the best of any market. For formats that came from our creators (no JobStep original).
    -> {'url', 'views', 'market'} or None"""
    tags, (_, vids) = own.hand_tags(), own.load()
    rows = [(t.get('market') == m and vids.get(vid, {}).get('views', 0) >= localize.MIN_VIEWS,
             vids.get(vid, {}).get('views', 0), vid, t.get('market')) for vid, t in tags.items()
            if t.get('format') == fid and not vid.startswith('ig_') and vids.get(vid, {}).get('handle')]
    if not rows:
        return None
    _, views, vid, mk = max(rows)
    return {'url': f"https://www.tiktok.com/@{vids[vid]['handle']}/video/{vid}", 'views': views, 'market': mk}


def backup_page(f, m, pid, blocks):
    """Old page text into state/script_backup.json before a full rebuild (nothing is lost)."""
    with state.LOCK:
        backup = state.load('script_backup.json', {})
        backup[f'rebuild:{f["id"]}:{m}:{int(time.time())}'] = {
            'page': pid, 'title': f.get('title'), 'blocks': [(b['type'], _plain_text(b)) for b in blocks]}
        state.save('script_backup.json', backup)


def missing_page(f, mk, fmts, origs, cfg):
    """Build a live format's missing page for one market from its example (strict example of another market, the
    JobStep original, or our creators' best video of it). -> (status, detail)"""
    ex = next((x for x in (f.get('inspo') or {}).values() if x.get('strict') and x.get('url')), {})
    url = origs.get(f['id']) or f.get('source_video') or (None if ex.get('own') else ex.get('url'))
    own_v = None if url else own_example(f['id'], mk['key'])
    url = url or (own_v or {}).get('url')
    m = re.search(r'@([^/]+)/video/(\d+)', url or '')
    v = tiktok.video_detail(*m.groups()) if m else None
    if not v:
        return 'error', f'no example video to build from ({url})'
    v['own'] = bool(own_v)
    added = ensure_market_pages(f, v, [mk], fmts, state.load('history.json', {}), cfg, None)
    if not added:
        return 'not built', f"page waits in the radar page until it passes the check ({url})"
    f.setdefault('inspo', {})[mk['key']] = {'url': url, 'views': v['views'], 'strict': True, 'built': True,
                                            **({'own': True} if own_v else {})}
    state.save('formats.json', fmts)
    return 'built', url


def ready_page(f, mk, fmts, origs, cfg, force=False):
    """One market's page of a format in the current layout. A missing page is built (missing_page: checked, then moved
    into the format folder); a page in the old hand-written layout (no example video, no resources section, no TikTok
    link, no script or no Parakeet AI link - verify.layout_problems) is rebuilt in place from its example video
    (same-language strict example if there is one, else the format's original JobStep video, else our creators' best
    video of it) - transcribed script, the old text kept in state/script_backup.json - and then goes through the same
    page check (audit.fix_page) as a new page. force: rebuild even a current page (mode example FORMAT:market:rebuild).
    -> (status, detail), status in READY ('ok', 'built', 'rebuilt') or 'not built' / 'not rebuilt' / 'error'."""
    from . import reword as _reword
    m = mk['key']
    if not M.for_format([mk], f):
        return 'ok', 'not a format of this market (skip_formats)'
    pid = page_of(f, m)
    if not pid:
        status, detail = missing_page(f, mk, fmts, origs, cfg)
        if status == 'built':  # page name = its title etc. right away (not on the next run)
            tidy.tidy_page(page_of(f, m), cfg['links'])
        return status, detail
    blocks = notion.children(pid)
    has_video = any(b['type'] == 'video' for b in blocks)
    has_res = any(b['type'].startswith('heading') and re.search(r'🔧|RESSOURCE|RECURSOS|VIRI', _plain_text(b), re.I) for b in blocks)
    if not force and has_video and has_res and not verify.layout_problems(blocks, _reword.script_blocks(pid), cfg['links']):
        return 'ok', ''
    ex = (f.get('inspo') or {}).get(m, {})
    url = ex.get('url') if ex.get('strict') else origs.get(f['id']) or f.get('source_video')
    own_v = None if url else own_example(f['id'], m)  # formats that came from our creators
    url = url or (own_v or {}).get('url') or (localize.current_source(pid) or {}).get('url')
    if not url or not re.search(r'@([^/]+)/video/(\d+)', url):
        return 'error', 'no example video link to rebuild from'
    h, vid = re.search(r'@([^/]+)/video/(\d+)', url).groups()
    v = tiktok.video_detail(h, vid)
    if not v:
        return 'error', f'example video unavailable: {url}'
    v['own'] = bool(own_v)  # our creator's video -> the "our own creator" note under it
    backup_page(f, m, pid, blocks)
    page, spec, problems = make_page(v, mk, cfg, None, replace_page=pid, attempts=3)
    if problems:
        return 'not rebuilt', '; '.join(problems)[:150]
    f.setdefault('reworded', {})[m] = True
    f.setdefault('inspo', {})[m] = {'url': url, 'views': v['views'], 'strict': bool(ex.get('strict') or own_v),
                                    'rebuilt': True, **({'own': True} if own_v else {})}
    state.save('formats.json', fmts)
    meta = CTX.get('meta') if CTX.get('meta') is not None else state.load('meta.json', {})
    accounts = CTX.get('accounts') or state.load('accounts.json', {})
    status, notes = audit.fix_page(f, mk, cfg, state.load('history.json', {}), accounts, meta, page_of)
    meta.setdefault('audit', {})[f"{f['id']}:{m}"] = status
    if 'meta' not in CTX:
        state.save('meta.json', meta)
    if status not in ('ok', 'fixed'):
        return 'not rebuilt', f"rebuilt but the page check says {status}: {'; '.join(notes)[:150]}"
    tidy.tidy_page(pid, cfg['links'])  # page name = the new title etc. right away (not on the next run)
    return 'rebuilt', url


def standardize(only=None):
    """Every active format page in every market in the current layout, without leftovers:
    - ready_page: a missing page is built, a page in the old layout is rebuilt from its example video;
    - duplicates are removed: a 2nd example video, repeated links/lines outside the script."""
    from . import audit as _audit, reword as _reword
    cfg, fmts = load_config(), load_formats()
    origs = _audit.originals()
    report = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in M.for_format(M.load(cfg), f):
            m = mk['key']
            if only and f['id'] not in only:
                continue
            try:
                status, detail = ready_page(f, mk, fmts, origs, cfg)
                if status != 'ok':
                    report.append((f['title'], m, status, detail))
                    continue
                pid = page_of(f, m)
                blocks = notion.children(pid)
                # duplicates outside the script section
                script_ids = {b['id'] for b in _reword.script_blocks(pid)}
                seen, removed, videos = set(), 0, 0
                for b in blocks:
                    if b['type'] == 'video':
                        videos += 1
                        if videos > 1:
                            notion.api('DELETE', f"/blocks/{b['id']}")
                            removed += 1
                        continue
                    t = _plain_text(b)
                    if b['id'] in script_ids or len(t) < 15 or b['type'] not in ('paragraph', 'bulleted_list_item'):
                        continue
                    if (b['type'], t) in seen:
                        notion.api('DELETE', f"/blocks/{b['id']}")
                        removed += 1
                    seen.add((b['type'], t))
                report.append((f['title'], m, 'ok', f'{removed} duplicate blocks removed' if removed else 'clean'))
            except Exception as e:
                report.append((f['title'], m, 'error', str(e)[:150]))
    state.save('formats.json', fmts)
    for r in report:
        print(' | '.join(str(x) for x in r))
    return report


def resolve_url(url):
    """Short share links (vm.tiktok.com/...) -> the full video link."""
    import requests
    if '/video/' in url:
        return url
    try:
        return requests.head(url, allow_redirects=True, timeout=30, headers={'User-Agent': tiktok.UA}).url
    except requests.RequestException:
        return url


def add_format(urls):
    """A format added by hand from TikTok videos of ANY app (e.g. a study or CV app we do not watch). The first video
    goes through exactly what a viral video goes through: judged against all our formats (list + archive) - known ->
    missing pages added / brought back from the archive; new -> built in every market's language and published
    through the quality gate. The engagement bar is skipped (the user picked the video). Every given video goes into
    the ranking data as this format, so the list places it by its real numbers like any other format."""
    cfg, fmts = load_config(), load_formats()
    mkts = M.load(cfg)
    history, meta = state.load('history.json', {}), state.load('meta.json', {})
    accounts = state.load('accounts.json', {})
    CTX.update({'meta': meta, 'accounts': accounts})
    now = time.time()
    vids = []
    for url in urls:
        m = re.search(r'@([^/?]+)/video/(\d+)', resolve_url(url.strip()))
        d = tiktok.video_detail(*m.groups()) if m else None
        if not d:
            print('video unavailable:', url)
            continue
        d.update({'notified': [], 'first_seen': int(now)})
        vids.append(d)
    if not vids:
        raise SystemExit('add-format: no video available')
    for h in dict.fromkeys(v['handle'] for v in vids):  # its creators are followed from now on: their new videos keep
        a = accounts.get(h) or {}                          # moving the format on the list (never paused or blocked)
        accounts[h] = {**a, 'status': 'manual', 'source': a.get('source') or 'added-by-hand', 'since': a.get('since', int(now)),
                       'lang': a.get('lang') or discover.language(h), 'added_format': True}
        accounts[h].pop('blocked', None)
    state.save('accounts.json', accounts)
    german = {v['handle'] for v in vids if discover.language(v['handle']) == 'de'}
    for v in vids:
        to_history(history, v, german, now)
    first = vids[0]
    result = handle_viral(first, mkts, fmts, history, cfg, now, only_detect=False, force=True,
                          label=f"➕ Format added by hand (@{first['handle']})")
    fid = first.get('format')
    for v in vids[1:]:
        set_format(v, history, fid, judged=True)
    watch = state.load('videos.json', {})  # already on the watchlist: the normal run must not alert on it again
    for v in [watch[v['id']] for v in vids if v['id'] in watch]:
        v['notified'] = list(dict.fromkeys(v.get('notified', []) + ['taking_off', 'viral']))
    state.save('videos.json', watch)
    state.save('history.json', history)
    state.save('formats.json', fmts)
    state.save('meta.json', meta)
    if result.get('error') or not fid:  # never fail silently: an alert, and the GitHub run turns red
        why = result.get('error') or 'no format was built (video unavailable?)'
        notify.push('⚠️ Format NOT added', f"{first['url']}\n{why}\nNothing was built - run add_format again later.",
                    click=first['url'])
        raise SystemExit(f'add-format failed: {why}')
    pos = None
    if fid and next((f for f in fmts if f['id'] == fid), {}).get('status') == 'active':
        ids = rerank(mkts, fmts, history, cfg)
        pos = ids.index(fid) + 1 if fid in ids else None
    print('add-format:', json.dumps({**result, 'format': fid, 'position': pos,
                                     'videos': [(v['handle'], v['id'], v['views']) for v in vids]}, ensure_ascii=False))


def group_report(fmts, mkts, cfg, meta, fix=False, force=False):
    """Cross-country check of all formats; with fix=True failing groups are repaired (never approved scripts) and
    checked again. Sends one Slack report with the result types kept separate."""
    notes = []
    if fix:  # script cues that point to nothing in the resources are removed (all unlocked pages)
        for f in [f for f in fmts if f.get('status') in ('active', 'pending')]:
            for mk in mkts:
                pid = page_of(f, mk['key'])
                if pid and not align.approved_script(f['id'], mk['lang']) and reword.fix_asset_cues(pid):
                    notes.append(f"{f['title']}: {mk['key']}: script cues cleaned (resources)")
    results, dups = crosscheck.run(fmts, mkts, cfg, page_of, meta, force=force)
    if fix:
        for f in [f for f in fmts if results.get(f['id'], {}).get('status') == 'fail'
                  or results.get(f['id'], {}).get('title_fixes')]:
            try:
                res, changed, awaiting = crosscheck.group_cycle(f, mkts, cfg, page_of, meta)
            except Exception as e:  # one format's error never stops the others
                res, changed, awaiting = {**results[f['id']], 'status': 'unverified', 'passed': False,
                                          'reasons': [f'repair error: {str(e)[:200]}']}, [], []
            results[f['id']] = res
            notes += [f"{f['title']}: {c}" for c in changed] + [f"{f['title']}: ⏸ {a}" for a in awaiting]
            state.save('meta.json', meta)
    text = crosscheck.report(results, dups, fmts) + ('\n\nRepairs:\n' + '\n'.join(notes) if notes else '')
    print(text)
    notify.push('🌍 Cross-country format check (DE/FR/ES)', text[:3800])
    state.save('meta.json', meta)
    return results, dups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='fetch + detect only, no notifications, no writes')
    ap.add_argument('--only-detect', action='store_true', help='alerts but never build pages or re-rank')
    ap.add_argument('--test-notify', action='store_true', help='send one test notification and exit')
    ap.add_argument('--test-claude', action='store_true', help='check the Claude subscription token and exit')
    ap.add_argument('--test-discord', action='store_true', help='check the Discord webhooks WITHOUT posting')
    ap.add_argument('--edit-discord', default='', help='DACH message id: rewrite that hot announcement with the current text')
    ap.add_argument('--weekly', action='store_true', help='send the weekly Slack report now')
    ap.add_argument('--megasheet-check', action='store_true', help='only read our creators from Megasheet (fails if it does not work)')
    ap.add_argument('--own-sync', action='store_true', help='catch up on our own creators (full Megasheet read, more video checks), then re-sort')
    ap.add_argument('--lineup', action='store_true', help='show the current form of every format and what Monday would take out (no changes)')
    ap.add_argument('--lineup-apply', action='store_true', help='take the badly performing formats out now')
    ap.add_argument('--accounts-sync', default='', help='JSON file: confirmed new/blocked accounts -> import, backfill, localize')
    ap.add_argument('--localize', action='store_true', help='inspiration videos in each market language (missing ones only)')
    ap.add_argument('--localize-recheck', action='store_true', help='strictly re-check every swapped inspiration video')
    ap.add_argument('--reword', action='store_true', help='off (scripts are transcribed now)')
    ap.add_argument('--reword-dry', action='store_true', help='off (scripts are transcribed now)')
    ap.add_argument('--audit', action='store_true', help='check every page (example video, script) and fix until it passes')
    ap.add_argument('--audit-failed', action='store_true', help='audit only the pages that did not pass last time')
    ap.add_argument('--standardize', action='store_true', help='all pages in the current layout, duplicates removed')
    ap.add_argument('--accounts-add', default='', help='JSON file of checked accounts to add (with evidence)')
    ap.add_argument('--align', action='store_true', help='transcribe every script from its example + short visual hook')
    ap.add_argument('--short-hooks', action='store_true', help='shorten every visual hook section that has more than one line')
    ap.add_argument('--set-example', default='', help='FORMAT_ID:market:tiktok_url - put this example video on that page')
    ap.add_argument('--group-audit', action='store_true', help='cross-country check of all formats (report only)')
    ap.add_argument('--group-fix', action='store_true', help='cross-country check + automatic repairs of failing groups')
    ap.add_argument('--gate-rehearsal', action='store_true', help='run the publication gate on passing live formats (no publish)')
    ap.add_argument('--apply-approved', action='store_true', help='write approved scripts (and their examples) to the pages')
    ap.add_argument('--approval-drafts', action='store_true', help='replacement drafts for approval-locked scripts that '
                    'fail the cross-country check (nothing written to Notion)')
    ap.add_argument('--force', action='store_true', help='with --group-audit/--group-fix: ignore cached group results')
    ap.add_argument('--strip-directions', action='store_true', help='every page (live, waiting, archived): bracketed stage directions / acting tips leave the scripts (approved scripts: via the registry + apply-approved)')
    ap.add_argument('--renote', action='store_true', help='every page (live, waiting, archived): the note under the inspiration video gets the current text')
    ap.add_argument('--refs', action='store_true', help='now: generated format references of live/waiting formats are rebuilt where the script rules changed (reviewed ones never)')
    ap.add_argument('--timing', action='store_true', help='read-only: second Parakeet AI is first shown/said on every live page')
    ap.add_argument('--tidy', action='store_true', help='every live page: few link cues, hook names the title, bold title, page name = title')
    ap.add_argument('--auto', action='store_true', help='scheduled run: full every 6 hours, light in between')
    ap.add_argument('--verify', action='store_true', help='read-only check of the lists and every format page (prints the problems)')
    ap.add_argument('--export', action='store_true', help='all scripts as one encrypted Markdown file (state/scripts_export.enc)')
    ap.add_argument('--relist', action='store_true', help='only re-draw the DE/FR/ES lists (order + going-viral section)')
    ap.add_argument('--check-hot', action='store_true', help='strict Claude check of ALL viral videos from the last 7 days')
    ap.add_argument('--init-market', default='', help='fr | es: connect a market to the shared format list')
    ap.add_argument('--fill-market', default='', help='fr | es: build missing pages of active formats')
    ap.add_argument('--reset-pending', action='store_true', help='formats waiting at the gate get their 4 tries back (after a fix), then are checked again')
    ap.add_argument('--add-format', default='', help='TikTok link(s), comma-separated: add this format by hand (any app), first link = example')
    ap.add_argument('--test-viral', default='', help='TikTok URL: send the full viral Slack message for it (no Notion changes)')
    a = ap.parse_args()
    if a.test_discord:
        import requests as _rq
        for mk in M.load(load_config()):
            url = os.environ.get(mk.get('discord_env', ''), '')
            if not url:
                print(mk['key'], 'webhook not set')
                continue
            r = _rq.get(url, timeout=20)  # reading the webhook does not post anything
            info = r.json() if r.ok else {}
            print(mk['key'], 'discord webhook ok:', r.ok, '| channel id:', info.get('channel_id'), '| server id:',
                  info.get('guild_id'), '| expected server:', info.get('guild_id') == mk.get('discord_server') if mk.get('discord_server') else '?')
        from . import discord_bot
        cfg = load_config()
        for mk in M.load(cfg):
            if not mk.get('creator_channels'):
                continue
            if not discord_bot.token():
                print(mk['key'], 'creator channels: DISCORD_BOT_TOKEN not set')
                continue
            try:  # only reads the channel list, posts nothing
                chans = discord_bot.creator_channels(mk['discord_server'], cfg)
                print(mk['key'], f'creator channels the bot can post in: {len(chans)}',
                      [(c['name'], len(c['members'])) for c in chans])
            except Exception as e:
                print(mk['key'], 'creator channels failed:', str(e)[:300])
        return
    if a.init_market:
        init_market(a.init_market)
        return
    if a.fill_market:
        fill_market(a.fill_market)
        return
    if a.check_hot:
        check_hot()
        return
    if a.edit_discord:
        cfg = load_config()
        meta, fmts = state.load('meta.json', {}), load_formats()
        by_id = {f['id']: f for f in fmts}
        mk = next(x for x in M.load(cfg) if x['key'] == 'de')
        fid = next(f for f, h in meta.get('hot', {}).items() if h.get('announced', {}).get('de'))
        text = hot.announcement(mk['T'], by_id[fid], meta['hot'][fid]['count'], page_of(by_id[fid], 'de'))
        hot.edit_discord(os.environ[mk['discord_env']], a.edit_discord, text)
        meta['hot'][fid].setdefault('messages', {})['de'] = a.edit_discord
        state.save('meta.json', meta)
        print('edited announcement', a.edit_discord, 'for', by_id[fid]['title'])
        return
    if a.weekly:
        own_accounts, own_videos = own.load()
        weekly.maybe_send({}, state.load('history.json', {}), own_videos, own_accounts, load_formats(), load_config(),
                          time.time(), force=True)
        return
    if a.megasheet_check:
        own_accounts, own_videos = own.load()
        if not own.sync_megasheet(own_accounts, own_videos, time.time(), full=True,
                                  markets=[m['key'] for m in M.load(load_config())]):
            raise SystemExit(1)
        return
    if a.own_sync:
        cfg, fmts = load_config(), load_formats()
        own_accounts, own_videos = own.load()
        own.sync_megasheet(own_accounts, own_videos, time.time(), full=True, markets=[m['key'] for m in M.load(cfg)])
        print('own creators:', own.update(own_accounts, own_videos, fmts, cfg, time.time(), max_details=300))
        state.save('own.json', own_videos)
        state.save('own_accounts.json', own_accounts)
        o = own.stats(own_videos, fmts, time.time())
        by = {f['id']: f['title'] for f in fmts}
        for fid, x in sorted(o.items(), key=lambda kv: -kv[1]['n']):
            print(f"  {by.get(fid, fid)[:50]:50} ours: {x['n']} videos, {2 ** x['lift']:.2f}x usual, {x['hits_100k']} >=100k")
        rerank(M.load(cfg), fmts, state.load('history.json', {}), cfg)
        return
    if a.lineup or a.lineup_apply:
        cfg, fmts, history = load_config(), load_formats(), state.load('history.json', {})
        _, own_videos = own.load()
        p = (lineup.apply(history, fmts, cfg, own_videos, M.load(cfg)) if a.lineup_apply
             else lineup.plan(history, fmts, cfg, own_videos))
        b = p['board']
        print('IN THE LIST (weakest last):')
        for f in sorted([f for f in fmts if f.get('status') == 'active' or f in [x[0] for x in p['out']]],
                        key=lambda f: -b[f['id']]['form']):
            x = b[f['id']]
            print(f"  {x['form']:.2f}  {f['title'][:50]:50} JobStep {x['js_form']:.2f} ({x['all_videos']} videos) "
                  f"x ours {x['own_factor']:.2f} ({x['own_videos']}) {'| protected: ' + p['protected'][f['id']] if p['protected'].get(f['id']) else ''}")
        print('OUT:', [(f['title'], round(sc, 2), r) for f, sc, r in p['out']])
        if a.lineup_apply:
            state.save('formats.json', fmts)
            rerank(M.load(cfg), fmts, history, cfg)
        return
    if a.accounts_sync:
        accounts_sync(a.accounts_sync)
        return
    if a.localize_recheck:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        rep = localize.recheck(fmts, M.load(cfg), state.load('history.json', {}), state.load('accounts.json', {}), meta, cfg, page_of)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        localize_report(rep)
        return
    if a.localize:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        rep = localize.run(fmts, M.load(cfg), state.load('history.json', {}), state.load('accounts.json', {}), meta, cfg, page_of)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        localize_report(rep)
        return
    if a.reword or a.reword_dry:
        print('rewording is off: scripts are transcribed from the example video (use mode align to redo all pages)')
        return
    if a.audit or a.audit_failed:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        rep = audit.run(fmts, M.load(cfg), cfg, state.load('history.json', {}), state.load('accounts.json', {}), meta, page_of,
                        rebuild=rebuild_page, only_failed=a.audit_failed)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        flags = {'de': '🇩🇪', 'fr': '🇫🇷', 'es': '🇪🇸', 'sl': '🇸🇮'}
        bad = [r for r in rep if r[2] not in ('ok', 'fixed')]
        notify.push('✅ Page audit (example video + script)', f"{len(rep) - len(bad)}/{len(rep)} pages check out "
                    f"({sum(1 for r in rep if r[2] == 'fixed')} fixed now)."
                    + ('\n\nStill failing:\n' + '\n'.join(f"{flags[m]} {t} – {' / '.join(n)[:160]}" for t, m, _, n in bad) if bad else ''))
        return
    if a.standardize:
        standardize()
        return
    if a.accounts_add:
        accounts_add(a.accounts_add)
        return
    if a.set_example:
        cfg, fmts = load_config(), load_formats()
        fid, m, url = a.set_example.split(':', 2)
        f = next(x for x in fmts if x['id'] == fid)
        mk = next(x for x in M.load(cfg) if x['key'] == m)
        if url.strip() == 'rebuild':  # the whole page again from its example video (title, script, hook), then checked
            print('rebuild:', ready_page(f, mk, fmts, audit.originals(), cfg, force=True))
            state.save('formats.json', fmts)
            return
        same = discover.language(re.search(r'@([^/]+)/', url).group(1)) == mk['lang']
        print('example set:', audit._put_example(f, m, page_of(f, m), mk['lang'], url, same_lang=same))
        st = align.align_page(f, page_of(f, m), mk['lang'], cfg, cfg['links'])
        print('script:', st)
        if st[0] == 'ok':
            f.setdefault('reworded', {})[m] = True
        meta = state.load('meta.json', {})
        meta.setdefault('audit', {}).pop(f'{fid}:{m}', None)
        state.save('meta.json', meta)
        state.save('formats.json', fmts)
        return
    if a.short_hooks:
        cfg = load_config()
        rep = reword.shorten_hooks(load_formats(), M.load(cfg), cfg, page_of)
        bad = [r for r in rep if r[2] not in ('ok',)]
        notify.push('🎬 Visual hooks shortened', f"{sum(1 for r in rep if r[3] == '')} pages shortened, "
                    f"{sum(1 for r in rep if r[3] == 'already short')} already short"
                    + ('\nNot changed: ' + '; '.join(f"{t} {m}: {w}" for t, m, _, w in bad) if bad else ''))
        return
    if a.align:
        cfg = load_config()
        for mk in M.load(cfg):  # first: every active format gets its missing language pages
            if any(f.get('status') == 'active' and not page_of(f, mk['key']) for f in load_formats()):
                fill_market(mk['key'])
        fmts, meta = load_formats(), state.load('meta.json', {})
        rep = align.run(fmts, M.load(cfg), cfg, page_of)
        meta['audit'] = {k: v for k, v in meta.get('audit', {}).items() if False}  # all pages changed -> audit again
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        bad = [r for r in rep if r[2] != 'ok']
        notify.push('✍️ Scripts transcribed, visual hooks shortened', f"{len(rep) - len(bad)}/{len(rep)} pages transcribed"
                    + ('\nNot changed: ' + '; '.join(f"{t} {m}: {w}" for t, m, _, w in bad) if bad else ''))
        return
    if a.gate_rehearsal:
        # controlled end-to-end check of the publication gate on live formats whose group already passes:
        # page audit of every country + cross-country check, exactly as for a new format - but nothing is published
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        history, account_info = state.load('history.json', {}), state.load('accounts.json', {})
        mkts = M.load(cfg)
        lines = []
        for f in [f for f in fmts if f.get('status') == 'active'
                  and (meta.get('group_audit') or {}).get(f['id'], {}).get('status') == 'pass']:
            before = f.get('status')
            ok, reasons = gate.check(f, mkts, cfg, history, account_info, meta, page_of, set_page, make_page, rebuild_page)
            assert f.get('status') == before  # the rehearsal never changes publication state
            lines.append(f"{f['title']}: {'PASS' if ok else 'HELD'} " + '; '.join(reasons)[:300])
        print('\n'.join(lines) or 'no passing group to rehearse', flush=True)
        state.save('meta.json', meta)
        notify.push('🧪 Gate rehearsal (nothing published)', '\n'.join(lines)[:3500] or 'no passing group')
        return
    if a.apply_approved:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        done = crosscheck.apply_approvals(fmts, M.load(cfg), cfg, page_of, meta)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        if done:
            notify.push('🔒 Approved scripts applied', '\n'.join(done)[:3500])
        return
    if a.approval_drafts:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        crosscheck.approval_drafts(fmts, M.load(cfg), cfg, page_of, meta)
        state.save('meta.json', meta)
        return
    if a.group_audit or a.group_fix:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        group_report(fmts, M.load(cfg), cfg, meta, fix=a.group_fix, force=a.force)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        return
    if a.strip_directions:
        cfg, n = load_config(), 0
        for f in load_formats():
            for mk in M.load(cfg):
                pid = page_of(f, mk['key'])
                if not pid or align.approved_script(f['id'], mk['lang']):
                    continue  # approval-locked scripts change only through registry/approved_scripts.json + apply-approved
                try:
                    k = reword.strip_directions(pid)
                    n += k
                    if k:
                        print(f"{f['title'][:45]} | {mk['key']} | {k} paragraphs cleaned", flush=True)
                except Exception as e:
                    print('strip failed:', f['title'], mk['key'], str(e)[:150], flush=True)
        print(f'strip-directions: {n} paragraphs cleaned')
        return
    if a.renote:
        cfg, n = load_config(), 0
        for f in load_formats():
            for mk in M.load(cfg):
                pid = page_of(f, mk['key'])
                if not pid:
                    continue
                try:
                    n += bool(localize.refresh_note(pid, mk['lang']))
                except Exception as e:
                    print('renote failed:', f['title'], mk['key'], str(e)[:150], flush=True)
        print(f'renote: {n} notes updated')
        return
    if a.refs:
        cfg = load_config()
        for f in [f for f in load_formats() if f.get('status') in ('active', 'pending')]:
            before = crosscheck.reference(f['id'])
            if before and ('generated' not in before or before.get('rules') == crosscheck.REF_RULES):
                continue
            ref = crosscheck.ensure_reference(f, page_of, cfg)
            print(f"{f['id']} {f['title'][:45]}: {'reference rebuilt' if ref else 'reference NOT rebuilt (retried on its next check)'}",
                  flush=True)
        return
    if a.timing:
        from . import timing
        cfg = load_config()
        timing.run(cfg, M.load(cfg), load_formats(), page_of)
        return
    if a.tidy:
        cfg = load_config()
        rep = tidy.run(load_formats(), M.load(cfg), cfg, page_of)
        for t, m, ch in rep:
            print('tidy:', m, t[:40], '-', '; '.join(ch))
        print(f'tidy: {len(rep)} pages changed')
        return
    if a.verify:
        from . import verify
        verify.run(load_config(), load_formats(), page_of)
        return
    if a.export:
        from . import export
        export.run(load_config(), load_formats(), page_of)
        return
    if a.relist:
        cfg, fmts = load_config(), load_formats()
        mkts = M.load(cfg)
        if own_comebacks(mkts, fmts, cfg, tiers=own_tiers(mkts, fmts, cfg, force=True), force=True):
            state.save('formats.json', fmts)
        rerank(mkts, fmts, state.load('history.json', {}), cfg, force=True)
        return
    if a.reset_pending:
        cfg, fmts = load_config(), load_formats()
        mkts = M.load(cfg)
        history, meta, accounts = state.load('history.json', {}), state.load('meta.json', {}), state.load('accounts.json', {})
        CTX.update({'meta': meta, 'accounts': accounts})
        for f in fmts:
            if f.get('status') == 'pending' and f.get('pending'):
                f['pending']['tries'] = 0
        state.save('formats.json', fmts)
        gate.retry_pending(fmts, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild_page, rerank)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        return
    if a.add_format:
        add_format([u for u in a.add_format.split(',') if u.strip()])
        return
    if a.test_viral:
        import re as _re
        handle, vid = _re.search(r'@([^/]+)/video/(\d+)', a.test_viral).groups()
        v = tiktok.video_detail(handle, vid)
        v.update({'notified': [], 'first_seen': int(time.time())})
        cfg = load_config()
        mkts = M.load(cfg)
        r = handle_viral(v, mkts, load_formats(), state.load('history.json', {}), cfg, time.time(), only_detect=True, test=True)
        print('test viral result:', json.dumps(r, ensure_ascii=False))
        return
    if a.test_claude:
        import re as _re
        tok = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', '')
        print('token length:', len(tok), '| starts with sk-ant-oat01-:', tok.startswith('sk-ant-oat01-'),
              '| contains whitespace/newline:', bool(_re.search(r'\s', tok)), '| ends with AA:', tok.endswith('AA'))
        try:
            print('claude says:', llm.chat('sonnet', 'Be brief.', 'Reply with exactly: OK'))
        except Exception as e:
            print('claude test failed:', str(e)[:300])
        return
    if a.test_notify:
        notify.push('✅ JobStep Radar connected', 'The watcher runs every 6 hours and posts here as soon as a JobStep video '
                    'takes off or goes viral (DACH / France / Spain).',
                    click='https://github.com/vcmyfzft8b-sudo/jobstep-viral-watch/actions')
        print('test notification sent' + ('' if os.environ.get('SLACK_WEBHOOK_URL') else ' (no SLACK_WEBHOOK_URL set!)'))
        return
    missing = [k for k in ('NOTION_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN', 'SONIOX_API_KEY') if not os.environ.get(k)]
    if missing and not a.dry_run:
        print('Missing secrets', missing, '-> running as dry run')
        a.dry_run = True
    run(dry_run=a.dry_run, only_detect=a.only_detect, auto=a.auto)


if __name__ == '__main__':
    main()
