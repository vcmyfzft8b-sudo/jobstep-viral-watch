"""One watcher run (every 6 hours on GitHub Actions).

1. Pull the latest videos of every JobStep account; new ones go on the watchlist (7 days).
2. Re-check every watchlist video (views, likes, shares, saves).
3. Alert on videos that are taking off / viral.
4. Viral + good engagement + format not on our instructions page yet -> build the German format page,
   add it to the DACH list at its ranked position, alert.
5. Weekly: re-rank the DACH list from the data, look for new JobStep accounts.
"""
import argparse
import datetime
import json
import os
import shutil
import tempfile
import time
import traceback

from . import builder, classify, detect, discover, hot, llm, media, notify, notion, rank, soniox, state, tiktok

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def load_config():
    with open(os.path.join(ROOT, 'config.json')) as f:
        cfg = json.load(f)
    # Notion page IDs can also come from the environment (repository variables).
    for key, env in (('holder_page', 'NOTION_HOLDER_PAGE'), ('radar_page', 'NOTION_RADAR_PAGE'), ('dach_page', 'NOTION_DACH_PAGE')):
        if os.environ.get(env):
            cfg['notion'][key] = os.environ[env]
    return cfg


def load_formats():
    formats = state.load('formats.json', None)
    if formats is None:
        with open(os.path.join(ROOT, 'registry', 'formats.json')) as f:
            formats = json.load(f)
    return formats


def fmt_views(n):
    return f'{n / 1000:.0f}k' if n >= 1000 else str(n)


def to_history(history, v, german, now):
    old = history.get(v['id'], {})
    entry = {'handle': v['handle'], 'created': v['created'], 'views': v['views'], 'format': v.get('format'),
             'hook': v.get('hook_en', ''), 'german': v['handle'] in german, 'mature': now - v['created'] >= 7 * 86400,
             'judged': bool(v.get('judged') or old.get('judged'))}
    # Views within the first 7 days after posting (what counts as "viral" for the ranking).
    if now - v['created'] <= 7.5 * 86400:
        entry['views_7d'] = v['views']
    elif 'views_7d' in old:
        entry['views_7d'] = old['views_7d']
    history[v['id']] = entry


