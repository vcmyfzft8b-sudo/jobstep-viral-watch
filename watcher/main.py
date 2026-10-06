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
import shutil
import tempfile
import time
import traceback

from . import builder, classify, detect, discover, hot, llm, markets as M, media, notify, notion, rank, soniox, state, tiktok

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ALL_MARKETS = ('de', 'fr', 'es')


def load_config():
    with open(os.path.join(ROOT, 'config.json')) as f:
        cfg = json.load(f)
    if os.environ.get('NOTION_RADAR_PAGE'):
        cfg['notion']['radar_page'] = os.environ['NOTION_RADAR_PAGE']
    return cfg


def load_formats(m='de'):
    formats = state.load(M.formats_file(m), None)
    if formats is None:
        if m != 'de':
            return []
        with open(os.path.join(ROOT, 'registry', 'formats.json')) as f:
            formats = json.load(f)
    return formats


def save_formats(fmts):
    for m, formats in fmts.items():
        state.save(M.formats_file(m), formats)


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
             'german': v['handle'] in german, 'mature': now - v['created'] >= 7 * 86400}
    for m in ALL_MARKETS:
        fk, jk = M.fkey(m), M.jkey(m)
        entry[fk] = v.get(fk, old.get(fk))
        entry[jk] = bool(v.get(jk) or old.get(jk))
    if now - v['created'] <= 7.5 * 86400:
        entry['views_7d'] = v['views']
    elif 'views_7d' in old:
        entry['views_7d'] = old['views_7d']
    history[v['id']] = entry


