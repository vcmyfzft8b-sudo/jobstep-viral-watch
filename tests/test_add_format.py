import tempfile
import unittest
from unittest import mock

from watcher import main, state


class AddFormatTests(unittest.TestCase):
    def test_every_given_video_counts_for_the_format_and_the_list_is_resorted(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        videos = {'1': {'id': '1', 'handle': 'lern.mit.domi', 'created': 1, 'views': 1_000_000, 'shares': 5, 'saves': 85,
                        'url': 'https://www.tiktok.com/@lern.mit.domi/video/1'},
                  '2': {'id': '2', 'handle': 'lern.mit.domi', 'created': 2, 'views': 290_000, 'shares': 5, 'saves': 30,
                        'url': 'https://www.tiktok.com/@lern.mit.domi/video/2'}}
        fmts = [{'id': 'OLD', 'status': 'active', 'title': 'old'}]

        def viral(v, mkts, f, history, cfg, now, only_detect, test=False, force=False, label=None):
            self.assertTrue(force)  # the user picked it: never blocked as "weak engagement"
            f.append({'id': 'NEW', 'status': 'active', 'title': 'MacBook'})
            main.set_format(v, history, 'NEW', judged=True)
            return {'video': v['id'], 'built': 'NEW'}

        with mock.patch.object(state, 'DIR', tmp.name), \
                mock.patch.object(main, 'load_config', return_value={'markets': {}, 'notion': {}}), \
                mock.patch.object(main.M, 'load', return_value=[]), \
                mock.patch.object(main, 'load_formats', return_value=fmts), \
                mock.patch.object(main.tiktok, 'video_detail', side_effect=lambda h, i: dict(videos[i])), \
                mock.patch.object(main.discover, 'language', return_value='de'), \
                mock.patch.object(main, 'handle_viral', side_effect=viral), \
                mock.patch.object(main, 'rerank', return_value=['NEW', 'OLD']) as rerank:
            main.add_format(['https://www.tiktok.com/@lern.mit.domi/video/1', 'https://www.tiktok.com/@lern.mit.domi/video/2'])
            history = state.load('history.json', {})
            accounts = state.load('accounts.json', {})
        self.assertEqual({history['1']['format'], history['2']['format']}, {'NEW'})
        self.assertTrue(history['2']['judged'] and history['1']['german'])
        rerank.assert_called_once()
        self.assertEqual(accounts['lern.mit.domi']['status'], 'manual')  # followed from now on, never paused
        self.assertTrue(accounts['lern.mit.domi']['added_format'])


if __name__ == '__main__':
    unittest.main()


class AddFormatFailureTests(unittest.TestCase):
    def test_a_failed_build_alerts_and_exits_non_zero(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        video = {'id': '1', 'handle': 'a', 'created': 1, 'views': 10, 'shares': 0, 'saves': 0, 'url': 'https://www.tiktok.com/@a/video/1'}
        with mock.patch.object(state, 'DIR', tmp.name), \
                mock.patch.object(main, 'load_config', return_value={'markets': {}, 'notion': {}}), \
                mock.patch.object(main.M, 'load', return_value=[]), mock.patch.object(main, 'load_formats', return_value=[]), \
                mock.patch.object(main.tiktok, 'video_detail', return_value=dict(video)), \
                mock.patch.object(main.discover, 'language', return_value=''), \
                mock.patch.object(main, 'handle_viral', return_value={'video': '1', 'error': 'session limit'}), \
                mock.patch.object(main.notify, 'push') as push:
            with self.assertRaises(SystemExit) as e:
                main.add_format(['https://www.tiktok.com/@a/video/1'])
        self.assertIn('session limit', str(e.exception))
        push.assert_called_once()