def run(dry_run=False, only_detect=False):
    cfg = load_config()
    formats = load_formats()
    videos = state.load('videos.json', {})
    history = state.load('history.json', {})
    meta = state.load('meta.json', {})
    now = time.time()
    th = cfg['thresholds']
    account_info = state.load('accounts.json', None) or {h: {'status': 'manual', 'since': int(now)} for h in cfg['accounts']}
    german = {h for h, a in account_info.items() if a.get('lang') == 'de'} | set(cfg['german_accounts'])
    accounts = [h for h, a in account_info.items() if a['status'] in ('active', 'manual')]
    radar_page = cfg['notion']['radar_page']

    # 1. new videos
    fresh = 0
    embed_views = {}
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
            # Full page not reachable: use the creator embed's view count (likes/shares/saves keep their last value).
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
          f'views_only={sum(1 for x in videos.values() if x.get("detail_missing"))}')
    if tiktok.LAST_ERROR:
        reasons = {}
        for err in tiktok.LAST_ERROR.values():
            reasons[err] = reasons.get(err, 0) + 1
        print('fetch failure reasons:', reasons)

    # 3./4. alerts
    actions, backlog = [], []
    for vid, v in sorted(videos.items(), key=lambda x: -x[1].get('views', 0)):
        if 'created' not in v:
            continue
        lvl = detect.level(v, now, detect.creator_baseline(history, v['handle']), th)
        if not lvl or 'viral' in v['notified'] or (lvl == 'taking_off' and 'taking_off' in v['notified']):
            continue
        # Older "taking off" videos of a newly added account: one summary instead of one message each.
        # Viral videos always get their own full message.
        quiet = lvl == 'taking_off' and v.get('first_seen') == int(now) and now - v['created'] > 48 * 3600
        try:
            result = handle_alert(v, lvl, formats, history, cfg, now, dry_run, only_detect, quiet=quiet)
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
        viral = sum(1 for r in backlog if r['level'] == 'viral')
        notify.push(f'📋 {len(backlog)} older "taking off" videos from newly added accounts',
                    'Last 7 days – details on the Notion radar page', tags='clipboard')

    # Classify every video once it is 48h old (not only the viral ones), so the ranking sees hits AND flops.
    if not dry_run:
        todo = [v for v in videos.values()
                if 'created' in v and not v.get('format_checked') and now - v['created'] >= 48 * 3600]

        results = classify.classify_many(todo, formats, cfg['models']['classify'])
        for v in todo:
            c = results.get(v['id'])
            if c:
                v['format'], v['hook_en'], v['format_checked'] = c['match'], c['hook_en'], True
                history.get(v['id'], {}).update({'format': v['format'], 'hook': v['hook_en']})
        print(f'classified {len(todo)} videos')

    # Viral videos tagged before the strict Claude check existed: re-check them quietly (max 5 per run).
    if not dry_run:
        todo = [v for v in videos.values() if v.get('views', 0) >= th['viral_views'] and not v.get('judged')
                and 'created' in v and now - v['created'] <= cfg['watch_days'] * 86400][:5]
        for v in todo:
            work = tempfile.mkdtemp(prefix='judge-')
            try:
                try:
                    transcript = soniox.transcribe(media.audio(media.download(v['url'], work), work)).get('text', '')
                except Exception:
                    transcript = v.get('subtitles', '')
                verdict = classify.judge(v, formats, cfg['models']['build'], transcript)
                fmt = resolve(formats, verdict.get('duplicate_of')) if verdict.get('duplicate_of') else None
                v['format'], v['judged'] = (fmt['id'] if fmt else v.get('format')), True
                history.get(v['id'], {}).update({'format': v['format'], 'judged': True})
                print('re-judged', v['handle'], v['views'], '->', v['format'])
            except Exception as e:
                print('re-judge failed', v['id'], str(e)[:150])
            finally:
                shutil.rmtree(work, ignore_errors=True)

    # Hot formats (5+ viral videos in 7 days): 🚀 callout at the top + Discord announcement
    if not only_detect:
        try:
            hot.update(history, videos, formats, cfg, meta, dry_run=dry_run)
        except Exception as e:
            print('hot update failed:', str(e)[:200])

    # 5. weekly re-rank
    today = datetime.datetime.now(datetime.timezone.utc)
    week = today.strftime('%G-%V')
    if not dry_run and not only_detect and today.weekday() == cfg['ranking']['rerank_weekday'] and meta.get('reranked_week') != week:
        rerank(formats, history, cfg, reason='Wöchentliches Update')
        meta['reranked_week'] = week

    # 6. every few days: complete the JobStep account list (Lightreel) and pause/revive accounts
    if not dry_run and now - meta.get('discovered_at', 0) >= cfg['discovery_every_days'] * 86400:
        account_info, added, paused, revived = discover.refresh(account_info)
        for h in added:
            account_info[h]['lang'] = discover.language(h)
        meta['discovered_at'] = int(now)
        n_active = sum(1 for a in account_info.values() if a['status'] in ('active', 'manual'))
        summary = (f"{n_active} aktive JobStep-Accounts" + (f" · neu: {', '.join('@' + h for h in added)}" if added else '')
                   + (f" · pausiert: {', '.join('@' + h for h in paused)}" if paused else '')
                   + (f" · wieder aktiv: {', '.join('@' + h for h in revived)}" if revived else ''))
        print('discovery:', summary)
        if added:
            notify.push(f'🔎 {len(added)} neue JobStep-Accounts', summary, tags='mag')
        notify.radar(radar_page, f"{today:%d.%m.%Y} – Account-Check: {summary}")
        state.log({'type': 'discovery', 'added': added, 'paused': paused, 'revived': revived})

    if not dry_run:
        state.save('videos.json', videos)
        state.save('history.json', history)
        state.save('formats.json', formats)
        state.save('accounts.json', account_info)
        meta['last_run'] = int(now)
        state.save('meta.json', meta)
    print('actions:', json.dumps(actions, ensure_ascii=False))


