"""Notion API (NOTION_TOKEN) - since 16 Oct 2026 ONLY for the private radar log page (notify.radar).

The format pages and lists live in Megasheet (watcher/pages.py); the old Notion format pages stay where they are in
Notion (nothing deleted) but are no longer read or written."""
import os
import re
import time

import requests


API = 'https://api.notion.com/v1'
VERSION = '2022-06-28'


def _headers(json_body=True):
    h = {'Authorization': 'Bearer ' + os.environ['NOTION_TOKEN'], 'Notion-Version': VERSION}
    if json_body:
        h['Content-Type'] = 'application/json'
    return h


def api(method, path, body=None, version=None):
    for attempt in range(5):
        h = _headers()
        if version:
            h['Notion-Version'] = version
        try:
            r = requests.request(method, API + path, headers=h, json=body, timeout=120)
        except (requests.Timeout, requests.ConnectionError):
            time.sleep(5 + attempt * 5)  # Notion was slow: try again
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get('Retry-After', 2 + attempt * 3)))
            continue
        if not r.ok:
            raise RuntimeError(f'Notion {method} {path}: HTTP {r.status_code} {r.text[:400]}')
        return r.json()
    raise RuntimeError(f'Notion {method} {path}: too many retries')


# ---------- the radar log ----------

def rt(text, bold=False, link=None):
    return {'type': 'text', 'text': {'content': text, 'link': {'url': link} if link else None},
            'annotations': {'bold': bold}}


def append_log(radar_page, rich):
    api('PATCH', f'/blocks/{radar_page}/children',
        {'children': [{'object': 'block', 'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': rich}}]})
