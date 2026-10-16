"""Formats in Megasheet (16 Oct 2026): creators read their format list in the Megasheet portal, not in Notion.

Notion stays the place where the watcher builds, checks, tidies and orders the format pages. After every workflow run
(`python -m watcher.megasheet_formats`, its own workflow step) each running market's Notion list is copied into its
Megasheet campaign (megasheet.CAMPAIGNS):
- one Megasheet idea per format page on the list, in the list's order; the going-viral formats (red card) come first
  and start with the market's bold hot_header line;
- title, script, visual hook, the ⚠️ note, the resources (TikTok original, Parakeet AI links) and the example video
  come from the page. Every run compares the idea with the page and only sends what differs (also hand edits made in
  Megasheet are put back to the page's text - Notion is the source);
- a format that leaves the list is archived in Megasheet (never deleted) and published again when it comes back;
- ideas made by hand in Megasheet are left alone (they stay after ours). On the first copy of a campaign, ideas with
  the same title are taken over (the one-time import of 15 Oct 2026) and the other published ones are archived.

State (public state branch - ids only): state/megasheet_formats.json
  {market: {page_id: {idea, media_key, media_ids, keep_titles}}, '_adopted': [markets], '_warned': ts}
Needs a Megasheet login with write access (scripts/save_megasheet_login.sh); without it the step only says so.
"""
import argparse
import json
import os
import re
import time
import unicodedata

import requests

from . import markets as M, megasheet, notion, notify, state

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
STATE_FILE = 'megasheet_formats.json'
MARKET_CAMPAIGN = {m: name for name, m in megasheet.CAMPAIGNS.items()}


# --- Notion page -> idea fields -----------------------------------------------------------------------------------

def _plain(rich):
    return ''.join(x.get('plain_text') or (x.get('text') or {}).get('content', '') for x in rich or [])


def md(rich):
    """Notion rich text -> Megasheet markdown (**bold**, [label](url)); spaces stay outside the markers."""
    out = []
    for x in rich or []:
        t = x.get('plain_text') or (x.get('text') or {}).get('content', '')
        core = t.strip()
        if not core:
            out.append(t)
            continue
        lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
        href = x.get('href') or (((x.get('text') or {}).get('link')) or {}).get('url')
        if href:
            core = f'[{core}]({href})'
        if (x.get('annotations') or {}).get('bold'):
            core = f'**{core}**'
        out.append(lead + core + trail)
    return ''.join(out)


def _paras(text):
    """Notion line breaks inside one block -> separate markdown paragraphs (one line break shows as a space)."""
    return [p.strip() for p in text.split('\n') if p.strip()]


def _links(rich):
    return [(_plain([x]).strip(), x.get('href') or (((x.get('text') or {}).get('link')) or {}).get('url'))
            for x in rich or [] if x.get('href') or ((x.get('text') or {}).get('link'))]


def _file_url(b):
    body = b.get(b['type']) or {}
    if body.get('type') == 'file':
        return body['file']['url']
    if body.get('type') == 'external':
        return body['external']['url']
    return None


SECTIONS = (('title_h', 'title'), ('script_h', 'script'), ('hook_h', 'hook'), ('res_h', 'res'))


def read_page(page_id, T, blocks=None):
    """The parts of a format page (current layout, notion.page_blocks): example video + source + note, title + subtitle
    line, script paragraphs, visual hook lines, resources. Images (also inside toggles) are kept as extra media."""
    blocks = notion.children(page_id) if blocks is None else blocks
    p = {'video': None, 'source': '', 'note': [], 'title': '', 'sub': '', 'script': [], 'hook': [], 'links': [],
         'res_text': [], 'media': [], 'extra': []}
    sec = 'video'
    for b in blocks:
        kind, body = b['type'], b.get(b['type']) or {}
        rich = body.get('rich_text')
        if kind.startswith('heading_'):
            h = _plain(rich)
            sec = next((name for key, name in SECTIONS if T[key].lstrip('💬🎬 ') in h), 'video' if kind == 'heading_1' else sec)
            continue
        if kind in ('divider', 'child_page', 'child_database', 'table_of_contents', 'breadcrumb'):
            continue
        if kind in ('video', 'image'):
            url = _file_url(b)
            if url and kind == 'video' and sec == 'video' and p['video'] is None:
                p['video'] = {'block': b['id'], 'url': url}
            elif url and (body.get('type') == 'file'):
                p['media'].append({'block': b['id'], 'url': url, 'kind': kind})
            continue
        if kind == 'toggle' and b.get('has_children'):
            inner = read_page(b['id'], T, notion.children(b['id']))
            p['media'] += inner['media'] + ([dict(inner['video'], kind='video')] if inner['video'] else [])
            text = md(rich)
            if text:
                (p['res_text'] if sec == 'res' else p['extra']).append(f'**{text}**' if '**' not in text else text)
            continue
        text = md(rich) if rich is not None else ''
        if sec == 'video':
            if kind == 'callout' and (body.get('icon') or {}).get('emoji') == '⚠️':
                p['note'] += _paras(text)
            elif kind == 'paragraph' and _links(rich) and not p['source']:
                p['source'] = _links(rich)[0][1]
            elif text.strip():
                p['extra'] += _paras(text)
        elif sec == 'title':
            if kind == 'bulleted_list_item':
                p['sub'] = _plain(rich).strip()
            elif not p['title'] and _plain(rich).strip():
                p['title'] = _plain(rich).strip()
            elif text.strip():
                p['extra'] += _paras(text)
        elif sec == 'script':
            if text.strip():
                p['script'].append(('- ' if kind == 'bulleted_list_item' else '') + text.strip())
        elif sec == 'hook':
            if 'Visual Hook Lab' in _plain(rich) and _links(rich) and len(_plain(rich).strip()) < 40:
                continue  # the lab is a guide on the same Megasheet page
            if text.strip():
                p['hook'].append(text.strip().replace('🚨👇', '🚨'))
        elif sec == 'res':
            links = _links(rich)
            p['links'] += links
            rest = _plain([x for x in rich or [] if not (x.get('href') or ((x.get('text') or {}).get('link')))])
            p['res_text'] += [line.strip() for line in rest.split('\n') if line.strip() and line.strip() not in '()·-–']
    return p


