"""Slovenia (15 Oct 2026): a fourth market like France and Spain - Slovenian texts, its own Notion list/holder/archive,
its Megasheet campaign, Slovenian JobStep accounts recognised, and the translated copies of the France pages linked to
their formats once (registry/market_adopt.json)."""
import json
import os
import unittest
from unittest import mock

from watcher import discover, localize, main, markets, megasheet, weekly

ROOT = os.path.join(os.path.dirname(__file__), '..')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
ADOPT = json.load(open(os.path.join(ROOT, 'registry', 'market_adopt.json')))


class SloveniaMarketTests(unittest.TestCase):
    def test_market_is_on_with_its_own_pages(self):
        sl = CFG['markets']['sl']
        self.assertTrue(sl['enabled'])
        self.assertEqual(sl['lang'], 'sl')
        for k in ('list_page', 'holder_page', 'archive_page', 'visual_hook_lab', 'discord_env', 'discord_server'):
            self.assertTrue(sl[k], k)
        others = {CFG['markets'][m][k] for m in ('de', 'fr', 'es') for k in ('list_page', 'holder_page', 'archive_page')}
        self.assertFalse({sl['list_page'], sl['holder_page'], sl['archive_page']} & others)
        self.assertIn('sl', [m['key'] for m in markets.load(CFG)])

    def test_slovenian_texts_are_complete(self):
        T = markets.TEXT['sl']
        self.assertEqual(set(T), set(markets.TEXT['fr']))
        self.assertEqual(len(T['inspo_note']), 2)
        self.assertEqual(len(T['list_fire']), 2)
        self.assertIn('{name}', T['asset_cue'])
        self.assertIn('{n}', T['hot_suffix'])
        self.assertIn('{title}', T['discord'])
        self.assertIn('{n}', T['discord'])

    def test_note_variants_are_told_apart(self):
        T = markets.TEXT['sl']
        self.assertTrue(localize.note_is_same(T['inspo_note_same'], 'sl'))
        self.assertTrue(localize.note_is_same(T['inspo_note_own'], 'sl'))  # own starts like 'same'
        self.assertFalse(localize.note_is_same(T['inspo_note'][0], 'sl'))

    def test_maps_know_slovenia(self):
        self.assertEqual(megasheet.CAMPAIGNS['ParakeetAI - Slovenia'], 'sl')
        self.assertIn('sl', weekly.MARKETS)
        self.assertIn('sl', main.ALL_MARKETS)
        self.assertEqual(localize.LANG_NAME['sl'], 'Slovenian')


def _captions(*texts):
    return [{'desc': t} for t in texts]


class LanguageTests(unittest.TestCase):
    def lang(self, *texts):
        with mock.patch.object(discover.tiktok, 'latest_videos', return_value=_captions(*texts)):
            return discover.language('x')

    def test_slovenian_account(self):
        self.assertEqual(self.lang('Tako sem končno dobila službo in to zelo hitro',
                                   'Če iščeš delo, ti lahko pomaga tudi tole', 'Kot vedno, že zdaj več prijav'), 'sl')

    def test_croatian_account_is_not_slovenian(self):
        self.assertNotEqual(self.lang('Ovako sam konačno dobila posao i to jako brzo',
                                      'Ako tražiš posao, ovo ti može pomoći', 'Kao i uvijek, već sada više prijava'), 'sl')

    def test_french_still_french(self):
        self.assertEqual(self.lang('je te montre comment trouver un job avec ton cv', "c’est pour toi si tu cherches"), 'fr')


class AdoptTests(unittest.TestCase):
    def test_registry_maps_26_france_pages_to_distinct_copies(self):
        pages = ADOPT['sl']['pages']
        self.assertEqual(ADOPT['sl']['from'], 'fr')
        self.assertEqual(len(pages), 26)
        self.assertEqual(len(set(pages.values())), 26)

    def test_copies_are_linked_once(self):
        adopt = {'sl': {'from': 'fr', 'pages': {'aaa111': 'sl111', 'bbb222': 'sl222'}}}
        fmts = [{'id': 'A', 'pages': {'fr': 'aaa-111', 'es': 'e1'}, 'inspo': {'fr': {'url': 'u', 'strict': True}}},
                {'id': 'B', 'pages': {'fr': 'bbb222', 'sl': 'own-sl'}},
                {'id': 'C', 'pages': {'es': 'e3'}}]
        self.assertEqual(main.adopt_market_pages(fmts, adopt), 1)
        self.assertEqual(main.page_of(fmts[0], 'sl'), 'sl111')
        self.assertNotIn('sl', fmts[0]['inspo'])  # the example is looked for in Slovenian by localize
        self.assertEqual(fmts[1]['pages']['sl'], 'own-sl')  # an existing page is never replaced
        self.assertNotIn('sl', fmts[2].get('pages', {}))
        self.assertEqual(main.adopt_market_pages(fmts, adopt), 0)  # nothing twice
        del fmts[0]['pages']['sl']  # a page taken away later is not linked again
        self.assertEqual(main.adopt_market_pages(fmts, adopt), 0)
        self.assertIsNone(main.page_of(fmts[0], 'sl'))


if __name__ == '__main__':
    unittest.main()
