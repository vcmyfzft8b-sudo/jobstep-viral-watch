"""Format pages in Megasheet (16 Oct 2026, user: "stop using Notion"): the watcher builds, checks, fixes and orders the
format pages directly as Megasheet ideas (watcher/pages.py). A fake Megasheet stands in for the real one."""
import copy
import io
import json
import os
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

from watcher import localize, megasheet, pages, reword, state, tidy
from watcher.markets import TEXT

LINKS = {'parakeet': 'https://www.parakeet-ai.com/resume-maker', 'linkedin': 'https://www.linkedin.com/jobs/'}
SPEC = {'title_hook': 'Les RH ne veulent PAS que tu saches ça', 'voiceover': True,
        'visual_hook_first': 'Filme-toi en marchant dehors, le titre à l’écran dès la première image.',
        'script': [{'text': 'Je viens de descendre du train.'},
                   {'text': 'Elle a dit que les CV passent par un filtre ATS.', 'new_paragraph': True},
                   {'cue': 'parakeet', 'text': 'Alors je mets mon CV sur Parakeet AI.', 'new_paragraph': True}],
        'assets_needed': [{'name': 'Gmail', 'description': 'capture de la boîte mail'}]}
VIDEO = {'url': 'https://www.tiktok.com/@origomez953/video/7696706553432345874'}
CAMPS = {'fr': '5cf4df12-f6dd-467a-a1e8-dbe07f709425', 'es': 'f70ac122-5e87-4780-9229-65b2740bfb3a',
         'sl': '28808b83-9313-4575-afc9-7b0805c497a5'}


