"""16 Oct 2026 (user): a script is its example video 1:1 - only language, app/features, X/Y, job sites and dates change;
the creator's claims and promises stay. The independent check (faithful.py) lists every other change."""
import unittest
from unittest import mock

from watcher import brands, builder, faithful


def page(problems):
    p = [mock.patch.object(faithful.localize, 'current_source', return_value={'url': 'https://www.tiktok.com/@a/video/1'}),
         mock.patch.object(faithful.localize, 'example_text', return_value='ON-SCREEN: x\nSPEECH: ' + 'Wie ich in 15 Minuten einen Job gefunden habe. ' * 4),
         mock.patch.object(faithful.reword, 'script_blocks', return_value=['b']),
         mock.patch.object(faithful.reword, 'spoken_text', return_value='Comment j’ai trouvé un job en 15 minutes. ' * 4),
         mock.patch.object(faithful.llm, 'chat_json', return_value={'problems': problems})]
    return p


class FaithfulTests(unittest.TestCase):
    def run_check(self, problems):
        ps = page(problems)
        for p in ps:
            p.start()
        self.addCleanup(mock.patch.stopall)
        return faithful.check_page({'id': 'X'}, 'pid', 'fr', 'opus')

    def test_one_to_one_passes(self):
        r = self.run_check([])
        self.assertTrue(r['ok'])
        prompt = faithful.llm.chat_json.call_args[0][2]
        self.assertIn('not shortened, not summarised, not softened', prompt)
        self.assertIn('X / Y', prompt)

    def test_a_softened_promise_is_a_problem(self):
        r = self.run_check([{'kind': 'softened', 'original': 'in 15 Minuten', 'script': 'plus vite'}])
        self.assertFalse(r['ok'])

    def test_fix_transcribes_again_with_the_problems(self):
        res = [('T', 'fr', {'ok': False, 'problems': [{'kind': 'dropped', 'original': 'Satz 3', 'script': ''}]})]
        fmts = [{'id': 'X', 'title': 'T', 'status': 'active'}]
        mkts = [{'key': 'fr', 'lang': 'fr'}]
        cfg = {'links': {}, 'models': {'build': 'opus', 'classify': 'sonnet'}}
        with mock.patch('watcher.align.align_page', return_value=('ok', '120 words')) as al, \
                mock.patch('watcher.reword.fix_directions'), \
                mock.patch.object(faithful, 'check_page', return_value={'ok': True, 'problems': []}):
            out = faithful.fix(res, fmts, mkts, cfg, lambda f, m: 'pid')
        self.assertIn('Satz 3', al.call_args.kwargs['feedback'])
        self.assertTrue(out[0][2]['ok'])


class RuleTextTests(unittest.TestCase):
    def test_no_softening_or_neutralising_any_more(self):
        self.assertNotIn('honest', builder.TRANSCRIBE.replace("made 'honest'", ''))
        self.assertIn('never neutralised, softened', brands.LOCALISE)
        self.assertIn('No shortening', builder.TRANSCRIBE.replace('no shortening', 'No shortening'))
        for kept in ('InfoJobs', 'timeless', 'Spain Spanish'):
            self.assertIn(kept, brands.LOCALISE)


if __name__ == '__main__':
    unittest.main()
