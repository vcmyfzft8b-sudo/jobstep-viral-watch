import base64
import json
import os
import tempfile
import unittest
from unittest import mock

from watcher import megasheet, own, state


def login_secret(refresh='r1', client='c1'):
    return base64.b64encode(json.dumps({'refresh_token': refresh, 'client_id': client}).encode()).decode()


class Resp:
    def __init__(self, status=200, body=None, text='', headers=None):
        self.status_code, self._body, self.text = status, body, text
        self.headers = headers or {'content-type': 'application/json'}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class StateDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(state, 'DIR', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)


class AccessTokenTests(StateDirTest):
    def env(self, **kw):
        p = mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def test_no_login_saved_skips(self):
        self.env(MEGASHEET_LOGIN='', MEGASHEET_KEY='')
        self.assertIsNone(megasheet.access_token())

    def test_rotated_login_is_kept_encrypted_and_used_next_time(self):
        self.env(MEGASHEET_LOGIN=login_secret('r1'), MEGASHEET_KEY='k' * 32)
        sent = []

        def post(url, data, timeout):
            sent.append(data['refresh_token'])
            n = len(sent)
            return Resp(body={'access_token': f'a{n}', 'refresh_token': f'r{n + 1}'})

        with mock.patch.object(megasheet.requests, 'post', side_effect=post):
            self.assertEqual(megasheet.access_token(), 'a1')
            enc = open(os.path.join(self.tmp.name, megasheet.LOGIN_FILE)).read()
            self.assertNotIn('r2', enc)  # the state branch is public: never in plain text
            self.assertEqual(megasheet.access_token(), 'a2')
        self.assertEqual(sent, ['r1', 'r2'])  # the replaced secret login is never sent again

    def test_non_rotating_login_keeps_using_the_secret(self):
        self.env(MEGASHEET_LOGIN=login_secret('r1'), MEGASHEET_KEY='k' * 32)
        with mock.patch.object(megasheet.requests, 'post',
                               return_value=Resp(body={'access_token': 'a', 'refresh_token': 'r1'})) as post:
            megasheet.access_token()
            # same refresh token back: nothing new to keep, the secret is still the login
            self.assertFalse(os.path.exists(os.path.join(self.tmp.name, megasheet.LOGIN_FILE)))
            self.assertEqual(megasheet.access_token(), 'a')
        self.assertEqual(post.call_count, 2)

    def test_new_secret_login_wins_after_saved_one_fails(self):
        self.env(MEGASHEET_LOGIN=login_secret('r1'), MEGASHEET_KEY='k' * 32)
        with mock.patch.object(megasheet.requests, 'post',
                               return_value=Resp(body={'access_token': 'a1', 'refresh_token': 'r2'})):
            megasheet.access_token()
        self.env(MEGASHEET_LOGIN=login_secret('fresh'), MEGASHEET_KEY='other-key' * 4)  # script run again
        with mock.patch.object(megasheet.requests, 'post',
                               return_value=Resp(body={'access_token': 'a9'})) as post:
            self.assertEqual(megasheet.access_token(), 'a9')
        self.assertEqual(post.call_args.kwargs['data']['refresh_token'], 'fresh')

    def test_refused_login_raises(self):
        self.env(MEGASHEET_LOGIN=login_secret('r1'), MEGASHEET_KEY='k' * 32)
        with mock.patch.object(megasheet.requests, 'post', return_value=Resp(status=400, body={})):
            with self.assertRaises(megasheet.LoginError):
                megasheet.access_token()


class ClientTests(unittest.TestCase):
    def test_event_stream_answer(self):
        r = Resp(text='event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"ok":1}}\n\n',
                 headers={'content-type': 'text/event-stream'})
        self.assertEqual(megasheet._message(r, 3), {'jsonrpc': '2.0', 'id': 3, 'result': {'ok': 1}})

    def test_tool_call_and_pages(self):
        pages = {1: {'data': [1, 2], 'pagination': {'total_pages': 2}},
                 2: {'data': [3], 'pagination': {'total_pages': 2}}}

        def post(url, json, timeout):
            if json['method'] == 'initialize':
                return Resp(body={'id': json['id'], 'result': {'protocolVersion': '2025-06-18'}},
                            headers={'content-type': 'application/json', 'mcp-session-id': 's1'})
            if 'id' not in json:
                return Resp(status=202, headers={})
            text = __import__('json').dumps(pages[json['params']['arguments']['page']])
            return Resp(body={'id': json['id'], 'result': {'content': [{'type': 'text', 'text': text}]}})

        with mock.patch('requests.Session.post', side_effect=post):
            c = megasheet.Client('tok')
            self.assertEqual(c.s.headers['Mcp-Session-Id'], 's1')
            self.assertEqual(list(c.pages('videos_getMany', campaignId='x')), [1, 2, 3])


