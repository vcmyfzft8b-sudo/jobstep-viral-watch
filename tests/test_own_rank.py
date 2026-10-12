"""Per-market list order from our own creators' results (own.tiers + rank.order) and Instagram videos from Megasheet."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from watcher import megasheet, own, rank, state

DAY = 86400
NOW = time.time()
CFG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))
FMTS = [{'id': i, 'status': 'active', 'title': i, 'description': i} for i in ('EXHR', 'LINKEDIN', 'OCT', 'HOT', 'WEAK', 'NEW')]


def ours(market, fmt, views, days_old=4, **kw):
    return {'handle': kw.pop('handle', f'c_{market}'), 'market': market, 'created': NOW - days_old * DAY,
            'views': views, 'ours': True, 'checked': True, 'format': fmt, **kw}


def own_videos():
    v = {}
    n = 0

    def add(market, fmt, views, **kw):
        nonlocal n
        n += 1
        v[str(n)] = ours(market, fmt, views, **kw)
    # Spain: Ex-HR is a hit, WEAK keeps flopping
    for x in (244000, 77000, 46000, 900):
        add('es', 'EXHR', x)
    for _ in range(7):
        add('es', 'WEAK', 800)
    add('es', 'OCT', 3000), add('es', 'OCT', 2500), add('es', 'OCT', 2200)
    # France: Ex-HR flops, LinkedIn had one 100k+ video this week (only 1 day old - still counts as proven)
    for _ in range(6):
        add('fr', 'EXHR', 1200)
    add('fr', 'LINKEDIN', 120000, days_old=1)
    return v


def jobstep_history():
    """HOT and WEAK are going viral for JobStep right now (5+ confirmed viral videos in 7 days)."""
    h = {}
    for fid in ('HOT', 'WEAK'):
        for k in range(5):
            h[f'{fid}{k}'] = {'handle': 'js', 'format': fid, 'judged': True, 'views': 150000, 'created': NOW - DAY}
    return h


class TierTests(unittest.TestCase):
    def test_tiers_are_per_market(self):
        es = own.tiers(own_videos(), FMTS, NOW, 'es', CFG)
        fr = own.tiers(own_videos(), FMTS, NOW, 'fr', CFG)
        self.assertEqual(es['EXHR']['tier'], 1)  # 92k average in Spain
        self.assertEqual(fr['EXHR']['tier'], 4)  # 6 videos, 1.2k average in France
        self.assertEqual(es['WEAK']['tier'], 4)
        self.assertEqual(es['OCT']['tier'], 2)  # 3 videos, 2.6k average
        self.assertEqual(fr['LINKEDIN']['tier'], 1)  # one 100k+ video in the last 14 days
        self.assertNotIn('NEW', es)  # none of our videos = tier 3 (JobStep decides)

    def test_weak_is_relative_to_the_market(self):
        low = {str(i): ours('de', 'OCT' if i < 6 else 'HOT', 500 if i < 6 else 400) for i in range(20)}
        self.assertEqual(own.tiers(low, FMTS, NOW, 'de', CFG)['OCT']['tier'], 3)  # normal for a low-view market
        low.update({f'x{i}': ours('de', 'HOT', 2000) for i in range(20)})
        self.assertEqual(own.tiers(low, FMTS, NOW, 'de', CFG)['OCT']['tier'], 4)  # clearly below the usual now

    def test_thresholds_come_from_config(self):
        cfg = json.loads(json.dumps(CFG))
        cfg['ranking']['own_tiers']['weak_min_videos'] = 20
        self.assertEqual(own.tiers(own_videos(), FMTS, NOW, 'fr', cfg)['EXHR']['tier'], 3)

    def test_old_and_too_young_videos_do_not_count_in_the_average(self):
        v = {'a': ours('es', 'OCT', 50000, days_old=40), 'b': ours('es', 'OCT', 50000, days_old=0.5),
             'c': ours('es', 'OCT', 500), 'd': ours('es', 'OCT', 500)}
        t = own.tiers(v, FMTS, NOW, 'es', CFG)['OCT']
        self.assertEqual((t['n'], t['avg'], t['tier']), (2, 500, 3))


class OrderTests(unittest.TestCase):
    def order(self, market):
        with mock.patch.object(rank, 'own_stats', return_value={}):
            t = own.tiers(own_videos(), FMTS, NOW, market, CFG)
            return rank.order(jobstep_history(), FMTS, CFG, tiers=t, market=market)

    def test_spain(self):
        ids, s = self.order('es')
        self.assertEqual(ids[:2], ['EXHR', 'HOT'])  # proven for us beats JobStep-hot; both in the top card
        self.assertTrue(s['EXHR']['top'] and s['HOT']['top'])
        self.assertEqual(ids[2], 'OCT')  # solid for us
        self.assertEqual(ids[-1], 'WEAK')  # weak for us sinks below everything, even though it is hot for JobStep
        self.assertFalse(s['WEAK']['top'])

    def test_france(self):
        ids, s = self.order('fr')
        self.assertEqual(ids[0], 'LINKEDIN')
        self.assertEqual(set(ids[1:3]), {'HOT', 'WEAK'})  # no videos of ours in France: JobStep-hot stays on top
        self.assertEqual(ids[-1], 'EXHR')  # Ex-HR is weak in France only
        self.assertEqual(sum(s[i]['top'] for i in ids), 3)

    def test_without_tiers_the_jobstep_order_is_unchanged(self):
        with mock.patch.object(rank, 'own_stats', return_value={}):
            ids, s = rank.order(jobstep_history(), FMTS, CFG)
        self.assertEqual(set(ids[:2]), {'HOT', 'WEAK'})
        self.assertTrue(s['WEAK']['top'])


class InstagramTests(unittest.TestCase):
    def test_megasheet_instagram_rows_are_kept(self):
        rows = [('es', {'adLink': 'https://www.instagram.com/reel/DeU1vKbRcia', 'views': 130024, 'title': 'Vosotros sabíais esto?',
                        'createdAt': '2026-10-10T21:16:44.791Z', 'account': {'handle': 'nati_job08'},
                        'creator': {'id': 'natalia-id'}}),
                ('es', {'adLink': 'https://www.tiktok.com/@n/video/7695116077092703520', 'views': 244049,
                        'account': {'handle': 'n'}, 'creator': {'id': 'natalia-id'}})]
        videos = {}
        self.assertEqual(megasheet.merge_videos(videos, rows, NOW), 2)
        ig = videos['ig_DeU1vKbRcia']
        self.assertEqual((ig['platform'], ig['creator'], ig['handle'], ig['sticker']), ('instagram', 'natalia-id', 'nati_job08', ''))
        self.assertEqual(time.strftime('%Y-%m-%d %H:%M', time.gmtime(ig['created'])), '2026-10-10 21:16')
        self.assertEqual(videos['7695116077092703520']['platform'], 'tiktok')
        self.assertEqual(megasheet.video_key({'adLink': 'https://www.instagram.com/p/AbC_1-x/?igsh=1'}), ('ig_AbC_1-x', 'instagram'))

    def test_instagram_takes_the_format_of_its_tiktok_twin(self):
        tt = {'handle': 'n', 'creator': 'c1', 'market': 'es', 'created': NOW - 3 * DAY, 'views': 244000, 'ours': True,
              'desc': 'Sabíais esto? #adparakeetai', 'platform': 'tiktok', 'checked': True, 'format': 'EXHR'}
        ig = {'handle': 'nati', 'creator': 'c1', 'market': 'es', 'created': NOW - 3 * DAY + 3600, 'views': 130000,
              'ours': True, 'desc': 'Vosotros sabíais esto? #adparakeetai', 'platform': 'instagram', 'sticker': '', 'subtitles': ''}
        other = {**tt, 'desc': 'Octubre es el mejor mes', 'format': 'OCT', 'created': NOW - 3.5 * DAY}
        videos = {'1': tt, '2': other, 'ig_x': ig}
        with mock.patch.object(own.tiktok, 'latest_videos', return_value=[]), \
                mock.patch.object(own.classify, 'classify_many', return_value={}) as cm:
            own.update({}, videos, FMTS, CFG, NOW)
        self.assertEqual((ig['format'], ig['twin'], ig['checked']), ('EXHR', '1', True))
        cm.assert_not_called()

    def test_instagram_waits_for_an_unsorted_twin_then_sorts_alone(self):
        tt = {'handle': 'n', 'creator': 'c1', 'market': 'fr', 'created': NOW - 3 * DAY, 'views': 900, 'ours': True,
              'desc': 'Octobre', 'platform': 'tiktok'}
        ig = {'handle': 'n2', 'creator': 'c1', 'market': 'fr', 'created': NOW - 3 * DAY, 'views': 37000, 'ours': True,
              'desc': 'Octobre', 'platform': 'instagram', 'sticker': '', 'subtitles': ''}
        self.assertEqual(own.tiktok_twin({'1': tt, 'ig': ig}, ig), own.WAIT)
        self.assertIsNone(own.tiktok_twin({'ig': ig}, ig))
        ig_old = {**ig, 'created': NOW - 6 * DAY}
        with mock.patch.object(own.tiktok, 'latest_videos', return_value=[]), \
                mock.patch.object(own.tiktok, 'video_detail', return_value=None), \
                mock.patch.object(own.classify, 'classify_many', return_value={'ig': {'match': 'OCT', 'hook_en': 'oct'}}) as cm:
            own.update({}, {'ig': ig_old}, FMTS, CFG, NOW)
        cm.assert_called_once()
        self.assertEqual(ig_old['format'], 'OCT')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(state, 'DIR', self.tmp.name)
        p.start()
        self.addCleanup(p.stop)

    def test_tiers_are_fixed_for_the_week(self):
        from watcher import main
        mkts = [{'key': 'es'}, {'key': 'fr'}]
        state.save('own.json', own_videos())
        first = main.own_tiers(mkts, FMTS, CFG, now=NOW)
        self.assertEqual(first['es']['EXHR']['tier'], 1)
        state.save('own.json', {})  # new data during the week does not reshuffle the list
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW + 3600)['es']['EXHR']['tier'], 1)
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW + 3600, force=True)['es'], {})
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW + 8 * DAY)['es'], {})  # next week: fresh

    def test_a_new_hit_moves_up_mid_week_but_a_flop_waits_for_monday(self):
        from watcher import main
        mkts = [{'key': 'es'}]
        state.save('own.json', {str(i): ours('es', 'OCT', 600) for i in range(7)})
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW)['es']['OCT']['tier'], 4)
        v = state.load('own.json', {})
        v['hit'] = ours('es', 'OCT', 236000, days_old=2.5)
        state.save('own.json', v)
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW + 3600)['es']['OCT']['tier'], 1)  # up right away
        state.save('own.json', {str(i): ours('es', 'OCT', 600) for i in range(7)})
        self.assertEqual(main.own_tiers(mkts, FMTS, CFG, now=NOW + 7200)['es']['OCT']['tier'], 1)  # down: not mid-week


if __name__ == '__main__':
    unittest.main()
