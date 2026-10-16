"""Manual test: build a format page for one video as an ARCHIVED Megasheet idea (creators never see it).
usage: python scripts/test_build.py <handle> <video_id> [fr|es|sl]
The idea is named '🧪 TEST – …' and sits in the market's staging place; delete it in Megasheet when done."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from watcher import builder, main, markets, media, pages, soniox, tiktok

handle, vid = sys.argv[1], sys.argv[2]
market = sys.argv[3] if len(sys.argv) > 3 else 'fr'
cfg = main.load_config()
mk = next(m for m in markets.load(cfg) if m['key'] == market)
lang = mk['lang']
v = tiktok.video_detail(handle, vid)
work = tempfile.mkdtemp(prefix='fmt-test-')
try:
    f = media.download(v['url'], work)
    print('downloaded', os.path.getsize(f) // 1024, 'KB')
    tr = soniox.transcribe(media.audio(f, work))
    print('transcript', tr['language'], len(tr['segments']), 'segments:', tr['text'][:200])
    frames = media.frames(f, work)
    print('frames', len(frames))
    spec = builder.build_spec(v, tr, frames, cfg['models']['build'], lang=lang)
    problems = builder.validate(spec, tr, lang=lang)
    print(json.dumps(spec, ensure_ascii=False, indent=1)[:4000])
    print('PROBLEMS:', problems)
    up = pages.upload_video(media.for_notion(f, work))
    spec = dict(spec, title_hook='🧪 TEST – ' + spec['title_hook'])
    page = pages.create_page(mk['staging_page'], spec['title_hook'], spec.get('icon') or '🧪',
                             pages.page_blocks(spec, v, up, cfg['links'], lang=lang,
                                               same_lang=(tr.get('language') or '')[:2] == lang))
    pages.STORE.finish()
    print('IDEA', market, page['id'], '(archived)')
    print(pages.summary())
finally:
    shutil.rmtree(work, ignore_errors=True)
