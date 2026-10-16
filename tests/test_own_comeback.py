"""Hand-checked formats of our videos, archived formats coming back when they are proven for our creators, and the
weekly clean-up never taking those out."""
import json
import os
import time
import unittest
from unittest import mock

from watcher import lineup, own
from watcher import main as W

DAY = 86400
NOW = time.time()
CFG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))
MKTS = [{'key': 'es', 'holder_page': 'ES_FOLDER', 'archive_page': 'ES_ARCHIVE'},
        {'key': 'fr', 'holder_page': 'FR_FOLDER', 'archive_page': 'FR_ARCHIVE'}]


def fmts():
    return [{'id': 'LIVE', 'status': 'active', 'title': 'Live', 'pages': {'es': 'es-live', 'fr': 'fr-live'}},
            {'id': 'SIXMONTHS', 'status': 'archived', 'title': 'Après six mois', 'archived_reason': 'clean-up',
             'pages': {'fr': 'fr-six'}},
            {'id': 'RDV', 'status': 'archived', 'title': 'Rendez-vous', 'pages': {'es': 'es-rdv', 'fr': 'fr-rdv'}},
            {'id': 'OLD', 'status': 'archived', 'title': 'Old', 'pages': {'es': 'es-old', 'fr': 'fr-old'}}]


def ours(market, fmt, views, days_old=5):
    return {'handle': f'c_{market}', 'market': market, 'created': NOW - days_old * DAY, 'views': views, 'ours': True,
            'checked': True, 'format': fmt}


class HandTagTests(unittest.TestCase):
    def test_hand_tags_win_over_the_automatic_sorting(self):
        videos = {'1': ours('fr', 'OLD', 1000), '2': ours('fr', None, 500), 'ig_x': {**ours('fr', None, 50), 'checked': False}}
        tags = {'1': {'format': 'SIXMONTHS'}, 'ig_x': {'format': 'SIXMONTHS'}, 'missing': {'format': 'LIVE'}}
        self.assertEqual(own.apply_hand_tags(videos, tags), 2)
        self.assertEqual((videos['1']['format'], videos['1']['format_by']), ('SIXMONTHS', 'hand'))
        self.assertTrue(videos['ig_x']['checked'])  # never re-sorted automatically
        self.assertIsNone(videos['2']['format'])
        self.assertNotIn('missing', videos)

    def test_registry_is_valid(self):
        tags = own.hand_tags()
        self.assertGreater(len(tags), 1000)
        self.assertTrue(all(t['format'] and t['market'] in ('es', 'fr') for t in tags.values()))


