"""Megasheet (megasheet.app): the source of truth for our own Parakeet AI creators.

Every run reads the TikTok accounts and videos of the three Parakeet AI campaigns (DACH, France, Spain) through
Megasheet's MCP server (read-only) and merges them into state/own_accounts.json + state/own.json (see own.py).

Login: Megasheet has no API key, only "log in with your account" (OAuth). scripts/save_megasheet_login.sh logs in once
on the Mac and saves two GitHub secrets:
  MEGASHEET_LOGIN  the long-lived login (refresh token + client id, base64 JSON)
  MEGASHEET_KEY    a random key that encrypts newer logins Megasheet hands out
If Megasheet replaces the refresh token on use, the new one is kept encrypted in state/megasheet_login.enc (the state
branch is public, so never in plain text). Without the secrets the sync is skipped and everything else runs as before.
"""
import base64
import hashlib
import json
import os
import subprocess
import time

import requests

from . import state

BASE = 'https://megasheet.app'
MCP_URL = BASE + '/api/mcp'
TOKEN_URL = BASE + '/api/oauth/token'
CAMPAIGNS = {'ParakeetAI - DACH': 'de', 'ParakeetAI - France': 'fr', 'ParakeetAI - Spain': 'es'}
RECENT_DAYS = 14  # normal runs re-read videos uploaded in the last 14 days; own-sync reads everything
LOGIN_FILE = 'megasheet_login.enc'
INFO_FILE = 'megasheet.json'  # {used_secret: sha256 of a consumed secret login, warned: ts, full_sync: ts}


class LoginError(Exception):
    pass


# --- login --------------------------------------------------------------------------------------------------------

def _crypt(data, decrypt=False):
    args = ['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000', '-a', '-A', '-pass', 'env:MEGASHEET_KEY']
    r = subprocess.run(args + (['-d'] if decrypt else ['-salt']), input=data.encode(), capture_output=True, check=True)
    return r.stdout.decode()


def _secret_login():
    raw = os.environ.get('MEGASHEET_LOGIN', '').strip()
    if not raw:
        return None
    try:
        return json.loads(base64.b64decode(raw))
    except ValueError:
        raise LoginError('MEGASHEET_LOGIN is not readable - run scripts/save_megasheet_login.sh again')


def _refresh(login):
    r = requests.post(TOKEN_URL, data={'grant_type': 'refresh_token', 'refresh_token': login['refresh_token'],
                                       'client_id': login['client_id'], 'resource': MCP_URL}, timeout=30)
    if r.status_code != 200:
        raise LoginError(f'Megasheet login refused ({r.status_code})')
    return r.json()


def access_token():
    """A fresh access token, or None when no login is saved. Tries the newest saved login first; the secret one is
    only used while it has not been replaced yet (re-using a replaced login can make Megasheet revoke all of them)."""
    secret = _secret_login()
    if secret is None:
        return None
    if not os.environ.get('MEGASHEET_KEY'):
        raise LoginError('MEGASHEET_KEY missing - run scripts/save_megasheet_login.sh again')
    info = state.load(INFO_FILE, {})
    fingerprint = hashlib.sha256(secret['refresh_token'].encode()).hexdigest()
    candidates = []
    try:
        with open(os.path.join(state.DIR, LOGIN_FILE)) as f:
            candidates.append(json.loads(_crypt(f.read(), decrypt=True)))
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        pass  # no newer login yet, or it was encrypted with an older key
    if info.get('used_secret') != fingerprint:
        candidates.append(secret)
    error = None
    for login in candidates:
        try:
            tok = _refresh(login)
        except LoginError as e:
            error = e
            continue
        newer = tok.get('refresh_token')
        if newer and newer != login['refresh_token']:  # Megasheet replaced the login: keep the new one
            if login is secret:
                info['used_secret'] = fingerprint
            os.makedirs(state.DIR, exist_ok=True)
            with open(os.path.join(state.DIR, LOGIN_FILE), 'w') as f:
                f.write(_crypt(json.dumps({'refresh_token': newer, 'client_id': login['client_id']})))
        info.pop('warned', None)
        state.save(INFO_FILE, info)
        return tok['access_token']
    state.save(INFO_FILE, info)
    raise error or LoginError('Megasheet login used up - run scripts/save_megasheet_login.sh again')


