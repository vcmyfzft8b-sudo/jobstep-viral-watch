"""Format pages in Megasheet (since 16 Oct 2026, user: "stop using Notion entirely" for the formats).

Creators read the formats in the Megasheet portal, and the watcher now builds, checks, fixes and orders them there
too - Notion is no longer read or written for format pages or lists (only the private radar log stays in Notion,
watcher/notion.py). One Megasheet idea = one format page of one market (campaigns in megasheet.CAMPAIGNS).

How it works: every check and fix of the watcher (builder, audit, align, tidy, faithful, localize, crosscheck,
verify, ...) was written for pages made of blocks. This module keeps that interface - `children(page_id)` gives the
blocks of a page, `api('PATCH' / 'DELETE', ...)` changes them, `create_page`, `replace_content`, `move_page`,
`list_entries`, `set_order` - but a "page" is a Megasheet idea:
- children(idea) draws the idea in the page layout (video + TikTok link + ⚠️ note, 📲 title + subtitle line, 💬 script
  paragraphs, 🎬 visual hook lines, 🔧 resources). Every change to those blocks is turned back into the idea's fields
  (megasheet: name, titles, description, visualHook, scripts, resources, captionsRequired, media) and sent at once -
  only the fields that really changed; nothing is sent when nothing changed.
- page ids are Megasheet idea ids (formats.json pages.<market>); the "folders" of a page are places kept in
  state/pages.json: live (published, on the list), archive and staging (both archived in Megasheet, invisible to
  creators). move_page = publish/archive.
- the list of a market = our published ideas in Megasheet's display order; set_order re-orders them, puts the bold
  🔥 going-viral line on the first `hot_count` ones, publishes the listed ones and archives our others. Ideas made by
  hand in Megasheet are left alone and stay after ours.
- hand edits WIN (user, 16 Oct 2026: "from now on just make changes directly in Megasheet"): an idea whose content or
  videos differ from what the watcher last wrote (fingerprint `fp`) is marked `hand` and its content and videos are
  never written again - only its place in the list, the 🔥 line and published/archived still follow the ranking.
- new example videos (local files) are uploaded with formats_createMediaUpload (UploadThing).
- DRY = True: nothing is written, every write is printed ("[dry]") and kept in memory (mode pages-dry).

state/pages.json: {'_migrated': ts, 'ideas': {idea_id: {market, place, fp, hand, media_ids, hand_media,
keep_titles}}}. The one-time migration from the Notion page ids (migrate) uses state/megasheet_formats.json, the
record of the old Notion -> Megasheet copy.
"""
import atexit
import copy
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata

import requests

from . import builder, megasheet, state
from .markets import TEXT

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
STATE_FILE = 'pages.json'
MARKETS = ('fr', 'es', 'sl')  # the only campaigns the watcher writes (megasheet.WRITE_CAMPAIGNS checks it again)
MARKET_CAMPAIGN = {m: name for name, m in megasheet.CAMPAIGNS.items()}
PLACES = ('live', 'archive', 'staging')
LAB_URL = 'https://megasheet.app/visual-hook-lab'  # drawn under the hook only (the lab is a guide on the Megasheet page)
PAGE_URL = 'https://megasheet.app'
DRY = False
LOCK = threading.RLock()


# ======================================================================================================================
# page layout (the blocks the checks work on - the same layout the Notion pages had)
# ======================================================================================================================

def rt(text, bold=False, link=None, code=False):
    return {'type': 'text', 'text': {'content': text, 'link': {'url': link} if link else None},
            'annotations': {'bold': bold, 'code': code}}


MD_TOKEN = re.compile(r'\*\*\[([^\]]+)\]\(([^)\s]+)\)\*\*|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*', re.S)


def md(text):
    """Markdown as Megasheet stores it (**bold**, [label](url), **[label](url)**) -> rich text items."""
    out, pos = [], 0
    for m in MD_TOKEN.finditer(text or ''):
        if m.start() > pos:
            out.append(rt(text[pos:m.start()]))
        if m.group(1):
            out.append(rt(m.group(1), bold=True, link=m.group(2)))
        elif m.group(3):
            out.append(rt(m.group(3), link=m.group(4)))
        else:
            out.append(rt(m.group(5), bold=True))
        pos = m.end()
    if pos < len(text or ''):
        out.append(rt(text[pos:]))
    return out


def block(kind, rich=None, **extra):
    b = {'object': 'block', 'type': kind, kind: {}}
    if rich is not None:
        b[kind]['rich_text'] = rich
    b[kind].update(extra)
    return b


def para(rich):
    return block('paragraph', rich)


def divider():
    return block('divider')


def inspo_note(lang, same_lang=False, own=False):
    """The note under the inspiration video: same-language example = 'use it as the model, say our script';
    otherwise 'film from our script'. Both say: another brand's video - copy vibe, angles, filming, editing and the demo
    moments as closely as possible. The second line ('another app is used - do the same with Parakeet AI') names no app."""
    T = TEXT[lang]
    if own:  # our own creator's video: it already shows Parakeet AI
        return [T['inspo_note_own']]
    first = T['inspo_note_same'] if same_lang else T['inspo_note'][0]
    return [first, T['inspo_note'][1]]


