"""When does Parakeet AI come in? (mode timing, read-only - user's question, 13 Oct 2026)

For every live page, in list order: the second the app is first SHOWN (first Parakeet AI link cue) and the second
"Parakeet AI" is first SAID, in the page's example video. The example is transcribed with timestamps (Soniox); a
script position is mapped to the example's timeline by its share of the words (the script is the example's own words,
so this is close - about +-1-2 s). When the example itself names the app (JobStep, or Parakeet AI in our creators'
videos), that exact moment is used for "said". Silent videos: share of the video's length.
"""
import re
import shutil
import tempfile

from . import media, pages, reword, soniox
from .brands import SOURCE_RE
from .localize import current_source


def _words(t):
    return re.findall(r'\w+', t or '')


def script_positions(page_id, parakeet_url):
    """(words before the first Parakeet AI cue, words before the first spoken 'Parakeet', total words)."""
    n, shown, said = 0, None, None
    for b in reword.script_blocks(page_id):
        for x in b[b['type']].get('rich_text', []):
            url = ((x.get('text') or {}).get('link') or {}).get('url')
            if url:
                if url == parakeet_url and shown is None:
                    shown = n
                continue
            t = re.sub(r'\([^)]*\)', ' ', x.get('plain_text', ''))
            if said is None and re.search(r'parakeet', t, re.I):
                said = n + len(_words(t[:re.search(r'parakeet', t, re.I).start()]))
            n += len(_words(t))
    return shown, said, n


def _at_share(segments, share):
    """Second in the example at this share of its spoken words."""
    counts = [len(_words(s['text'])) for s in segments]
    total = sum(counts) or 1
    target, seen = share * total, 0
    for s, c in zip(segments, counts):
        if seen + c >= target and c:
            return s['start'] + (s['end'] - s['start']) * (target - seen) / c
        seen += c
    return segments[-1]['end'] if segments else None


def _brand_said(segments, own):
    """Exact second the example itself names the app (JobStep, or Parakeet AI in our own videos)."""
    pat = re.compile(r'parakeet', re.I) if own else SOURCE_RE
    for s in segments:
        m = pat.search(s['text'])
        if m:
            return s['start'] + (s['end'] - s['start']) * m.start() / max(len(s['text']), 1)
    return None


def _duration(video):
    import subprocess
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def page_timing(page_id, links, cache):
    src = (current_source(page_id) or {}).get('url')
    if not src:
        return {'error': 'no example video link'}
    if src not in cache:
        work = tempfile.mkdtemp(prefix='timing-')
        try:
            video = media.download(src, work)
            cache[src] = {'segments': soniox.transcribe(media.audio(video, work)).get('segments', []),
                          'duration': _duration(video)}
        except Exception as e:
            cache[src] = {'error': str(e)[:120]}
        finally:
            shutil.rmtree(work, ignore_errors=True)
    ex = cache[src]
    if ex.get('error'):
        return {'error': ex['error']}
    segs = ex['segments']
    shown, said, total = script_positions(page_id, links['parakeet'])
    spoken = sum(len(_words(s['text'])) for s in segs) >= 15
    dur = ex.get('duration') or (segs[-1]['end'] if segs else None)

    def at(pos):
        if pos is None or not total:
            return None
        share = pos / total
        return _at_share(segs, share) if spoken else (share * dur if dur else None)
    from .localize import is_own_url
    exact = _brand_said(segs, is_own_url(src)) if spoken else None
    return {'shown': at(shown), 'said': exact if (exact is not None and said is not None) else at(said),
            'duration': dur, 'silent': not spoken, 'example': src}


def run(cfg, mkts, fmts, page_of):
    by_page = {(page_of(f, mk['key']) or '').replace('-', ''): f for f in fmts for mk in mkts}
    cache, rows = {}, []
    for mk in mkts:
        entries, _ = pages.list_entries(mk['list_page'])
        for n, (_, pid) in enumerate(entries, 1):
            f = by_page.get(pid.replace('-', ''))
            try:
                r = page_timing(pid, cfg['links'], cache)
            except Exception as e:
                r = {'error': str(e)[:120]}
            s = lambda v: f'{v:.0f}s' if isinstance(v, (int, float)) else '-'
            from .tidy import page_name
            line = (f"TIMING | {mk['T']['flag']} | {page_name(pid)[:60]} | "
                    + (f"error: {r['error']}" if r.get('error') else
                       f"shown {s(r['shown'])} | said {s(r['said'])} | video {s(r['duration'])}"
                       + (' | silent video (estimate)' if r['silent'] else '')))
            print(line, flush=True)
            rows.append(line)
    return rows