class FakeMegasheet:
    """Megasheet's format tools as they behave: create/update answer with the id only, update replaces the idea."""

    def __init__(self):
        self.ideas = {c: [] for c in CAMPS.values()}
        self.calls = []
        self.known = {}
        self.title_locked = set()  # titles used by creators' videos (cannot be removed)

    def _find(self, iid):
        return next(i for ideas in self.ideas.values() for i in ideas if i['id'] == iid)

    def call(self, tool, campaignId=None, **a):
        self.calls.append((tool, a))
        if tool == 'list_campaigns':
            return [{'id': c, 'name': n} for n, c in zip(('ParakeetAI - France', 'ParakeetAI - Spain',
                                                           'ParakeetAI - Slovenia'), CAMPS.values())] + \
                   [{'id': 'dach', 'name': 'ParakeetAI - DACH'}]
        if tool == 'formats_getIdeas':
            return copy.deepcopy(self.ideas[campaignId])
        if tool in ('formats_createIdea', 'formats_updateIdea'):
            missing = {'name', 'tag', 'groupId', 'status', 'captionsRequired', 'titles', 'description', 'visualHook',
                       'mediaNotice', 'scripts', 'resources'} - set(a)
            assert not missing, f'{tool}: {missing} Required'
        if tool == 'formats_createIdea':
            idea = self._idea(a, campaignId)
            self.ideas[campaignId].append(idea)
            return {'id': idea['id']}
        if tool == 'formats_updateIdea':
            i = self._find(a['id'])
            kept = {t['text'] for t in a['titles']}
            gone = [t['text'] for t in i['titles'] if t['text'] in self.title_locked and t['text'] not in kept]
            if gone:
                raise RuntimeError('megasheet formats_updateIdea: title is assigned to videos and cannot be removed')
            new = self._idea(a, campaignId)
            i.update({k: v for k, v in new.items() if k not in ('id', 'media', 'createdAt')})
            return {'id': i['id']}
        if tool == 'formats_updateIdeaStatus':
            self._find(a['id'])['status'] = a['status']
            return {}
        if tool == 'formats_reorderIdeas':
            assert sorted(a['ids']) == sorted(i['id'] for i in self.ideas[campaignId]), 'every idea must be named'
            self.ideas[campaignId].sort(key=lambda i: a['ids'].index(i['id']))
            return {}
        if tool == 'formats_createMediaUpload':
            return {'url': 'https://megasheet.app/api/uploadthing', 'slug': 'ideaMedia',
                    'input': {'campaignId': campaignId, 'ideaId': a['ideaId'], 'token': 't'}}
        if tool == 'formats_removeMedia':
            for ideas in self.ideas.values():
                for i in ideas:
                    i['media'] = [m for m in i['media'] if m['id'] != a['id']]
            return {}
        raise AssertionError(tool)

    def attach(self, idea_id, name):
        mid = str(uuid.uuid4())
        self._find(idea_id)['media'].append({'id': mid, 'kind': 'video', 'fileUrl': f'https://ufs/f/{mid}',
                                             'fileName': name, 'fileSizeBytes': 10})
        return {'id': mid, 'kind': 'video', 'fileUrl': f'https://ufs/f/{mid}?sig=1', 'fileName': name}

    @staticmethod
    def _idea(a, camp):
        return {'id': a.get('id') or str(uuid.uuid4()), 'campaignId': camp, 'tag': a['tag'], 'name': a['name'],
                'groupId': a.get('groupId'), 'status': a['status'], 'captionsRequired': a['captionsRequired'],
                'description': a['description'], 'visualHook': a['visualHook'], 'mediaNotice': a['mediaNotice'],
                'media': [], 'updatedAt': '2026-10-16T20:00:00.000Z',
                'titles': [{'id': t.get('id') or str(uuid.uuid4()), 'label': None, 'text': t['text']} for t in a['titles']],
                'scripts': [{'id': s.get('id') or str(uuid.uuid4()), 'label': None, 'text': s['text']} for s in a['scripts']],
                'resources': [{'id': r.get('id') or str(uuid.uuid4()), 'fileKey': None, **r} for r in a['resources']]}

    def writes(self):
        return [c for c in self.calls if c[0] not in ('formats_getIdeas', 'list_campaigns')]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(state, 'DIR', tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.ms = FakeMegasheet()
        self.video = os.path.join(tmp.name, 'example.mp4')
        with open(self.video, 'wb') as f:
            f.write(b'\0' * 2048)
        self.http = []
        for name in ('post', 'put'):
            p = mock.patch.object(pages.requests, name, side_effect=getattr(self, 'fake_' + name))
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.fresh_run)
        self.fresh_run()

    def fresh_run(self):
        """A new watcher process: nothing cached, the state file is read again."""
        pages.DRY = False
        st = pages.reset()
        st.client, st.camps = self.ms, dict(CAMPS)
        return st

    def fake_post(self, url, json=None, timeout=None):
        self.http.append(('post', url))
        r = mock.Mock(ok=True)
        r.raise_for_status = lambda: None
        r.json = lambda: [{'url': 'https://ingest/put/' + json['input']['ideaId'], 'key': 'k'}]
        return r

    def fake_put(self, url, headers=None, files=None, timeout=None):
        self.http.append(('put', url))
        idea_id = url.rsplit('/', 1)[1]
        media = self.ms.attach(idea_id, files['file'][0])
        r = mock.Mock(ok=True)
        r.raise_for_status = lambda: None
        r.json = lambda: {'serverData': {'media': media}}
        return r

    def build(self, market='fr', spec=SPEC, place='staging', video=True):
        lang = 'fr' if market == 'fr' else market
        up = pages.upload_video(self.video) if video else None
        blocks = pages.page_blocks(spec, VIDEO, up, LINKS, lang=lang)
        return pages.create_page(pages.place(place, market), spec['title_hook'], '🎬', blocks)['id']

    def idea(self, iid):
        return self.ms._find(iid)


