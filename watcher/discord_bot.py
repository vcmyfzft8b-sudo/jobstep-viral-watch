"""Our own Discord bot (DISCORD_BOT_TOKEN): posts into every creator's private channel of a server.

Creator channels = text channels inside the categories whose name starts with config discord.creator_category_prefix
("Creators 1", "Creators 2", ...). The creator is pinged via the member permission of their channel. The bot only ever
touches the servers listed in config.json markets (never e.g. the Talking Head server).
"""
import os
import time

import requests

API = 'https://discord.com/api/v10'


def token():
    return os.environ.get('DISCORD_BOT_TOKEN', '')


def _req(method, path, **kw):
    for _ in range(5):
        r = requests.request(method, API + path, headers={'Authorization': f'Bot {token()}'}, timeout=20, **kw)
        if r.status_code == 429:
            time.sleep(float(r.json().get('retry_after', 2)) + 0.5)
            continue
        r.raise_for_status()
        return r.json() if r.content else {}
    raise RuntimeError(f'Discord rate limit: {path}')


def allowed_servers(cfg):
    return {m['discord_server'] for m in cfg['markets'].values() if m.get('discord_server')}


def creator_channels(guild_id, cfg):
    """[{'id', 'name', 'members': [user ids with their own permission on the channel]}]"""
    if guild_id not in allowed_servers(cfg):
        raise ValueError(f'server {guild_id} is not one of our markets')
    prefix = cfg.get('discord', {}).get('creator_category_prefix', 'Creators').lower()
    me = _req('GET', '/users/@me')['id']
    chans = _req('GET', f'/guilds/{guild_id}/channels')
    cats = {c['id'] for c in chans if c['type'] == 4 and c['name'].lower().startswith(prefix)}
    out = []
    for c in sorted((c for c in chans if c['type'] == 0 and c.get('parent_id') in cats), key=lambda c: c.get('position', 0)):
        members = [o['id'] for o in c.get('permission_overwrites', []) if o['type'] == 1 and o['id'] != me
                   and int(o.get('allow', 0)) & 1024]
        out.append({'id': c['id'], 'name': c['name'], 'members': members})
    return out


def send(channel_id, text, mention_ids=()):
    prefix = ''.join(f'<@{u}> ' for u in mention_ids)
    _req('POST', f'/channels/{channel_id}/messages',
         json={'content': prefix + text, 'allowed_mentions': {'users': list(mention_ids)}})
    time.sleep(0.4)
