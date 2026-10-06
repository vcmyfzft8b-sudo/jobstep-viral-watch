"""Notion API (NOTION_TOKEN): build format pages exactly like our existing ones and manage the DACH list."""
import os
import re
import time

import requests

from . import builder
from .markets import TEXT

API = 'https://api.notion.com/v1'
VERSION = '2022-06-28'


def _headers(json_body=True):
    h = {'Authorization': 'Bearer ' + os.environ['NOTION_TOKEN'], 'Notion-Version': VERSION}
    if json_body:
        h['Content-Type'] = 'application/json'
    return h


def api(method, path, body=None):
    for attempt in range(5):
        r = requests.request(method, API + path, headers=_headers(), json=body, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get('Retry-After', 2 + attempt * 3)))
            continue
        if not r.ok:
            raise RuntimeError(f'Notion {method} {path}: HTTP {r.status_code} {r.text[:400]}')
        return r.json()
    raise RuntimeError(f'Notion {method} {path}: too many retries')


# ---------- rich text helpers ----------

def rt(text, bold=False, link=None, code=False):
    return {'type': 'text', 'text': {'content': text, 'link': {'url': link} if link else None},
            'annotations': {'bold': bold, 'code': code}}


def mention(page_id):
    return {'type': 'mention', 'mention': {'type': 'page', 'page': {'id': page_id}}}


def md(text):
    """Very small markdown subset used in our pages: **bold** and [label](url)."""
    out = []
    for part in re.split(r'(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))', text):
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            out.append(rt(part[2:-2], bold=True))
        elif part.startswith('['):
            label, url = re.match(r'\[([^\]]+)\]\(([^)]+)\)', part).groups()
            out.append(rt(label, link=url))
        else:
            out.append(rt(part))
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


# ---------- file upload ----------

def upload_video(path):
    up = api('POST', '/file_uploads', {'mode': 'single_part', 'filename': os.path.basename(path), 'content_type': 'video/mp4'})
    with open(path, 'rb') as f:
        r = requests.post(f"{API}/file_uploads/{up['id']}/send", headers=_headers(json_body=False),
                          files={'file': (os.path.basename(path), f, 'video/mp4')}, timeout=300)
    if not r.ok:
        raise RuntimeError(f'Notion upload: HTTP {r.status_code} {r.text[:300]}')
    return up['id']


# ---------- page content (same layout as our existing format pages) ----------

def page_blocks(spec, video, file_upload_id, links, lang='de', lab_url=None):
    T = TEXT[lang]
    cue_links = {'parakeet': ('Parakeet AI · Resume Maker', links['parakeet']),
                 'linkedin': (T['cue_linkedin'], links['linkedin'])}
    blocks = [block('heading_1', [rt(T['video_heading'])])]
    if file_upload_id:
        blocks.append(block('video', type='file_upload', file_upload={'id': file_upload_id}))
    blocks.append(para([rt(T['source'], link=video['url'])]))
    blocks.append(block('callout', md(T['inspo_note'][0] + '\n' + T['inspo_note'][1]),
                        icon={'type': 'emoji', 'emoji': '⚠️'}, color='gray_background'))

    blocks.append(block('heading_2', [rt('📲'), rt(T['title_h'], bold=True)]))
    blocks.append(para([rt(spec['title_hook'], bold=True)]))
    sub = T['sub_voice'] if spec.get('voiceover', True) else T['sub_silent']
    blocks.append(block('bulleted_list_item', [rt(sub)]))
    blocks.append(divider())

    blocks.append(block('heading_2', [rt(T['script_h'])]))
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
            parts.append(rt(T['asset_cue'].format(name=seg.get('asset_name') or '📎')))
        elif cue == 'direction' and seg.get('asset_name'):
            parts.append(rt(f"({seg['asset_name']}) "))
        parts.append(rt(seg['text'].strip() + ' ', bold=silent))
        if silent:
            paragraphs.append(parts)
            continue
        if seg.get('new_paragraph') and current:
            paragraphs.append(current)
            current = []
        current += parts
    if current:
        paragraphs.append(current)
    blocks += [para(p) for p in paragraphs]
    blocks.append(divider())

    blocks.append(block('heading_2', [rt(T['hook_h'])]))
    blocks += [para([rt(line)]) for line in builder.hook_lines(spec, lang)]
    blocks.append(para([rt(T['required_line'])]))
    blocks.append(para([rt('Visual Hook Lab', link=lab_url or links.get('visual_hook_lab'))]))
    blocks.append(divider())

    blocks.append(block('heading_2', [rt('🔧'), rt(T['res_h'], bold=True)]))
    res = [rt('Parakeet AI · Resume Maker', link=links['parakeet'])]
    for asset in spec.get('assets_needed', []):
        res.append(rt(f"\n📎 {asset['name']} – {T['asset_todo']}: {asset.get('description', '')}"))
    blocks.append(block('callout', res, icon={'type': 'emoji', 'emoji': '💡'}, color='gray_background'))
    return blocks