# --- MCP client (streamable HTTP, read-only tools) ------------------------------------------------------------------

class Client:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                               'Accept': 'application/json, text/event-stream'})
        self.n = 0
        init = self._rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                        'clientInfo': {'name': 'jobstep-viral-watch', 'version': '1'}})
        self.s.headers['MCP-Protocol-Version'] = init.get('protocolVersion', '2025-06-18')
        self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def _post(self, body):
        r = self.s.post(MCP_URL, json=body, timeout=60)
        if r.status_code == 401:
            raise LoginError('Megasheet rejected the access token')
        r.raise_for_status()
        if r.headers.get('mcp-session-id'):
            self.s.headers['Mcp-Session-Id'] = r.headers['mcp-session-id']
        return r

    def _rpc(self, method, params):
        self.n += 1
        r = self._post({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params})
        msg = _message(r, self.n, method)
        if 'error' in msg:
            raise RuntimeError(f"megasheet {method}: {msg['error'].get('message', msg['error'])}")
        return msg['result']

    def call(self, tool, **args):
        res = self._rpc('tools/call', {'name': tool, 'arguments': args})
        text = ''.join(c.get('text', '') for c in res.get('content', []) if c.get('type') == 'text')
        if res.get('isError'):
            raise RuntimeError(f'megasheet {tool}: {text[:200]}')
        return res.get('structuredContent') or json.loads(text)

    def pages(self, tool, **args):
        page = 1
        while True:
            out = self.call(tool, page=page, limit=100, **args)
            yield from out.get('data', [])
            if page >= out.get('pagination', {}).get('total_pages', 1):
                return
            page += 1


def _events(text):
    """Server-sent events -> list of (event name, data): events end at a blank line, data lines are joined."""
    out, name, data = [], 'message', []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') + ['']:
        if not line:
            if data:
                out.append((name, '\n'.join(data)))
            name, data = 'message', []
        elif line.startswith('data:'):
            data.append(line[5:][1:] if line[5:6] == ' ' else line[5:])
        elif line.startswith('event:'):
            name = line[6:].strip()
    return out


def _message(r, rid, method=''):
    """The JSON-RPC answer with our id - the server may answer as plain JSON (single or batch) or as an event stream.
    When nothing matches, the error names only the shape of the answer (never its data: the run log is public)."""
    ctype = r.headers.get('content-type', '')
    body = r.content.decode('utf-8', 'replace')
    if 'text/event-stream' in ctype:
        events = _events(body)
        msgs = []
        for _, data in events:
            try:
                msgs.append(json.loads(data))
            except ValueError:
                pass
    else:
        events, msgs = [], [json.loads(body)] if body.strip() else []
    flat = [m for x in msgs for m in (x if isinstance(x, list) else [x]) if isinstance(m, dict)]
    for m in flat:
        if str(m.get('id')) == str(rid) and ('result' in m or 'error' in m):
            return m
    shape = [{'id': m.get('id'), 'method': m.get('method'), 'keys': sorted(m)[:6]} for m in flat][:5]
    raise RuntimeError(f'megasheet {method}: no answer (status {r.status_code}, {ctype or "no type"}, {len(body)} chars, '
                       f'{len(events)} events, {len(msgs)} parsed, {shape})')


# --- merge into our state -----------------------------------------------------------------------------------------

TIKTOK = [{'field': 'platform', 'kind': 'enum', 'op': 'equals', 'value': 'tiktok'}]


def tracked(acc):
    """Track an account unless Megasheet says it is gone (removed, scam) or the creator left without ever posting."""
    creator = acc.get('creator') or {}
    if acc.get('status') == 'removed' or creator.get('status') == 'scam':
        return False
    return not (creator.get('status') in ('stopped', 'ghosted') and not acc.get('firstPostedAt'))