def page_blocks(spec, video, file_upload_id, links, lang='de', lab_url=None, same_lang=False):
    T = TEXT[lang]
    blocks = [block('heading_1', [rt(T['video_heading'])])]
    if file_upload_id:
        blocks.append(block('video', type='file_upload', file_upload={'id': file_upload_id}))
    blocks.append(para([rt(T['source'], link=video['url'])]))
    note = inspo_note(lang, same_lang, own=video.get('own'))
    blocks.append(block('callout', md('\n'.join(note)), icon={'type': 'emoji', 'emoji': '⚠️'}, color='gray_background'))

    blocks.append(block('heading_2', [rt('📲'), rt(T['title_h'], bold=True)]))
    blocks.append(para([rt(spec['title_hook'], bold=True)]))
    sub = T['sub_voice'] if spec.get('voiceover', True) else T['sub_silent']
    blocks.append(block('bulleted_list_item', [rt(sub)]))
    blocks.append(divider())

    blocks.append(block('heading_2', [rt(T['script_h'])]))
    blocks += script_paragraphs(spec, links, lang)
    blocks.append(divider())

    blocks.append(block('heading_2', [rt(T['hook_h'])]))
    blocks += [para([rt(line)]) for line in builder.hook_lines(spec, lang)]
    blocks.append(para([rt(T['required_line'])]))
    blocks.append(para([rt('Visual Hook Lab', link=lab_url or links.get('visual_hook_lab') or LAB_URL)]))
    blocks.append(divider())

    blocks.append(block('heading_2', [rt('🔧'), rt(T['res_h'], bold=True)]))
    res = [rt('Parakeet AI · Resume Maker', link=links['parakeet'])]
    for asset in spec.get('assets_needed', []):
        res.append(rt(f"\n📎 {asset['name']} – {T['asset_todo']}: {asset.get('description', '')}"))
    blocks.append(block('callout', res, icon={'type': 'emoji', 'emoji': '💡'}, color='gray_background'))
    return blocks


# '– siehe Ressourcen' / '– voir Ressources' / '– ver Recursos' / '– glej Viri': every market's asset cue ending
ASSET_SEE = '|'.join(re.escape(T['asset_cue'].split('{name}')[1].strip(' )').lstrip('–- ').strip()) for T in TEXT.values())


def asset_label(name):
    """Bare asset name: a rewrite copies the rendered cue ('📎 Gmail – siehe Ressourcen'), which must not be decorated
    again (it piled up as '📎 📎 📎 … – ver Recursos – ver Recursos')."""
    t = (name or '').strip()
    while True:
        new = re.sub(r'^[(\s]*📎\s*', '', t)
        new = re.sub(r'\s*[–-]\s*(' + ASSET_SEE + r')\s*\)?\s*$', '', new).strip()
        if new == t:
            return t
        t = new


DIRECTION_RE = re.compile(r'\((?!\s*📎)[^()]*\)\s*')


def strip_directions(text):
    """Script text without bracketed stage directions / acting tips (the 📎 material cues stay)."""
    return re.sub(r'\s{2,}', ' ', DIRECTION_RE.sub('', text or '')).strip()


def script_paragraphs(spec, links, lang='de'):
    """The script section's paragraphs (cue links in front of the line where the app/LinkedIn/asset appears)."""
    T = TEXT[lang]
    cue_links = {'parakeet': ('Parakeet AI · Resume Maker', links['parakeet']),
                 'linkedin': (T['cue_linkedin'], links['linkedin'])}
    paragraphs, current = [], []
    silent = not spec.get('voiceover', True)
    if silent:
        paragraphs.append([rt(T['silent_label'], bold=True)])
    for seg in spec['script']:
        cue = seg.get('cue')
        parts = []
        if cue in cue_links:
            label, url = cue_links[cue]
            parts += [rt('('), rt(label, link=url), rt(') ')]
        elif cue == 'asset':
            parts.append(rt(T['asset_cue'].format(name=asset_label(seg.get('asset_name')) or '📎')))
        # cue 'direction' (stage directions) is never rendered: scripts have no acting tips (brands.NO_DIRECTIONS)
        text = strip_directions(seg.get('text'))
        if not text and not parts:
            continue
        parts.append(rt(text + ' ', bold=silent))
        if silent:
            paragraphs.append(parts)
            continue
        if seg.get('new_paragraph') and current:
            paragraphs.append(current)
            current = []
        current += parts
    if current:
        paragraphs.append(current)
    from .tidy import trim_cues  # one cue of a kind per paragraph, at most tidy.MAX_CUES Parakeet AI cues
    paragraphs, _ = trim_cues(paragraphs, links)
    return [para(p) for p in paragraphs]


# ======================================================================================================================
# blocks <-> idea fields
# ======================================================================================================================

def _plain(rich):
    return ''.join(x.get('plain_text') or (x.get('text') or {}).get('content', '') for x in rich or [])


def to_md(rich):
    """Rich text -> Megasheet markdown (**bold**, [label](url)); spaces stay outside the markers."""
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
    """Line breaks inside one block -> separate markdown paragraphs (one line break shows as a space)."""
    return [p.strip() for p in text.split('\n') if p.strip()]


def _links(rich):
    return [(_plain([x]).strip(), x.get('href') or (((x.get('text') or {}).get('link')) or {}).get('url'))
            for x in rich or [] if x.get('href') or ((x.get('text') or {}).get('link'))]


SECTIONS = (('title_h', 'title'), ('script_h', 'script'), ('hook_h', 'hook'), ('res_h', 'res'))


def read_blocks(blocks, T):
    """The parts of a page: source link + note, title + subtitle line, script paragraphs, visual hook lines, resources."""
    p = {'source': '', 'source_label': '', 'note': [], 'title': '', 'sub': '', 'script': [], 'hook': [], 'links': [],
         'res_text': [], 'extra': []}
    sec = 'video'
    for b in blocks:
        kind, body = b['type'], b.get(b['type']) or {}
        rich = body.get('rich_text')
        if kind.startswith('heading_'):
            h = _plain(rich)
            sec = next((name for key, name in SECTIONS if T[key].lstrip('💬🎬 ') in h), 'video' if kind == 'heading_1' else sec)
            continue
        if kind in ('divider', 'child_page', 'child_database', 'table_of_contents', 'breadcrumb', 'video', 'image'):
            continue
        text = to_md(rich) if rich is not None else ''
        if sec == 'video':
            if kind == 'callout' and (body.get('icon') or {}).get('emoji') == '⚠️':
                p['note'] += _paras(text)
            elif kind == 'paragraph' and _links(rich) and not p['source']:
                p['source_label'], p['source'] = _links(rich)[0]
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
            p['links'] += _links(rich)
            for line in text.split('\n'):  # a line keeps its link ('[Gmail](…) — film it full screen')
                t = re.sub(r'\((\[[^\]]+\]\([^)]+\))\)', r'\1', line).strip()  # '([Gmail](…))' -> '[Gmail](…)'
                if t and not re.fullmatch(r'\[[^\]]+\]\([^)]+\)', t):  # a bare link is in the resources list
                    p['res_text'].append(t)
    return p


