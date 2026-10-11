"""All scripts as one Markdown file (mode export): every format (live, waiting, archived), every market page - title,
on-screen title, script with its cues, visual hook. The repo and its run logs are public, so the file is encrypted
with registry/export_cert.pem (the same certificate as the Memo AI watcher's export; the private key stays on the
user's Mac, ~/.config/memo-viral-watch/export_key.pem) and saved as state/scripts_export.enc. Read it locally with
scripts/read_export.sh.
"""
import os
import subprocess
import time

from . import notion, rank, state
from .markets import TEXT

CERT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'export_cert.pem')


def _rich(b):
    out = []
    for x in (b.get(b['type']) or {}).get('rich_text', []) or []:
        url = ((x.get('text') or {}).get('link') or {}).get('url')
        t = x.get('plain_text', '')
        bold = (x.get('annotations') or {}).get('bold')
        out.append(f'[{t}]' if url else (f'**{t}**' if bold and t.strip() else t))
    return ''.join(out).strip()


def page_text(pid):
    """Title, on-screen title, script and visual hook of one format page (sections by their emoji headings)."""
    sections, cur = {}, None
    for b in notion.children(pid):
        if b['type'].startswith('heading'):
            h = _rich(b)
            cur = ('title' if '📲' in h else 'script' if '💬' in h else 'hook' if ('🎬' in h or '👀' in h)
                   else 'res' if '🔧' in h else None)
            continue
        if b['type'] == 'divider':
            cur = None
            continue
        if cur and _rich(b):
            sections.setdefault(cur, []).append(_rich(b))
    return sections


def build(cfg, fmts, page_of):
    history = state.load('history.json', {})
    ids, _ = rank.order(history, fmts, cfg)
    active = [i for i in ids if any(f['id'] == i and f.get('status') == 'active' for f in fmts)]
    pos = {fid: n for n, fid in enumerate(active, 1)}
    order = {'active': 0, 'pending': 1, 'archived': 2}
    lines = [f"# Parakeet AI – all scripts ({time.strftime('%d.%m.%Y %H:%M', time.gmtime())} UTC)", '']
    for f in sorted(fmts, key=lambda f: (order.get(f.get('status'), 3), pos.get(f['id'], 999))):
        status = f.get('status')
        lines += [f"## {('#' + str(pos[f['id']]) + ' ') if f['id'] in pos else ''}{f['title']}  ({status})",
                  f"Original: {f.get('source_video', '-')}", '']
        if status == 'pending':
            lines += ['In the quality check: ' + '; '.join((f.get('pending') or {}).get('reasons', []))[:400], '']
        for key, m in cfg['markets'].items():
            pid = page_of(f, key)
            if not pid:
                continue
            T = TEXT[m['lang']]
            try:
                s = page_text(pid)
            except Exception as e:  # e.g. a page moved to the trash
                lines += [f"### {T['flag']} (page unreadable: {str(e)[:80]})", '']
                continue
            lines += [f"### {T['flag']} {T['name']} · https://app.notion.com/p/{pid.replace('-', '')}",
                      '**Title:** ' + ' / '.join(s.get('title', [])[:1]), '', '**Script:**'] + s.get('script', []) + \
                     ['', '**Visual hook:** ' + ' '.join(s.get('hook', [])[:1]), '']
    return '\n'.join(lines)


def run(cfg, fmts, page_of):
    text = build(cfg, fmts, page_of)
    out = os.path.join(state.DIR, 'scripts_export.enc')
    os.makedirs(state.DIR, exist_ok=True)
    subprocess.run(['openssl', 'smime', '-encrypt', '-binary', '-aes-256-cbc', '-outform', 'PEM', '-out', out, CERT],
                   input=text.encode(), check=True)
    print(f'export: {len(fmts)} formats, {len(text)} characters, encrypted to state/scripts_export.enc')
