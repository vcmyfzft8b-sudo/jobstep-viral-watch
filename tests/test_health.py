"""Runs every 2 hours (full every 6 h, light in between) and Slack notes when something breaks (15 Oct 2026)."""
import unittest
from unittest import mock

from watcher import main

H = 3600


class LightRunTests(unittest.TestCase):
    def test_full_every_six_hours_light_in_between(self):
        self.assertFalse(main.is_light({}, 100 * H, auto=True))  # never ran fully -> full
        self.assertTrue(main.is_light({'last_full_run': 98 * H}, 100 * H, auto=True))
        self.assertFalse(main.is_light({'last_full_run': 94.4 * H}, 100 * H, auto=True))  # 5.6 h: full (GitHub is late)
        self.assertFalse(main.is_light({'last_full_run': 99 * H}, 100 * H, auto=False))  # by hand: always full


class FailureNoteTests(unittest.TestCase):
    def setUp(self):
        main.FAILED.clear()
        self.push = mock.patch.object(main.notify, 'push').start()
        self.addCleanup(mock.patch.stopall)

    def test_one_note_then_quiet_until_something_else_fails_or_a_day_passed(self):
        meta = {}
        main.step_failed('tidy', RuntimeError('notion 502'))
        main.report_failures(meta, 1000)
        self.assertEqual(self.push.call_count, 1)
        self.assertIn('tidy: notion 502', self.push.call_args[0][1])
        main.report_failures(meta, 1000 + 2 * H)  # same step again 2 h later: quiet
        self.assertEqual(self.push.call_count, 1)
        main.step_failed('own creators', RuntimeError('x'))  # another step: a new note
        main.report_failures(meta, 1000 + 4 * H)
        self.assertEqual(self.push.call_count, 2)
        main.report_failures(meta, 1000 + 30 * H)  # a day later: reminded
        self.assertEqual(self.push.call_count, 3)

    def test_a_clean_run_resets(self):
        meta = {'failed_steps': {'sig': ['tidy'], 'at': 1}}
        main.report_failures(meta, 1000)
        self.push.assert_not_called()
        self.assertNotIn('failed_steps', meta)


if __name__ == '__main__':
    unittest.main()