def hot_line(T):
    return f"**🔥 {T['hot_header']}**"


def set_hot(desc, T, hot):
    """The description with (hot) or without the bold 🔥 going-viral first line."""
    line = hot_line(T)
    body = desc[len(line):].lstrip('\n') if desc.startswith(line) else desc
    return (line + ('\n\n' + body if body else '')) if hot else body


def is_hot(desc, T):
    return (desc or '').startswith(hot_line(T))


def fields_of(blocks, T, links):
    """The idea fields a page's blocks stand for (without the 🔥 line; name = the 📲 title)."""
    p = read_blocks(blocks, T)
    desc = list(p['note'])
    silent = p['sub'] == T['sub_silent']
    if silent:
        desc.append(f"🎵 {p['sub']}")
    desc += p['extra']
    if p['res_text']:
        desc.append(f"**🔧 {T['res_h'].capitalize()}**")
        desc += [('- ' + t if not t.startswith('**') else t) for t in p['res_text']]
    res, seen = [], set()
    if p['source']:
        res.append({'kind': 'link', 'label': (p['source_label'] or T['source'])[:120], 'url': p['source']})
        seen.add(p['source'])
    for label, url in p['links'] + [('Parakeet AI · Resume Maker', links['parakeet'])]:
        if url and url not in seen and url.startswith('http'):
            seen.add(url)
            res.append({'kind': 'link', 'label': (label or url)[:120], 'url': url})
    title = re.sub(r'^\d+\.\s*', '', p['title'])[:300]
    return {'name': title[:255], 'titles': [title] if title else [], 'description': '\n\n'.join(desc),
            'visualHook': '\n\n'.join(p['hook']), 'scripts': ['\n\n'.join(p['script'])] if p['script'] else [],
            'resources': res, 'captionsRequired': not silent}


def current(idea):
    """The fields we compare, read from a Megasheet idea."""
    return {'name': idea['name'], 'titles': [t['text'] for t in idea.get('titles', [])],
            'description': idea.get('description') or '', 'visualHook': idea.get('visualHook') or '',
            'scripts': [s['text'] for s in idea.get('scripts', [])],
            'resources': [{'kind': 'link', 'label': r['label'], 'url': r['url']} for r in idea.get('resources', [])
                          if r.get('kind') == 'link'],
            'captionsRequired': bool(idea.get('captionsRequired', True))}


def fingerprint(f, T):
    """What we last wrote into an idea (content only - not the status, not the 🔥 line)."""
    x = {k: v for k, v in f.items() if k != 'status'}
    x['description'] = set_hot(x['description'], T, False)
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _desc_parts(desc, T):
    """description -> (note lines, resource lines) without the 🔥 line (the 🎵 line follows captionsRequired)."""
    lines = [x for x in set_hot(desc or '', T, False).split('\n\n') if x.strip()]
    head = f"**🔧 {T['res_h'].capitalize()}**"
    k = lines.index(head) if head in lines else len(lines)
    note = [x for x in lines[:k] if not x.startswith('🎵 ')]
    res = [x[2:] if x.startswith('- ') else x for x in lines[k + 1:]]
    return note, res


def render(idea, T):
    """An idea drawn as page blocks (no ids yet). Media blocks carry their Megasheet media id in '_media'."""
    out = [block('heading_1', [rt(T['video_heading'])])]
    for m in idea.get('media') or []:
        kind = 'image' if m.get('kind') == 'image' else 'video'
        b = block(kind, type='file', file={'url': m.get('fileUrl') or ''})
        b['_media'] = m['id']
        out.append(b)
    links = [r for r in idea.get('resources') or [] if r.get('kind') == 'link' and r.get('url')]
    src = next((r for r in links if 'tiktok.com/' in r['url']), None)
    if src:
        out.append(para([rt(src['label'] or T['source'], link=src['url'])]))
    note, res_lines = _desc_parts(idea.get('description'), T)
    if note:
        out.append(block('callout', md('\n'.join(note)), icon={'type': 'emoji', 'emoji': '⚠️'}, color='gray_background'))
    out.append(block('heading_2', [rt('📲'), rt(T['title_h'], bold=True)]))
    titles = [t['text'] for t in idea.get('titles') or []]
    out.append(para([rt(titles[0] if titles else idea.get('name') or '', bold=True)]))
    out.append(block('bulleted_list_item', [rt(T['sub_voice'] if idea.get('captionsRequired', True) else T['sub_silent'])]))
    out.append(divider())
    out.append(block('heading_2', [rt(T['script_h'])]))
    scripts = idea.get('scripts') or []
    for p in [x for x in (scripts[0]['text'] if scripts else '').split('\n\n') if x.strip()]:
        out.append(block('bulleted_list_item', md(p[2:])) if p.startswith('- ') else para(md(p)))
    out.append(divider())
    out.append(block('heading_2', [rt(T['hook_h'])]))
    for p in [x for x in (idea.get('visualHook') or '').split('\n\n') if x.strip()]:
        out.append(para(md(p)))
    out.append(para([rt('Visual Hook Lab', link=LAB_URL)]))
    out.append(divider())
    out.append(block('heading_2', [rt('🔧'), rt(T['res_h'], bold=True)]))
    rich = []
    for r in [r for r in links if r is not src]:
        if rich:
            rich.append(rt('\n'))
        rich.append(rt(r['label'], link=r['url']))
    for line in res_lines:
        rich += ([rt('\n')] if rich else []) + md(line)
    out.append(block('callout', rich, icon={'type': 'emoji', 'emoji': '💡'}, color='gray_background'))
    return out


