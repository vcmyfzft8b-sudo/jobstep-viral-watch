"""Our app demo recordings in the scripts (19 Oct 2026, user: "put those recordings into scripts, one link per script,
where they should start playing it" - Slovenia for now).

demo/drive_folders.json (written by demo/drive_sync.py) has one Drive folder per format page with the recording in its
length for iPhone, Android, Mac and Windows. A market whose texts have `demo_cue` (markets.TEXT, today only Slovenian)
gets ONE "(🎥 …)" link cue to that folder in every live script, right before the first Parakeet AI cue (where the app
appears first); tidy puts it there and keeps it there (also after a rebuild or re-transcription), verify checks it. How to
film it (download, full screen, laptop, phone overlay) is in the ⚠️ note (`demo_note`, pages.inspo_note).
"""
import json
import os

from . import pages
from .markets import TEXT

FILE = os.path.join(os.path.dirname(__file__), '..', 'demo', 'drive_folders.json')
FOLDER_PREFIX = 'https://drive.google.com/drive/folders/'
_cache = {}


def _folders():
    if 'pages' not in _cache:
        try:
            with open(FILE) as fh:
                _cache['pages'] = json.load(fh).get('pages') or []
        except FileNotFoundError:
            _cache['pages'] = []
    return _cache['pages']


def _idea(page_id):
    key = (page_id or '').replace('-', '').lower()
    with pages.LOCK:
        full = pages.STORE._full(key)
        return full, pages.STORE.state()['ideas'].get(full) or {}


def label(market):
    """The cue's label in this market (markets.TEXT keys are languages; fr/es/sl market = its language), or None when the
    market has no demo cues."""
    return (TEXT.get(market) or {}).get('demo_cue')


def cue_for(page_id, fmt_id=None, market=None):
    """(label, Drive folder url) for this page's demo cue; (label, None) when the market has cues but no folder fits;
    None when the market has no demo cues."""
    full, idea = _idea(page_id)
    market = market or idea.get('market')
    lab = label(market)
    if not lab:
        return None
    rows = [r for r in _folders() if r.get('market') == market]
    fmt_id = fmt_id or idea.get('format')
    row = next((r for r in rows if r.get('idea_id') == full), None) or \
        next((r for r in rows if fmt_id and r.get('format') == fmt_id), None)
    return lab, (row or {}).get('url')


def is_demo_url(url):
    return (url or '').startswith(FOLDER_PREFIX)
