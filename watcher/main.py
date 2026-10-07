"""One watcher run (every 6 hours on GitHub Actions), for all markets (DACH / France / Spain).

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

from . import audit, builder, classify, detect, discover, hot, lineup, llm, localize, markets as M, media, notify, notion, own, rank, reword, soniox, state, tiktok, weekly

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ALL_MARKETS = ('de', 'fr', 'es')


def load_config():
    with open(os.path.join(ROOT, 'config.json')) as f:
        cfg = json.load(f)
    if os.environ.get('NOTION_RADAR_PAGE'):
        cfg['notion']['radar_page'] = os.environ['NOTION_RADAR_PAGE']
    return cfg


def load_formats():
    """One shared format list for all markets. Each format has a page per market: page_id (DACH) + pages{fr, es}."""
    formats = state.load('formats.json', None)
    if formats is None:
        with open(os.path.join(ROOT, 'registry', 'formats.json')) as f:
            formats = json.load(f)
    return formats


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


def run(dry_run=False, only_detect=False):
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
        if age_h > 72 and now - last < 20 * 3600 and v.get('views', 0) < th['viral_views']:
            # 3-7 day old videos: full check once a day; in between only the free embed view count
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
    actions, backlog = [], []
    for vid, v in sorted(videos.items(), key=lambda x: -x[1].get('views', 0)):
        if 'created' not in v:
            continue
        lvl = detect.level(v, now, detect.creator_baseline(history, v['handle']), th)
        if not lvl or 'viral' in v['notified'] or (lvl == 'taking_off' and 'taking_off' in v['notified']):
            continue
        quiet = lvl == 'taking_off' and v.get('first_seen') == int(now) and now - v['created'] > 48 * 3600
        try:
            result = handle_alert(v, lvl, mkts, fmts, history, cfg, now, dry_run, only_detect, quiet=quiet)
            actions.append(result)
            if quiet:
                backlog.append(result)
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
    if backlog and not dry_run:
        notify.push(f'📋 {len(backlog)} older "taking off" videos from newly added accounts',
                    'Last 7 days – details on the Notion radar page')

    if not dry_run:
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

    # 4b. our own creators: new videos, views, formats (feeds the ranking: how each format does for US)
    own_accounts, own_videos = own.load()
    if not dry_run:
        try:
            print('own creators:', own.update(own_accounts, own_videos, fmts, cfg, now))
            state.save('own.json', own_videos)
            state.save('own_accounts.json', own_accounts)
        except Exception as e:
            print('own creators failed:', str(e)[:200])

    # 4c. Monday: weekly clean-up - formats that perform badly leave the list
    if not dry_run and not only_detect:
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
            try:  # Monday: inspiration videos in each market's language for formats that still miss one
                localize_report(localize.run(fmts, mkts, history, account_info, meta, cfg, page_of, now), only_changes=True)
                state.save('formats.json', fmts)
            except Exception as e:
                print('localize failed:', str(e)[:200])
            try:  # Monday: every page must check out (example video = format, script follows it, reworded)
                bad = [r for r in audit.run(fmts, mkts, cfg, history, account_info, meta, page_of, rebuild=rebuild_page) if r[2] not in ('ok', 'fixed')]
                state.save('formats.json', fmts)
                if bad:
                    notify.push('⚠️ Page audit: pages that need a look', '\n'.join(f"{m} {t} – {' / '.join(n)[:150]}" for t, m, _, n in bad))
            except Exception as e:
                print('audit failed:', str(e)[:200])

    # 5. going-viral card + Discord (every market), then sort all lists in the same order (what goes viral right now first)
    if not only_detect:
        try:
            hot.update(history, videos, fmts, cfg, meta, mkts, dry_run=dry_run)
        except Exception as e:
            print('hot update failed:', str(e)[:200])
        if not dry_run:
            try:
                before_top = meta.get('top3', [])
                ids = rerank(mkts, fmts, history, cfg)
                meta['top3'] = ids[:3]
                if before_top and ids[:3] != before_top:
                    by = {f['id']: f for f in fmts}
                    recent = rank.recent_viral(history, fmts, cfg)
                    notify.push('🔁 New top of the format lists (DE/FR/ES)', '\n'.join(
                        f"{n}. {by[i]['title']} – {recent.get(i, 0)} viral in 7 days" for n, i in enumerate(ids[:5], 1)))
            except Exception as e:
                print('re-sort failed:', str(e)[:200])

    # 5b. Monday: weekly report in Slack
    if not dry_run:
        try:
            weekly.maybe_send(meta, history, own_videos, own_accounts, fmts, cfg, now)
        except Exception as e:
            print('weekly report failed:', str(e)[:200])

    # 6. every few days: complete the JobStep account list (Lightreel) and pause/revive accounts
    today = datetime.datetime.now(datetime.timezone.utc)
    if not dry_run and now - meta.get('discovered_at', 0) >= cfg['discovery_every_days'] * 86400:
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
            print('own discovery failed:', str(e)[:200])

    if not dry_run:
        state.save('videos.json', videos)
        state.save('history.json', history)
        state.save('formats.json', fmts)
        state.save('accounts.json', account_info)
        meta['last_run'] = int(now)
        state.save('meta.json', meta)
    print('actions:', json.dumps(actions, ensure_ascii=False))


def handle_alert(v, lvl, mkts, fmts, history, cfg, now, dry_run, only_detect, quiet=False):
    """Taking off: short message. Viral: see handle_viral."""
    if now - v['created'] > cfg['watch_days'] * 86400:  # never alert on old videos
        return {'video': v['id'], 'level': lvl, 'skipped': 'older than watch window'}
    if dry_run:
        print('DRY', lvl, v['handle'], v['views'], v.get('url'))
        return {'video': v['id'], 'level': lvl, 'views': v['views']}
    if lvl == 'viral':
        return handle_viral(v, mkts, fmts, history, cfg, now, only_detect)
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
    if not quiet:
        notify.push('🟡 Taking off: JobStep video', msg, click=v['url'])
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


def handle_viral(v, mkts, fmts, history, cfg, now, only_detect, test=False):
    """Every viral video (creators from ALL markets): download + Soniox transcript, Claude (Opus) judges it against
    ALL our formats (list + archive) and translates the script to English. Then for every market (DE/FR/ES):
    in the list -> nothing to build (missing language pages are added); in the archive -> brought back everywhere;
    new -> built in every market's language and added to every list. One Slack message with link, verdict, English
    script. If Claude fails, a basic message still goes out and the full check is retried next run."""
    age_h = (now - v['created']) / 3600
    eng = detect.engagement(v)
    eng_unknown = v.get('detail_missing') and not v.get('shares') and not v.get('saves')
    weak = (not eng_unknown) and eng < cfg['thresholds']['min_engagement']
    stats = (f"@{v['handle']} – *{fmt_views(v['views'])} views* after {age_h:.0f} h · shares+saves {eng:.1%}"
             f"{' (weak)' if weak else ''}{' (unknown)' if eng_unknown else ''}")
    title = ('🧪 TEST – ' if test else '') + '🟢 VIRAL: JobStep video'
    result = {'video': v['id'], 'level': 'viral', 'views': v['views']}
    work = tempfile.mkdtemp(prefix='viral-')
    try:
        video_file, note = None, ''
        try:
            video_file = media.download(v['url'], work)
            transcript = soniox.transcribe(media.audio(video_file, work))
        except Exception as e:
            note = f'\n_(video download/transcription failed: {str(e)[:80]} – judged from TikTok text)_'
            transcript = {'text': v.get('subtitles', ''), 'segments': [], 'language': ''}
        try:
            verdict = classify.judge(v, fmts, cfg['models']['build'], transcript.get('text', ''))
        except Exception as e:
            if 'viral_basic' not in v['notified']:
                notify.push(title, f"{stats}\n⚠️ Claude check failed ({str(e)[:120]}) – the full check + English script "
                            'will follow in the next run (6 h).', click=v['url'])
                v['notified'].append('viral_basic')
            state.log({'type': 'judge_failed', 'video': v['id'], 'error': str(e)[:300]})
            result['error'] = str(e)[:200]
            return result

        prepared = {'work': work, 'video_file': video_file, 'transcript': transcript} if video_file else None
        blocked = 'weak engagement' if weak else 'only-detect mode' if only_detect else None if prepared else 'video unavailable'
        known = resolve(fmts, verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
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
                pos = revive_format(known, v, mkts, fmts, history, cfg, prepared=prepared)
                outcome = f"♻️ *Was in the archive → brought back as #{pos}* in all lists: *{known['title']}* ({market_links(known, mkts)})"
        else:
            set_format(v, history, None, judged=True)
            if blocked:
                outcome = f"🆕 *NEW format – not in Notion yet*, not added ({blocked})"
            else:
                fmt, problems, position = build_format(v, mkts, fmts, history, cfg, prepared=prepared,
                                                       description=verdict.get('new_format_description', ''))
                result.update({'built': fmt['id'], 'problems': problems, 'position': position})
                outcome = (f"🆕 *NEW format → added as #{position}* in all lists: *{fmt['title']}* ({market_links(fmt, mkts)})"
                           + (f"\n⚠️ drafts to check: {'; '.join(problems)}" if problems else ''))
        result['format'] = v.get('format')
        script = (verdict.get('english_script') or '').strip() or '(no speech / text found)'
        quoted = '\n'.join('> ' + line for line in script.splitlines() if line.strip())
        msg = (f"{stats}\n▶ <{v['url']}|Open video on TikTok>{note}\n\n*Format check (Claude):* {outcome}\n"
               f"_{verdict.get('reason', '')}_\n\n*Script (English):*\n{quoted[:3500]}")
        notify.push(title, msg)
        notify.radar(cfg['notion']['radar_page'], f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🟢 VIRAL – "
                     f"@{v['handle']} {fmt_views(v['views'])} – {outcome.split(chr(10))[0]}", link=v['url'], link_label='Video')
        v['notified'].append('viral')
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


def make_page(v, mk, cfg, prepared, parent=None, title=None, replace_page=None):
    """Build one market's page (its language, current layout). Returns (page_id_or_url, spec, problems)."""
    work, video_file, transcript, frames, own = _prepare(v, prepared)
    try:
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'], lang=mk['lang'])
        problems = builder.validate(spec, transcript, lang=mk['lang'])
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
    """A format in the list that is missing in a market gets that market's page (built from this viral video)."""
    added = []
    for mk in mkts:
        if not page_of(fmt, mk['key']):
            pid, spec, problems = make_page(v, mk, cfg, prepared)
            if not problems:
                set_page(fmt, mk['key'], pid)
                added.append(mk['T']['flag'])
    if added:
        rerank(mkts, fmts, history, cfg)
    return added