def _norm_rich(items):
    out = []
    for x in items or []:
        if x.get('type', 'text') != 'text':
            continue  # mentions/equations do not exist in Megasheet
        t = x.get('text') or {}
        content = t.get('content', x.get('plain_text', ''))
        url = (t.get('link') or {}).get('url') or x.get('href')
        ann = {'bold': False, 'italic': False, 'strikethrough': False, 'underline': False, 'code': False,
               'color': 'default', **(x.get('annotations') or {})}
        out.append({'type': 'text', 'text': {'content': content, 'link': {'url': url} if url else None},
                    'annotations': ann, 'plain_text': content, 'href': url})
    return out


# ======================================================================================================================
# the store
# ======================================================================================================================

class PageNotFound(RuntimeError):
    pass


class Doc:
    """One idea as a page: its blocks (stable ids) and the fields they stood for when last saved."""

    def __init__(self, store, idea, market):
        self.store, self.idea, self.market = store, idea, market
        self.T = store.T(market)
        self.n = 0
        self.stamp = 'content:' + fingerprint(current(idea), self.T)  # not updatedAt: the 🔥 line / status don't count
        self.blocks = [self.adopt(b) for b in render(idea, self.T)]
        self.base = fields_of(self.blocks, self.T, store.links())
        self.rename = None

    def adopt(self, b, stamp=None):
        """A block as the page holds it: id, plain text, children list."""
        b = copy.deepcopy(b)
        self.n += 1
        b['id'] = f"{self.idea['id']}.{self.n}"
        b['object'] = 'block'
        b['has_children'] = False
        b['last_edited_time'] = stamp or self.stamp
        body = b.setdefault(b['type'], {})
        if 'rich_text' in body:
            body['rich_text'] = _norm_rich(body['rich_text'])
        b.pop('children', None)
        return b

    def index(self, bid):
        return next((k for k, b in enumerate(self.blocks) if b['id'] == bid), None)