def create_page(parent_id, title, icon, blocks):
    first, rest = blocks[:90], blocks[90:]
    page = api('POST', '/pages', {'parent': {'page_id': parent_id}, 'icon': {'type': 'emoji', 'emoji': icon},
                                  'properties': {'title': {'title': [rt(title)]}}, 'children': first})
    while rest:
        api('PATCH', f"/blocks/{page['id']}/children", {'children': rest[:90]})
        rest = rest[90:]
    return page


def replace_content(page_id, blocks):
    """Replace everything on a page with new blocks (title and page link stay the same)."""
    for b in children(page_id):
        api('DELETE', f"/blocks/{b['id']}")
    while blocks:
        api('PATCH', f'/blocks/{page_id}/children', {'children': blocks[:90]})
        blocks = blocks[90:]


def move_page(page_id, new_parent_id):
    """Move a page under another page (Notion API 2025-09-03 'move page' endpoint)."""
    h = _headers()
    h['Notion-Version'] = '2025-09-03'
    r = requests.post(f'{API}/pages/{page_id}/move', headers=h, timeout=60,
                      json={'parent': {'type': 'page_id', 'page_id': new_parent_id}})
    if not r.ok:
        raise RuntimeError(f'Notion move: HTTP {r.status_code} {r.text[:300]}')
    return r.json()


# ---------- the DACH list ----------

def children(block_id):
    out, cursor = [], None
    while True:
        q = f'/blocks/{block_id}/children?page_size=100' + (f'&start_cursor={cursor}' if cursor else '')
        r = api('GET', q)
        out += r['results']
        if not r.get('has_more'):
            return out
        cursor = r['next_cursor']


def _icon(b):
    return ((b.get(b['type']) or {}).get('icon') or {}).get('emoji')


SECTION_ICONS = ('📈', '🚀', '⬇️')  # older section header callouts (no page link) - removed on the next re-sort


def _page_mention(b):
    return next((x['mention']['page']['id'] for x in b['callout']['rich_text']
                 if x['type'] == 'mention' and x['mention']['type'] == 'page'), None)


def _is_empty(b):
    return b['type'] == 'paragraph' and not b['paragraph']['rich_text']