def build_format(v, mkts, fmts, history, cfg, prepared=None, description=''):
    """New format: build its page in every market's language (DE/FR/ES) and add it to every list.
    Returns (format entry, problems, position)."""
    fid = 'A' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    entry = {'id': fid, 'source_video': v['url'], 'created': int(time.time()), 'pages': {}, 'status': 'active'}
    problems = []
    for mk in mkts:
        pid, spec, probs = make_page(v, mk, cfg, prepared)
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
    if not entry.get('page_id'):  # DACH page failed: keep it as a draft entry, don't list it
        entry['status'] = 'draft'
        entry.setdefault('title', v.get('hook_en') or 'draft')
    fmts.append(entry)
    set_format(v, history, fid, judged=True)
    position = None
    if entry['status'] == 'active':
        position = rerank(mkts, fmts, history, cfg).index(fid) + 1
    state.log({'type': 'format_built', 'format': fid, 'pages': entry.get('pages'), 'page_de': entry.get('page_id'),
               'problems': problems, 'position': position})
    return entry, problems, position


def revive_format(fmt, v, mkts, fmts, history, cfg, prepared=None):
    """Archived format went viral again: in every market move its page back from the archive into the format folder
    (refreshed to the current layout with the new video); markets without a page get one. Returns its position."""
    for mk in mkts:
        m = mk['key']
        pid = page_of(fmt, m)
        try:
            if pid:
                notion.move_page(pid, mk['holder_page'])
                make_page(v, mk, cfg, prepared, replace_page=pid)
            else:
                new_pid, spec, problems = make_page(v, mk, cfg, prepared)
                if not problems:
                    set_page(fmt, m, new_pid)
        except Exception as e:
            notify.radar(cfg['notion']['radar_page'], f"{mk['T']['flag']} revive issue for {fmt['title']}: {str(e)[:150]}")
    fmt['status'] = 'active'
    fmt.pop('archived_reason', None)
    fmt['revived'] = {'at': int(time.time()), 'because': v['url'], 'views': v['views']}
    set_format(v, history, fmt['id'], judged=True)
    position = rerank(mkts, fmts, history, cfg).index(fmt['id']) + 1
    state.log({'type': 'format_revived', 'format': fmt['id'], 'video': v['id'], 'position': position})
    return position