def set_format(v, history, m, fid, judged=None):
    v[M.fkey(m)] = fid
    h = history.get(v['id'])
    if h is not None:
        h[M.fkey(m)] = fid
    if judged:
        v[M.jkey(m)] = True
        if h is not None:
            h[M.jkey(m)] = True


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
    fmts = {mk['key']: load_formats(mk['key']) for mk in mkts}
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
        except Exception as e:  # keep going with the other videos
            traceback.print_exc()
            notify.push('⚠️ JobStep watcher error', f"{v['url']}\n{str(e)[:300]}", click=v.get('url'))
            state.log({'type': 'error', 'video': vid, 'error': str(e)[:500]})
    if backlog and not dry_run:
        notify.push(f'📋 {len(backlog)} older "taking off" videos from newly added accounts',
                    'Last 7 days – details on the Notion radar page')

    if not dry_run:
        # Sort every video into each market's formats once it is 48h old, so the ranking sees hits AND flops.
        for mk in mkts:
            m = mk['key']
            ck = M.ckey(m)
            todo = [v for v in videos.values() if 'created' in v and not v.get(ck) and now - v['created'] >= 48 * 3600]
            if not todo or not fmts[m]:
                continue
            results = classify.classify_many(todo, fmts[m], cfg['models']['classify'])
            for v in todo:
                c = results.get(v['id'])
                if c:
                    set_format(v, history, m, c['match'])
                    v[ck] = True
                    v.setdefault('hook_en', c['hook_en'])
            print(f"{mk['T']['flag']} sorted {len(todo)} videos")

        # Viral videos not yet confirmed by the strict Claude check (e.g. older tags): re-check quietly.
        for v in [v for v in videos.values() if v.get('views', 0) >= th['viral_views'] and 'created' in v
                  and now - v['created'] <= cfg['watch_days'] * 86400
                  and any(not v.get(M.jkey(mk['key'])) for mk in mkts)][:5]:
            work = tempfile.mkdtemp(prefix='judge-')
            try:
                try:
                    transcript = soniox.transcribe(media.audio(media.download(v['url'], work), work)).get('text', '')
                except Exception:
                    transcript = v.get('subtitles', '')
                for mk in mkts:
                    m = mk['key']
                    if v.get(M.jkey(m)) or not fmts[m]:
                        continue
                    verdict = classify.judge(v, fmts[m], cfg['models']['build'], transcript, translate=False)
                    f = resolve(fmts[m], verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
                    set_format(v, history, m, f['id'] if f else None, judged=True)
                    print('re-judged', mk['T']['flag'], v['handle'], v['views'], '->', v.get(M.fkey(m)))
            except Exception as e:
                print('re-judge failed', v['id'], str(e)[:150])
            finally:
                shutil.rmtree(work, ignore_errors=True)

    # 5. per market: 🚀 hot spot + Discord, then sort the list (what goes viral right now first)
    if not only_detect:
        for mk in mkts:
            m, T = mk['key'], mk['T']
            if not fmts[m]:
                continue
            try:
                hot.update(history, videos, fmts[m], cfg, meta, mk, dry_run=dry_run)
            except Exception as e:
                print(T['flag'], 'hot update failed:', str(e)[:200])
            if dry_run:
                continue
            try:
                tkey = 'top3' if m == 'de' else f'top3_{m}'
                before_top = meta.get(tkey, [])
                ids = rerank(mk, fmts[m], history, cfg, account_info)
                meta[tkey] = ids[:3]
                if before_top and ids[:3] != before_top:
                    by = {f['id']: f for f in fmts[m]}
                    recent = rank.recent_viral(history, fmts[m], cfg, m)
                    notify.push(f"🔁 {T['flag']} New top of the {T['name']} list", '\n'.join(
                        f"{n}. {by[i]['title']} – {recent.get(i, 0)} viral in 7 days" for n, i in enumerate(ids[:5], 1)))
            except Exception as e:
                print(T['flag'], 're-sort failed:', str(e)[:200])

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

    if not dry_run:
        state.save('videos.json', videos)
        state.save('history.json', history)
        save_formats(fmts)
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
    first = mkts[0]['key']
    if not v.get(M.ckey(first)) and fmts[first]:
        c = classify.classify(v, fmts[first], cfg['models']['classify'])
        set_format(v, history, first, c.get('match'))
        v[M.ckey(first)], v['hook_en'] = True, c.get('hook_en', '')
    known = resolve(fmts[first], v.get(M.fkey(first)))
    age_h = (now - v['created']) / 3600
    fmt_text = (f"Probably format: {known['title']}" + ('' if known.get('status') == 'active' else ' (archive)')
                if known else f"Possibly new format: {v.get('hook_en') or '?'}")
    msg = (f"@{v['handle']} – {fmt_views(v['views'])} views after {age_h:.0f} h · shares+saves {detect.engagement(v):.1%}\n"
           f"{fmt_text}\n(Full check per market with script follows if it goes viral.)")
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


def handle_viral(v, mkts, fmts, history, cfg, now, only_detect, test=False):
    """Every viral video: download + Soniox transcript; per market Claude (Opus) judges it against ALL of that
    market's formats (list + archive); the first check also translates the script to English. Then per market:
    in the list -> report; in the archive -> bring back; new -> build the page in the market's language.
    One Slack message with link, English script and a line per market. If Claude fails, a basic message still goes
    out and the full check is retried next run."""
    age_h = (now - v['created']) / 3600
    eng = detect.engagement(v)
    eng_unknown = v.get('detail_missing') and not v.get('shares') and not v.get('saves')
    weak = (not eng_unknown) and eng < cfg['thresholds']['min_engagement']
    stats = (f"@{v['handle']} – *{fmt_views(v['views'])} views* after {age_h:.0f} h · shares+saves {eng:.1%}"
             f"{' (weak)' if weak else ''}{' (unknown)' if eng_unknown else ''}")
    title = ('🧪 TEST – ' if test else '') + '🟢 VIRAL: JobStep video'
    result = {'video': v['id'], 'level': 'viral', 'views': v['views'], 'markets': {}}
    work = tempfile.mkdtemp(prefix='viral-')
    try:
        video_file, note = None, ''
        try:
            video_file = media.download(v['url'], work)
            transcript = soniox.transcribe(media.audio(video_file, work))
        except Exception as e:
            note = f'\n_(video download/transcription failed: {str(e)[:80]} – judged from TikTok text)_'
            transcript = {'text': v.get('subtitles', ''), 'segments': [], 'language': ''}
        verdicts = {}
        try:
            for i, mk in enumerate(mkts):
                if fmts[mk['key']]:
                    verdicts[mk['key']] = classify.judge(v, fmts[mk['key']], cfg['models']['build'],
                                                         transcript.get('text', ''), translate=(i == 0))
        except Exception as e:
            if 'viral_basic' not in v['notified']:
                notify.push(title, f"{stats}\n⚠️ Claude check failed ({str(e)[:120]}) – the full check + English script "
                            'will follow in the next run (6 h).', click=v['url'])
                v['notified'].append('viral_basic')
            state.log({'type': 'judge_failed', 'video': v['id'], 'error': str(e)[:300]})
            result['error'] = str(e)[:200]
            return result

        prepared = {'work': work, 'video_file': video_file, 'transcript': transcript} if video_file else None
        lines = []
        for mk in mkts:
            m, T = mk['key'], mk['T']
            if m not in verdicts:
                continue
            verdict = verdicts[m]
            known = resolve(fmts[m], verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
            reason = ''
            if known:
                set_format(v, history, m, known['id'], judged=True)
                if known.get('status') == 'active':
                    pos = list_position(mk, known.get('page_id'))
                    outcome = f"✅ already in the list{f' (#{pos})' if pos else ''}: <{page_url(known['page_id'])}|{known['title']}>"
                elif weak or only_detect or not prepared:
                    outcome = f"📦 in the archive: {known['title']} – not brought back (" + \
                              ('weak engagement' if weak else 'only-detect mode' if only_detect else 'video unavailable') + ')'
                else:
                    pos = revive_format(known, v, mk, fmts[m], history, cfg, prepared=prepared)
                    outcome = f"♻️ was in the archive → *brought back as #{pos}*: <{page_url(known['page_id'])}|{known['title']}>"
            else:
                set_format(v, history, m, None, judged=True)
                if weak or only_detect or not prepared:
                    outcome = '🆕 *NEW format – not in Notion yet*, not added (' + \
                              ('weak engagement' if weak else 'only-detect mode' if only_detect else 'video unavailable') + ')'
                else:
                    page, problems, position = build_format(v, mk, fmts[m], history, cfg, prepared=prepared,
                                                            description=verdict.get('new_format_description', ''))
                    result['markets'][m] = {'built': page['url'], 'problems': problems, 'position': position}
                    outcome = (f"🆕 *NEW format → added as #{position}*: <{page['url']}|open page>" if not problems else
                               f"🆕 NEW format → draft to check ({'; '.join(problems)}): <{page['url']}|draft>")
            reason = verdict.get('reason', '')
            lines.append(f"{T['flag']} {outcome}" + (f"\n      _{reason}_" if reason else ''))
            result['markets'].setdefault(m, {})['format'] = v.get(M.fkey(m))
        first = next(iter(verdicts.values()), {})
        script = (first.get('english_script') or '').strip() or '(no speech / text found)'
        quoted = '\n'.join('> ' + line for line in script.splitlines() if line.strip())
        msg = (f"{stats}\n▶ <{v['url']}|Open video on TikTok>{note}\n\n*Format check (Claude) per market:*\n" + '\n'.join(lines) +
               f"\n\n*Script (English):*\n{quoted[:3500]}")
        notify.push(title, msg)
        notify.radar(cfg['notion']['radar_page'], f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🟢 VIRAL – "
                     f"@{v['handle']} {fmt_views(v['views'])} – " + ' | '.join(l.split('\n')[0] for l in lines),
                     link=v['url'], link_label='Video')
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


def refresh_page(fmt, v, mk, cfg, prepared=None):
    """Rebuild a format page in the current layout (market language) from a fresh viral video. Returns problems."""
    work, video_file, transcript, frames, own = _prepare(v, prepared)
    try:
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'], lang=mk['lang'])
        problems = builder.validate(spec, transcript, lang=mk['lang'])
        if problems:
            return problems
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        notion.replace_content(fmt['page_id'], notion.page_blocks(spec, v, upload_id, cfg['links'], lang=mk['lang'],
                                                                  lab_url=mk['visual_hook_lab']))
        fmt['script'] = ' '.join(seg.get('text', '') for seg in spec.get('script', []))[:900]
        return []
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def revive_format(fmt, v, mk, formats, history, cfg, prepared=None):
    """Move an archived format page back into the market's format folder, refresh it to the current layout with the
    new viral video, and put it into the list. Returns its position."""
    notion.move_page(fmt['page_id'], mk['holder_page'])
    try:
        problems = refresh_page(fmt, v, mk, cfg, prepared=prepared)
    except Exception as e:
        problems = [f'refresh failed: {str(e)[:150]}']
    if problems:
        notify.radar(cfg['notion']['radar_page'], f"{mk['T']['flag']} brought back, page not refreshed ({'; '.join(problems)}): "
                     f"{fmt['title']}", link=page_url(fmt['page_id']), link_label='Page')
    fmt['status'] = 'active'
    fmt.pop('archived_reason', None)
    fmt['revived'] = {'at': int(time.time()), 'because': v['url'], 'views': v['views']}
    set_format(v, history, mk['key'], fmt['id'], judged=True)
    position = rerank(mk, formats, history, cfg, state.load('accounts.json', {})).index(fmt['id']) + 1
    state.log({'type': 'format_revived', 'market': mk['key'], 'format': fmt['id'], 'video': v['id'], 'position': position})
    return position


def build_format(v, mk, formats, history, cfg, prepared=None, description=''):
    """Build a new format page in the market's language (current layout) and add it to that market's list.
    Returns (page, problems, position)."""
    m, T = mk['key'], mk['T']
    work, video_file, transcript, frames, own = _prepare(v, prepared)
    try:
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'], lang=mk['lang'])
        problems = builder.validate(spec, transcript, lang=mk['lang'])
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        blocks = notion.page_blocks(spec, v, upload_id, cfg['links'], lang=mk['lang'], lab_url=mk['visual_hook_lab'])
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)

    fid = m.upper() + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    entry = {'id': fid, 'title': spec['page_title'], 'description': spec.get('registry_description') or description,
             'script': ' '.join(seg.get('text', '') for seg in spec.get('script', []))[:900],
             'source_video': v['url'], 'created': int(time.time())}
    position = None
    if problems:
        page = notion.create_page(cfg['notion']['radar_page'], T['draft_prefix'] + spec['page_title'], spec.get('icon') or '📝', blocks)
        entry.update({'page_id': page['id'], 'status': 'draft', 'problems': problems})
    else:
        page = notion.create_page(mk['holder_page'], spec['page_title'], spec.get('icon') or '🎬', blocks)
        entry.update({'page_id': page['id'], 'status': 'active'})
    formats.append(entry)
    set_format(v, history, m, fid, judged=True)
    if not problems:
        position = rerank(mk, formats, history, cfg, state.load('accounts.json', {})).index(fid) + 1
    assets = spec.get('assets_needed') or []
    if assets:
        notify.push(f"📎 {T['flag']} New format needs a resource", f"{spec['page_title']}: " + ', '.join(a['name'] for a in assets),
                    click=page['url'])
    notify.radar(cfg['notion']['radar_page'], f"{T['flag']} " + (f"new format added as #{position}: " if not problems
                 else f"draft ({'; '.join(problems)}): ") + spec['page_title'], link=page['url'], link_label='Page')
    state.log({'type': 'format_built', 'market': m, 'format': fid, 'page': page['url'], 'problems': problems, 'position': position})
    return page, problems, position


def rerank(mk, formats, history, cfg, account_info):
    m = mk['key']
    ids, scores = rank.order(history, formats, cfg, m, local_accounts(account_info, cfg, mk['lang']))
    by_id = {f['id']: f for f in formats}
    page_ids = [by_id[i]['page_id'] for i in ids]
    current = [pid.replace('-', '') for _, pid in notion.list_entries(mk['list_page'])[0]]
    if [p.replace('-', '') for p in page_ids] != current:
        notion.set_order(mk['list_page'], page_ids)
    state.log({'type': 'rerank', 'market': m, 'order': ids})
    return ids


def check_hot():
    """Strict Claude check of every viral video (100k+) posted in the last 7 days, per market, then report."""
    cfg = load_config()
    mkts = M.load(cfg)
    fmts = {mk['key']: load_formats(mk['key']) for mk in mkts}
    videos, history = state.load('videos.json', {}), state.load('history.json', {})
    now = time.time()
    todo = [v for v in videos.values() if v.get('views', 0) >= cfg['thresholds']['viral_views']
            and 'created' in v and now - v['created'] <= cfg['watch_days'] * 86400]
    print(f'{len(todo)} viral videos from the last 7 days')
    for v in todo:
        if all(v.get(M.jkey(mk['key'])) for mk in mkts if fmts[mk['key']]):
            continue
        work = tempfile.mkdtemp(prefix='judge-')
        try:
            try:
                transcript = soniox.transcribe(media.audio(media.download(v['url'], work), work)).get('text', '')
            except Exception:
                transcript = v.get('subtitles', '')
            for mk in mkts:
                m = mk['key']
                if v.get(M.jkey(m)) or not fmts[m]:
                    continue
                verdict = classify.judge(v, fmts[m], cfg['models']['build'], transcript, translate=False)
                f = resolve(fmts[m], verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
                set_format(v, history, m, f['id'] if f else None, judged=True)
                v['hook_en'] = verdict.get('hook_en', v.get('hook_en', ''))
        except Exception as e:
            print('judge failed', v['id'], str(e)[:150])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    state.save('videos.json', videos)
    state.save('history.json', history)
    for mk in mkts:
        m = mk['key']
        by = {f['id']: f for f in fmts[m]}
        groups = {}
        for v in todo:
            groups.setdefault(v.get(M.fkey(m)) or 'NEW/none', []).append(v)
        print(f"\n{mk['T']['flag']} CONFIRMED VIRAL VIDEOS PER FORMAT (last 7 days):")
        for fid, vs in sorted(groups.items(), key=lambda x: -len(x[1])):
            f = by.get(fid)
            name = f['title'] + ('' if f.get('status') == 'active' else ' [archive]') if f else 'not in Notion'
            print(f'{len(vs)} | {fid} | {name}')
            for v in sorted(vs, key=lambda x: -x['views']):
                print(f"    {v['views']:>7} @{v['handle']:22} {v['url']}  | {v.get('hook_en', '')[:70]}")


def init_market(m):
    """Create a market's format registry from Notion: active formats (format folder) + archived formats (archive page).
    Claude writes a one-sentence description of each format for the duplicate check."""
    cfg = load_config()
    mk = cfg['markets'][m]
    pages = []
    for status, parent in (('active', mk['holder_page']), ('archived', mk['archive_page'])):
        for b in notion.children(parent):
            if b['type'] != 'child_page':
                continue
            texts = []
            for c in notion.children(b['id']):
                rt = c.get(c['type'], {}).get('rich_text')
                if rt:
                    texts.append(''.join(x['plain_text'] for x in rt))
            pages.append({'page_id': b['id'], 'title': b['child_page']['title'], 'status': status, 'text': ' '.join(texts)[:1500]})
    items = '\n'.join(f"{i}: TITLE {p['title']} | PAGE TEXT {p['text'][:900]}" for i, p in enumerate(pages))
    r = llm.chat_json(cfg['models']['build'], 'Reply JSON only.', f"""For each of these short-form video format pages
(CV-app UGC formats), write ONE English sentence describing the format's core premise/hook and structure, in the style
"<hook idea>: <what happens>. Examples: '<hook>'".
{items}
Return JSON {{"descriptions": {{"<index>": "<sentence>"}}}}""", timeout=1800)
    formats = []
    for i, p in enumerate(pages):
        prefix = 'X' if p['status'] == 'archived' else ''
        formats.append({'id': f"{m.upper()}{prefix}{i + 1:02d}", 'page_id': p['page_id'], 'title': p['title'],
                        'status': p['status'], 'description': r['descriptions'].get(str(i), p['title']),
                        'script': p['text'][:900]})
    state.save(M.formats_file(m), formats)
    print(f'{m}: {sum(f["status"] == "active" for f in formats)} active, {sum(f["status"] != "active" for f in formats)} archived')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='fetch + detect only, no notifications, no writes')
    ap.add_argument('--only-detect', action='store_true', help='alerts but never build pages or re-rank')
    ap.add_argument('--test-notify', action='store_true', help='send one test notification and exit')
    ap.add_argument('--test-claude', action='store_true', help='check the Claude subscription token and exit')
    ap.add_argument('--test-discord', action='store_true', help='check the Discord webhooks WITHOUT posting')
    ap.add_argument('--check-hot', action='store_true', help='strict Claude check of ALL viral videos from the last 7 days')
    ap.add_argument('--init-market', default='', help='fr | es: build the market format registry from Notion')
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
        return
    if a.init_market:
        init_market(a.init_market)
        return
    if a.check_hot:
        check_hot()
        return
    if a.test_viral:
        import re as _re
        handle, vid = _re.search(r'@([^/]+)/video/(\d+)', a.test_viral).groups()
        v = tiktok.video_detail(handle, vid)
        v.update({'notified': [], 'first_seen': int(time.time())})
        cfg = load_config()
        mkts = M.load(cfg)
        r = handle_viral(v, mkts, {mk['key']: load_formats(mk['key']) for mk in mkts}, state.load('history.json', {}), cfg,
                         time.time(), only_detect=True, test=True)
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