class BuildTests(Base):
    def test_a_new_page_is_an_archived_idea_with_its_video(self):
        iid = self.build()
        i = self.idea(iid)
        self.assertEqual(i['status'], 'archived')  # staging: creators do not see it yet
        self.assertEqual(i['name'], SPEC['title_hook'])
        self.assertEqual([t['text'] for t in i['titles']], [SPEC['title_hook']])
        self.assertEqual(i['scripts'][0]['text'], 'Je viens de descendre du train.\n\n'
                         'Elle a dit que les CV passent par un filtre ATS.\n\n'
                         '([Parakeet AI · Resume Maker](https://www.parakeet-ai.com/resume-maker)) '
                         'Alors je mets mon CV sur Parakeet AI.')
        self.assertEqual(i['visualHook'], SPEC['visual_hook_first'] + '\n\n🚨 Un visual hook est obligatoire sur chaque vidéo !')
        self.assertEqual(i['resources'][0]['url'], VIDEO['url'])
        self.assertEqual(i['resources'][1]['url'], LINKS['parakeet'])
        self.assertTrue(i['description'].startswith('**Important :**'))
        self.assertIn('- 📎 Gmail – à préparer: capture de la boîte mail', i['description'])
        self.assertTrue(i['captionsRequired'])
        self.assertEqual(len(i['media']), 1)  # the example video was uploaded (UploadThing)
        self.assertEqual([h[0] for h in self.http], ['post', 'put'])
        r = pages.STORE.rec(iid)
        self.assertEqual((r['market'], r['place']), ('fr', 'staging'))
        self.assertEqual(r['media_ids'], [i['media'][0]['id']])

    def test_silent_video_needs_no_captions(self):
        i = self.idea(self.build(spec=dict(SPEC, voiceover=False)))
        self.assertFalse(i['captionsRequired'])
        self.assertIn('🎵 ' + TEXT['fr']['sub_silent'], i['description'])

    def test_every_market_draws_and_reads_its_own_layout(self):
        for m in ('fr', 'es', 'sl'):
            iid = self.build(market=m, spec=dict(SPEC, title_hook=f'Titre {m}'))
            blocks = pages.children(iid)
            self.assertEqual(reword._plain(next(b for b in blocks if b['type'] == 'heading_2')), '📲' + TEXT[m]['title_h'])
            self.assertEqual(len(reword.script_blocks(iid)), 3, m)
            self.assertEqual(localize.current_source(iid)['url'], VIDEO['url'], m)

    def test_nothing_is_written_when_nothing_changed(self):
        iid = self.build()
        pages.STORE.finish()
        self.fresh_run()
        n = len(self.ms.writes())
        for b in pages.children(iid):  # every block written back exactly as it is
            if 'rich_text' in b[b['type']]:
                pages.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': b[b['type']]['rich_text']}})
        self.assertEqual(tidy.tidy_page(iid, LINKS), [])
        self.assertEqual(len(self.ms.writes()), n)

    def test_the_numbered_title_is_not_used(self):
        iid = self.build(spec=dict(SPEC, title_hook='3. Mens sur ton CV'))
        self.assertEqual(self.idea(iid)['name'], 'Mens sur ton CV')


class UpdateTests(Base):
    def test_a_changed_paragraph_changes_only_the_script(self):
        iid = self.build()
        pages.STORE.finish()
        before = copy.deepcopy(self.idea(iid))
        self.fresh_run()
        b = reword.script_blocks(iid)[0]
        pages.api('PATCH', f"/blocks/{b['id']}", {'paragraph': {'rich_text': [pages.rt('Je descends du train.')]}})
        calls = [c for c in self.ms.writes() if c[0] == 'formats_updateIdea']
        self.assertEqual(len(calls), 1)
        after = self.idea(iid)
        self.assertTrue(after['scripts'][0]['text'].startswith('Je descends du train.\n\nElle a dit'))
        for k in ('name', 'description', 'visualHook', 'captionsRequired'):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(after['titles'][0]['id'], before['titles'][0]['id'])  # unchanged parts keep their ids
        self.assertEqual(after['resources'][0]['id'], before['resources'][0]['id'])

    def test_title_change_renames_the_idea(self):
        from watcher import crosscheck
        iid = self.build()
        self.assertTrue(crosscheck.set_title(iid, 'Nouveau titre'))
        self.assertEqual(self.idea(iid)['name'], 'Nouveau titre')
        self.assertEqual([t['text'] for t in self.idea(iid)['titles']], ['Nouveau titre'])

    def test_a_title_used_by_videos_is_kept_after_ours(self):
        from watcher import crosscheck
        iid = self.build()
        self.ms.title_locked.add(SPEC['title_hook'])
        crosscheck.set_title(iid, 'Nouveau titre')
        self.assertEqual([t['text'] for t in self.idea(iid)['titles']], ['Nouveau titre', SPEC['title_hook']])
        self.assertEqual(pages.STORE.rec(iid)['keep_titles'], [SPEC['title_hook']])

    def test_new_example_video_replaces_the_old_one(self):
        iid = self.build()
        old = self.idea(iid)['media'][0]['id']
        src = localize.current_source(iid)
        new_url = 'https://www.tiktok.com/@other/video/7600000000000000001'
        with mock.patch.object(localize.media, 'download', return_value=self.video), \
                mock.patch.object(localize.media, 'for_notion', side_effect=lambda f, w: f):
            localize.replace_video(iid, src, {'url': new_url}, 'fr')
        i = self.idea(iid)
        self.assertEqual(len(i['media']), 1)
        self.assertNotEqual(i['media'][0]['id'], old)  # uploaded first, then the old one removed
        self.assertEqual(i['resources'][0]['url'], new_url)  # the "original on TikTok" link follows
        tools = [c[0] for c in self.ms.writes()]
        self.assertLess(tools.index('formats_createMediaUpload', 2), tools.index('formats_removeMedia'))

    def test_rebuild_replaces_the_content_of_the_same_idea(self):
        iid = self.build()
        spec = dict(SPEC, script=[{'text': 'Tout nouveau script.'}])
        pages.replace_content(iid, pages.page_blocks(spec, VIDEO, None, LINKS, lang='fr'))
        i = self.idea(iid)
        self.assertEqual(i['scripts'][0]['text'], 'Tout nouveau script.')
        self.assertEqual(len(self.ms.ideas[CAMPS['fr']]), 1)  # no second idea

    def test_dry_run_writes_nothing(self):
        iid = self.build()
        pages.STORE.finish()
        self.fresh_run()
        pages.DRY = True
        n = len(self.ms.writes())
        b = reword.script_blocks(iid)[0]
        with redirect_stdout(io.StringIO()) as out:
            pages.api('PATCH', f"/blocks/{b['id']}", {'paragraph': {'rich_text': [pages.rt('Autre texte.')]}})
            pages.move_page(iid, pages.place('live', 'fr'))
        self.assertEqual(len(self.ms.writes()), n)
        self.assertIn('[dry] fr: updated', out.getvalue())
        self.assertIn('[dry] fr: published', out.getvalue())
        self.assertEqual(len(pages.STORE.writes), 2)


