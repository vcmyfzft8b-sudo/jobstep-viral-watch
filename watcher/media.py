"""Download a TikTok video and cut it into audio + frames."""
import glob
import os
import re
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'{cmd[0]} failed: {(r.stderr or r.stdout).strip()[-400:]}')


def download(url, out_dir):
    """1) straight from the TikTok page data, 2) yt-dlp, 3) yt-dlp through the European route."""
    from . import tiktok
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'video.mp4')
    m = re.search(r'@([^/]+)/video/(\d+)', url)
    if m and tiktok.download(m.group(1), m.group(2), out):
        return out
    cmd = ['yt-dlp', '-q', '--no-warnings', '-f', 'mp4/best', '-o', out, url]
    errors = []
    for extra in ([], ['--proxy', os.environ['TIKTOK_PROXY']] if os.environ.get('TIKTOK_PROXY') else None):
        if extra is None:
            continue
        try:
            _run(cmd[:1] + extra + cmd[1:])
            return out
        except RuntimeError as e:
            errors.append(str(e))
    raise RuntimeError('video download failed: ' + ' | '.join(errors))


def duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)


def audio(video, out_dir):
    out = os.path.join(out_dir, 'audio.flac')
    _run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-vn', '-ac', '1', '-ar', '16000', out])
    return out


def frames(video, out_dir, max_frames=48):
    """Dense frames for the first 3 s (visual hook) + one frame per second (or fewer for long videos).
    Returns [(seconds, path)]."""
    fdir = os.path.join(out_dir, 'frames')
    os.makedirs(fdir, exist_ok=True)
    dur = duration(video)
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    step = max(1.0, dur / max(1, max_frames - len(times)))
    t = 4.0
    while t < dur:
        times.append(round(t, 1))
        t += step
    result = []
    for i, t in enumerate(times):
        p = os.path.join(fdir, f'{i:03d}.jpg')
        _run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', '-vf', 'scale=360:-2', '-q:v', '5', p])
        if os.path.exists(p):
            result.append((t, p))
    return result


def for_notion(video, out_dir, max_mb=19):
    """Notion single-part uploads are limited to 20 MB: re-encode if needed."""
    if os.path.getsize(video) <= max_mb * 1024 * 1024:
        return video
    dur = max(duration(video), 1)
    kbps = int(max_mb * 8 * 1024 * 0.9 / dur) - 96
    out = os.path.join(out_dir, 'video-notion.mp4')
    _run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-c:v', 'libx264', '-b:v', f'{max(kbps, 300)}k',
          '-vf', "scale='min(720,iw)':-2", '-c:a', 'aac', '-b:a', '96k', out])
    return out


def cleanup(out_dir):
    for p in glob.glob(os.path.join(out_dir, '**', '*'), recursive=True):
        if os.path.isfile(p):
            os.remove(p)


def contact_sheets(frames, out_dir, per_sheet=12, cols=4):
    """Combine frames into a few labelled sheets (timestamp on each tile) so Claude reads 3-4 images, not 45.
    Returns [(first_second, last_second, path)]."""
    from PIL import Image, ImageDraw, ImageFont
    sheets = []
    font = ImageFont.load_default(size=28)
    for i in range(0, len(frames), per_sheet):
        chunk = frames[i:i + per_sheet]
        tiles = [Image.open(p).convert('RGB') for _, p in chunk]
        w = max(t.width for t in tiles)
        h = max(t.height for t in tiles)
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * w, rows * (h + 40)), 'white')
        draw = ImageDraw.Draw(sheet)
        for k, ((t, _), tile) in enumerate(zip(chunk, tiles)):
            x, y = (k % cols) * w, (k // cols) * (h + 40)
            draw.text((x + 8, y + 4), f'{t:.1f}s', fill='red', font=font)
            sheet.paste(tile, (x, y + 40))
        path = os.path.join(out_dir, f'sheet_{i // per_sheet:02d}.jpg')
        sheet.save(path, quality=80)
        sheets.append((chunk[0][0], chunk[-1][0], path))
    return sheets
