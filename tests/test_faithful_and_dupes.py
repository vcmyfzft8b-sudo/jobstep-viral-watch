"""16 Oct 2026 (user): scripts must be 1:1 with their example (French / Slovenian ones were cut to 25-60% and passed);
the same format must never be on a list twice (X16 and A202610061332: "I quit HR, now I tell you their secrets")."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from watcher import dupes, lineup, own, state

CFG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))
NOW = time.time()


class DupeTitleTests(unittest.TestCase):
    def test_the_two_hr_titles_are_the_same(self):
        self.assertTrue(dupes.similar('4. ‼️Ne delam več v kadrovski, zato ti izdam VSE njihove skrivnosti 🤫‼️',
                                      '5. ‼️Ne delam več v HR-ju, zato ti izdam njihove skrivnosti 🤫‼️'))
        self.assertTrue(dupes.similar("‼️Ich hab meinen HR-Job gekündigt – jetzt verrate ich dir ALLE ihre Geheimnisse",
                                      "‼️Ich hab meinen HR-Job GEKÜNDIGT – jetzt verrat ich dir ALLE ihre Geheimnisse"))

    def test_different_formats_are_not(self):
        self.assertFalse(dupes.similar('Rekruterji NIKAKOR nočejo, da to veš😳❗️', 'Stvari, ki ti jih kadroviki skrivajo 😳❌'))
        self.assertFalse(dupes.similar('Seit wann kann LinkedIn das? 🤯', 'Jetzt ist die BESTE Zeit für die Jobsuche 👀'))

    def test_find_pairs_per_market(self):
        fmts = [{'id': i, 'status': 'active', 'pages': {'sl': f'p{i}'}} for i in ('A', 'B', 'C')]
        mkts = [{'key': 'sl', 'T': {'flag': 'SI'}}]
        t = {'pA': 'Ne delam več v kadrovski, zato ti izdam VSE njihove skrivnosti', 'pB': 'Ne delam več v HR-ju, zato ti izdam njihove skrivnosti',
             'pC': 'Seit wann kann LinkedIn das?'}
        pairs = dupes.find(fmts, mkts, lambda f, m: f['pages'].get(m), title=t.get)
        self.assertEqual([(a, b, m) for a, b, m, _, _ in pairs], [('A', 'B', 'sl')])


class MergeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(state, 'DIR', tmp.name), mock.patch.object(lineup.pages, 'move_page'),
                  mock.patch.object(lineup.notify, 'push')):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_the_better_one_stays_and_the_other_counts_for_it(self):
        h = {str(i): {'handle': 'x', 'format': 'STRONG', 'views': 200_000, 'saves': 8_000, 'likes': 8_000,
                      'created': NOW - 5 * 86400, 'judged': True} for i in range(5)}
        h.update({f'w{i}': {'handle': 'x', 'format': 'WEAK', 'views': 50_000, 'saves': 500, 'likes': 2_000,
                            'created': NOW - 5 * 86400} for i in range(3)})
        ours = {'o1': {'format': 'WEAK', 'ours': True, 'market': 'es', 'views': 1000, 'created': NOW - 3 * 86400, 'handle': 'c'}}
        fmts = [{'id': 'STRONG', 'status': 'active', 'title': 'S', 'pages': {'sl': 'pS'}},
                {'id': 'WEAK', 'status': 'active', 'title': 'W', 'pages': {'sl': 'pW'}}]
        mkts = [{'key': 'sl', 'archive_page': 'arch'}]
        merged = lineup.merge_duplicates(h, fmts, CFG, ours, mkts, now=NOW, pairs=[('STRONG', 'WEAK', 'sl', 'a', 'b')])
        self.assertEqual([(d['id'], k['id']) for d, k, _ in merged], [('WEAK', 'STRONG')])
        self.assertEqual(fmts[1]['status'], 'archived')
        self.assertTrue(fmts[1]['archived_reason'].startswith('duplicate of STRONG'))
        self.assertEqual({v['format'] for v in h.values()}, {'STRONG'})
        self.assertEqual(ours['o1']['format'], 'STRONG')
        lineup.pages.move_page.assert_called_once_with('pW', 'arch')
        state.save('formats.json', fmts)
        self.assertEqual(own.aliases(), {'WEAK': 'STRONG'})


if __name__ == '__main__':
    unittest.main()