class HandEditTests(Base):
    def edited_by_hand(self):
        iid = self.build()
        pages.STORE.finish()
        i = self.idea(iid)  # the user edits the script directly in Megasheet
        i['scripts'][0]['text'] = 'Mon texte à moi.\n\n' + i['scripts'][0]['text']
        self.fresh_run()
        return iid

    def test_an_idea_edited_in_megasheet_is_never_overwritten(self):
        iid = self.edited_by_hand()
        with redirect_stdout(io.StringIO()):
            blocks = reword.script_blocks(iid)
            self.assertTrue(pages.is_hand(iid))
            n = len(self.ms.writes())
            pages.api('PATCH', f"/blocks/{blocks[0]['id']}", {'paragraph': {'rich_text': [pages.rt('Watcher text')]}})
            pages.api('DELETE', f"/blocks/{blocks[1]['id']}")
            self.assertFalse(pages.replace_content(iid, pages.page_blocks(SPEC, VIDEO, None, LINKS, lang='fr')))
            self.assertEqual(tidy.tidy_page(iid, LINKS), [])
        self.assertEqual(len(self.ms.writes()), n)
        self.assertTrue(self.idea(iid)['scripts'][0]['text'].startswith('Mon texte à moi.'))
        self.assertTrue(state.load('pages.json', {})['ideas'][iid]['hand'])  # remembered for every later run

    def test_list_order_hot_line_and_status_still_follow_the_ranking(self):
        iid = self.edited_by_hand()
        other = self.build(spec=dict(SPEC, title_hook='Autre format'))
        with redirect_stdout(io.StringIO()):
            pages.set_order('list:fr', [iid, other], hot_count=1)
        i = self.idea(iid)
        self.assertEqual(i['status'], 'published')
        self.assertTrue(i['description'].startswith('**🔥 En train de devenir viral'))
        self.assertTrue(i['scripts'][0]['text'].startswith('Mon texte à moi.'))  # content still the user's
        self.assertEqual([x['id'] for x in self.ms.ideas[CAMPS['fr']]], [iid, other])

    def test_videos_changed_by_hand_are_kept(self):
        iid = self.build()
        pages.STORE.finish()
        self.ms.attach(iid, 'second.mp4')  # the user adds a video in Megasheet
        self.fresh_run()
        with redirect_stdout(io.StringIO()):
            pages.children(iid)
        self.assertTrue(pages.is_hand(iid))
        n = len(self.ms.writes())
        src = localize.current_source(iid)
        with redirect_stdout(io.StringIO()):
            pages.api('DELETE', f"/blocks/{src['video']}")
        self.assertEqual(len(self.ms.writes()), n)
        self.assertEqual(len(self.idea(iid)['media']), 2)

    def test_audit_and_ready_page_leave_a_hand_page_alone(self):
        from watcher import audit, main
        iid = self.edited_by_hand()
        with redirect_stdout(io.StringIO()):
            pages.children(iid)
        f = {'id': 'F1', 'title': 'T', 'status': 'active', 'pages': {'fr': iid}}
        mk = {'key': 'fr', 'lang': 'fr', 'T': TEXT['fr']}
        with mock.patch.object(audit, 'check', side_effect=AssertionError('no Claude check for a hand page')):
            self.assertEqual(audit.fix_page(f, mk, {'models': {'build': 'b'}, 'links': LINKS}, {}, {}, {},
                                            main.page_of)[0], 'ok')
        self.assertEqual(main.ready_page(f, mk, [f], {}, {'links': LINKS})[0], 'ok')

    def test_our_own_write_is_not_taken_for_a_hand_edit(self):
        iid = self.build()
        b = reword.script_blocks(iid)[0]
        pages.api('PATCH', f"/blocks/{b['id']}", {'paragraph': {'rich_text': [pages.rt('Texte du watcher.')]}})
        pages.STORE.finish()
        self.fresh_run()
        pages.children(iid)
        self.assertFalse(pages.is_hand(iid))


