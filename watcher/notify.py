"""Notifications: phone push via ntfy (NTFY_TOPIC, optional) + a log line on the private Notion radar page."""
import os

import requests

from . import notion


def push(title, message, click=None, tags=''):
    topic = os.environ.get('NTFY_TOPIC')
    if not topic:
        return
    headers = {'Title': title.encode('utf-8'), 'Tags': tags, 'Priority': 'high'}
    if click:
        headers['Click'] = click
    try:
        requests.post(f'https://ntfy.sh/{topic}', data=message.encode('utf-8'), headers=headers, timeout=20)
    except requests.RequestException:
        pass


def radar(radar_page, text, link=None, link_label=None):
    if not radar_page:
        return
    rich = [notion.rt(text)]
    if link:
        rich.append(notion.rt(' ' + (link_label or 'Link'), link=link))
    try:
        notion.append_log(radar_page, rich)
    except RuntimeError as e:
        print('radar log failed:', str(e)[:200])