class Store:
    def __init__(self):
        self.client = None
        self.camps = None
        self.ideas = {}  # market -> [idea] in display order
        self.docs = {}  # idea id -> Doc
        self.S = None
        self.cfg = None
        self.writes = []  # what this process wrote (or, DRY, would write)
        self.touched = set()  # (market, idea id) written: fingerprints are read back from Megasheet at the end
        self.uploads = {}  # upload token -> local file (copied, kept until the process ends)
        self.updir = None
        self.warned_hand = set()

    # --- setup -------------------------------------------------------------------------------------------------------

    def config(self):
        if self.cfg is None:
            with open(os.path.join(ROOT, 'config.json')) as f:
                self.cfg = json.load(f)
        return self.cfg

    def links(self):
        return self.config()['links']

    def T(self, market):
        return TEXT[self.config()['markets'][market]['lang']]

    def state(self):
        if self.S is None:
            self.S = state.load(STATE_FILE, {})
            self.S.setdefault('ideas', {})
        return self.S

    def save_state(self):
        if not DRY:
            state.save(STATE_FILE, self.state())

    def rec(self, idea_id):
        return self.state()['ideas'].get(idea_id)

    def connect(self, fresh=False):
        if self.client is None:
            token = megasheet.access_token(fresh=fresh)
            if token is None:
                raise RuntimeError('no Megasheet login saved (scripts/save_megasheet_login.sh) - format pages unavailable')
            known = self.client.known if self.client else {}
            self.client = megasheet.Client(token)
            self.client.known.update(known)
        if self.camps is None:
            camps = {x['name']: x['id'] for x in self.client.call('list_campaigns')}
            self.camps = {m: camps[MARKET_CAMPAIGN[m]] for m in MARKETS
                          if camps.get(MARKET_CAMPAIGN[m]) in megasheet.WRITE_CAMPAIGNS}
        return self.client

    def call(self, tool, **args):
        """A Megasheet call; a login that ran out during a long run is renewed once."""
        self.connect()
        try:
            return self.client.call(tool, **args)
        except megasheet.LoginError:
            known = self.client.known
            self.client = None
            self.connect(fresh=True)
            self.client.known.update(known)
            return self.client.call(tool, **args)

    def camp(self, market):
        self.connect()
        if market not in self.camps:
            raise PageNotFound(f'no Megasheet campaign the watcher may write for market {market}')
        return self.camps[market]

    def load(self, market, force=False):
        """All ideas of a market's campaign (display order); finds the ideas changed by hand since our last write."""
        with LOCK:
            if market in self.ideas and not force:
                return self.ideas[market]
            ideas = self.call('formats_getIdeas', campaignId=self.camp(market))
            self.ideas[market] = ideas
            T = self.T(market)
            for i in ideas:
                r = self.rec(i['id'])
                if not r or r.get('market') != market:
                    continue
                self.docs.pop(i['id'], None)
                if not r.get('hand') and r.get('fp') and fingerprint(current(i), T) != r['fp']:
                    r['hand'] = True  # edited in Megasheet since our last write: Megasheet wins from now on
                    print(f"pages: edited by hand in Megasheet - kept as it is: {market} {i['name'][:60]}", flush=True)
                media = [m['id'] for m in i.get('media') or []]
                if not r.get('hand_media') and r.get('media_ids') is not None and set(media) != set(r['media_ids']):
                    r['hand_media'] = True
                    print(f"pages: videos changed by hand in Megasheet - kept: {market} {i['name'][:60]}", flush=True)
            self.save_state()
            return ideas

    def find(self, page_id):
        """(market, idea) of a page id (with or without dashes). Our ideas are looked up in their market; an unknown
        id in every campaign the watcher may write."""
        key = (page_id or '').replace('-', '').lower()
        if not key or '.' in key:
            raise PageNotFound(f'not a format page: {page_id}')
        with LOCK:
            r = self.state()['ideas'].get(self._full(key))
            order = [r['market']] if r and r.get('market') in MARKETS else list(MARKETS)
            for m in order:
                try:
                    ideas = self.load(m)
                except PageNotFound:
                    continue
                idea = next((i for i in ideas if i['id'].replace('-', '').lower() == key), None)
                if idea:
                    return m, idea
            raise PageNotFound(f'format page {page_id} is not a Megasheet idea of France, Spain or Slovenia')

    def _full(self, key):
        return next((i for i in self.state()['ideas'] if i.replace('-', '').lower() == key), key)

    def doc(self, page_id):
        with LOCK:
            m, idea = self.find(page_id)
            d = self.docs.get(idea['id'])
            if d is None or d.idea is not idea:
                d = self.docs[idea['id']] = Doc(self, idea, m)
            return d

    def locked(self, d):
        r = self.rec(d.idea['id']) or {}
        if r.get('hand') or r.get('hand_media'):
            if d.idea['id'] not in self.warned_hand:
                self.warned_hand.add(d.idea['id'])
                print(f"pages: not changed - edited by hand in Megasheet: {d.market} {d.idea['name'][:60]}", flush=True)
            return True
        return False

    # --- writing -----------------------------------------------------------------------------------------------------

    def write(self, tool, what, market, **args):
        self.writes.append(f'{market}: {what}')
        print(('  [dry] ' if DRY else '  megasheet: ') + f'{market}: {what}', flush=True)
        if DRY:
            return None
        return self.call(tool, campaignId=self.camp(market), **args)

    def save(self, d):
        """Send what changed on a page (content fields, then new / removed videos)."""
        with LOCK:
            T, idea = d.T, d.idea
            new = fields_of(d.blocks, T, self.links())
            cur = current(idea)
            out = {k: (cur[k] if new[k] == d.base[k] else new[k]) for k in cur}
            if new['titles'] == d.base['titles'] and d.rename is None:
                out['name'] = cur['name']
            elif d.rename is not None:
                out['name'] = d.rename
            out['description'] = set_hot(out['description'], T, is_hot(cur['description'], T))
            if out != cur:
                self._update(d.market, idea, out, f"updated: {out['name'][:60]} ({', '.join(k for k in cur if out[k] != cur[k])})")
            d.base, d.rename = new, None
            self._media(d)

    def _payload(self, idea, f, keep):
        # ids of unchanged titles / scripts / resources are kept (an id we do not know yet is left out: new item)
        old_t = {t['text']: t['id'] for t in idea.get('titles', []) if t.get('id')}
        old_s = {s['text']: s['id'] for s in idea.get('scripts', []) if s.get('id')}
        old_r = {(r['label'], r.get('url')): r['id'] for r in idea.get('resources', []) if r.get('id')}
        titles = f['titles'] + [t for t in keep if t not in f['titles']]
        res = [{**{k: r[k] for k in ('kind', 'label', 'url')},
                **({'id': old_r[(r['label'], r['url'])]} if (r['label'], r['url']) in old_r else {})}
               for r in f['resources']]
        res += [{k: r[k] for k in ('id', 'kind', 'label', 'fileKey', 'fileUrl', 'fileName', 'fileType', 'fileSizeBytes')}
                for r in idea.get('resources', []) if r.get('kind') == 'file']
        return {'name': f['name'][:255] or 'format', 'tag': idea['tag'], 'groupId': idea.get('groupId'),
                'status': idea.get('status', 'archived'), 'captionsRequired': f['captionsRequired'],
                'titles': [{'label': None, 'text': t, **({'id': old_t[t]} if t in old_t else {})} for t in titles],
                'description': f['description'], 'visualHook': f['visualHook'], 'mediaNotice': idea.get('mediaNotice') or '',
                'scripts': [{'label': None, 'text': s, **({'id': old_s[s]} if s in old_s else {})} for s in f['scripts']],
                'resources': res[:20]}

    def _update(self, market, idea, f, what):
        r = self.state()['ideas'].setdefault(idea['id'], {'market': market, 'place': 'archive'})
        keep = r.get('keep_titles', [])
        args = self._payload(idea, f, keep)
        try:
            self.write('formats_updateIdea', what, market, id=idea['id'], **args)
        except RuntimeError as e:
            if 'title' not in str(e).lower():
                raise
            # an old title is used by creators' videos and cannot be removed: the old titles stay after ours
            r['keep_titles'] = [t['text'] for t in idea['titles'] if t['text'] not in f['titles']]
            args = self._payload(idea, f, r['keep_titles'])
            self.write('formats_updateIdea', what + ' (old titles kept)', market, id=idea['id'], **args)
        self._remember(idea, args)
        r['fp'] = fingerprint(current(idea), self.T(market))
        self.touched.add((market, idea['id']))
        self.save_state()

    def _remember(self, idea, args):
        """Our copy of the idea after a write (Megasheet only answers with the id; read back at the end of the run)."""
        idea.update({k: args[k] for k in ('name', 'description', 'visualHook', 'captionsRequired', 'status')})
        idea['titles'] = [{'id': t.get('id'), 'text': t['text']} for t in args['titles']]
        idea['scripts'] = [{'id': s.get('id'), 'text': s['text']} for s in args['scripts']]
        idea['resources'] = [dict(r) for r in args['resources']]

    def _media(self, d):
        """Uploads new example videos (blocks from upload_video) and removes the ones taken off the page."""
        idea = d.idea
        on_page = [b for b in d.blocks if b['type'] in ('video', 'image')]
        keep = {b['_media'] for b in on_page if b.get('_media')}
        new = [b for b in on_page if (b[b['type']] or {}).get('type') == 'file_upload']
        gone = [m for m in idea.get('media') or [] if m['id'] not in keep]
        if not new and not gone:
            return
        for b in new:
            token = b[b['type']]['file_upload']['id']
            mid, url = self._upload(d.market, idea, self.uploads.get(token))
            b[b['type']] = {'type': 'file', 'file': {'url': url or ''}}
            b['_media'] = mid
            idea.setdefault('media', []).append({'id': mid, 'kind': b['type'], 'fileUrl': url})
        for m in gone:
            self.write('formats_removeMedia', f"video removed <- {idea['name'][:50]}", d.market, id=m['id'])
            idea['media'].remove(m)
        r = self.state()['ideas'].setdefault(idea['id'], {'market': d.market, 'place': 'archive'})
        r['media_ids'] = [m['id'] for m in idea['media']]
        self.touched.add((d.market, idea['id']))
        self.save_state()

    def _upload(self, market, idea, path):
        """A local video into the idea (UploadThing grant from formats_createMediaUpload). -> (media id, url)"""
        if not path or not os.path.exists(path):
            raise RuntimeError(f'pages: upload file missing ({path})')
        what = f"video added ({os.path.getsize(path) // 1024} KB) -> {idea['name'][:50]}"
        grant = self.write('formats_createMediaUpload', what, market, ideaId=idea['id'])
        if DRY:
            return f'dry-media-{len(self.writes)}', ''
        name = 'video' + (os.path.splitext(path)[1] or '.mp4')
        mime = mimetypes.guess_type(name)[0] or 'video/mp4'
        r = requests.post(f"{grant['url']}?slug={grant['slug']}&actionType=upload", timeout=60, json={
            'files': [{'name': name, 'size': os.path.getsize(path), 'type': mime, 'lastModified': 0}],
            'input': grant['input']})
        r.raise_for_status()
        target = r.json()[0]['url']
        for attempt in range(3):
            with open(path, 'rb') as f:
                up = requests.put(target, headers={'Range': 'bytes=0-'}, files={'file': (name, f, mime)}, timeout=600)
            if up.ok:
                break
            time.sleep(5 + attempt * 10)
        up.raise_for_status()
        media = ((up.json() or {}).get('serverData') or {}).get('media') or {}
        if not media.get('id'):
            raise RuntimeError('pages: Megasheet did not attach the uploaded video')
        self.client.known.setdefault(self.camp(market), set()).add(media['id'])
        return media['id'], media.get('fileUrl') or ''

    def status(self, market, idea, status, what):
        if idea.get('status') == status:
            return
        self.write('formats_updateIdeaStatus', f"{what}: {idea['name'][:60]}", market, id=idea['id'], status=status)
        idea['status'] = status

    # --- the end of a run --------------------------------------------------------------------------------------------

    def finish(self):
        """The written ideas read back from Megasheet: their fingerprints are what Megasheet really stores (so a
        normalised space is never taken for a hand edit)."""
        with LOCK:
            if DRY or not self.touched:
                return
            for m in sorted({m for m, _ in self.touched}):
                try:
                    ideas = self.call('formats_getIdeas', campaignId=self.camp(m))
                except Exception as e:
                    print('pages: read back failed', m, str(e)[:150], flush=True)
                    continue
                by = {i['id']: i for i in ideas}
                for _, iid in [x for x in self.touched if x[0] == m]:
                    r, i = self.rec(iid), by.get(iid)
                    if r and i and not r.get('hand'):
                        r['fp'] = fingerprint(current(i), self.T(m))
                    if r and i and not r.get('hand_media'):
                        r['media_ids'] = [x['id'] for x in i.get('media') or []]
                self.ideas[m] = ideas
                self.docs = {k: v for k, v in self.docs.items() if v.market != m}
            self.touched.clear()
            self.save_state()


