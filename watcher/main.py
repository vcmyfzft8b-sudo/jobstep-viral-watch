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

from . import builder, classify, detect, discover, media, notify, notion, rank, soniox, state, tiktok

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
    history[v['id']] = {'handle': v['handle'], 'created': v['created'], 'views': v['views'], 'format': v.get('format'),
                        'hook': v.get('hook_en', ''), 'german': v['handle'] in german,
                        'mature': now - v['created'] >= 7 * 86400}


def run(dry_run=False, only_detect=False):
    cfg = load_config()
    formats = load_formats()
    videos = state.load('videos.json', {})
    history = state.load('history.json', {})
    meta = state.load('meta.json', {})
    now = time.time()
    th = cfg['thresholds']
    german = set(cfg['german_accounts'])
    accounts = list(dict.fromkeys(cfg['accounts'] + meta.get('discovered_accounts', [])))
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
    actions = []
    for vid, v in sorted(videos.items(), key=lambda x: -x[1].get('views', 0)):
        if 'created' not in v:
            continue
        lvl = detect.level(v, now, detect.creator_baseline(history, v['handle']), th)
        if not lvl or lvl in v['notified'] or ('viral' in v['notified']):
            continue
        try:
            actions.append(handle_alert(v, lvl, formats, history, cfg, now, dry_run, only_detect))
            v['notified'].append(lvl)
        except Exception as e:  # keep going with the other videos
            traceback.print_exc()
            notify.push('⚠️ JobStep-Watcher Fehler', f"{v['url']}\n{str(e)[:300]}", click=v.get('url'), tags='warning')
            state.log({'type': 'error', 'video': vid, 'error': str(e)[:500]})

    # Classify every video once it is 48h old (not only the viral ones), so the ranking sees hits AND flops.
    if not dry_run:
        for v in videos.values():
            if 'created' in v and not v.get('format_checked') and now - v['created'] >= 48 * 3600:
                try:
                    c = classify.classify(v, formats, cfg['models']['classify'])
                    v['format'], v['hook_en'], v['format_checked'] = c.get('match'), c.get('hook_en', ''), True
                    history.get(v['id'], {}).update({'format': v['format'], 'hook': v['hook_en']})
                except Exception as e:
                    print('classify failed', v['id'], str(e)[:200])

    # 5. weekly re-rank + account discovery
    today = datetime.datetime.now(datetime.timezone.utc)
    week = today.strftime('%G-%V')
    if not dry_run and not only_detect and today.weekday() == cfg['ranking']['rerank_weekday'] and meta.get('reranked_week') != week:
        rerank(formats, history, cfg, reason='Wöchentliches Update')
        meta['reranked_week'] = week
        new_accounts = discover.find_accounts(accounts)
        if new_accounts:
            meta.setdefault('discovered_accounts', []).extend(new_accounts)
            notify.push('🔎 Neue JobStep-Accounts', ', '.join('@' + h for h in new_accounts), tags='mag')
            notify.radar(radar_page, f"{today:%d.%m.%Y} – neue JobStep-Accounts beobachtet: " + ', '.join('@' + h for h in new_accounts))

    if not dry_run:
        state.save('videos.json', videos)
        state.save('history.json', history)
        state.save('formats.json', formats)
        meta['last_run'] = int(now)
        state.save('meta.json', meta)
    print('actions:', json.dumps(actions, ensure_ascii=False))


