"""A stopped campaign (DACH, enabled=false): Megasheet only reads the running campaigns, the lists/report skip it,
and a failing Megasheet sync is reported instead of silently leaving old numbers."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from watcher import megasheet, own, state, weekly

NOW = time.time()
CFG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))


class StateDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(state, 'DIR', self.tmp.name)
        p.start()
        self.addCleanup(p.stop)


class FakeClient:
    """Megasheet with the France and Spain campaigns only (DACH archived)."""
    camps = [{'name': 'ParakeetAI - France', 'id': 'fr-id'}, {'name': 'ParakeetAI - Spain', 'id': 'es-id'}]

    def __init__(self, token):
        self.read = []

    def call(self, tool, **kw):
        return self.camps

    def pages(self, tool, campaignId, filters):
        self.read.append(campaignId)
        if tool == 'account_getMany':
            return [{'handle': f'creator_{campaignId}', 'status': 'active', 'creator': {'status': 'active'},
                     'lastPostedAt': '2026-10-10'}]
        return []


class MegasheetTests(StateDirTest):
    def test_dach_is_live_in_config_off(self):
        self.assertFalse(CFG['markets']['de']['enabled'])
        self.assertTrue(CFG['markets']['fr']['enabled'] and CFG['markets']['es']['enabled'])

    def test_only_running_campaigns_are_read_and_dach_creators_pause(self):
        accounts = {'dach.creator': {'status': 'active', 'source': 'megasheet', 'market': 'de'}}
        videos = {'1': {'handle': 'dach.creator', 'market': 'de', 'views': 5000, 'ours': True}}
        with mock.patch.object(megasheet, 'access_token', return_value='tok'), \
                mock.patch.object(megasheet, 'Client', FakeClient), \
                mock.patch.object(megasheet, 'tracked', return_value=True):
            s = megasheet.sync(accounts, videos, NOW, markets=['fr', 'es'])
        self.assertEqual(s['paused'], ['dach.creator'])  # DACH campaign stopped: no more TikTok reads for them
        self.assertEqual(videos['1']['views'], 5000)  # their old videos stay
        self.assertEqual(state.load(megasheet.INFO_FILE, {})['last_ok'], int(NOW))
        with mock.patch.object(megasheet, 'access_token', return_value='tok'), \
                mock.patch.object(megasheet, 'Client', FakeClient):
            with self.assertRaises(RuntimeError):  # reading DACH too would fail - the campaign is gone
                megasheet.sync({}, {}, NOW)

    def test_any_sync_failure_is_reported_once_a_day(self):
        with mock.patch.object(megasheet, 'sync', side_effect=RuntimeError('campaign "x" not found')), \
                mock.patch('watcher.notify.push') as push:
            self.assertIsNone(own.sync_megasheet({}, {}, NOW))
            own.sync_megasheet({}, {}, NOW + 3600)
            own.sync_megasheet({}, {}, NOW + 2 * 86400)
        self.assertEqual(push.call_count, 2)
        self.assertIn('Megasheet sync failed', push.call_args[0][0])


class ReportTests(StateDirTest):
    def test_weekly_report_skips_dach(self):
        fmts = [{'id': 'A', 'status': 'active', 'title': 'A', 'description': 'A'}]
        lines = weekly.market_lines({}, {}, fmts, CFG, NOW, lambda f: f)
        text = '\n'.join(lines)
        self.assertIn('France', text)
        self.assertIn('Spain', text)
        self.assertNotIn('DACH', text)


class MainTests(StateDirTest):
    def test_rerank_without_dach_orders_france_and_spain(self):
        from watcher import main, markets as M
        mkts = M.load(CFG)
        self.assertEqual([m['key'] for m in mkts], ['fr', 'es', 'sl'])  # Slovenia added 15 Oct 2026, DACH still off
        fmts = [{'id': 'A', 'status': 'active', 'title': 'A', 'description': 'A', 'pages': {'fr': 'pfa', 'es': 'pea'}},
                {'id': 'B', 'status': 'active', 'title': 'B', 'description': 'B', 'pages': {'fr': 'pfb', 'es': 'peb'}}]
        state.save('own.json', {})
        with mock.patch.object(main.pages, 'list_entries', return_value=([], None)), \
                mock.patch.object(main.pages, 'hot_entry_count', return_value=0), \
                mock.patch.object(main.pages, 'set_order') as so:
            ids = main.rerank(mkts, fmts, {}, CFG)
        self.assertEqual(sorted(ids), ['A', 'B'])
        self.assertEqual({c.args[0] for c in so.call_args_list}, {'list:fr', 'list:es'})

    def test_source_video_without_a_dach_page(self):
        from watcher import main
        with mock.patch.object(main.pages, 'children', return_value=[]) as ch:
            self.assertIsNone(main.source_video({'id': 'N', 'pages': {'fr': 'pfr'}}))
        ch.assert_called_once_with('pfr')


if __name__ == '__main__':
    unittest.main()
