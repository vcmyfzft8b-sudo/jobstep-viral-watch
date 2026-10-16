"""Rising fast (15 Oct 2026, user's choice "publish early"): 30k+ views in the first 24 h -> a NEW (or archived)
format is built and listed right away with the video's one Slack ping; a live format's video is pinged at 100k."""
import json
import os
import tempfile
import unittest
from unittest import mock

from watcher import detect, main, state

NOW = 2_000_000_000
TH = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))['thresholds']
CFG = {'watch_days': 7, 'thresholds': TH, 'notion': {'radar_page': 'radar'}, 'models': {'classify': 'c', 'build': 'b'}}
MKTS = [{'key': 'fr', 'T': {'flag': 'FR'}}]
LIVE = {'id': 'LIVE', 'status': 'active', 'title': 'Live format', 'pages': {}}


def video(**kw):
    return {'id': '1', 'handle': 'someone', 'created': NOW - 20 * 3600, 'views': 35_000, 'shares': 700, 'saves': 700,
            'likes': 2_000, 'url': 'https://www.tiktok.com/@someone/video/1', 'notified': [], **kw}


class LevelTests(unittest.TestCase):
    def test_rising_within_24_hours_only(self):
        self.assertEqual(detect.level(video(), NOW, None, TH), 'rising')
        self.assertIsNone(detect.level(video(created=NOW - 30 * 3600), NOW, None, TH))  # older than 24 h, under 50k
        self.assertEqual(detect.level(video(views=25_000), NOW, None, TH), 'taking_off')
        self.assertEqual(detect.level(video(notified=['rising']), NOW, None, TH), 'taking_off')
        self.assertEqual(detect.level(video(views=120_000), NOW, None, TH), 'viral')


class RisingAlertTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        prepared = {'work': tmp.name, 'video_file': 'v.mp4'}
        for p in (mock.patch.object(state, 'DIR', tmp.name),
                  mock.patch.object(main.notify, 'radar'),
                  mock.patch.object(main.media, 'download', return_value='v.mp4'),
                  mock.patch.object(main.media, 'audio', return_value='a.mp3'),
                  mock.patch.object(main.soniox, 'transcribe', return_value={'text': 'hi', 'segments': []}),
                  mock.patch.object(main, 'list_position', return_value=3),
                  mock.patch.object(main, 'ensure_market_pages', return_value=[])):
            p.start()
        self.push = mock.patch.object(main.notify, 'push').start()
        self.addCleanup(mock.patch.stopall)

    def test_live_format_waits_for_100k_and_reuses_the_check(self):
        v, fmts = video(), [dict(LIVE)]
        verdict = {'duplicate_of': 'LIVE', 'english_script': 'hi', 'reason': 'same'}
        with mock.patch.object(main.classify, 'judge', return_value=verdict) as judge:
            main.handle_alert(v, 'rising', MKTS, fmts, {}, CFG, NOW, False, False)
            self.push.assert_not_called()
            main.notify.radar.assert_called_once()
            self.assertIn('rising', v['notified'])
            self.assertNotIn('viral', v['notified'])
            v['views'] = 110_000
            main.handle_alert(v, 'viral', MKTS, fmts, {}, CFG, NOW, False, False)
        self.push.assert_called_once()  # the one Slack ping, at 100k
        self.assertEqual(judge.call_count, 1)  # check reused
        self.assertIn('viral', v['notified'])

    def test_new_format_is_built_now_with_the_one_ping(self):
        v = video()
        fmt = {'id': 'NEW', 'title': 'New one', 'pages': {}}
        with mock.patch.object(main.classify, 'judge', return_value={'english_script': 'hi'}), \
                mock.patch.object(main, 'build_format', return_value=(fmt, [], 4)) as build:
            r = main.handle_alert(v, 'rising', [], [], {}, CFG, NOW, False, False)
        build.assert_called_once()
        self.push.assert_called_once()
        self.assertIn('RISING', self.push.call_args[0][0])
        self.assertIn('Rising fast', self.push.call_args[0][1])
        self.assertEqual(r['level'], 'rising')
        self.assertIn('viral', v['notified'])  # no second ping at 100k

    def test_weak_engagement_is_not_built_early(self):
        v = video(shares=10, saves=10)
        with mock.patch.object(main.classify, 'judge', return_value={'english_script': 'hi'}), \
                mock.patch.object(main, 'build_format') as build:
            main.handle_alert(v, 'rising', [], [], {}, CFG, NOW, False, False)
        build.assert_not_called()
        self.push.assert_not_called()
        self.assertNotIn('viral', v['notified'])

    def test_a_failed_check_while_rising_is_quiet(self):
        v = video()
        with mock.patch.object(main.classify, 'judge', side_effect=RuntimeError('limit')):
            main.handle_alert(v, 'rising', [], [], {}, CFG, NOW, False, False)
        self.push.assert_not_called()
        self.assertEqual(v.get('judge_fails', 0), 0)  # the basic viral alert counter is untouched
        self.assertNotIn('rising', v['notified'])  # tried again next run


if __name__ == '__main__':
    unittest.main()
