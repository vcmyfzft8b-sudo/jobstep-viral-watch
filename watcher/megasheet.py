"""Megasheet (megasheet.app): the source of truth for our own Parakeet AI creators.

Every run reads the TikTok accounts and the TikTok + Instagram videos of the three Parakeet AI campaigns (DACH, France, Spain) through
Megasheet's MCP server (read-only) and merges them into state/own_accounts.json + state/own.json (see own.py).

Login: Megasheet has no API key, only "log in with your account" (OAuth). scripts/save_megasheet_login.sh logs in once
on the Mac and saves two GitHub secrets:
  MEGASHEET_LOGIN  the long-lived login (refresh token + client id, base64 JSON)
  MEGASHEET_KEY    a random key that encrypts newer logins Megasheet hands out
If Megasheet replaces the refresh token on use, the new one is kept encrypted in state/megasheet_login.enc (the state
branch is public, so never in plain text). Without the secrets the sync is skipped and everything else runs as before.
"""
import base64
import calendar
import hashlib
import json
import os
import re
import subprocess
import time

import requests

from . import state

BASE = 'https://megasheet.app'
MCP_URL = BASE + '/api/mcp'
TOKEN_URL = BASE + '/api/oauth/token'
CAMPAIGNS = {'ParakeetAI - DACH': 'de', 'ParakeetAI - France': 'fr', 'ParakeetAI - Spain': 'es',
             'ParakeetAI - Slovenia': 'sl'}
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

# What the watcher may do in Megasheet. A Megasheet login is either read-only or read + write for everything (its only
# scopes are mcp:read / mcp:write), so the limit is kept here, before anything is sent (user, 16 Oct 2026: "only write
# access for writing the formats, nothing else; nothing about DACH"):
# - reading: the campaign list, accounts, videos and the formats pages;
# - writing: only the format ideas (+ their example media) of the France, Spain and Slovenia campaigns, and only ideas
#   and media read from or created in that same campaign. Never DACH, never page settings, guides, creators, payouts.
READ_TOOLS = {'list_campaigns', 'account_getMany', 'videos_getMany', 'formats_getIdeas', 'formats_getGroups',
              'formats_getGuides', 'formats_getPageSettings'}
WRITE_TOOLS = {'formats_createIdea', 'formats_updateIdea', 'formats_updateIdeaStatus', 'formats_reorderIdeas',
               'formats_addMediaFromUrl', 'formats_removeMedia'}
WRITE_CAMPAIGNS = {'5cf4df12-f6dd-467a-a1e8-dbe07f709425': 'ParakeetAI - France',
                   'f70ac122-5e87-4780-9229-65b2740bfb3a': 'ParakeetAI - Spain',
                   '28808b83-9313-4575-afc9-7b0805c497a5': 'ParakeetAI - Slovenia'}


class NotAllowed(Exception):
    pass


class Client:
    def __init__(self, token):
        self.known = {}  # campaign id -> ids of its ideas and media (the only ones a write may touch)
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

    def _check(self, tool, args):
        if tool in READ_TOOLS:
            return
        if tool not in WRITE_TOOLS:
            raise NotAllowed(f'megasheet: {tool} is not allowed for the watcher')
        camp = args.get('campaignId')
        if camp not in WRITE_CAMPAIGNS:  # also: no campaign = Megasheet's "active campaign" - never written blindly
            raise NotAllowed(f'megasheet: {tool} refused - campaign {camp} is not France, Spain or Slovenia')
        known = self.known.get(camp)
        if known is None:
            raise NotAllowed(f'megasheet: {tool} refused - the formats of {WRITE_CAMPAIGNS[camp]} were not read first')
        targets = [args[k] for k in ('id', 'ideaId') if args.get(k)] + list(args.get('ids') or [])
        if tool == 'formats_updateIdea' and args.get('groupId'):
            targets.append(args['groupId'])
        unknown = [t for t in targets if t not in known]
        if unknown:
            raise NotAllowed(f'megasheet: {tool} refused - {len(unknown)} id(s) not in {WRITE_CAMPAIGNS[camp]}')

    def _remember(self, tool, args, out):
        camp = args.get('campaignId')
        if tool == 'formats_getIdeas' and camp:
            ids = self.known.setdefault(camp, set())
            for i in out or []:
                ids.add(i['id'])
                ids.update(m['id'] for m in i.get('media', []))
                if i.get('groupId'):
                    ids.add(i['groupId'])
        elif tool in ('formats_createIdea', 'formats_addMediaFromUrl') and isinstance(out, dict) and out.get('id'):
            self.known[camp].add(out['id'])

    def call(self, tool, **args):
        self._check(tool, args)
        out = self._call(tool, **args)
        self._remember(tool, args, out)
        return out

    def _call(self, tool, **args):
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