STORE = Store()


def _cleanup():
    try:
        STORE.finish()
    finally:
        if STORE.updir:
            shutil.rmtree(STORE.updir, ignore_errors=True)


atexit.register(_cleanup)


def reset():
    """A fresh store (tests; a mode that re-reads everything)."""
    global STORE
    STORE = Store()
    return STORE


# ======================================================================================================================
# the page interface the checks use
# ======================================================================================================================

def place(kind, market):
    return f'{kind}:{market}'


def _place(parent):
    kind, _, market = (parent or '').partition(':')
    if kind not in PLACES or market not in MARKETS:
        raise PageNotFound(f'unknown place for a format page: {parent}')
    return kind, market


def page_url(page_id):
    return PAGE_URL


def is_hand(page_id):
    """True when the page (idea) was edited by hand in Megasheet - the watcher never changes its content. (From the
    state: a campaign read in this run has marked its hand-edited ideas already.)"""
    key = (page_id or '').replace('-', '').lower()
    with LOCK:
        r = STORE.state()['ideas'].get(STORE._full(key)) or {}
    return bool(r.get('hand') or r.get('hand_media'))


def children(block_id):
    """The blocks of a page (or [] for a block: Megasheet pages have no nested blocks)."""
    if '.' in (block_id or ''):
        return []
    with LOCK:
        return copy.deepcopy(STORE.doc(block_id).blocks)


def _title_rich(text):
    return [{'type': 'text', 'text': {'content': text, 'link': None}, 'plain_text': text, 'href': None,
             'annotations': {'bold': False}}]


def _page(d):
    r = STORE.rec(d.idea['id']) or {}
    return {'object': 'page', 'id': d.idea['id'], 'url': PAGE_URL,
            'parent': {'type': 'page_id', 'page_id': place(r.get('place', 'archive'), d.market)},
            'properties': {'title': {'id': 'title', 'type': 'title', 'title': _title_rich(d.idea['name'])}}}


