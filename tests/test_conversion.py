"""Saves decide (user's rule, 16 Oct 2026 - like the Memo AI watcher): the lists hold formats that convert best AND
still go viral. Each market saves at its own level, paid ads do not count, and "proven for our creators" needs our
viewers to save the format too."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from watcher import conversion, detect, lineup, main, own, rank, state

DAY = 86400
NOW = time.time()
CFG = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')))
MARKETS = {'es_a': 'es', 'es_b': 'es', 'de_a': 'de', 'fr_a': 'fr'}


def vid(handle, fmt, views, saves, likes=None, days_old=10, **kw):
    return {'handle': handle, 'format': fmt, 'views': views, 'saves': saves,
            'likes': likes if likes is not None else views // 25, 'shares': 0, 'created': NOW - days_old * DAY, **kw}


def history():
    """Spain saves a lot (typical 3%), DACH little (typical 0.6%)."""
    h, n = {}, 0

    def add(**kw):
        nonlocal n
        n += 1
        h[str(n)] = vid(**kw)
    for _ in range(12):
        add(handle='es_a', fmt='BASE', views=50_000, saves=1_500)   # 3.0%
        add(handle='de_a', fmt='BASE', views=50_000, saves=300)     # 0.6%
    return h, add


class BaselineTests(unittest.TestCase):
    def test_each_market_has_its_own_typical_rate(self):
        h, _ = history()
        base = conversion.baselines(h, conversion.conf(CFG), NOW, MARKETS)
        self.assertAlmostEqual(base['es'], 0.03)
        self.assertAlmostEqual(base['de'], 0.006)
        self.assertNotIn('fr', base)  # too few videos: France uses all markets
        self.assertEqual(conversion.typical(base, 'fr'), base['all'])
        self.assertEqual(conversion.typical(base, None), base['all'])

    def test_a_video_counts_against_its_own_market(self):
        """A DACH format saved by 1.2% beats a Spanish one saved by 1.5% - DACH saves less."""
        h, add = history()
        for _ in range(4):
            add(handle='de_a', fmt='DE_GOOD', views=40_000, saves=480)   # 1.2% = 2x DACH typical
            add(handle='es_b', fmt='ES_WEAK', views=40_000, saves=600)   # 1.5% = half of Spain typical
        fmts = [{'id': i} for i in ('DE_GOOD', 'ES_WEAK', 'BASE')]
        b, _ = conversion.board(h, fmts, CFG, NOW, markets=MARKETS)
        self.assertGreater(b['DE_GOOD']['conv'], 1.3)
        self.assertLess(b['ES_WEAK']['conv'], 0.8)
        self.assertAlmostEqual(b['BASE']['conv'], 1.0, places=1)

    def test_paid_ads_are_left_out(self):
        h, add = history()
        add(handle='jobstep.io', fmt='ADS', views=1_100_000, saves=1_400, likes=2_600)  # 0.24% likes
        self.assertTrue(conversion.looks_paid(h[str(len(h))], CFG))
        b, _ = conversion.board(h, [{'id': 'ADS'}], CFG, NOW, markets=MARKETS)
        self.assertEqual(b['ADS']['videos'], 0)
        self.assertAlmostEqual(b['ADS']['conv'], 1.0)  # unknown = average, not a flop

    def test_one_odd_video_cannot_carry_a_format(self):
        h, add = history()
        add(handle='es_a', fmt='ODD', views=12_000, saves=6_000)  # 50% -> capped at 12%
        b, _ = conversion.board(h, [{'id': 'ODD'}], CFG, NOW, markets=MARKETS)
        self.assertLess(b['ODD']['conv'], 2.0)


class TriggerTests(unittest.TestCase):
    def test_too_few_saves_is_relative_to_the_market(self):
        v = vid('es_a', None, 200_000, 2_000)  # 1.0%
        self.assertTrue(conversion.too_few_saves(v, CFG, 0.03))    # Spain: under half of 3%
        self.assertFalse(conversion.too_few_saves(v, CFG, 0.006))  # DACH: well above
        self.assertFalse(conversion.too_few_saves({**v, 'detail_missing': True}, CFG, 0.03))  # unknown: not blocked
        self.assertTrue(conversion.too_few_saves({**v, 'likes': 500}, CFG, 0.006))  # paid ad: never builds

    def test_converting_needs_more_in_a_market_that_saves_more(self):
        v = vid('x', None, 40_000, 1_000, created=NOW - DAY)  # 2.5%
        self.assertTrue(conversion.converting(v, CFG, 0.017))   # France: 1.2 x 1.7% = 2.0%
        self.assertFalse(conversion.converting(v, CFG, 0.03))   # Spain: 1.2 x 3% = 3.6%
        self.assertFalse(conversion.converting({**v, 'views': 20_000, 'saves': 500}, CFG, 0.017))  # under 30k

    def test_detect_converting_level(self):
        th = CFG['thresholds']
        v = vid('x', None, 40_000, 1_000, days_old=3, notified=[])
        self.assertEqual(detect.level(v, NOW, None, th, CFG, 0.017), 'converting')
        self.assertIsNone(detect.level(v, NOW, None, th))  # without the conversion settings: as before
        self.assertEqual(detect.level({**v, 'views': 120_000}, NOW, None, th, CFG, 0.017), 'viral')


class HistoryTests(unittest.TestCase):
    def test_history_keeps_saves_and_a_views_only_check_keeps_the_last_ones(self):
        h = {}
        v = {'id': '9', 'handle': 'a', 'created': NOW - DAY, 'views': 50_000, 'likes': 2_000, 'saves': 900, 'shares': 10}
        main.to_history(h, v, set(), NOW)
        self.assertEqual(h['9']['saves'], 900)
        main.to_history(h, {**v, 'views': 60_000, 'saves': 0, 'detail_missing': True}, set(), NOW)
        self.assertEqual(h['9']['views'], 60_000)
        self.assertEqual(h['9']['saves'], 900)

    def test_backfill_reads_older_videos(self):
        h = {'1': {'handle': 'a', 'views': 80_000, 'created': NOW - 20 * DAY},
             '2': {'handle': 'a', 'views': 5_000, 'created': NOW - 20 * DAY}}  # under 10k: not read
        detail = lambda handle, i: {'views': 81_000, 'likes': 3_000, 'saves': 2_000, 'shares': 5}
        done = conversion.backfill(h, 10, NOW, detail=detail)
        self.assertEqual([d['id'] for d in done], ['1'])
        self.assertEqual(h['1']['saves'], 2_000)
        self.assertNotIn('saves', h['2'])


def ours(market, fmt, views, bookmarks=None, platform='tiktok', days_old=4):
    v = {'handle': f'c_{market}', 'market': market, 'created': NOW - days_old * DAY, 'views': views, 'ours': True,
         'checked': True, 'format': fmt, 'platform': platform}
    if bookmarks is not None:
        v['bookmarks'] = bookmarks
    return v


class ProvenTests(unittest.TestCase):
    FMTS = [{'id': i, 'status': 'active', 'title': i} for i in ('OUTRAGE', 'HACK', 'IG')]

    def videos(self):
        return {'1': ours('fr', 'OUTRAGE', 160_000, 1_400), '2': ours('fr', 'OUTRAGE', 35_000, 300),      # 0.9%
                '3': ours('fr', 'HACK', 50_000, 3_300), '4': ours('fr', 'HACK', 12_000, 700),             # 6.5%
                '5': ours('fr', 'IG', 150_000, 0, platform='instagram'), '6': ours('fr', 'IG', 20_000, 0, platform='instagram')}

    def test_proven_needs_our_viewers_to_save_it(self):
        t = own.tiers(self.videos(), self.FMTS, NOW, 'fr', CFG, typical_rate=0.017)
        self.assertEqual(t['OUTRAGE']['tier'], 2)  # many views for us, saved by 0.9% < 1.7%
        self.assertTrue(t['OUTRAGE']['saves_low'])
        self.assertEqual(t['HACK']['tier'], 1)
        self.assertEqual(t['IG']['tier'], 1)  # Instagram hides saves: views alone decide
        self.assertIsNone(t['IG']['save_rate'])


class OrderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(state, 'DIR', tmp.name), mock.patch.object(conversion, 'market_map', return_value=MARKETS)):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_a_format_that_converts_beats_one_that_only_goes_viral(self):
        h, add = history()
        for k in range(6):  # goes viral (6 x 300k this week) but nobody saves it: 0.3% in Spain
            add(handle='es_a', fmt='SKIT', views=300_000, saves=900, days_old=2, judged=True)
        for k in range(4):  # 60k views, saved by 6%
            add(handle='es_b', fmt='HACK', views=60_000, saves=3_600, days_old=5, judged=True)
        fmts = [{'id': i, 'status': 'active', 'title': i} for i in ('SKIT', 'HACK', 'BASE')]
        ids, s = rank.order(h, fmts, CFG, tiers={}, market='es')
        self.assertLess(ids.index('HACK'), ids.index('SKIT'))
        self.assertFalse(s['SKIT']['hot'])  # 5+ viral, but not saved like an average format
        self.assertGreater(s['HACK']['conv'], 1.5)

    def test_our_viral_video_puts_a_format_on_the_red_card_only_when_it_is_saved(self):
        h, _ = history()
        fmts = [{'id': i, 'status': 'active', 'title': i} for i in ('OUTRAGE', 'HACK')]
        own_week = {'OUTRAGE': {'n': 2, 'recent_viral': 1}, 'HACK': {'n': 2, 'recent_viral': 1}}
        tiers = {'OUTRAGE': {'tier': 2, 'saves_low': True}, 'HACK': {'tier': 1}}
        with mock.patch.object(rank, 'own_stats', return_value=own_week):
            _, s = rank.order(h, fmts, CFG, tiers=tiers, market='fr')
        self.assertFalse(s['OUTRAGE']['top'])
        self.assertTrue(s['HACK']['top'])

    def test_clean_up_takes_out_a_measured_format_nobody_saves_even_when_viral(self):
        h, add = history()
        for k in range(3):
            add(handle='es_a', fmt='SKIT', views=300_000, saves=600, days_old=3, judged=True)
        fmts = [{'id': i, 'status': 'active', 'title': i, 'listed_at': NOW - 60 * DAY} for i in 'ABCDEFGH'] + \
               [{'id': 'SKIT', 'status': 'active', 'title': 'SKIT', 'listed_at': NOW - 2 * DAY}]
        cfg = {**CFG, 'markets': {'es': {'enabled': True}}}
        with mock.patch.object(own, 'tiers', return_value={}):
            p = lineup.plan(h, fmts, cfg, {}, now=NOW)
        self.assertIn('SKIT', [f['id'] for f, _, _ in p['out']])
        self.assertIsNone(p['protected']['SKIT'])  # viral and new, but measured and not saved

    def test_proven_for_us_still_protects(self):
        h, add = history()
        for k in range(3):
            add(handle='es_a', fmt='SKIT', views=300_000, saves=600, days_old=3, judged=True)
        fmts = [{'id': 'SKIT', 'status': 'active', 'title': 'SKIT'}]
        cfg = {**CFG, 'markets': {'es': {'enabled': True}}, 'lineup': {**CFG['lineup'], 'min_formats': 0}}
        with mock.patch.object(own, 'tiers', return_value={'SKIT': {'tier': 1}}):
            p = lineup.plan(h, fmts, cfg, {}, now=NOW)
        self.assertEqual(p['out'], [])
        self.assertEqual(p['protected']['SKIT'], 'proven for our creators')


class BuildGateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(state, 'DIR', tmp.name),
                  mock.patch.object(conversion, 'market_map', return_value=MARKETS),
                  mock.patch.object(main.notify, 'radar'),
                  mock.patch.object(main.media, 'download', return_value='v.mp4'),
                  mock.patch.object(main.media, 'audio', return_value='a.mp3'),
                  mock.patch.object(main.soniox, 'transcribe', return_value={'text': 'hi', 'segments': []}),
                  mock.patch.object(main.classify, 'judge', return_value={'english_script': 'hi'})):
            p.start()
        self.push = mock.patch.object(main.notify, 'push').start()
        self.addCleanup(mock.patch.stopall)
        self.cfg = {**CFG, 'notion': {'radar_page': 'radar'}, 'models': {'classify': 'c', 'build': 'b'}}

    def viral(self, saves, likes=8_000):
        return {'id': '7', 'handle': 'es_a', 'created': NOW - 2 * DAY, 'views': 200_000, 'likes': likes, 'saves': saves,
                'shares': 100, 'url': 'https://www.tiktok.com/@es_a/video/7', 'notified': []}

    def test_a_viral_video_nobody_saves_does_not_build(self):
        h, _ = history()
        with mock.patch.object(main, 'build_format') as build:
            r = main.handle_alert(self.viral(saves=1_000), 'viral', [], [], h, self.cfg, NOW, False, False)  # 0.5% in Spain
        build.assert_not_called()
        self.assertIn('too few saves', self.push.call_args[0][1])
        self.assertEqual(r['level'], 'viral')

    def test_a_viral_video_with_saves_builds(self):
        h, _ = history()
        with mock.patch.object(main, 'build_format', return_value=({'id': 'N', 'title': 'N'}, [], 3)) as build:
            main.handle_alert(self.viral(saves=6_000), 'viral', [], [], h, self.cfg, NOW, False, False)  # 3%
        build.assert_called_once()

    def test_a_paid_ad_does_not_build(self):
        h, _ = history()
        with mock.patch.object(main, 'build_format') as build:
            main.handle_alert(self.viral(saves=6_000, likes=400), 'viral', [], [], h, self.cfg, NOW, False, False)
        build.assert_not_called()
        self.assertIn('paid ad', self.push.call_args[0][1])

    def test_an_archived_format_comes_back_only_with_typical_saves(self):
        h, _ = history()
        old = {'id': 'OLD', 'status': 'archived', 'title': 'Old one', 'pages': {}}
        verdict = {'duplicate_of': 'OLD', 'english_script': 'hi'}
        with mock.patch.object(main.classify, 'judge', return_value=verdict), \
                mock.patch.object(main, 'revive_format', return_value=(True, 2, [])) as revive:
            main.handle_alert(self.viral(saves=4_000), 'viral', [], [old], h, self.cfg, NOW, False, False)  # 2% < 3%
            revive.assert_not_called()
            self.assertIn('less than a typical video', self.push.call_args[0][1])
            v = self.viral(saves=8_000)  # 4%
            v['id'] = '8'
            main.handle_alert(v, 'viral', [], [old], h, self.cfg, NOW, False, False)
            revive.assert_called_once()

    def test_unknown_saves_wait_for_a_full_check(self):
        v = {**self.viral(saves=0), 'detail_missing': True}
        with mock.patch.object(main, 'handle_viral') as hv:
            r = main.handle_alert(v, 'viral', [], [], {}, self.cfg, NOW, False, False)
        hv.assert_not_called()
        self.assertEqual(r['deferred'], 'saves unknown')

    def test_converting_video_builds_like_a_rising_one(self):
        h, _ = history()
        v = {**self.viral(saves=1_800), 'views': 45_000, 'likes': 3_000}  # 4% in Spain
        with mock.patch.object(main, 'build_format', return_value=({'id': 'N', 'title': 'N'}, [], 3)) as build:
            r = main.handle_alert(v, 'converting', [], [], h, self.cfg, NOW, False, False)
        build.assert_called_once()
        self.assertIn('CONVERTING', self.push.call_args[0][0])
        self.assertEqual(r['level'], 'converting')
        self.assertTrue({'converting', 'rising', 'viral'} <= set(v['notified']))  # one Slack ping per video


if __name__ == '__main__':
    unittest.main()
