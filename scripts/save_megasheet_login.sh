#!/bin/zsh
# Logs in to Megasheet once (browser) and saves the long-lived login for the 6-hourly GitHub run:
#   MEGASHEET_LOGIN  refresh token + client id (base64 JSON)   MEGASHEET_KEY  random key for newer logins
# Nothing secret is printed. Run again whenever the run says "Megasheet login needed".
REPO="${1:-vcmyfzft8b-sudo/jobstep-viral-watch}"
LOGIN="$(/usr/bin/python3 - <<'EOF'
import base64, hashlib, http.server, json, os, secrets, sys, urllib.parse, urllib.request, webbrowser

BASE, PORT = 'https://megasheet.app', 8765
REDIRECT, RESOURCE, SCOPE = f'http://127.0.0.1:{PORT}/callback', BASE + '/api/mcp', 'mcp:read offline_access'


def post(url, data, as_json=False):
    body = json.dumps(data).encode() if as_json else urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json' if as_json
                                             else 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f'❌ Megasheet hat abgelehnt ({e.code}) – nochmal starten.')


client = post(BASE + '/api/oauth/register', {
    'client_name': 'JobStep viral watch (GitHub Actions)', 'redirect_uris': [REDIRECT],
    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
    'token_endpoint_auth_method': 'none', 'scope': SCOPE}, as_json=True)
verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
st = secrets.token_urlsafe(16)
result = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get('state', [''])[0] == st:
            result.update(code=q.get('code', [''])[0], error=q.get('error', [''])[0])
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write('Fertig – du kannst dieses Fenster schließen.'.encode())

    def log_message(self, *a):
        pass


server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
url = BASE + '/oauth/authorize?' + urllib.parse.urlencode({
    'response_type': 'code', 'client_id': client['client_id'], 'redirect_uri': REDIRECT, 'scope': SCOPE,
    'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': st, 'resource': RESOURCE})
print('Im Browser bei Megasheet anmelden und "Allow" klicken …', file=sys.stderr)
webbrowser.open(url)
while not result:
    server.handle_request()
if not result.get('code'):
    sys.exit(f"❌ Anmeldung abgebrochen ({result.get('error') or 'kein Code'}).")
tok = post(BASE + '/api/oauth/token', {'grant_type': 'authorization_code', 'code': result['code'],
                                       'redirect_uri': REDIRECT, 'client_id': client['client_id'],
                                       'code_verifier': verifier, 'resource': RESOURCE})
if not tok.get('refresh_token'):
    sys.exit('❌ Megasheet hat kein dauerhaftes Login ausgegeben – sag Claude Bescheid.')
print(base64.b64encode(json.dumps({'refresh_token': tok['refresh_token'],
                                   'client_id': client['client_id']}).encode()).decode())
EOF
)" || exit 1
printf '%s' "$LOGIN" | gh secret set MEGASHEET_LOGIN -R "$REPO" || exit 1
openssl rand -base64 32 | tr -d '\n' | gh secret set MEGASHEET_KEY -R "$REPO" || exit 1
echo "✅ Megasheet-Login gespeichert – sag Claude: done"