def api(method, path, body=None, version=None):
    """The block interface on top of Megasheet ideas: GET/PATCH a page, PATCH/DELETE a block, add blocks."""
    body = body or {}
    with LOCK:
        m = re.fullmatch(r'/pages/([^/?]+)', path)
        if m:
            d = STORE.doc(m.group(1))
            if method == 'GET':
                return _page(d)
            title = ''.join(x.get('text', {}).get('content', x.get('plain_text', ''))
                            for x in ((body.get('properties') or {}).get('title') or {}).get('title', []))
            if title and not STORE.locked(d):
                name = re.sub(r'^\d+\.\s*', '', title).strip()[:255]
                if name != d.idea['name']:
                    d.rename = name
                    STORE.save(d)
            return _page(d)
        m = re.fullmatch(r'/blocks/([^/?]+)/children', path)
        if m and method == 'PATCH':
            target = m.group(1)
            if '.' in target:  # children of a block: Megasheet pages are flat - they go right after it
                body = {**body, 'after': target}
                target = target.split('.')[0]
            d = STORE.doc(target)
            if STORE.locked(d):
                return {'results': [d.adopt(b) for b in body.get('children', [])]}
            new = [d.adopt(b, stamp=_now()) for b in body.get('children', [])]
            after = body.get('after')
            if (body.get('position') or {}).get('type') == 'start':
                at = 0
            elif after:
                k = d.index(after)
                if k is None:
                    raise PageNotFound(f'block {after} is not on the page')
                at = k + 1
            else:
                at = len(d.blocks)
            d.blocks[at:at] = new
            STORE.save(d)
            return {'results': copy.deepcopy(new)}
        m = re.fullmatch(r'/blocks/([^/?]+)', path)
        if m:
            bid = m.group(1)
            d = STORE.doc(bid.split('.')[0])
            k = d.index(bid)
            if k is None:
                raise PageNotFound(f'block {bid} is not on the page')
            if method == 'GET':
                return copy.deepcopy(d.blocks[k])
            if STORE.locked(d):
                return copy.deepcopy(d.blocks[k])
            if method == 'DELETE':
                d.blocks.pop(k)
                STORE.save(d)
                return {}
            b = d.blocks[k]
            data = body.get(b['type']) or {}
            if 'rich_text' in data:
                b[b['type']]['rich_text'] = _norm_rich(data['rich_text'])
                b['last_edited_time'] = _now()
            STORE.save(d)
            return copy.deepcopy(b)
    raise RuntimeError(f'pages: {method} {path} is not supported')


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())


def upload_video(path):
    """A local video for a page: kept (copied) until the page is saved, then uploaded to the idea."""
    with LOCK:
        if STORE.updir is None:
            STORE.updir = tempfile.mkdtemp(prefix='pages-upload-')
        token = f'upload-{len(STORE.uploads) + 1}'
        dst = os.path.join(STORE.updir, token + os.path.splitext(path)[1])
        shutil.copyfile(path, dst)
        STORE.uploads[token] = dst
        return token


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


def create_page(parent, title, icon, blocks):
    """A new idea in the market of `parent` (live = published, archive / staging = archived). -> {'id', 'url'}"""
    kind, market = _place(parent)
    with LOCK:
        ideas = STORE.load(market)
        T = STORE.T(market)
        tmp = Doc.__new__(Doc)
        tmp.store, tmp.market, tmp.T, tmp.n, tmp.rename, tmp.stamp = STORE, market, T, 0, None, _now()
        tmp.idea = {'id': 'new', 'updatedAt': _now()}
        tmp.blocks = [tmp.adopt(b) for b in blocks]
        f = fields_of(tmp.blocks, T, STORE.links())
        name = f['name'] or re.sub(r'^\d+\.\s*', '', title or '').strip() or 'format'
        f['name'] = name[:255]
        if not f['titles']:
            f['titles'] = [name[:300]]
        status = 'published' if kind == 'live' else 'archived'
        tag = slug(name, {i['tag'] for i in ideas})
        args = {'name': f['name'], 'tag': tag, 'groupId': None, 'status': status, 'captionsRequired': f['captionsRequired'],
                'titles': [{'label': None, 'text': t} for t in f['titles']], 'description': f['description'],
                'visualHook': f['visualHook'], 'mediaNotice': '',
                'scripts': [{'label': None, 'text': s} for s in f['scripts']], 'resources': f['resources'][:20],
                'mediaIds': []}
        out = STORE.write('formats_createIdea', f"new ({kind}): {f['name'][:60]}", market, **args)
        iid = (out or {}).get('id') or f'dry-{len(STORE.writes)}-0000-0000-0000-000000000000'
        idea = {'id': iid, 'campaignId': STORE.camps.get(market) if STORE.camps else None, 'media': [],
                'updatedAt': _now(), **{k: v for k, v in args.items() if k != 'mediaIds'}}
        idea['titles'] = [{'id': None, 'text': t['text']} for t in args['titles']]
        idea['scripts'] = [{'id': None, 'text': s['text']} for s in args['scripts']]
        ideas.append(idea)
        STORE.state()['ideas'][iid] = {'market': market, 'place': kind, 'fp': fingerprint(current(idea), T),
                                       'media_ids': [], 'created': int(time.time())}
        STORE.touched.add((market, iid))
        d = STORE.docs[iid] = Doc.__new__(Doc)
        d.store, d.idea, d.market, d.T, d.n, d.rename, d.stamp = STORE, idea, market, T, 0, None, tmp.stamp
        for b in tmp.blocks:  # the same blocks, now with the idea's id
            b['id'] = b['id'].replace('new.', iid + '.', 1)
        d.blocks, d.n, d.base = tmp.blocks, tmp.n, fields_of(tmp.blocks, T, STORE.links())
        STORE._media(d)
        STORE.save_state()
        return {'id': iid, 'url': PAGE_URL}


def replace_content(page_id, blocks):
    """Everything on a page replaced (a rebuild): changed fields and the new example video are sent."""
    with LOCK:
        d = STORE.doc(page_id)
        if STORE.locked(d):
            return False
        d.blocks = [d.adopt(b, stamp=_now()) for b in blocks]
        STORE.save(d)
        return True


def move_page(page_id, new_parent_id):
    """A page to another place: live = published (creators see it), archive / staging = archived."""
    kind, market = _place(new_parent_id)
    with LOCK:
        m, idea = STORE.find(page_id)
        if m != market:
            raise PageNotFound(f'page {page_id} belongs to {m}, not {market}')
        r = STORE.state()['ideas'].setdefault(idea['id'], {'market': m, 'place': 'archive'})
        STORE.status(m, idea, 'published' if kind == 'live' else 'archived',
                     'published' if kind == 'live' else f'archived ({kind})')
        r['place'] = kind
        STORE.save_state()
        return {'id': idea['id']}