IG_LINK = re.compile(r'instagram\.com/(?:[^/?#]+/)?(?:reels?|p)/([A-Za-z0-9_-]+)')


def video_key(v):
    """(key, platform) of a Megasheet video row: TikTok -> its numeric id, Instagram -> 'ig_<shortcode>'."""
    vid = video_id(v)
    if vid:
        return vid, 'tiktok'
    m = IG_LINK.search(v.get('adLink') or '')
    return ('ig_' + m.group(1), 'instagram') if m else (None, None)


def _created(row, key):
    """Upload time: TikTok ids carry it; Instagram rows use Megasheet's createdAt/uploadedAt."""
    if key.isdigit():
        return int(key) >> 32
    for field, fmt in (('createdAt', '%Y-%m-%dT%H:%M:%S'), ('uploadedAt', '%Y-%m-%d')):
        raw = (row.get(field) or '')[:19 if field == 'createdAt' else 10]
        try:
            return int(calendar.timegm(time.strptime(raw, fmt)))
        except ValueError:
            continue
    return 0


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
    """rows: [(market, video_row)]. Megasheet only lists campaign videos, so they are ours; views only go up.
    Instagram videos are kept too (key 'ig_<shortcode>'): there is no TikTok page to read, so they are sorted into a
    format from their caption or from the creator's TikTok post of the same video (own.update)."""
    new = 0
    for market, row in rows:
        vid, platform = video_key(row)
        if not vid:
            continue
        handle = ((row.get('account') or {}).get('handle') or row.get('username') or '').lower()
        v = videos.get(vid)
        if v is None:
            v = videos[vid] = {'handle': handle, 'market': market, 'created': _created(row, vid), 'views': 0,
                               'desc': (row.get('title') or '')[:300]}
            if platform == 'instagram':
                v.update({'sticker': '', 'subtitles': ''})  # caption only - no TikTok details to wait for
            new += 1
        v['platform'] = platform
        creator = (row.get('creator') or {}).get('id')
        if creator:
            v['creator'] = creator
        if not v.get('ours'):
            v['ours'] = True
            v.pop('checked', None)  # was skipped as "not ours" - sort it into a format after all
        v['views'] = max(v.get('views', 0), int(row.get('views') or 0))
        for k in ('likes', 'comments', 'shares', 'bookmarks'):
            if row.get(k) is not None:
                v[k] = max(v.get(k, 0), int(row[k]))
        v['megasheet'] = int(now)
    return new


def sync(accounts, videos, now, full=False, markets=None):
    """Reads the campaigns of the given markets (default: all) and merges them in. Returns a summary dict, or None
    when no login is saved. Creators of a stopped market (not in markets) are paused - their old videos stay."""
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
        if markets is not None and market not in markets:
            continue
        if name not in camps:
            raise RuntimeError(f'megasheet: campaign "{name}" not found')
        acc_rows += [(market, a) for a in c.pages('account_getMany', campaignId=camps[name], filters=TIKTOK)]
        vf = [] if full else [{'field': 'uploadedAt', 'kind': 'date', 'op': 'gte', 'value': since}]  # TikTok + Instagram
        vid_rows += [(market, v) for v in c.pages('videos_getMany', campaignId=camps[name], filters=vf)]
    added, paused, revived = merge_accounts(accounts, acc_rows, now)
    new = merge_videos(videos, vid_rows, now)
    if full:
        info['full_sync'] = int(now)
    info['last_ok'] = int(now)
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