class ListTests(Base):
    def three(self):
        ids = [self.build(spec=dict(SPEC, title_hook=f'Format {x}')) for x in 'ABC']
        hand_made = FakeMegasheet._idea({'tag': 'hand', 'name': 'Idée faite à la main', 'status': 'published',
                                         'captionsRequired': True, 'titles': [{'text': 'Idée faite à la main'}],
                                         'description': '', 'visualHook': '', 'mediaNotice': '', 'scripts': [],
                                         'resources': []}, CAMPS['fr'])
        self.ms.ideas[CAMPS['fr']].insert(0, hand_made)
        self.fresh_run()
        return ids, hand_made['id']

    def test_the_list_is_our_published_ideas_in_order_hot_first(self):
        (a, b, c), hand_made = self.three()
        pages.set_order('list:fr', [b, a], hot_count=1)
        order = [i['id'] for i in self.ms.ideas[CAMPS['fr']]]
        self.assertEqual(order, [b, a, hand_made, c])  # ours, then the hand-made idea, then the archive
        self.assertEqual([self.idea(x)['status'] for x in (b, a, c)], ['published', 'published', 'archived'])
        self.assertTrue(self.idea(b)['description'].startswith('**🔥'))
        self.assertFalse(self.idea(a)['description'].startswith('**🔥'))
        self.assertEqual(pages.list_entries('list:fr')[0], [(b, b), (a, a)])
        self.assertEqual(pages.hot_entry_count('list:fr'), 1)
        self.assertEqual(self.idea(hand_made)['status'], 'published')  # never touched

    def test_the_same_order_again_writes_nothing(self):
        (a, b, c), _ = self.three()
        pages.set_order('list:fr', [b, a], hot_count=1)
        pages.STORE.finish()
        self.fresh_run()
        n = len(self.ms.writes())
        pages.set_order('list:fr', [b.replace('-', ''), a], hot_count=1)  # ids with or without dashes
        self.assertEqual(len(self.ms.writes()), n)

    def test_off_the_list_is_archived_and_a_comeback_publishes_the_same_idea(self):
        (a, b, c), _ = self.three()
        pages.set_order('list:fr', [a, b, c], hot_count=2)
        pages.set_order('list:fr', [a], hot_count=0)  # b and c leave the list
        self.assertEqual([self.idea(x)['status'] for x in (a, b, c)], ['published', 'archived', 'archived'])
        self.assertFalse(self.idea(b)['description'].startswith('**🔥'))  # no 🔥 left on an archived idea
        self.assertEqual(pages.STORE.rec(b)['place'], 'archive')
        pages.move_page(c, 'live:fr')  # comeback: the same idea, nothing rebuilt
        pages.set_order('list:fr', [c, a])
        self.assertEqual([self.idea(x)['status'] for x in (a, b, c)], ['published', 'archived', 'published'])
        self.assertEqual(len(self.ms.ideas[CAMPS['fr']]), 4)
        self.assertNotIn('formats_deleteIdea', [w[0] for w in self.ms.writes()])

    def test_rerank_draws_the_list_from_the_ranking(self):
        from watcher import main, markets as M
        (a, b, c), _ = self.three()
        fmts = [{'id': x, 'status': 'active', 'title': x, 'description': x, 'pages': {'fr': pid}}
                for x, pid in (('A', a), ('B', b), ('C', c))]
        cfg = json.load(open(os.path.join(pages.ROOT, 'config.json')))
        mkts = [m for m in M.load(cfg) if m['key'] == 'fr']
        state.save('own.json', {})
        ids = main.rerank(mkts, fmts, {}, cfg)
        self.assertEqual([p for _, p in pages.list_entries('list:fr')[0]], [dict(A=a, B=b, C=c)[i] for i in ids])
        pages.STORE.finish()
        self.fresh_run()
        n = len(self.ms.writes())
        main.rerank(mkts, fmts, {}, cfg)
        self.assertEqual(len(self.ms.writes()), n)  # unchanged ranking: nothing sent

    def test_publish_and_rollback_through_the_gate(self):
        from watcher import gate
        a = self.build()
        fmt = {'id': 'F', 'status': 'pending', 'pages': {'fr': a}}
        mk = {'key': 'fr', 'holder_page': 'live:fr', 'T': TEXT['fr']}
        gate.publish(fmt, [mk], lambda f, m: f['pages'].get(m))
        self.assertEqual(self.idea(a)['status'], 'published')
        self.assertEqual(fmt['status'], 'active')