# --- the lists -------------------------------------------------------------------------------------------------------

def _market_of_list(list_page):
    kind, _, market = (list_page or '').partition(':')
    if kind != 'list' or market not in MARKETS:
        raise PageNotFound(f'unknown format list: {list_page}')
    return market


def _ours(market):
    return [i for i in STORE.load(market) if (STORE.rec(i['id']) or {}).get('market') == market]


def list_entries(list_page):
    """[(entry id, page id)] of a market's list in order (going-viral formats first), plus None (no anchor)."""
    m = _market_of_list(list_page)
    with LOCK:
        return [(i['id'], i['id']) for i in _ours(m) if i.get('status') == 'published'], None


def hot_entry_count(list_page):
    """How many formats at the top of the list carry the 🔥 going-viral line."""
    m = _market_of_list(list_page)
    T = STORE.T(m)
    n = 0
    for _, pid in list_entries(list_page)[0]:
        idea = STORE.find(pid)[1]
        if not is_hot(idea.get('description'), T):
            break
        n += 1
    return n


def set_order(list_page, page_ids, hot_count=0, lang=None):
    """The list = these pages in this order: the first hot_count with the 🔥 line, all of them published, our other
    ideas archived; then the ideas made by hand in Megasheet, then the archive."""
    m = _market_of_list(list_page)
    with LOCK:
        T = STORE.T(m)
        ideas = STORE.load(m)
        by = {i['id'].replace('-', '').lower(): i for i in ideas}
        want = []
        for pid in page_ids:
            i = by.get((pid or '').replace('-', '').lower())
            if i is None:
                print(f'pages: {m} list - page {pid} not found in Megasheet (deleted by hand?)', flush=True)
            elif i['id'] not in want:
                want.append(i['id'])
        hot = set(want[:hot_count])
        for iid in want:
            i = next(x for x in ideas if x['id'] == iid)
            r = STORE.state()['ideas'].setdefault(iid, {'market': m, 'place': 'live'})
            if is_hot(i.get('description'), T) != (iid in hot):
                f = current(i)
                f['description'] = set_hot(f['description'], T, iid in hot)
                STORE._update(m, i, f, f"🔥 line {'added' if iid in hot else 'removed'}: {i['name'][:60]}")
            STORE.status(m, i, 'published', 'published (on the list)')
            r['place'] = 'live'
        for i in _ours(m):
            if i['id'] not in want and i.get('status') == 'published':
                STORE.status(m, i, 'archived', 'archived (off the list)')
                STORE.state()['ideas'][i['id']]['place'] = 'archive'
            if i['id'] not in want and is_hot(i.get('description'), T):
                f = current(i)
                f['description'] = set_hot(f['description'], T, False)
                STORE._update(m, i, f, f"🔥 line removed: {i['name'][:60]}")
        rest = [i['id'] for i in ideas if i['id'] not in want]
        order = want + [x for x in rest if next(i for i in ideas if i['id'] == x).get('status') == 'published'] + \
            [x for x in rest if next(i for i in ideas if i['id'] == x).get('status') != 'published']
        if [i['id'] for i in ideas] != order:
            STORE.write('formats_reorderIdeas', f'order: {len(want)} formats ({len(hot)} hot)', m,
                        ids=[x for x in order if not x.startswith('dry-')])
            pos = {x: k for k, x in enumerate(order)}
            ideas.sort(key=lambda i: pos[i['id']])
        STORE.save_state()


# ======================================================================================================================
# one-time migration from the Notion page ids
# ======================================================================================================================

def migrate(formats, save=True):
    """formats.json pages.<market> held Notion page ids. Each becomes the Megasheet idea the old copy step
    (state/megasheet_formats.json) made of it - nothing is rebuilt or duplicated. A page that never had an idea
    (archived formats) is set aside in `notion_pages` (the Notion page stays in Notion, nothing is deleted): if such a
    format comes back, its page is built from its example video like a missing page. Runs once (pages.json
    '_migrated'). Returns a summary dict, or None when already done."""
    S = STORE.state()
    if S.get('_migrated'):
        return None
    old = state.load('megasheet_formats.json', {})
    known = {r['idea'] for m in MARKETS for r in (old.get(m) or {}).values() if r.get('idea')} | set(S['ideas'])
    linked, aside = {m: 0 for m in MARKETS}, {m: 0 for m in MARKETS}
    for f in formats:
        pages = f.get('pages') or {}
        for m in MARKETS:
            pid = pages.get(m)
            if not pid:
                continue
            if pid in known:
                continue  # already a Megasheet idea
            rec = (old.get(m) or {}).get(pid.replace('-', ''))
            if rec and rec.get('idea'):
                pages[m] = rec['idea']
                live = f.get('status') == 'active' and m not in (f.get('off_markets') or [])
                S['ideas'][rec['idea']] = {'market': m, 'place': 'live' if live else 'archive', 'format': f['id'],
                                           **{k: rec[k] for k in ('fp', 'hand', 'media_ids', 'hand_media', 'keep_titles')
                                              if rec.get(k) is not None}}
                linked[m] += 1
            else:
                f.setdefault('notion_pages', {})[m] = pid
                pages.pop(m)
                aside[m] += 1
        if f.get('pending_pages'):
            f['notion_pending_pages'] = f.pop('pending_pages')
    S['_migrated'] = int(time.time())
    if save:  # saved even in a dry run: both files must always agree (the switch only touches the state)
        state.save('formats.json', formats)
        state.save(STATE_FILE, S)
    out = {'linked': linked, 'notion_only': aside}
    print('pages: migrated from Notion page ids to Megasheet ideas:', out, flush=True)
    return out


def summary():
    return f"megasheet format writes{' (dry)' if DRY else ''}: {len(STORE.writes)}"