def resolve(formats, fid):
    """Formats archived as duplicates point to the format they duplicate."""
    f = next((x for x in formats if x['id'] == fid), None)
    seen = set()
    while f and f.get('archived_reason', '').startswith('duplicate of ') and f['id'] not in seen:
        seen.add(f['id'])
        target = f['archived_reason'].split()[2]
        f = next((x for x in formats if x['id'] == target), f)
    return f


def handle_alert(v, lvl, formats, history, cfg, now, dry_run, only_detect, quiet=False):
    """Taking off: short message. Viral: see handle_viral."""
    if now - v['created'] > cfg['watch_days'] * 86400:  # never alert on old videos
        return {'video': v['id'], 'level': lvl, 'skipped': 'older than watch window'}
    if dry_run:
        print('DRY', lvl, v['handle'], v['views'], v.get('url'))
        return {'video': v['id'], 'level': lvl, 'views': v['views'], 'format': v.get('format')}
    if lvl == 'viral':
        return handle_viral(v, formats, history, cfg, now, only_detect)
    radar_page = cfg['notion']['radar_page']
    if not v.get('format_checked'):
        c = classify.classify(v, formats, cfg['models']['classify'])
        v['format'], v['hook_en'], v['format_checked'] = c.get('match'), c.get('hook_en', ''), True
        history.get(v['id'], {}).update({'format': v['format'], 'hook': v['hook_en']})
    known = resolve(formats, v['format'])
    age_h = (now - v['created']) / 3600
    fmt_text = (f"Probably format: {known['title']}" + ('' if known.get('status') == 'active' else ' (archive)')
                if known else f"Possibly new format: {v.get('hook_en') or '?'}")
    msg = (f"@{v['handle']} – {fmt_views(v['views'])} views after {age_h:.0f} h · shares+saves {detect.engagement(v):.1%}\n"
           f"{fmt_text}\n(Full check with script follows if it goes viral.)")
    if not quiet:
        notify.push('🟡 Taking off: JobStep video', msg, click=v['url'])
    notify.radar(radar_page, f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🟡 – {msg.replace(chr(10), ' – ')}",
                 link=v['url'], link_label='Video')
    result = {'video': v['id'], 'level': lvl, 'views': v['views'], 'format': v['format']}
    state.log({'type': 'alert', **result})
    return result


def list_position(cfg, page_id):
    ids = [pid.replace('-', '') for _, pid in notion.list_entries(cfg['notion']['dach_page'])[0]]
    pid = (page_id or '').replace('-', '')
    return ids.index(pid) + 1 if pid in ids else None


