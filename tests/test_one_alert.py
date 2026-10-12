import tempfile
import unittest
from unittest import mock

from watcher import main, state

NOW = 2_000_000_000
CFG = {'watch_days': 7, 'thresholds': {'min_engagement': 0.015}, 'notion': {'radar_page': 'radar'},
       'models': {'classify': 'c', 'build': 'b'}}


def video(**kw):
    return {'id': '1', 'handle': 'someone', 'created': NOW - 3600, 'views': 150_000, 'shares': 3000, 'saves': 3000,
            'url': 'https://www.tiktok.com/@someone/video/1', 'notified': [], **kw}


class OneAlertPerVideoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(state, 'DIR', tmp.name),
                  mock.patch.object(main.notify, 'radar'),
                  mock.patch.object(main.media, 'download', side_effect=RuntimeError('no video')),
                  mock.patch.object(main.classify, 'classify', return_value={'match': None, 'hook_en': 'x'})):
            p.start()
            self.addCleanup(p.stop)
        self.push = mock.patch.object(main.notify, 'push').start()
        self.addCleanup(mock.patch.stopall)

    def test_taking_off_never_pings_slack(self):
        main.handle_alert(video(views=20_000), 'taking_off', [], [], {}, CFG, NOW, False, False)
        self.push.assert_not_called()
        main.notify.radar.assert_called_once()  # still on the Notion radar page

    def test_viral_alert_once_even_when_claude_fails_first(self):
        v = video()
        with mock.patch.object(main.classify, 'judge', side_effect=RuntimeError('overloaded')):
            for _ in range(main.JUDGE_TRIES - 1):
                main.handle_alert(v, 'viral', [], [], {}, CFG, NOW, False, True)
            self.push.assert_not_called()  # retried quietly
            main.handle_alert(v, 'viral', [], [], {}, CFG, NOW, False, True)
            main.handle_alert(v, 'viral', [], [], {}, CFG, NOW, False, True)
        self.assertEqual(self.push.call_count, 1)  # the basic alert, once
        with mock.patch.object(main.classify, 'judge', return_value={'english_script': 'hi'}):
            main.handle_alert(v, 'viral', [], [], {}, CFG, NOW, False, True)
        self.assertEqual(self.push.call_count, 1)  # the full check later is not a second ping
        self.assertIn('viral', v['notified'])

    def test_viral_alert_when_claude_works(self):
        v = video()
        with mock.patch.object(main.classify, 'judge', return_value={'english_script': 'hi'}):
            main.handle_alert(v, 'viral', [], [], {}, CFG, NOW, False, True)
        self.push.assert_called_once()
        self.assertIn('viral', v['notified'])  # the run loop skips it from now on


if __name__ == '__main__':
    unittest.main()
