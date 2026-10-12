import unittest
from unittest import mock

from watcher import localize, main, notion, verify
from watcher.markets import TEXT

TAGS = {'1': {'format': 'FRX22', 'market': 'fr'}, '2': {'format': 'FRX22', 'market': 'fr'},
        '3': {'format': 'X06', 'market': 'fr'}, 'ig_x': {'format': 'X06', 'market': 'es'}}
VIDS = {'1': {'handle': 'lucie', 'views': 157_000}, '2': {'handle': 'sha', 'views': 900},
        '3': {'handle': 'lucie', 'views': 171_000}, 'ig_x': {'handle': 'leyy', 'views': 41_000}}


class OwnExampleTests(unittest.TestCase):
    def pick(self, fid, m):
        with mock.patch.object(main.own, 'hand_tags', return_value=TAGS), \
                mock.patch.object(main.own, 'load', return_value=({}, VIDS)):
            return main.own_example(fid, m)

    def test_best_tiktok_video_of_ours_in_that_market(self):
        self.assertEqual(self.pick('FRX22', 'fr')['url'], 'https://www.tiktok.com/@lucie/video/1')

    def test_other_market_when_this_market_has_no_tiktok_video(self):
        self.assertEqual(self.pick('X06', 'es')['url'], 'https://www.tiktok.com/@lucie/video/3')  # Instagram can't be rebuilt from

    def test_none_without_videos(self):
        self.assertIsNone(self.pick('NOPE', 'fr'))


class OwnNoteTests(unittest.TestCase):
    def test_own_note_is_accepted_and_kept(self):
        for lang in ('de', 'fr', 'es'):
            own = TEXT[lang]['inspo_note_own']
            self.assertEqual(notion.inspo_note(lang, True, own=True), [own])
            self.assertTrue(localize.note_is_same(own, lang))
            blocks = [{'type': 'video', 'video': {}},
                      {'type': 'callout', 'callout': {'rich_text': [{'plain_text': own.replace('**', '')}]}}]
            self.assertIsNone(verify.note_problem(blocks, lang))
            self.assertNotIn('Parakeet AI', TEXT[lang]['inspo_note'][0])  # other brands' note stays app-neutral


if __name__ == '__main__':
    unittest.main()