def idea_fields(p, T, hot, links):
    """The Megasheet idea for a read page (only the fields we own)."""
    desc = [f"**🔥 {T['hot_header']}**"] if hot else []
    desc += p['note']
    silent = p['sub'] == T['sub_silent']
    if silent:
        desc.append(f"🎵 {p['sub']}")
    desc += p['extra']
    if p['res_text']:
        desc.append(f"**🔧 {T['res_h'].capitalize()}**")
        desc += [('- ' + t if not t.startswith('**') else t) for t in p['res_text']]
    res, seen = [], set()
    if p['source']:
        res.append({'kind': 'link', 'label': T['source'], 'url': p['source']})
        seen.add(p['source'])
    for label, url in p['links'] + [('Parakeet AI · Resume Maker', links['parakeet'])]:
        if url and url not in seen and url.startswith('http'):
            seen.add(url)
            res.append({'kind': 'link', 'label': (label or url)[:120], 'url': url})
    title = re.sub(r'^\d+\.\s*', '', p['title'])[:300]
    return {'name': title[:255], 'titles': [title], 'description': '\n\n'.join(desc),
            'visualHook': '\n\n'.join(p['hook']), 'scripts': ['\n\n'.join(p['script'])] if p['script'] else [],
            'resources': res, 'captionsRequired': not silent, 'status': 'published'}


# --- comparing and writing -----------------------------------------------------------------------------------------

def _norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def slug(text, taken):
    base = re.sub(r'-+', '-', _norm(text).replace(' ', '-'))[:36].strip('-') or 'format'
    tag, n = base, 2
    while tag in taken:
        tag, n = f'{base}-{n}', n + 1
    taken.add(tag)
    return tag


def current(idea, keep_titles=()):
    """The same fields read back from a Megasheet idea (to compare with idea_fields)."""
    return {'name': idea['name'], 'titles': [t['text'] for t in idea['titles']],
            'description': idea.get('description') or '', 'visualHook': idea.get('visualHook') or '',
            'scripts': [s['text'] for s in idea['scripts']],
            'resources': [{'kind': 'link', 'label': r['label'], 'url': r['url']} for r in idea['resources']
                          if r['kind'] == 'link'],
            'captionsRequired': idea['captionsRequired'], 'status': idea['status']}


def wanted(fields, keep_titles):
    w = dict(fields)
    w['titles'] = fields['titles'] + [t for t in keep_titles if t not in fields['titles']]
    return w


def payload(fields, idea, keep_titles=()):
    """Arguments for formats_updateIdea / createIdea: ids of unchanged titles, scripts and resources are kept;
    uploaded resource files on the idea are kept as they are."""
    old_t = {t['text']: t['id'] for t in (idea or {}).get('titles', [])}
    old_s = {s['text']: s['id'] for s in (idea or {}).get('scripts', [])}
    old_r = {(r['label'], r.get('url')): r for r in (idea or {}).get('resources', [])}
    titles = [{'label': None, 'text': t, **({'id': old_t[t]} if t in old_t else {})}
              for t in wanted(fields, keep_titles)['titles']]
    scripts = [{'label': None, 'text': s, **({'id': old_s[s]} if s in old_s else {})} for s in fields['scripts']]
    res = []
    for r in fields['resources']:
        o = old_r.get((r['label'], r['url']))
        res.append({**r, **({'id': o['id']} if o else {})})
    for r in (idea or {}).get('resources', []):
        if r['kind'] == 'file':
            res.append({k: r[k] for k in ('id', 'kind', 'label', 'fileKey', 'fileUrl', 'fileName', 'fileType',
                                          'fileSizeBytes')})
    return {'name': fields['name'], 'titles': titles, 'description': fields['description'],
            'visualHook': fields['visualHook'], 'scripts': scripts, 'resources': res[:20],
            'captionsRequired': fields['captionsRequired'], 'status': fields['status'], 'mediaNotice': '',
            'groupId': (idea or {}).get('groupId')}


