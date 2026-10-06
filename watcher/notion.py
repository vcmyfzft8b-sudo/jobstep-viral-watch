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


def list_entries(dach_page):
    """[(callout_block_id, page_id)] in order, plus the id of the block the list comes after."""
    blocks = children(dach_page)
    start = next(i for i, b in enumerate(blocks) if b['type'] == 'callout' and _icon(b) == '🔥')
    entries, anchor = [], blocks[start]['id']
    for b in blocks[start + 1:]:
        if b['type'] == 'callout' and _icon(b) == '🚨':
            break
        if b['type'] == 'callout' and _icon(b) != HOT_ICON:
            pid = next((x['mention']['page']['id'] for x in b['callout']['rich_text']
                        if x['type'] == 'mention' and x['mention']['type'] == 'page'), None)
            if pid:
                entries.append((b['id'], pid))
                continue
        if not entries:
            anchor = b['id']
    return entries, anchor


def set_order(dach_page, page_ids):
    """Rewrite the list so it shows page_ids in this order, and number the page titles 1., 2., ..."""
    entries, anchor = list_entries(dach_page)
    style = {'icon': {'type': 'emoji', 'emoji': '▶️'}, 'color': 'gray_background'}
    if entries:  # keep the look of the existing list entries
        first = api('GET', f'/blocks/{entries[0][0]}')['callout']
        style = {k: first[k] for k in ('icon', 'color') if first.get(k)}
    for block_id, _ in entries:
        api('DELETE', f'/blocks/{block_id}')
    callouts = [block('callout', [mention(pid)], **style) for pid in page_ids]
    api('PATCH', f'/blocks/{dach_page}/children', {'children': callouts, 'after': anchor})
    for i, pid in enumerate(page_ids, 1):
        page = api('GET', f'/pages/{pid}')
        prop = next(v for v in page['properties'].values() if v['type'] == 'title')
        title = ''.join(x['plain_text'] for x in prop['title'])
        new = f'{i}. ' + re.sub(r'^\d+\.\s*', '', title)
        if new != title:
            api('PATCH', f'/pages/{pid}', {'properties': {'title': {'title': [rt(new)]}}})


HOT_ICON = '🚀'


def set_hot(dach_page, hot, lang='de'):
    """hot: [(page_id, viral_count)]. Shows them as 🚀 callouts right under the 🔥 instructions (top of the list)."""
    T = TEXT[lang]
    blocks = children(dach_page)
    fire = next(b for b in blocks if b['type'] == 'callout' and _icon(b) == '🔥')
    for b in blocks:
        if b['type'] == 'callout' and _icon(b) == HOT_ICON:
            api('DELETE', f"/blocks/{b['id']}")
    if not hot:
        return
    callouts = [block('callout', [rt(T['hot_prefix'], bold=True), mention(pid), rt(T['hot_suffix'].format(n=n))],
                      icon={'type': 'emoji', 'emoji': HOT_ICON}, color='orange_background') for pid, n in hot]
    api('PATCH', f'/blocks/{dach_page}/children', {'children': callouts, 'after': fire['id']})


def append_log(radar_page, rich):
    api('PATCH', f'/blocks/{radar_page}/children', {'children': [block('bulleted_list_item', rich)]})
