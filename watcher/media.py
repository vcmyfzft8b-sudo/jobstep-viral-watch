"""Download a TikTok video and cut it into audio + frames."""
import glob
import os
import subprocess


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def download(url, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'video.mp4')
    _run(['yt-dlp', '-q', '--no-warnings', '-f', 'mp4/best', '-o', out, url])
    return out


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