def rerank(mkts, fmts, history, cfg, force=False):
    """One order for all markets (creators of all markets count the same); applied to every market's list.
    Hot formats (5+ confirmed viral videos in 7 days) come first, inside the "going viral" section."""
    ids, scores = rank.order(history, fmts, cfg)
    by_id = {f['id']: f for f in fmts}
    hot_ids = [i for i in ids if scores[i].get('recent_viral', 0) >= hot.MIN_VIRAL]
    for mk in mkts:
        page_ids = [page_of(by_id[i], mk['key']) for i in ids if page_of(by_id[i], mk['key'])]
        hot_count = sum(1 for i in hot_ids if page_of(by_id[i], mk['key']))
        entries, _ = notion.list_entries(mk['list_page'])
        current = [pid.replace('-', '') for _, pid in entries]
        if force or [p.replace('-', '') for p in page_ids] != current or notion.hot_entry_count(mk['list_page']) != hot_count:
            notion.set_order(mk['list_page'], page_ids, hot_count=hot_count, lang=mk['lang'])
    state.log({'type': 'rerank', 'order': ids})
    return ids


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
    """The TikTok inspiration video of a format (stored, or the 'Original auf TikTok' link on its DACH page)."""
    if fmt.get('source_video'):
        return fmt['source_video']
    for b in notion.children(fmt['page_id']):
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
    """Build the missing pages of active formats for one market from their inspiration videos, then sort the list."""
    cfg = load_config()
    mk = next(x for x in M.load({**cfg, 'markets': {k: {**v, 'enabled': True} for k, v in cfg['markets'].items()}}) if x['key'] == m)
    fmts, history = load_formats(), state.load('history.json', {})
    built = 0
    for f in [f for f in fmts if f.get('status') == 'active' and not page_of(f, m)]:
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
            pid, spec, problems = make_page(v, mk, cfg, None)
            if problems:
                print('draft only for', f['title'], problems)
                continue
            set_page(f, m, pid)
            built += 1
            state.save('formats.json', fmts)
            print('built', m, f['title'], '->', spec['page_title'])
        except Exception as e:
            print('build failed', f['title'], str(e)[:200])
    state.save('formats.json', fmts)
    rerank([mk], fmts, history, cfg)
    print(f'{m}: built {built} pages')