def handle_viral(v, formats, history, cfg, now, only_detect, test=False):
    """Every viral video: download + Soniox transcript, Claude (Opus) judges against ALL formats in Notion (list +
    archive) and translates the script to English. Then: already in the list -> report; in the archive -> bring
    it back; new -> build the page. One Slack message with link, verdict and English script.
    If anything fails, a basic Slack message still goes out and the full check is retried next run."""
    radar_page = cfg['notion']['radar_page']
    age_h = (now - v['created']) / 3600
    eng = detect.engagement(v)
    eng_unknown = v.get('detail_missing') and not v.get('shares') and not v.get('saves')
    weak = (not eng_unknown) and eng < cfg['thresholds']['min_engagement']
    stats = (f"@{v['handle']} – *{fmt_views(v['views'])} views* after {age_h:.0f} h · shares+saves {eng:.1%}"
             f"{' (weak)' if weak else ''}{' (unknown)' if eng_unknown else ''}")
    result = {'video': v['id'], 'level': 'viral', 'views': v['views']}
    work = tempfile.mkdtemp(prefix='viral-')
    try:
        video_file, note = None, ''
        try:
            video_file = media.download(v['url'], work)
            transcript = soniox.transcribe(media.audio(video_file, work))
        except Exception as e:
            note = f' (video download/transcription failed: {str(e)[:80]} – judged from TikTok text)'
            transcript = {'text': v.get('subtitles', ''), 'segments': [], 'language': ''}
        try:
            verdict = classify.judge(v, formats, cfg['models']['build'], transcript.get('text', ''))
        except Exception as e:
            if 'viral_basic' not in v['notified']:
                notify.push(('🧪 TEST – ' if test else '') + '🟢 VIRAL: JobStep video', f"{stats}\n⚠️ Claude check failed ({str(e)[:120]}) – "
                            'the full check + English script will follow in the next run (6 h).', click=v['url'])
                v['notified'].append('viral_basic')
            state.log({'type': 'judge_failed', 'video': v['id'], 'error': str(e)[:300]})
            result['error'] = str(e)[:200]
            return result

        dup = verdict.get('duplicate_of')
        known = resolve(formats, dup) if dup else None
        v['judged'] = True
        history.get(v['id'], {})['judged'] = True
        prepared = {'work': work, 'video_file': video_file, 'transcript': transcript} if video_file else None
        if known:
            v['format'] = known['id']
            history.get(v['id'], {})['format'] = known['id']
            if known.get('status') == 'active':
                pos = list_position(cfg, known.get('page_id'))
                outcome = (f"✅ *Already in Notion* – in the list{f' as #{pos}' if pos else ''}: "
                           f"<https://app.notion.com/p/{known['page_id'].replace('-', '')}|{known['title']}>")
            elif weak or only_detect or not prepared:
                outcome = f"📦 *Already in Notion* – in the archive: {known['title']} (not brought back: " + \
                          ('weak engagement' if weak else 'only-detect mode' if only_detect else 'video unavailable') + ')'
            else:
                pos = revive_format(known, v, formats, history, cfg, prepared=prepared)
                outcome = (f"♻️ *Was in the archive – brought back as #{pos}*: "
                           f"<https://app.notion.com/p/{known['page_id'].replace('-', '')}|{known['title']}>")
        else:
            if weak or only_detect or not prepared:
                outcome = '🆕 *NEW format – not in Notion yet*, not added (' + \
                          ('weak engagement' if weak else 'only-detect mode' if only_detect else 'video unavailable') + ')'
            else:
                page, problems, position = build_format(v, formats, history, cfg, prepared=prepared,
                                                        description=verdict.get('new_format_description', ''))
                result.update({'built': page['url'], 'problems': problems, 'position': position})
                outcome = (f"🆕 *NEW format – not in Notion yet → added as #{position}*: <{page['url']}|{page['url']}>"
                           if not problems else
                           f"🆕 *NEW format* → draft to check ({'; '.join(problems)}): <{page['url']}|draft>")
        result['format'] = v.get('format')
        script = (verdict.get('english_script') or '').strip() or '(no speech / text found)'
        quoted = '\n'.join('> ' + line for line in script.splitlines() if line.strip())
        msg = (f"{stats}\n▶ <{v['url']}|Open video on TikTok>\n\n"
               f"*Format check (Claude):* {outcome}\n_{verdict.get('reason', '')}_{note}\n\n"
               f"*Script (English):*\n{quoted[:3500]}")
        notify.push(('🧪 TEST – ' if test else '') + '🟢 VIRAL: JobStep video', msg)
        notify.radar(radar_page, f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – 🟢 VIRAL – @{v['handle']} "
                     f"{fmt_views(v['views'])} – {outcome}", link=v['url'], link_label='Video')
        v['notified'].append('viral')
        state.log({'type': 'alert', **result})
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _prepare(v, cfg, prepared):
    """Reuse an already downloaded video + transcript, or fetch them."""
    if prepared:
        return prepared['work'], prepared['video_file'], prepared['transcript'], False
    work = tempfile.mkdtemp(prefix='fmt-')
    video_file = media.download(v['url'], work)
    return work, video_file, soniox.transcribe(media.audio(video_file, work)), True