def _layout(list_page):
    """Splits the list page into its parts.

    Layout: <heading> · going-viral entries (gray ▶️ callouts "Dreh das jetzt – geht gerade viral: <page>") · empty line ·
    🔥 instructions · ▶️ entries · 🚨 rule. Returns dict(blocks, top_anchor, top_ids, fire_anchor, entries, stale)."""
    blocks = children(list_page)
    fire = next(i for i, b in enumerate(blocks) if b['type'] == 'callout' and _icon(b) == '🔥')
    top, stale, k = [], [], fire - 1
    while k >= 0 and (_is_empty(blocks[k]) or (blocks[k]['type'] == 'callout' and (
            _page_mention(blocks[k]) or _icon(blocks[k]) in SECTION_ICONS))):
        b = blocks[k]
        if b['type'] == 'callout' and _page_mention(b):
            top.insert(0, (b['id'], _page_mention(b)))
        else:
            stale.append(b['id'])  # spacer lines / old headers above 🔥
        k -= 1
    fire_anchor = blocks[fire]['id']
    if fire + 1 < len(blocks) and _is_empty(blocks[fire + 1]):
        fire_anchor = blocks[fire + 1]['id']
    rest = []
    for b in blocks[fire + 1:]:
        if b['type'] == 'callout' and _icon(b) == '🚨':
            break
        if b['type'] == 'callout' and _page_mention(b):
            rest.append((b['id'], _page_mention(b)))
        elif b['type'] == 'callout' and _icon(b) in SECTION_ICONS:
            stale.append(b['id'])
    return {'blocks': blocks, 'top_anchor': blocks[k]['id'] if k >= 0 else None, 'top': top,
            'fire_anchor': fire_anchor, 'rest': rest, 'stale': stale}


def list_entries(list_page):
    """[(callout_block_id, page_id)] in order (going-viral formats at the top first), plus the 🔥 anchor."""
    L = _layout(list_page)
    return L['top'] + L['rest'], L['fire_anchor']


def hot_entry_count(list_page):
    """How many formats are shown in the going-viral spot above the 🔥 instructions."""
    return len(_layout(list_page)['top'])


def _insert(list_page, blocks, anchor):
    for i in range(0, len(blocks), 90):
        body = {'children': blocks[i:i + 90]}
        if anchor:
            body['after'] = anchor
        r = api('PATCH', f'/blocks/{list_page}/children', body)
        anchor = r['results'][-1]['id']


def set_order(list_page, page_ids, hot_count=0, lang='de'):
    """Rewrite the list: hot formats at the very top (above the 🔥 instructions, same gray ▶️ box with
    "Dreh das jetzt – geht gerade viral:" in front), then the rest under 🔥; number the titles 1., 2., ..."""
    T = TEXT[lang]
    page_ids = list(dict.fromkeys(p.replace('-', '') for p in page_ids))  # never show a format twice
    L = _layout(list_page)
    for block_id in [e[0] for e in L['top'] + L['rest']] + L['stale']:
        api('DELETE', f'/blocks/{block_id}')
    box = {'icon': {'type': 'emoji', 'emoji': '▶️'}, 'color': 'gray_background'}
    hot = [block('callout', [rt(T['hot_header'] + ' ', bold=True), mention(pid)], **box) for pid in page_ids[:hot_count]]
    if hot:
        _insert(list_page, hot + [block('paragraph', [])], L['top_anchor'])
    _insert(list_page, [block('callout', [mention(pid)], **box) for pid in page_ids[hot_count:]], L['fire_anchor'])
    # keep at most one empty line after the 🚨 rule
    blocks = children(list_page)
    rule = next((k for k, b in enumerate(blocks) if b['type'] == 'callout' and _icon(b) == '🚨'), None)
    if rule is not None:
        empties = [b['id'] for b in blocks[rule + 1:] if _is_empty(b)]
        for bid in empties[1:]:
            api('DELETE', f'/blocks/{bid}')
    for i, pid in enumerate(page_ids, 1):
        page = api('GET', f'/pages/{pid}')
        prop = next(v for v in page['properties'].values() if v['type'] == 'title')
        title = ''.join(x['plain_text'] for x in prop['title'])
        new_title = f'{i}. ' + re.sub(r'^\d+\.\s*', '', title)
        if new_title != title:
            api('PATCH', f'/pages/{pid}', {'properties': {'title': {'title': [rt(new_title)]}}})


def append_log(radar_page, rich):
    api('PATCH', f'/blocks/{radar_page}/children', {'children': [block('bulleted_list_item', rich)]})
