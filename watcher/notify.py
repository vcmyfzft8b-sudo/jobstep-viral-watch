"""Notifications: Slack (SLACK_WEBHOOK_URL), optional phone push via ntfy (NTFY_TOPIC),
plus a log line on the private Notion radar page."""
import os

import requests

from . import notion


def slack(title, message, click=None):
    url = os.environ.get('SLACK_WEBHOOK_URL')
    if not url:
        return
    text = f'*{title}*\n{message}' + (f'\n<{click}|▶ Öffnen>' if click else '')
    try:
        requests.post(url, json={'text': text, 'unfurl_links': False}, timeout=20)
    except requests.RequestException:
        pass


def push(title, message, click=None, tags=''):
    slack(title, message, click)
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