def _size(url):
    try:
        with requests.get(url, timeout=30, stream=True) as r:  # signed links allow GET only: read the headers
            return int(r.headers.get('content-length') or 0)
    except (requests.RequestException, ValueError):
        return 0


class Writer:
    """Megasheet calls; with dry=True nothing is written, the planned changes are only printed."""

    def __init__(self, client, camp, dry, log):
        self.c, self.camp, self.dry, self.log = client, camp, dry, log

    def call(self, tool, what, **args):
        self.log.append(what)
        print(('  [dry] ' if self.dry else '  ') + what, flush=True)
        if self.dry:
            return None
        return self.c.call(tool, campaignId=self.camp, **args)


def _media_key(p):
    return [m['block'] for m in ([p['video']] if p['video'] else []) + p['media']][:6]


def sync_media(w, idea, p, rec, adopted):
    """Example video (+ images of the page) as the idea's media. Only re-uploaded when the page's video changed."""
    key = _media_key(p)
    have = [m['id'] for m in idea.get('media', [])]
    if rec.get('media_key') == key and set(rec.get('media_ids', [])) <= set(have):
        return
    if adopted and p['video'] and have and rec.get('media_key') is None:
        sizes = {m['fileSizeBytes'] for m in idea['media']}
        if _size(p['video']['url']) in sizes:  # the import already has this exact example video
            rec.update(media_key=key, media_ids=have)
            return
    items = ([dict(p['video'], kind='video')] if p['video'] else []) + p['media']
    new = []
    for m in items[:6]:
        ext = 'mp4' if m['kind'] == 'video' else (re.search(r'\.(png|jpe?g|gif|webp)', m['url'].lower()) or [None, 'png'])[1]
        out = w.call('formats_addMediaFromUrl', f"media: {m['kind']} -> {idea['name'][:50]}", ideaId=idea['id'],
                     url=m['url'], fileName=f"{m['kind']}.{ext}")
        if out and out.get('id'):
            new.append(out['id'])
    old = rec.get('media_ids') if rec.get('media_key') is not None else have  # adopted: the import's old example
    for mid in old or []:
        if mid in have and mid not in new:
            w.call('formats_removeMedia', f"media: old example removed <- {idea['name'][:50]}", id=mid)
    rec.update(media_key=key, media_ids=new)


