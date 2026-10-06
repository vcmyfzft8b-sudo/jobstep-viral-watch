"""Speech-to-text with Soniox (SONIOX_API_KEY): async transcription with language detection + timestamps."""
import os
import time

import requests

BASE = 'https://api.soniox.com/v1'


def _session():
    s = requests.Session()
    s.headers['Authorization'] = 'Bearer ' + os.environ['SONIOX_API_KEY']
    return s


def _api(s, method, path, **kw):
    r = s.request(method, BASE + path, timeout=120, **kw)
    if not r.ok:
        raise RuntimeError(f'Soniox {method} {path}: HTTP {r.status_code} {r.text[:300]}')
    return r.json() if r.content else {}


def transcribe(audio_path):
    """Returns {'language': 'sr', 'segments': [{'start': s, 'end': s, 'text': '...'}], 'text': '...'}."""
    s = _session()
    with open(audio_path, 'rb') as f:
        up = _api(s, 'POST', '/files', files={'file': (os.path.basename(audio_path), f, 'audio/flac')})
    job = _api(s, 'POST', '/transcriptions', json={'model': 'stt-async-v5', 'file_id': up['id'],
                                                  'enable_language_identification': True})
    try:
        for _ in range(200):
            st = _api(s, 'GET', '/transcriptions/' + job['id'])
            if st['status'] == 'completed':
                break
            if st['status'] == 'error':
                raise RuntimeError('Soniox error: ' + str(st.get('error_message')))
            time.sleep(3)
        else:
            raise RuntimeError('Soniox timeout')
        tokens = _api(s, 'GET', f"/transcriptions/{job['id']}/transcript").get('tokens', [])
    finally:
        # Don't leave files/transcripts stored at Soniox.
        for path in (f"/transcriptions/{job['id']}", f"/files/{up['id']}"):
            try:
                s.delete(BASE + path, timeout=30)
            except requests.RequestException:
                pass
    return _segments(tokens)


def _segments(tokens):
    segs, cur, langs = [], None, {}
    for t in tokens:
        text = t.get('text', '')
        if not text:
            continue
        if t.get('language'):
            langs[t['language']] = langs.get(t['language'], 0) + 1
        start, end = t.get('start_ms', 0) / 1000, t.get('end_ms', 0) / 1000
        if cur is None:
            cur = {'start': start, 'end': end, 'text': ''}
        cur['text'] += text
        cur['end'] = end
        if text.strip().endswith(('.', '?', '!')) or (cur['end'] - cur['start'] > 6 and text.startswith(' ')):
            cur['text'] = cur['text'].strip()
            segs.append(cur)
            cur = None
    if cur and cur['text'].strip():
        cur['text'] = cur['text'].strip()
        segs.append(cur)
    lang = max(langs, key=langs.get) if langs else ''
    return {'language': lang, 'segments': segs, 'text': ' '.join(x['text'] for x in segs)}