class ComebackTests(unittest.TestCase):
    def run_comebacks(self, tiers, cfg=CFG, ready=None, f=None, force=False):
        f = f or fmts()
        ready = ready or (lambda fmt, mk, *_: ('ok', ''))
        with mock.patch.object(W.pages, 'move_page') as mv, mock.patch.object(W.notify, 'push') as push, \
                mock.patch.object(W.state, 'log'), mock.patch.object(W, 'ready_page', side_effect=ready) as rp, \
                mock.patch.object(W.audit, 'originals', return_value={}):
            back = W.own_comebacks(MKTS, f, cfg, tiers=tiers, now=NOW, force=force)
        self.ready_calls = rp.call_count
        return {x['id']: x for x in f}, back, mv, push

    def test_proven_archived_format_comes_back_in_every_market_it_has_a_page(self):
        tiers = {'fr': {'SIXMONTHS': {'tier': 1, 'n': 14, 'avg': 15146, 'best': 156955},
                        'OLD': {'tier': 2, 'n': 5, 'avg': 3000, 'best': 9000}},
                 'es': {'LIVE': {'tier': 1, 'n': 3, 'avg': 20000, 'best': 50000}}}
        f, back, mv, push = self.run_comebacks(tiers)
        self.assertEqual([x['id'] for x in back], ['SIXMONTHS'])
        self.assertEqual(f['SIXMONTHS']['status'], 'active')
        self.assertEqual(f['SIXMONTHS']['listed_at'], int(NOW))  # 14 days of protection like any newly listed format
        self.assertNotIn('archived_reason', f['SIXMONTHS'])
        self.assertIn('proven for our creators', f['SIXMONTHS']['revived']['because'])
        mv.assert_called_once_with('fr-six', 'FR_FOLDER')  # no Spanish page before: ready_page builds it (in the folder)
        self.assertEqual(self.ready_calls, 2)  # every running market's page is made ready first
        self.assertEqual(f['OLD']['status'], 'archived')  # only solid, not proven
        push.assert_called_once()

    def test_never_revive_keeps_a_format_out(self):
        cfg = json.loads(json.dumps(CFG))
        cfg['lineup']['never_revive'] = ['RDV']
        tiers = {'fr': {'RDV': {'tier': 1, 'n': 20, 'avg': 21000, 'best': 218000}}}
        f, back, mv, push = self.run_comebacks(tiers, cfg)
        self.assertEqual(back, [])
        self.assertEqual(f['RDV']['status'], 'archived')
        mv.assert_not_called()
        push.assert_not_called()

    def test_a_failed_move_does_not_stop_the_comeback(self):
        tiers = {'es': {'RDV': {'tier': 1, 'n': 2, 'avg': 33000, 'best': 44000}}}
        f = fmts()
        with mock.patch.object(W.pages, 'move_page', side_effect=[RuntimeError('boom'), None]) as mv, \
                mock.patch.object(W.notify, 'push'), mock.patch.object(W.state, 'log'), \
                mock.patch.object(W, 'ready_page', return_value=('ok', '')), \
                mock.patch.object(W.audit, 'originals', return_value={}):
            back = W.own_comebacks(MKTS, f, CFG, tiers=tiers, now=NOW)
        self.assertEqual([x['id'] for x in back], ['RDV'])
        self.assertEqual(mv.call_count, 2)

    def test_a_comeback_waits_until_every_page_is_in_the_current_layout(self):
        # the case of 15 Oct 2026: proven in Spain, no Spanish page, old hand-written French page
        tiers = {'es': {'SIXMONTHS': {'tier': 1, 'n': 2, 'avg': 12000, 'best': 23000}}}
        built = {}

        def ready(fmt, mk, *_):
            if mk['key'] == 'es':
                fmt['pages']['es'] = built['es'] = 'es-new'  # built, checked, moved into the Spanish folder
                return 'built', 'url'
            return 'not rebuilt', 'check failed'
        f, back, mv, push = self.run_comebacks(tiers, ready=ready)
        self.assertEqual(back, [])
        self.assertEqual(f['SIXMONTHS']['status'], 'archived')
        self.assertEqual(f['SIXMONTHS']['comeback_tries'], 1)
        mv.assert_called_once_with('es-new', 'ES_ARCHIVE')  # the new page waits in the archive too
        push.assert_not_called()

    def test_ready_pages_come_back_together(self):
        tiers = {'es': {'SIXMONTHS': {'tier': 1, 'n': 2, 'avg': 12000, 'best': 23000}}}

        def ready(fmt, mk, *_):
            if mk['key'] == 'es':
                fmt['pages']['es'] = 'es-new'
                return 'built', 'url'
            return 'rebuilt', 'url'
        f, back, mv, push = self.run_comebacks(tiers, ready=ready)
        self.assertEqual([x['id'] for x in back], ['SIXMONTHS'])
        mv.assert_called_once_with('fr-six', 'FR_FOLDER')  # the built Spanish page is already in its folder
        self.assertNotIn('comeback_tries', f['SIXMONTHS'])

    def test_after_three_failed_runs_one_note_then_only_relist_tries(self):
        tiers = {'fr': {'SIXMONTHS': {'tier': 1, 'n': 14, 'avg': 15146, 'best': 156955}}}
        f = fmts()
        f[1]['comeback_tries'] = 2
        _, back, _, push = self.run_comebacks(tiers, ready=lambda *a: ('error', 'x'), f=f)
        push.assert_called_once()
        self.assertEqual(f[1]['comeback_tries'], 3)
        self.run_comebacks(tiers, ready=lambda *a: ('error', 'x'), f=f)
        self.assertEqual(self.ready_calls, 0)  # not tried again on its own
        _, back, _, _ = self.run_comebacks(tiers, f=f, force=True)  # mode relist
        self.assertEqual([x['id'] for x in back], ['SIXMONTHS'])


class LineupTests(unittest.TestCase):
    def test_clean_up_never_takes_out_a_format_proven_for_us(self):
        cfg = json.loads(json.dumps(CFG))
        cfg['lineup']['min_formats'] = 0
        live = [{'id': f'F{i}', 'status': 'active', 'title': f'F{i}'} for i in range(3)]
        own_videos = {str(i): ours('es', 'F0', 30000) for i in range(3)}
        p = lineup.plan({}, live, cfg, own_videos, now=NOW)
        out = {f['id'] for f, _, _ in p['out']}
        self.assertNotIn('F0', out)
        self.assertEqual(p['protected']['F0'], 'proven for our creators')


if __name__ == '__main__':
    unittest.main()
