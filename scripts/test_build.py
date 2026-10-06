"""Manual test: build a format page for one video into the PRIVATE radar page (never the public list).
usage: python scripts/test_build.py <handle> <video_id>"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from watcher import builder, main, media, notion, soniox, tiktok

handle, vid = sys.argv[1], sys.argv[2]
cfg = main.load_config()
v = tiktok.video_detail(handle, vid)
work = tempfile.mkdtemp(prefix='fmt-test-')
try:
    f = media.download(v['url'], work)
    print('downloaded', os.path.getsize(f) // 1024, 'KB')
    tr = soniox.transcribe(media.audio(f, work))
    print('transcript', tr['language'], len(tr['segments']), 'segments:', tr['text'][:200])
    frames = media.frames(f, work)
    print('frames', len(frames))
    spec = builder.build_spec(v, tr, frames, cfg['models']['build'])
    problems = builder.validate(spec, tr)
    print(json.dumps(spec, ensure_ascii=False, indent=1)[:4000])
    print('PROBLEMS:', problems)
    up = notion.upload_video(media.for_notion(f, work))
    page = notion.create_page(cfg['notion']['radar_page'], 'TEST – ' + spec['page_title'], spec.get('icon') or '🧪',
                              notion.page_blocks(spec, v, up, cfg['links']))
    print('PAGE', page['url'])
finally:
    shutil.rmtree(work, ignore_errors=True)