def refresh_page(fmt, v, cfg, prepared=None):
    """Rebuild a format page in the current layout from a fresh viral video. Returns problems (empty = done)."""
    work, video_file, transcript, own = _prepare(v, cfg, prepared)
    try:
        frames = media.frames(video_file, work)
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'])
        problems = builder.validate(spec, transcript)
        if problems:
            return problems
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        notion.replace_content(fmt['page_id'], notion.page_blocks(spec, v, upload_id, cfg['links']))
        fmt['script'] = ' '.join(seg.get('text', '') for seg in spec.get('script', []))[:900]
        return []
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def revive_format(fmt, v, formats, history, cfg, prepared=None):
    """Move an archived format page back into "Alle Formatseiten", refresh it to the current layout with the new
    viral video as inspiration, and put it into the ranked list. Returns its position."""
    notion.move_page(fmt['page_id'], cfg['notion']['holder_page'])
    try:
        problems = refresh_page(fmt, v, cfg, prepared=prepared)
    except Exception as e:
        problems = [f'refresh failed: {str(e)[:150]}']
    if problems:  # keep the old (working) page content, but note it
        notify.radar(cfg['notion']['radar_page'], f"Zurückgeholt, aber Seite nicht aktualisiert ({'; '.join(problems)}): {fmt['title']}",
                     link=f"https://app.notion.com/p/{fmt['page_id'].replace('-', '')}", link_label='Seite')
    fmt['status'] = 'active'
    fmt.pop('archived_reason', None)
    fmt['revived'] = {'at': int(time.time()), 'because': v['url'], 'views': v['views']}
    v['format'] = fmt['id']
    history.get(v['id'], {})['format'] = fmt['id']
    position = rerank(formats, history, cfg, reason=None).index(fmt['id']) + 1
    state.log({'type': 'format_revived', 'format': fmt['id'], 'video': v['id'], 'position': position})
    return position


def build_format(v, formats, history, cfg, prepared=None, description=''):
    """Build a new German format page (current layout) and add it to the list. Returns (page, problems, position)."""
    work, video_file, transcript, own = _prepare(v, cfg, prepared)
    try:
        frames = media.frames(video_file, work)
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'])
        problems = builder.validate(spec, transcript)
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        blocks = notion.page_blocks(spec, v, upload_id, cfg['links'])
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)

    fid = 'A' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    entry = {'id': fid, 'title': spec['page_title'], 'description': spec.get('registry_description') or description,
             'script': ' '.join(seg.get('text', '') for seg in spec.get('script', []))[:900],
             'source_video': v['url'], 'created': int(time.time())}
    position = None
    if problems:
        page = notion.create_page(cfg['notion']['radar_page'], 'ENTWURF – ' + spec['page_title'], spec.get('icon') or '📝', blocks)
        entry.update({'page_id': page['id'], 'status': 'draft', 'problems': problems})
    else:
        page = notion.create_page(cfg['notion']['holder_page'], spec['page_title'], spec.get('icon') or '🎬', blocks)
        entry.update({'page_id': page['id'], 'status': 'active'})
    formats.append(entry)
    v['format'] = fid
    history.get(v['id'], {})['format'] = fid
    if not problems:
        position = rerank(formats, history, cfg, reason=None).index(fid) + 1
    assets = spec.get('assets_needed') or []
    if assets:
        notify.push('📎 New format needs a resource', f"{spec['page_title']}: " + ', '.join(a['name'] for a in assets), click=page['url'])
    notify.radar(cfg['notion']['radar_page'], (f"Neues Format hinzugefügt auf Platz {position}: " if not problems
                 else f"Entwurf erstellt ({'; '.join(problems)}): ") + spec['page_title'], link=page['url'], link_label='Seite')
    state.log({'type': 'format_built', 'format': fid, 'page': page['url'], 'problems': problems, 'position': position})
    return page, problems, position