def localize_report(rep, only_changes=False):
    for r in rep:
        print(' | '.join(str(x) for x in r))
    flags = {'de': '🇩🇪', 'fr': '🇫🇷', 'es': '🇪🇸'}
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
        if v.get('verdict') in ('other_app', 'not_ugc') and h != 'jobstep.io':
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
    """Rebuild one market page (current layout, reworded script) from the given example video. -> (ok, reason)"""
    cfg = load_config()
    m = re.search(r'@([^/]+)/video/(\d+)', url)
    v = tiktok.video_detail(*m.groups()) if m else None
    if not v:
        return False, 'example video unavailable'
    page, spec, problems = make_page(v, mk, cfg, None, replace_page=page_of(fmt, mk['key']))
    if problems:
        return False, '; '.join(problems)[:150]
    fmt.setdefault('reworded', {})[mk['key']] = True
    return True, ''


def standardize(only=None):
    """Every active format page in every market in the current layout, without leftovers:
    - pages in the old layout (no example video or no resources section) are rebuilt from their example video
      (same-language strict example if there is one, else the format's original JobStep video) - reworded script;
    - duplicates are removed: a 2nd example video, repeated links/lines outside the script."""
    from . import audit as _audit, reword as _reword
    cfg, fmts = load_config(), load_formats()
    origs = _audit.originals()
    report = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in M.load(cfg):
            m = mk['key']
            pid = page_of(f, m)
            if not pid or (only and f['id'] not in only):
                continue
            try:
                blocks = notion.children(pid)
                has_video = any(b['type'] == 'video' for b in blocks)
                has_res = any(b['type'].startswith('heading') and re.search(r'🔧|RESSOURCE|RECURSOS', _plain_text(b), re.I) for b in blocks)
                if not (has_video and has_res):
                    ex = (f.get('inspo') or {}).get(m, {})
                    url = ex.get('url') if ex.get('strict') else origs.get(f['id']) or f.get('source_video')
                    h, vid = re.search(r'@([^/]+)/video/(\d+)', url).groups()
                    v = tiktok.video_detail(h, vid)
                    if not v:
                        report.append((f['title'], m, 'error', f'example video unavailable: {url}'))
                        continue
                    page, spec, problems = make_page(v, mk, cfg, None, replace_page=pid)
                    if problems:
                        report.append((f['title'], m, 'not rebuilt', '; '.join(problems)[:150]))
                        continue
                    f.setdefault('reworded', {})[m] = True
                    f.setdefault('inspo', {})[m] = {'url': url, 'views': v['views'], 'strict': bool(ex.get('strict')), 'rebuilt': True}
                    report.append((f['title'], m, 'rebuilt', url))
                    state.save('formats.json', fmts)
                    continue
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='fetch + detect only, no notifications, no writes')
    ap.add_argument('--only-detect', action='store_true', help='alerts but never build pages or re-rank')
    ap.add_argument('--test-notify', action='store_true', help='send one test notification and exit')
    ap.add_argument('--test-claude', action='store_true', help='check the Claude subscription token and exit')
    ap.add_argument('--test-discord', action='store_true', help='check the Discord webhooks WITHOUT posting')
    ap.add_argument('--edit-discord', default='', help='DACH message id: rewrite that hot announcement with the current text')
    ap.add_argument('--weekly', action='store_true', help='send the weekly Slack report now')
    ap.add_argument('--own-sync', action='store_true', help='catch up on our own creators (more video checks), then re-sort')
    ap.add_argument('--lineup', action='store_true', help='show the current form of every format and what Monday would take out (no changes)')
    ap.add_argument('--lineup-apply', action='store_true', help='take the badly performing formats out now')
    ap.add_argument('--accounts-sync', default='', help='JSON file: confirmed new/blocked accounts -> import, backfill, localize')
    ap.add_argument('--localize', action='store_true', help='inspiration videos in each market language (missing ones only)')
    ap.add_argument('--localize-recheck', action='store_true', help='strictly re-check every swapped inspiration video')
    ap.add_argument('--reword', action='store_true', help='reword all page scripts (similar, not 1:1) - writes to Notion')
    ap.add_argument('--reword-dry', action='store_true', help='show reworded scripts without writing')
    ap.add_argument('--audit', action='store_true', help='check every page (example video, script) and fix until it passes')
    ap.add_argument('--standardize', action='store_true', help='all pages in the current layout, duplicates removed')
    ap.add_argument('--relist', action='store_true', help='only re-draw the DE/FR/ES lists (order + going-viral section)')
    ap.add_argument('--check-hot', action='store_true', help='strict Claude check of ALL viral videos from the last 7 days')
    ap.add_argument('--init-market', default='', help='fr | es: connect a market to the shared format list')
    ap.add_argument('--fill-market', default='', help='fr | es: build missing pages of active formats')
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
    if a.own_sync:
        cfg, fmts = load_config(), load_formats()
        own_accounts, own_videos = own.load()
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
        cfg, fmts = load_config(), load_formats()
        rep = reword.run(fmts, M.load(cfg), cfg, page_of, dry=a.reword_dry)
        for t, m, status, why, changes in rep:
            print(f'== {t} | {m} | {status} {why}')
            for b, old, new, _ in changes[:30]:
                print('   OLD:', old[:300].replace('\n', ' '))
                print('   NEW:', new[:300].replace('\n', ' '))
        if not a.reword_dry:
            state.save('formats.json', fmts)
            ok = [r for r in rep if r[2] == 'ok']
            bad = [r for r in rep if r[2] != 'ok']
            notify.push('✍️ Scripts reworded (similar, not 1:1)', f"{len(ok)} pages reworded"
                        + (f"\nNot changed ({len(bad)}): " + '; '.join(f"{t} {m}: {why}" for t, m, _, why, _ in bad) if bad else ''))
        return
    if a.audit:
        cfg, fmts, meta = load_config(), load_formats(), state.load('meta.json', {})
        rep = audit.run(fmts, M.load(cfg), cfg, state.load('history.json', {}), state.load('accounts.json', {}), meta, page_of, rebuild=rebuild_page)
        state.save('formats.json', fmts)
        state.save('meta.json', meta)
        flags = {'de': '🇩🇪', 'fr': '🇫🇷', 'es': '🇪🇸'}
        bad = [r for r in rep if r[2] not in ('ok', 'fixed')]
        notify.push('✅ Page audit (example video + script)', f"{len(rep) - len(bad)}/{len(rep)} pages check out "
                    f"({sum(1 for r in rep if r[2] == 'fixed')} fixed now)."
                    + ('\n\nStill failing:\n' + '\n'.join(f"{flags[m]} {t} – {' / '.join(n)[:160]}" for t, m, _, n in bad) if bad else ''))
        return
    if a.standardize:
        standardize()
        return
    if a.relist:
        rerank(M.load(load_config()), load_formats(), state.load('history.json', {}), load_config(), force=True)
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
    run(dry_run=a.dry_run, only_detect=a.only_detect)


if __name__ == '__main__':
    main()