def handle_alert(v, lvl, formats, history, cfg, now, dry_run, only_detect):
    radar_page = cfg['notion']['radar_page']
    age_h = (now - v['created']) / 3600
    eng = detect.engagement(v)
    if not v.get('format_checked'):
        c = classify.classify(v, formats, cfg['models']['classify'])
        v['format'], v['hook_en'], v['format_checked'] = c.get('match'), c.get('hook_en', ''), True
        v['new_format_description'] = c.get('new_format_description', '')
        history.get(v['id'], {}).update({'format': v['format'], 'hook': v['hook_en']})
    known = next((f for f in formats if f['id'] == v['format']), None)
    eng_unknown = v.get('detail_missing') and not v.get('shares') and not v.get('saves')
    weak = (not eng_unknown) and eng < cfg['thresholds']['min_engagement']
    head = '🟢 VIRAL' if lvl == 'viral' else '🟡 Hebt ab'
    fmt_text = (f"Format: {known['title']}" if known and known.get('status') == 'active'
                else f"Neues Format: {v.get('hook_en') or '?'}")
    msg = (f"@{v['handle']} – {fmt_views(v['views'])} Aufrufe nach {age_h:.0f} h · Shares+Saves {eng:.1%}"
           f"{' (schwach)' if weak else ''}{' (Shares/Saves unbekannt)' if eng_unknown else ''}\n{fmt_text}")
    result = {'video': v['id'], 'level': lvl, 'views': v['views'], 'format': v['format']}
    if dry_run:
        print('DRY', head, msg)
        return result
    notify.push(f'{head}: JobStep-Video', msg, click=v['url'], tags='chart_with_upwards_trend')
    notify.radar(radar_page, f"{datetime.datetime.now(datetime.timezone.utc):%d.%m.%Y %H:%M} – {head} – {msg.replace(chr(10), ' – ')}",
                 link=v['url'], link_label='Video')
    state.log({'type': 'alert', **result})

    if lvl == 'viral' and not known and not weak and not only_detect:
        page, problems, position = build_format(v, formats, history, cfg)
        result.update({'built': page['url'], 'problems': problems, 'position': position})
    return result


def build_format(v, formats, history, cfg):
    work = tempfile.mkdtemp(prefix='fmt-')
    try:
        video_file = media.download(v['url'], work)
        transcript = soniox.transcribe(media.audio(video_file, work))
        frames = media.frames(video_file, work)
        spec = builder.build_spec(v, transcript, frames, cfg['models']['build'])
        problems = builder.validate(spec, transcript)
        upload_id = notion.upload_video(media.for_notion(video_file, work))
        blocks = notion.page_blocks(spec, v, upload_id, cfg['links'])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    fid = 'A' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M')
    entry = {'id': fid, 'title': spec['page_title'], 'description': spec.get('registry_description') or v.get('new_format_description', ''),
             'source_video': v['url'], 'created': int(time.time())}
    position = None
    if problems:
        page = notion.create_page(cfg['notion']['radar_page'], 'ENTWURF – ' + spec['page_title'], spec.get('icon') or '📝', blocks)
        entry.update({'page_id': page['id'], 'status': 'draft', 'problems': problems})
        formats.append(entry)
        v['format'] = fid
        history[v['id']]['format'] = fid
        notify.push('📝 Neues Format als Entwurf', f"{spec['page_title']}\nBitte prüfen: " + '; '.join(problems), click=page['url'], tags='memo')
        notify.radar(cfg['notion']['radar_page'], f"Entwurf erstellt (nicht veröffentlicht): {spec['page_title']} – " + '; '.join(problems),
                     link=page['url'], link_label='Entwurf')
    else:
        page = notion.create_page(cfg['notion']['holder_page'], spec['page_title'], spec.get('icon') or '🎬', blocks)
        entry.update({'page_id': page['id'], 'status': 'active'})
        formats.append(entry)
        v['format'] = fid
        history[v['id']]['format'] = fid
        position = rerank(formats, history, cfg, reason=None).index(fid) + 1
        assets = spec.get('assets_needed') or []
        extra = ('\nNoch zu erstellen: ' + ', '.join(a['name'] for a in assets)) if assets else ''
        notify.push(f'✅ Neues Format auf Platz {position}', f"{spec['page_title']}\nVorbild: @{v['handle']}, {fmt_views(v['views'])} Aufrufe{extra}",
                    click=page['url'], tags='white_check_mark')
        notify.radar(cfg['notion']['radar_page'], f"Neues Format hinzugefügt auf Platz {position}: {spec['page_title']}{extra}",
                     link=page['url'], link_label='Seite')
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
    a = ap.parse_args()
    missing = [k for k in ('NOTION_TOKEN', 'OPENROUTER_API_KEY', 'SONIOX_API_KEY') if not os.environ.get(k)]
    if missing and not a.dry_run:
        # Without keys we can't notify or build: watch only and don't mark anything as notified.
        print('Missing secrets', missing, '-> running as dry run (run scripts/set_secrets.sh once)')
        a.dry_run = True
    run(dry_run=a.dry_run, only_detect=a.only_detect)


if __name__ == '__main__':
    main()