class AllowListTests(unittest.TestCase):
    def test_uploads_only_for_ideas_of_france_spain_slovenia(self):
        c = megasheet.Client.__new__(megasheet.Client)
        c.known = {CAMPS['fr']: {'idea-1'}}
        c._check('formats_createMediaUpload', {'campaignId': CAMPS['fr'], 'ideaId': 'idea-1'})
        with self.assertRaises(megasheet.NotAllowed):
            c._check('formats_createMediaUpload', {'campaignId': CAMPS['fr'], 'ideaId': 'other'})
        with self.assertRaises(megasheet.NotAllowed):
            c._check('formats_createMediaUpload', {'campaignId': 'dach', 'ideaId': 'idea-1'})
        with self.assertRaises(megasheet.NotAllowed):
            c._check('formats_deleteIdea', {'campaignId': CAMPS['fr'], 'id': 'idea-1'})
        with self.assertRaises(megasheet.NotAllowed):
            c._check('formats_updatePageSettings', {'campaignId': CAMPS['fr']})

    def test_dach_is_never_a_page_market(self):
        self.assertEqual(pages.MARKETS, ('fr', 'es', 'sl'))
        with self.assertRaises(pages.PageNotFound):
            pages.move_page('x', 'live:de')


class RoundTripTests(unittest.TestCase):
    """An idea as Megasheet has it (also one edited by hand, with resources and two titles) is drawn as a page and
    read back to exactly the same fields - so a check that changes one thing never changes another."""

    IDEA = {'id': 'i1', 'name': 'Mesece brez odgovora… zdaj pa RAZGOVORI? 🤯', 'captionsRequired': True,
            'description': '**🔥 Postaja viralno – posnemi najprej**\n\n**Pomembno:** Svoj video posnemi po spodnjem '
                           'scenariju.\n\nV videu je uporabljena druga aplikacija.\n\n**🔧 Viri**\n\n- [Posnetek Gmaila]'
                           '(https://drive.google.com/file/d/1/view) — ta video odpri čez cel zaslon.',
            'visualHook': 'Začni točno kot v videu za navdih.\n\n🚨 Visual hook je obvezen v vsakem videu!',
            'titles': [{'id': 't1', 'text': 'Mesece brez odgovora… zdaj pa RAZGOVORI? 🤯'},
                       {'id': 't2', 'text': 'Starejši naslov'}],
            'scripts': [{'id': 's1', 'text': 'Že mesece iščem službo.\n\n(📎 Posnetek Gmaila – glej Viri) Pa poglejte '
                                             'danes moj mail.\n\n([Parakeet AI · Resume Maker](https://www.parakeet-ai'
                                             '.com/resume-maker)) To je bil moj CV, **res grozen**.'}],
            'resources': [{'kind': 'link', 'label': 'Original na TikToku', 'url': 'https://www.tiktok.com/@a/video/1'},
                          {'kind': 'link', 'label': 'Parakeet AI · Resume Maker', 'url': LINKS['parakeet']},
                          {'kind': 'link', 'label': 'Posnetek Gmaila', 'url': 'https://drive.google.com/file/d/1/view'}],
            'media': [{'id': 'm1', 'kind': 'video', 'fileUrl': 'https://ufs/f/m1'}]}

    def test_round_trip(self):
        T = TEXT['sl']
        f = pages.fields_of(pages.render(self.IDEA, T), T, LINKS)
        cur = pages.current(self.IDEA)
        self.assertEqual(f['scripts'], cur['scripts'])
        self.assertEqual(f['visualHook'], cur['visualHook'])
        self.assertEqual(f['resources'], cur['resources'])
        self.assertEqual(f['description'], pages.set_hot(cur['description'], T, False))
        self.assertEqual(f['titles'], cur['titles'][:1])  # the old title is kept by the merge (not drawn)

    def test_the_note_check_does_not_see_the_hot_line(self):
        T = TEXT['sl']
        note = next(b for b in pages.render(self.IDEA, T) if b['type'] == 'callout')
        self.assertTrue(pages._plain(note['callout']['rich_text']).startswith('Pomembno:'))


class MigrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(state, 'DIR', tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(pages.reset)
        pages.reset()

    def test_notion_pages_become_their_megasheet_ideas_once(self):
        state.save('megasheet_formats.json', {
            'fr': {'aaaa1111bbbb2222cccc3333dddd4444': {'idea': 'idea-a', 'fp': 'fpa', 'media_ids': ['m1'], 'hand': True}},
            'es': {'eeee1111bbbb2222cccc3333dddd4444': {'idea': 'idea-e', 'fp': 'fpe', 'keep_titles': ['old']}}})
        fmts = [{'id': 'A', 'status': 'active', 'page_id': 'dach-page',
                 'pages': {'fr': 'aaaa1111-bbbb-2222-cccc-3333dddd4444', 'es': 'eeee1111bbbb2222cccc3333dddd4444',
                           'sl': 'ffff0000ffff0000ffff0000ffff0000'}, 'off_markets': ['es'],
                 'pending_pages': {'sl': 'staging-notion'}},
                {'id': 'B', 'status': 'archived', 'pages': {'fr': 'notion-only'}}]
        with redirect_stdout(io.StringIO()):
            out = pages.migrate(fmts)
        self.assertEqual(fmts[0]['pages'], {'fr': 'idea-a', 'es': 'idea-e'})
        self.assertEqual(fmts[0]['page_id'], 'dach-page')  # DACH (stopped) untouched
        self.assertEqual(fmts[0]['notion_pages'], {'sl': 'ffff0000ffff0000ffff0000ffff0000'})
        self.assertEqual(fmts[0]['notion_pending_pages'], {'sl': 'staging-notion'})
        self.assertEqual(fmts[1]['pages'], {})
        self.assertEqual(fmts[1]['notion_pages'], {'fr': 'notion-only'})
        S = state.load('pages.json', {})
        self.assertEqual(S['ideas']['idea-a'], {'market': 'fr', 'place': 'live', 'format': 'A', 'fp': 'fpa',
                                                'media_ids': ['m1'], 'hand': True})
        self.assertEqual(S['ideas']['idea-e']['place'], 'archive')  # off the Spanish list
        self.assertEqual(S['ideas']['idea-e']['keep_titles'], ['old'])
        self.assertEqual(out, {'linked': {'fr': 1, 'es': 1, 'sl': 0}, 'notion_only': {'fr': 1, 'es': 0, 'sl': 1}})
        self.assertEqual(state.load('formats.json', None), fmts)
        self.assertIsNone(pages.migrate(fmts))  # only once


class VerifyTests(Base):
    def test_verify_reads_the_megasheet_lists_and_pages(self):
        from watcher import main, verify
        a = self.build(spec=dict(SPEC, assets_needed=[]))
        pages.set_order('list:fr', [a])
        cfg = json.load(open(os.path.join(pages.ROOT, 'config.json')))
        cfg['markets'] = {'fr': cfg['markets']['fr']}
        fmts = [{'id': 'A', 'status': 'active', 'title': 'A', 'pages': {'fr': a}}]
        with mock.patch.object(localize, 'is_own_url', return_value=False), redirect_stdout(io.StringIO()) as out:
            problems = verify.run(cfg, fmts, main.page_of)
        self.assertEqual(problems, [], out.getvalue())
        self.assertIn('list: 1 live formats', out.getvalue())


if __name__ == '__main__':
    unittest.main()