def sync_market(c, mk, camp, S, dry=False, links=None):
    """Mirror one market's Notion list into its campaign. Returns a list of the changes."""
    m, T = mk['key'], mk['T']
    log = []
    w = Writer(c, camp, dry, log)
    L = notion._layout(mk['list_page'])
    order = list(dict.fromkeys(pid.replace('-', '') for _, pid in L['top'] + L['rest']))
    hot = set(pid.replace('-', '') for _, pid in L['top'][:L['hot']])
    ideas = c.call('formats_getIdeas', campaignId=camp)
    by_id = {i['id']: i for i in ideas}
    st = S.setdefault(m, {})
    first = m not in S.setdefault('_adopted', [])
    claimed = {r['idea'] for r in st.values() if r.get('idea') in by_id}
    taken = {i['tag'] for i in ideas}
    ours = []
    for pid in order:
        p = read_page(pid, T)
        if not p['title'] or not p['script']:
            print(f'  {m}: page {pid} has no title/script - not copied', flush=True)
            continue
        fields = idea_fields(p, T, pid in hot, links)
        rec = st.setdefault(pid, {})
        idea = by_id.get(rec.get('idea'))
        adopted = False
        if idea is None:  # take over an idea with this title (the one-time import, or a lost record)
            n = _norm(fields['name'])
            idea = next((i for i in ideas if i['id'] not in claimed and
                         (_norm(i['name']) == n or any(_norm(t['text']) == n for t in i['titles']))), None)
            adopted = idea is not None
            if adopted:
                print(f"  {m}: taken over '{idea['name'][:50]}'", flush=True)
        created = idea is None
        if created:
            args = payload(fields, None)
            args.pop('groupId')
            out = w.call('formats_createIdea', f"new: {fields['name'][:60]}", tag=slug(fields['name'], taken),
                         groupId=None, mediaIds=[], **args)
            idea = out if out else {'id': f'dry-{pid}', 'name': fields['name'], 'media': [], 'titles': [],
                                    'scripts': [], 'resources': []}
            by_id[idea['id']] = idea
        rec['idea'] = idea['id']
        claimed.add(idea['id'])
        ours.append(idea['id'])
        if not created and current(idea) != wanted(fields, rec.get('keep_titles', [])):
            _update(w, idea, fields, rec)
        sync_media(w, idea, p, rec, adopted or first)
    # formats off the list -> archived (ours, and on the first copy every other published idea)
    for pid, rec in st.items():
        i = by_id.get(rec.get('idea'))
        if i and i['id'] not in ours and i.get('status') == 'published':
            w.call('formats_updateIdeaStatus', f"archived (off the list): {i['name'][:60]}", id=i['id'], status='archived')
            i['status'] = 'archived'
    if first:
        for i in ideas:
            if i['id'] not in claimed and i['status'] == 'published':
                w.call('formats_updateIdeaStatus', f"archived (old import, not on the list): {i['name'][:60]}",
                       id=i['id'], status='archived')
                i['status'] = 'archived'
        S['_adopted'].append(m)
    # order: our list, then other published ideas, then the archive
    rest = [i['id'] for i in ideas if i['id'] not in ours]
    new_order = ours + [x for x in rest if by_id[x]['status'] == 'published'] + \
        [x for x in rest if by_id[x]['status'] != 'published']
    if [i['id'] for i in ideas] != new_order and not any(x.startswith('dry-') for x in new_order):
        w.call('formats_reorderIdeas', f'order: {len(ours)} formats as on the Notion list', ids=new_order)
    elif dry and ours:
        print(f'  [dry] order: {len(ours)} formats as on the Notion list', flush=True)
    st_keep = {pid for pid in order}
    for pid in [pid for pid, r in st.items() if pid not in st_keep and r.get('idea') not in by_id]:
        st.pop(pid)  # the idea was deleted by hand in Megasheet: forget it
    return log


def _update(w, idea, fields, rec):
    what = f"updated: {fields['name'][:60]}"
    try:
        w.call('formats_updateIdea', what, id=idea['id'], **payload(fields, idea, rec.get('keep_titles', [])))
    except RuntimeError as e:
        if 'title' not in str(e).lower():
            raise
        # an old title is used by creators' videos and cannot be removed: keep the old titles after ours
        rec['keep_titles'] = [t['text'] for t in idea['titles'] if t['text'] not in fields['titles']]
        w.call('formats_updateIdea', what + ' (old titles kept)', id=idea['id'],
               **payload(fields, idea, rec['keep_titles']))


def load_cfg():
    with open(os.path.join(ROOT, 'config.json')) as f:
        return json.load(f)


def sync(dry=False, only=None):
    cfg = load_cfg()
    token = megasheet.access_token()
    if token is None:
        print('megasheet formats: no Megasheet login saved - skipped')
        return None
    c = megasheet.Client(token)
    camps = {x['name']: x['id'] for x in c.call('list_campaigns')}
    S = state.load(STATE_FILE, {})
    summary, failed = {}, []
    for mk in M.load(cfg):
        if only and mk['key'] not in only:
            continue
        name = MARKET_CAMPAIGN.get(mk['key'])
        if name not in camps:
            print(f"megasheet formats: no campaign for {mk['key']}")
            continue
        print(f"megasheet formats {mk['key']} ({name}):", flush=True)
        try:
            summary[mk['key']] = sync_market(c, mk, camps[name], S, dry=dry, links=cfg['links'])
        except Exception as e:  # one market failing never stops the others
            failed.append(f"{mk['key']}: {str(e)[:300]}")
            print('  FAILED:', str(e)[:300], flush=True)
        if not dry:
            state.save(STATE_FILE, S)
    for m, log in summary.items():
        print(f'megasheet formats {m}: {len(log)} changes')
    if failed and not dry:
        now = time.time()
        if now - S.get('_warned', 0) > 86400:
            S['_warned'] = int(now)
            state.save(STATE_FILE, S)
            hint = (' The Megasheet login has no write access yet - run scripts/save_megasheet_login.sh again.'
                    if any('scope' in f.lower() or 'permission' in f.lower() or 'forbidden' in f.lower()
                           or 'write' in f.lower() for f in failed) else '')
            notify.push('⚠️ Formats not copied to Megasheet', '\n'.join(failed)[:1500] + hint)
    return summary, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='print what would change in Megasheet, change nothing')
    ap.add_argument('--market', default='', help='only these markets (comma-separated)')
    a = ap.parse_args()
    out = sync(dry=a.dry_run, only=[x for x in a.market.split(',') if x] or None)
    if out and out[1]:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
