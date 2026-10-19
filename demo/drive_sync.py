"""Puts the demo videos on the Parakeet Drive and checks them (rclone remote `gdrive`).

  python3 demo/drive_sync.py          upload what changed, tidy, then check everything
  python3 demo/drive_sync.py --check  only check

Layout: `Parakeet AI – Demo videos/<France|Spain|Slovenia>/`
  `<page title>/Parakeet AI demo – <iPhone|Android|Mac|Windows>.mp4`   the format's length (format_lengths.json)
  `_All lengths/Parakeet AI demo (<n> s) – <device>.mp4`             every length, for new formats

Files are replaced in place (same name, so links and sharing stay), one at a time with retries: Drive lists new
files late, and parallel copies once made duplicate folders and files. `rclone dedupe --dedupe-mode newest` runs
after every upload. Old files in `_All lengths` that no length uses any more go to the Drive trash.
The check compares every file's MD5 on Drive with the local video, its sharing (anyone with the link), duplicates
and extra files, and writes drive_folders.json and drive_links.md.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
FINAL = HERE / 'out' / 'final'
ROOT = 'Parakeet AI – Demo videos'
REMOTE = f'gdrive:{ROOT}'
MARKETS = {'fr': 'France', 'es': 'Spain', 'sl': 'Slovenia'}
DEVICES = ['iPhone', 'Android', 'Mac', 'Windows']


def rclone(*args, check=True):
    for attempt in range(5):
        r = subprocess.run(['rclone', '-q', *args], capture_output=True, text=True)
        if r.returncode == 0 or not check:
            return r
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"rclone {' '.join(args)}: {r.stderr.strip().splitlines()[-1:]}")


def md5(path):
    return hashlib.md5(pathlib.Path(path).read_bytes()).hexdigest()


def local(market, seconds, device):
    return FINAL / market / f'Parakeet AI demo ({seconds} s) – {device} ({market}).mp4'


def expected():
    """Drive path -> local file, for every file that should be there."""
    lengths = json.loads((HERE / 'format_lengths.json').read_text())['formats']
    pages = json.loads((HERE / 'drive_folders.json').read_text())['pages']
    all_seconds = sorted({f['demo_seconds'] for f in lengths.values()})
    want = {}
    for market in MARKETS.values():
        for s in all_seconds:
            for d in DEVICES:
                want[f'{market}/_All lengths/Parakeet AI demo ({s} s) – {d}.mp4'] = local(market, s, d)
    for p in pages:
        s = lengths[p['format']]['demo_seconds']
        rel = p['folder'].split('/', 1)[1]  # drop the root folder name
        for d in DEVICES:
            want[f'{rel}/Parakeet AI demo – {d}.mp4'] = local(rel.split('/')[0], s, d)
    return want, pages, lengths


def listing():
    r = rclone('lsjson', '-R', '--hash', '-M', '--drive-metadata-permissions', 'read', REMOTE)
    return json.loads(r.stdout)


def shared(item):
    perms = json.loads((item.get('Metadata') or {}).get('permissions') or '[]')
    return any(p.get('type') == 'anyone' for p in perms)


def upload(want):
    have = {i['Path']: i for i in listing() if not i['IsDir']}
    n = 0
    for dst, src in want.items():
        if not src.exists():
            raise SystemExit(f'missing local video: {src}')
        if (have.get(dst, {}).get('Hashes') or {}).get('md5') == md5(src):
            continue
        rclone('copyto', str(src), f'{REMOTE}/{dst}')
        n += 1
    print(f'uploaded {n} files')
    old = [p for p in have if '/_All lengths/' in p and p not in want]
    for p in old:
        rclone('deletefile', f'{REMOTE}/{p}')  # Drive moves it to the trash
    print(f'moved {len(old)} unused _All lengths files to the Drive trash')
    rclone('dedupe', '--dedupe-mode', 'newest', REMOTE)
    for i in listing():  # files dropped into a shared folder inherit its sharing; make sure anyway
        if not shared(i):
            rclone('link', f"{REMOTE}/{i['Path']}")


def check(want, pages, lengths):
    items = listing()
    paths = [i['Path'] for i in items]
    dups = sorted({p for p in paths if paths.count(p) > 1})
    files = {i['Path']: i for i in items if not i['IsDir']}
    dirs = {i['Path']: i for i in items if i['IsDir']}
    problems = [('duplicate', p) for p in dups]
    for dst, src in want.items():
        f = files.get(dst)
        if not f:
            problems.append(('missing', dst))
            continue
        if (f.get('Hashes') or {}).get('md5') != md5(src):
            problems.append(('different video', dst))
        if not shared(f):
            problems.append(('file not shared', dst))
    problems += [('extra file', p) for p in files if p not in want]
    problems += [('folder not shared', p) for p, d in dirs.items() if not shared(d)]
    print(f'Drive: {len(dirs)} folders, {len(files)} files, expected {len(want)} files – {len(problems)} problems')
    for p in problems[:30]:
        print('  ', *p)

    url = lambda i: f'https://drive.google.com/drive/folders/{i}'
    root_id = json.loads(rclone('lsjson', '--dirs-only', 'gdrive:').stdout)
    root_id = next(d['ID'] for d in root_id if d['Path'] == ROOT)
    out = {'checked': time.strftime('%Y-%m-%d %H:%M'), 'drive': 'rclone remote gdrive (Parakeet Drive, owner nace@parakeet-ai.com) – anyone with the link can view',
           'root': ROOT, 'root_url': url(root_id),
           'markets': {m: {'url': url(dirs[m]['ID']), 'all_lengths_url': url(dirs[f'{m}/_All lengths']['ID'])} for m in MARKETS.values()},
           'files': 'each format folder: Parakeet AI demo – iPhone|Android|Mac|Windows.mp4 in the format\'s demo_seconds',
           'pages': []}
    lines = ['# Parakeet AI demo videos – Drive links', '', f'All: {url(root_id)}', '']
    for m in MARKETS.values():
        lines += [f'## {m}', f"Market folder: {out['markets'][m]['url']}", f"All lengths: {out['markets'][m]['all_lengths_url']}", '']
        for p in pages:
            rel = p['folder'].split('/', 1)[1]
            if rel.split('/')[0] != m:
                continue
            f = lengths[p['format']]
            row = {k: p[k] for k in ('market', 'format', 'idea_id', 'page_title')}
            row.update({'example_app_seconds': f['app_seconds'], 'demo_seconds': f['demo_seconds'], 'folder': p['folder'],
                        'folder_id': dirs[rel]['ID'], 'url': url(dirs[rel]['ID'])})
            if p.get('note'):
                row['note'] = p['note']
            out['pages'].append(row)
            lines.append(f"- {p['page_title']} — {f['demo_seconds']} s (example: {f['app_seconds']} s): {row['url']}")
        lines.append('')
    (HERE / 'drive_folders.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    (HERE / 'drive_links.md').write_text('\n'.join(lines))
    return problems


if __name__ == '__main__':
    want, pages, lengths = expected()
    if '--check' not in sys.argv:
        upload(want)
        time.sleep(10)  # Drive lists fresh changes late
    sys.exit(1 if check(want, pages, lengths) else 0)