def acc(handle, status='active', creator='posting', posted='2026-09-20'):
    return {'handle': handle, 'status': status, 'firstPostedAt': posted, 'creator': {'status': creator}}


class MergeTests(unittest.TestCase):
    def test_accounts(self):
        accounts = {'old.de': {'status': 'active', 'source': 'megasheet', 'market': 'de'},
                    'gone': {'status': 'active', 'source': 'megasheet', 'market': 'de'},
                    'lightreel.fr': {'status': 'inactive', 'source': 'lightreel', 'market': ''}}
        rows = [('de', acc('old.de')), ('fr', acc('new.fr', creator='trialing', posted=None)),
                ('fr', acc('lightreel.fr')), ('es', acc('removed.es', status='removed')),
                ('es', acc('ghost.es', creator='ghosted', posted=None))]
        added, paused, revived = megasheet.merge_accounts(accounts, rows, 1000)
        self.assertEqual(added, ['new.fr'])
        self.assertEqual(paused, ['gone'])  # no longer in Megasheet
        self.assertEqual(revived, ['lightreel.fr'])
        self.assertEqual(accounts['lightreel.fr'], {'status': 'active', 'source': 'megasheet', 'market': 'fr'})
        self.assertNotIn('removed.es', accounts)
        self.assertNotIn('ghost.es', accounts)

    def test_videos(self):
        vid = '7693908974831160608'
        videos = {vid: {'handle': 'tifajobs', 'market': 'es', 'created': 1, 'views': 9000, 'checked': True,
                        'ours': False}}
        rows = [('es', {'adLink': f'https://www.tiktok.com/@tifajobs/video/{vid}', 'views': 6723, 'likes': 412,
                        'account': {'handle': 'tifajobs'}}),
                ('fr', {'adLink': 'https://www.tiktok.com/@a/video/7694019366375017750?x=1', 'views': 5,
                        'title': 'x' * 400, 'account': {'handle': 'a'}}),
                ('fr', {'adLink': None, 'views': 1})]
        self.assertEqual(megasheet.merge_videos(videos, rows, 1000), 1)
        self.assertEqual(videos[vid]['views'], 9000)  # views never go down
        self.assertTrue(videos[vid]['ours'])
        self.assertNotIn('checked', videos[vid])  # gets sorted into a format after all
        new = videos['7694019366375017750']
        self.assertEqual((new['handle'], new['market'], len(new['desc'])), ('a', 'fr', 300))
        self.assertEqual(new['created'], 7694019366375017750 >> 32)


class SeedTests(StateDirTest):
    def test_seed_adds_missing_entries_without_touching_state(self):
        state.save('own_accounts.json', {'annfi.jobtipps': {'status': 'inactive', 'source': 'megasheet',
                                                            'market': 'de'}})
        state.save('own.json', {'7684737630604496161': {'handle': 'kerstin.echoes', 'views': 10 ** 9,
                                                       'created': 1, 'ours': True}})
        accounts, videos = own.load()
        self.assertEqual(accounts['annfi.jobtipps']['status'], 'inactive')
        self.assertEqual(videos['7684737630604496161']['views'], 10 ** 9)
        with open(own.SEED) as f:
            seed = json.load(f)
        self.assertEqual(set(accounts), set(seed['accounts']))
        self.assertEqual({a['market'] for a in seed['accounts'].values()}, {'de', 'fr', 'es'})
        self.assertTrue(all(v['ours'] for v in videos.values()))

    def test_sync_failure_never_breaks_the_run(self):
        with mock.patch.object(megasheet, 'sync', side_effect=RuntimeError('boom')):
            self.assertIsNone(own.sync_megasheet({}, {}, 0))
        with mock.patch.object(megasheet, 'sync', side_effect=megasheet.LoginError('used up')), \
                mock.patch('watcher.notify.push') as push:
            own.sync_megasheet({}, {}, 100000)
            own.sync_megasheet({}, {}, 100001)
        self.assertEqual(push.call_count, 1)  # at most one "log in again" message a day


if __name__ == '__main__':
    unittest.main()