def rerank(formats, history, cfg, reason):
    ids, scores = rank.order(history, formats, cfg)
    by_id = {f['id']: f for f in formats}
    page_ids = [by_id[i]['page_id'] for i in ids]
    current = [pid.replace('-', '') for _, pid in notion.list_entries(cfg['notion']['dach_page'])[0]]
    if [p.replace('-', '') for p in page_ids] != current:
        notion.set_order(cfg['notion']['dach_page'], page_ids)
        if reason:
            lines = '\n'.join(f"{n}. {by_id[i]['title']}" for n, i in enumerate(ids, 1))
            notify.push('🔁 Formate neu sortiert', f'{reason}\n{lines}', tags='arrows_counterclockwise')
            notify.radar(cfg['notion']['radar_page'], f'{reason}: Reihenfolge geändert – ' + ' | '.join(by_id[i]['title'] for i in ids))
    state.log({'type': 'rerank', 'order': ids, 'scores': {k: round(v['score'], 4) for k, v in scores.items()}})
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='fetch + detect only, no notifications, no writes')
    ap.add_argument('--only-detect', action='store_true', help='alerts but never build pages or re-rank')
    ap.add_argument('--test-notify', action='store_true', help='send one test notification and exit')
    ap.add_argument('--test-claude', action='store_true', help='check the Claude subscription token and exit')
    ap.add_argument('--test-viral', default='', help='TikTok URL: send the full viral Slack message for it (no Notion changes)')
    a = ap.parse_args()
    if a.test_viral:
        import re as _re
        handle, vid = _re.search(r'@([^/]+)/video/(\d+)', a.test_viral).groups()
        v = tiktok.video_detail(handle, vid)
        v.update({'notified': [], 'first_seen': int(time.time())})
        cfg = load_config()
        r = handle_viral(v, load_formats(), state.load('history.json', {}), cfg, time.time(), only_detect=True, test=True)
        print('test viral result:', json.dumps(r, ensure_ascii=False))
        return
    if a.test_claude:
        import re as _re, subprocess as _sp
        tok = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', '')
        print('token length:', len(tok), '| starts with sk-ant-oat01-:', tok.startswith('sk-ant-oat01-'),
              '| contains whitespace/newline:', bool(_re.search(r'\s', tok)), '| ends with AA:', tok.endswith('AA'))
        try:
            print('claude says:', llm.chat('sonnet', 'Be brief.', 'Reply with exactly: OK'))
        except Exception as e:
            print('claude test failed:', str(e)[:300])
        return
    if a.test_notify:
        notify.push('✅ JobStep-Radar: GitHub → Slack funktioniert',
                    'Der Watcher läuft alle 6 Stunden und meldet sich hier, sobald ein JobStep-Video abhebt oder viral geht.',
                    click='https://github.com/vcmyfzft8b-sudo/jobstep-viral-watch/actions')
        print('test notification sent' + ('' if os.environ.get('SLACK_WEBHOOK_URL') else ' (no SLACK_WEBHOOK_URL set!)'))
        return
    missing = [k for k in ('NOTION_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN', 'SONIOX_API_KEY') if not os.environ.get(k)]
    if missing and not a.dry_run:
        # Without keys we can't notify or build: watch only and don't mark anything as notified.
        print('Missing secrets', missing, '-> running as dry run (run scripts/set_secrets.sh once)')
        a.dry_run = True
    run(dry_run=a.dry_run, only_detect=a.only_detect)


if __name__ == '__main__':
    main()