def video_id(v):
    link = v.get('adLink') or ''
    vid = link.split('/video/')[-1].split('?')[0].split('/')[0] if '/video/' in link else ''
    return vid if vid.isdigit() else None


def merge_accounts(accounts, rows, now):
    """rows: [(market, account_row)] for every campaign. Megasheet decides for megasheet creators: new ones are added,
    gone ones paused, returning ones revived. Accounts found elsewhere (Lightreel) are upgraded to megasheet."""
    added, paused, revived, seen = [], [], [], set()
    for market, acc in rows:
        h = (acc.get('handle') or '').lower().lstrip('@')
        if not h:
            continue
        if h in seen and not tracked(acc):
            continue  # the same handle twice (e.g. two campaigns): one tracked entry wins
        seen.add(h)
        status = 'active' if tracked(acc) else 'inactive'
        a = accounts.get(h)
        if a is None:
            if status == 'active':
                accounts[h] = {'status': 'active', 'since': int(now), 'source': 'megasheet', 'market': market}
                added.append(h)
            continue
        a.update({'source': 'megasheet', 'market': market})
        if a.get('status') != status:
            a['status'] = status
            (revived if status == 'active' else paused).append(h)
    for h, a in accounts.items():
        if a.get('source') == 'megasheet' and h not in seen and a.get('status') == 'active':
            a['status'] = 'inactive'
            paused.append(h)
    return added, paused, revived


def merge_videos(videos, rows, now):
    """rows: [(market, video_row)]. Megasheet only lists campaign videos, so they are ours; views only go up."""
    new = 0
    for market, row in rows:
        vid = video_id(row)
        if not vid:
            continue
        handle = ((row.get('account') or {}).get('handle') or row.get('username') or '').lower()
        v = videos.get(vid)
        if v is None:
            v = videos[vid] = {'handle': handle, 'market': market, 'created': int(vid) >> 32, 'views': 0,
                               'desc': (row.get('title') or '')[:300]}
            new += 1
        if not v.get('ours'):
            v['ours'] = True
            v.pop('checked', None)  # was skipped as "not ours" - sort it into a format after all
        v['views'] = max(v.get('views', 0), int(row.get('views') or 0))
        for k in ('likes', 'comments', 'shares', 'bookmarks'):
            if row.get(k) is not None:
                v[k] = max(v.get(k, 0), int(row[k]))
        v['megasheet'] = int(now)
    return new


def sync(accounts, videos, now, full=False):
    """Reads the campaigns and merges them in. Returns a summary dict, or None when no login is saved."""
    token = access_token()
    if token is None:
        return None
    c = Client(token)
    info = state.load(INFO_FILE, {})
    full = full or not info.get('full_sync')
    camps = {x['name']: x['id'] for x in c.call('list_campaigns')}
    acc_rows, vid_rows = [], []
    since = time.strftime('%Y-%m-%d', time.gmtime(now - RECENT_DAYS * 86400))
    for name, market in CAMPAIGNS.items():
        if name not in camps:
            raise RuntimeError(f'megasheet: campaign "{name}" not found')
        acc_rows += [(market, a) for a in c.pages('account_getMany', campaignId=camps[name], filters=TIKTOK)]
        vf = TIKTOK + ([] if full else [{'field': 'uploadedAt', 'kind': 'date', 'op': 'gte', 'value': since}])
        vid_rows += [(market, v) for v in c.pages('videos_getMany', campaignId=camps[name], filters=vf)]
    added, paused, revived = merge_accounts(accounts, acc_rows, now)
    new = merge_videos(videos, vid_rows, now)
    if full:
        info['full_sync'] = int(now)
    state.save(INFO_FILE, info)
    return {'accounts': len(acc_rows), 'videos': len(vid_rows), 'new_videos': new, 'added': added,
            'paused': paused, 'revived': revived, 'full': full}


def should_warn(now):
    """At most one 'log in again' message per day."""
    info = state.load(INFO_FILE, {})
    if now - info.get('warned', 0) < 86400:
        return False
    info['warned'] = int(now)
    state.save(INFO_FILE, info)
    return True
