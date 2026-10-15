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
    def test_registry_maps_24_france_pages_to_distinct_copies(self):
        pages = ADOPT['sl']['pages']
        self.assertEqual(ADOPT['sl']['from'], 'fr')
        self.assertEqual(len(pages), 24)
        self.assertEqual(len(set(pages.values())), 24)

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


class SkipTests(unittest.TestCase):
    """Only JobStep formats in Slovenia: the two study-app formats (from @lern.mit.domi, also a Memo AI source) never
    get a Slovenian page, list entry or check."""
    SKIP = ('A20261009204851', 'A20261014173459')

    def test_config_skips_the_study_app_formats(self):
        self.assertEqual(set(CFG['markets']['sl']['skip_formats']), set(self.SKIP))
        mkts = markets.load(CFG)
        self.assertNotIn('sl', [mk['key'] for mk in markets.for_format(mkts, {'id': self.SKIP[0]})])
        self.assertIn('sl', [mk['key'] for mk in markets.for_format(mkts, {'id': 'N10'})])
        self.assertIn('fr', [mk['key'] for mk in markets.for_format(mkts, {'id': self.SKIP[0]})])  # France keeps them

    def test_skipped_format_is_never_built_or_listed(self):
        mkts = [mk for mk in markets.load(CFG) if mk['key'] == 'sl']
        f = {'id': self.SKIP[1], 'status': 'active', 'title': 't', 'pages': {'fr': 'x'}}
        with mock.patch.object(main, 'missing_page') as mp:
            self.assertEqual(main.ready_page(f, mkts[0], [f], {}, CFG)[0], 'ok')
        mp.assert_not_called()
        with mock.patch.object(main, 'make_page') as mkp:
            self.assertEqual(main.ensure_market_pages(f, {}, mkts, [f], {}, CFG, None), [])
        mkp.assert_not_called()
        fmts = [f, {'id': 'N10', 'status': 'active', 'title': 'n', 'description': 'n', 'pages': {'sl': 'psl'}},
                {**f, 'pages': {'sl': 'should-not-show'}, 'id': self.SKIP[0]}]
        with mock.patch.object(main.notion, 'list_entries', return_value=([], None)), \
                mock.patch.object(main.notion, 'hot_entry_count', return_value=0), \
                mock.patch.object(main, 'own_tiers', return_value={}), \
                mock.patch.object(main.state, 'log'), \
                mock.patch.object(main.notion, 'set_order') as so:
            main.rerank(mkts, fmts, {}, CFG)
        self.assertEqual(so.call_args.args[1], ['psl'])


if __name__ == '__main__':
    unittest.main()


class SloveniaPageChecksTests(unittest.TestCase):
    """verify on 15 Oct 2026: the copied Slovenian pages link the Visual Hook Lab inside Notion ('/<id>'), and
    Slovenian quotes are »…« - neither may count as an extra hook line / a wrong on-screen text."""

    def test_slovenian_quotes_are_read(self):
        from watcher import tidy
        self.assertEqual(tidy.hook_fixes('Na zaslonu naj bo »Ne delaj tega!!«, začni pa z »Drugo«.', 'Ne delaj tega!!', ''),
                         [('Drugo', 'Ne delaj tega!!')])
        self.assertEqual(tidy.hook_fixes('Affiche « Évitez cette erreur !! » 3 s', 'Évitez cette erreur !!', ''), [])

    def test_notion_link_to_the_lab_is_not_a_hook_line(self):
        from watcher import reword

        def para(text, url=None):
            return {'type': 'paragraph', 'paragraph': {'rich_text': [
                {'type': 'text', 'plain_text': text, 'text': {'content': text, 'link': {'url': url} if url else None}}]}}
        blocks = [{'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'plain_text': '🎬 VIZUALNI HOOK',
                                                                     'text': {'content': '🎬 VIZUALNI HOOK'}}]}},
                  para('Skopiraj začetek videa.'), para('🚨👇 Visual hook je obvezen v vsakem videu!'),
                  para('Visual Hook Lab', '/74d958b0fc148297b4a1819f32230950'), {'type': 'divider', 'divider': {}}]
        with mock.patch.object(reword.notion, 'children', return_value=blocks):
            self.assertEqual(len(reword.direction_blocks('p')), 1)

    def test_verify_skips_formats_that_are_not_in_the_market(self):
        from watcher import verify
        cfg = {'markets': {'sl': {**CFG['markets']['sl']}}, 'links': CFG['links']}
        fmts = [{'id': 'A20261009204851', 'status': 'active', 'title': 'laptop', 'pages': {'fr': 'x'}}]
        with mock.patch.object(verify.notion, 'list_entries', return_value=([], None)):
            self.assertEqual(verify.run(cfg, fmts, main.page_of), [])
