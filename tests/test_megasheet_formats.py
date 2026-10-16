"""Formats in Megasheet (16 Oct 2026): every Notion format list is copied into its Megasheet campaign - one idea per
page, same order, hot formats first, formats off the list archived, nothing deleted, unchanged ideas left alone."""
import copy
import tempfile
import unittest
import uuid
from unittest import mock

from watcher import megasheet_formats as MF, notion, state
from watcher.markets import TEXT

LINKS = {'parakeet': 'https://www.parakeet-ai.com/resume-maker', 'linkedin': 'https://www.linkedin.com/jobs/'}
SPEC = {'title_hook': 'Les RH ne veulent PAS que tu saches ça', 'voiceover': True,
        'visual_hook_first': 'Filme-toi en marchant dehors, le titre à l’écran dès la première image.',
        'script': [{'text': 'Je viens de descendre du train.'},
                   {'text': 'Elle a dit que les CV passent par un filtre ATS.', 'new_paragraph': True},
                   {'cue': 'parakeet', 'text': 'Alors je mets mon CV sur Parakeet AI.', 'new_paragraph': True}],
        'assets_needed': [{'name': 'Gmail', 'description': 'capture de la boîte mail'}]}
VIDEO = {'url': 'https://www.tiktok.com/@origomez953/video/7696706553432345874'}


def page(spec=SPEC, video=VIDEO, lang='fr', video_block='vb1', file_url='https://s3/video.mp4'):
    """A Notion page as the API returns it, built with the watcher's own page layout."""
    blocks = notion.page_blocks(spec, video, 'upload', LINKS, lang=lang, lab_url='https://notion/lab')
    out = []
    for b in blocks:
        b = copy.deepcopy(b)
        b['id'] = str(uuid.uuid4())
        if b['type'] == 'video':
            b['id'] = video_block
            b['video'] = {'type': 'file', 'file': {'url': file_url}}
        body = b[b['type']]
        for x in body.get('rich_text', []):
            x['plain_text'] = x['text']['content']
            x['href'] = (x['text'].get('link') or {}).get('url')
        out.append(b)
    return out


def fr_fields(blocks, hot=False):
    return MF.idea_fields(MF.read_page('p', TEXT['fr'], blocks), TEXT['fr'], hot, LINKS)


class ReadPageTests(unittest.TestCase):
    def test_page_becomes_an_idea(self):
        f = fr_fields(page())
        self.assertEqual(f['name'], SPEC['title_hook'])
        self.assertEqual(f['titles'], [SPEC['title_hook']])
        self.assertEqual(f['scripts'], ['Je viens de descendre du train.\n\n'
                                        'Elle a dit que les CV passent par un filtre ATS.\n\n'
                                        '([Parakeet AI · Resume Maker](https://www.parakeet-ai.com/resume-maker)) '
                                        'Alors je mets mon CV sur Parakeet AI.'])
        self.assertEqual(f['visualHook'], SPEC['visual_hook_first'] + '\n\n'
                         '🚨 Un visual hook est obligatoire sur chaque vidéo !')  # lab link -> the guide on the page
        self.assertEqual(f['resources'][0], {'kind': 'link', 'label': 'Original sur TikTok', 'url': VIDEO['url']})
        self.assertEqual(f['resources'][1]['url'], LINKS['parakeet'])
        self.assertEqual(len(f['resources']), 2)
        self.assertTrue(f['description'].startswith('**Important :**'))
        self.assertIn('\n\nDans la vidéo, c’est une autre app', f['description'])  # two note lines = two paragraphs
        self.assertIn('**🔧 Ressources**', f['description'])
        self.assertIn('- 📎 Gmail – à préparer: capture de la boîte mail', f['description'])
        self.assertTrue(f['captionsRequired'])
        self.assertEqual(f['status'], 'published')

    def test_hot_format_gets_the_label_first(self):
        f = fr_fields(page(), hot=True)
        self.assertTrue(f['description'].startswith('**🔥 En train de devenir viral – à tourner en premier**\n\n'))

    def test_silent_video_needs_no_captions(self):
        f = fr_fields(page(dict(SPEC, voiceover=False)))
        self.assertFalse(f['captionsRequired'])
        self.assertIn('🎵 ' + TEXT['fr']['sub_silent'], f['description'])
        self.assertTrue(f['scripts'][0].startswith('**' + TEXT['fr']['silent_label'] + '**'))

    def test_numbered_page_title_is_not_used(self):
        blocks = page(dict(SPEC, title_hook='3. Mens sur ton CV'))
        self.assertEqual(fr_fields(blocks)['name'], 'Mens sur ton CV')

    def test_every_market_layout_is_read(self):
        for lang in ('de', 'es', 'sl', 'fr'):
            p = MF.read_page('p', TEXT[lang], page(lang=lang))
            self.assertEqual(p['title'], SPEC['title_hook'], lang)
            self.assertEqual(len(p['script']), 3, lang)
            self.assertEqual(p['video']['block'], 'vb1', lang)
            self.assertEqual(p['source'], VIDEO['url'], lang)
            self.assertTrue(p['note'], lang)


class FakeMegasheet:
    def __init__(self, ideas=()):
        self.ideas = [copy.deepcopy(i) for i in ideas]
        self.calls = []

    def _find(self, iid):
        return next(i for i in self.ideas if i['id'] == iid)

    def call(self, tool, campaignId=None, **a):
        self.calls.append((tool, a))
        if tool == 'formats_getIdeas':
            return copy.deepcopy(self.ideas)
        if tool == 'formats_createIdea':
            idea = self._idea(a)
            self.ideas.append(idea)
            return copy.deepcopy(idea)
        if tool == 'formats_updateIdea':
            i = self._find(a['id'])
            i.update({k: v for k, v in self._idea(a).items() if k not in ('id', 'media', 'tag')})
            return copy.deepcopy(i)
        if tool == 'formats_updateIdeaStatus':
            self._find(a['id'])['status'] = a['status']
            return {}
        if tool == 'formats_reorderIdeas':
            self.ideas.sort(key=lambda i: a['ids'].index(i['id']))
            return {}
        if tool == 'formats_addMediaFromUrl':
            mid = str(uuid.uuid4())
            self._find(a['ideaId'])['media'].append({'id': mid, 'fileSizeBytes': 1})
            return {'id': mid}
        if tool == 'formats_removeMedia':
            for i in self.ideas:
                i['media'] = [m for m in i['media'] if m['id'] != a['id']]
            return {}
        raise AssertionError(tool)

    @staticmethod
    def _idea(a):
        return {'id': a.get('id') or str(uuid.uuid4()), 'tag': a.get('tag', 'x'), 'name': a['name'],
                'groupId': a.get('groupId'), 'status': a['status'], 'captionsRequired': a['captionsRequired'],
                'description': a['description'], 'visualHook': a['visualHook'], 'media': [],
                'titles': [{'id': t.get('id') or str(uuid.uuid4()), 'text': t['text']} for t in a['titles']],
                'scripts': [{'id': s.get('id') or str(uuid.uuid4()), 'text': s['text']} for s in a['scripts']],
                'resources': [{'id': r.get('id') or str(uuid.uuid4()), **r} for r in a['resources']]}

    def writes(self):
        return [c for c in self.calls if c[0] != 'formats_getIdeas']


def imported(name, status='published', media_size=None):
    return {'id': str(uuid.uuid4()), 'tag': MF.slug(name, set()), 'name': name, 'groupId': None, 'status': status,
            'captionsRequired': True, 'description': 'old', 'visualHook': 'old', 'titles': [{'id': 't', 'text': name}],
            'scripts': [{'id': 's', 'text': 'old'}], 'resources': [],
            'media': [{'id': 'm-' + name[:3], 'fileSizeBytes': media_size}] if media_size else []}


class SyncTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(state, 'DIR', tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.pages = {'a' * 32: page(dict(SPEC, title_hook='Format A'), video_block='va'),
                      'b' * 32: page(dict(SPEC, title_hook='Format B'), video_block='vb'),
                      'c' * 32: page(dict(SPEC, title_hook='Format C'), video_block='vc')}
        self.list = ['a' * 32, 'b' * 32]
        self.hot = 1
        for target, fn in ((MF.notion, 'children'), (MF.notion, '_layout'), (MF, '_size')):
            p = mock.patch.object(target, fn, getattr(self, 'fake_' + fn.lstrip('_')))
            p.start()
            self.addCleanup(p.stop)
        self.mk = {'key': 'fr', 'list_page': 'list', 'T': TEXT['fr']}

    def fake_children(self, pid):
        return self.pages[pid]

    def fake_layout(self, list_page):
        entries = [(f'blk{n}', pid) for n, pid in enumerate(self.list)]
        return {'top': entries[:self.hot], 'rest': entries[self.hot:], 'hot': self.hot}

    def fake_size(self, url):
        return 777

    def run_sync(self, ms, S):
        return MF.sync_market(ms, self.mk, 'camp', S, links=LINKS)

    def test_first_copy_takes_over_the_import_and_archives_the_rest(self):
        ms = FakeMegasheet([imported('Old idea X'), imported('Format B', media_size=777),
                            imported('Archived Y', status='archived')])
        S = {}
        self.run_sync(ms, S)
        names = [(i['name'], i['status']) for i in ms.ideas]
        self.assertEqual(names, [('Format A', 'published'), ('Format B', 'published'), ('Old idea X', 'archived'),
                                 ('Archived Y', 'archived')])
        b = ms.ideas[1]
        self.assertEqual(b['id'], S['fr']['b' * 32]['idea'])  # taken over, not a second idea
        self.assertEqual(b['tag'], MF.slug('Format B', set()))
        self.assertEqual([m['id'] for m in b['media']], ['m-For'])  # same example video (same size): not uploaded again
        self.assertEqual(len(ms.ideas[0]['media']), 1)  # new idea: example video uploaded
        self.assertTrue(ms.ideas[0]['description'].startswith('**🔥'))  # hot
        self.assertFalse(ms.ideas[1]['description'].startswith('**🔥'))
        self.assertNotIn('formats_deleteIdea', [c[0] for c in ms.calls])
        self.assertEqual(S['_adopted'], ['fr'])

    def test_second_run_without_changes_writes_nothing(self):
        ms, S = FakeMegasheet(), {}
        self.run_sync(ms, S)
        ms.calls.clear()
        self.run_sync(ms, S)
        self.assertEqual(ms.writes(), [])

    def test_list_changes_follow(self):
        ms, S = FakeMegasheet(), {}
        self.run_sync(ms, S)
        ids = {pid: S['fr'][pid]['idea'] for pid in self.list}
        self.list, self.hot = ['c' * 32, 'a' * 32], 0  # B leaves the list, C comes in on top, nothing hot any more
        self.run_sync(ms, S)
        state_of = {i['name']: i['status'] for i in ms.ideas}
        self.assertEqual(state_of, {'Format A': 'published', 'Format B': 'archived', 'Format C': 'published'})
        self.assertEqual([i['name'] for i in ms.ideas][:2], ['Format C', 'Format A'])
        self.assertFalse(ms._find(ids['a' * 32])['description'].startswith('**🔥'))
        self.list = ['b' * 32, 'c' * 32, 'a' * 32]  # B comes back: same idea, published again
        self.run_sync(ms, S)
        self.assertEqual(S['fr']['b' * 32]['idea'], ids['b' * 32])
        self.assertEqual(ms._find(ids['b' * 32])['status'], 'published')
        self.assertEqual(len(ms.ideas), 3)

    def test_changed_script_and_new_example_video(self):
        ms, S = FakeMegasheet(), {}
        self.run_sync(ms, S)
        old_media = ms._find(S['fr']['a' * 32]['idea'])['media'][0]['id']
        ms.calls.clear()
        spec = dict(SPEC, title_hook='Format A', script=SPEC['script'] + [{'text': 'Nouvelle phrase.'}])
        self.pages['a' * 32] = page(spec, video_block='va2')
        self.run_sync(ms, S)
        a = ms._find(S['fr']['a' * 32]['idea'])
        self.assertTrue(a['scripts'][0].endswith('Nouvelle phrase.') if isinstance(a['scripts'][0], str)
                        else a['scripts'][0]['text'].endswith('Nouvelle phrase.'))
        self.assertEqual(len(a['media']), 1)
        self.assertNotEqual(a['media'][0]['id'], old_media)  # old example removed, new one added
        self.assertEqual(sorted(c[0] for c in ms.writes()),
                         ['formats_addMediaFromUrl', 'formats_removeMedia', 'formats_updateIdea'])

    def test_hand_made_ideas_stay_after_ours(self):
        ms, S = FakeMegasheet(), {'_adopted': ['fr']}  # not the first copy any more
        ms.ideas.append(imported('Made by hand'))
        self.run_sync(ms, S)
        self.assertEqual([(i['name'], i['status']) for i in ms.ideas],
                         [('Format A', 'published'), ('Format B', 'published'), ('Made by hand', 'published')])

    def test_title_used_by_videos_is_kept(self):
        ms, S = FakeMegasheet(), {}
        self.run_sync(ms, S)
        real = ms.call

        def call(tool, campaignId=None, **a):
            if tool == 'formats_updateIdea' and 'Format A' not in [t['text'] for t in a['titles']]:
                raise RuntimeError('megasheet formats_updateIdea: Titles already assigned to videos cannot be removed')
            return real(tool, campaignId, **a)
        ms.call = call
        self.pages['a' * 32] = page(dict(SPEC, title_hook='Format A2'), video_block='va')
        self.run_sync(ms, S)
        a = ms._find(S['fr']['a' * 32]['idea'])
        self.assertEqual([t['text'] for t in a['titles']], ['Format A2', 'Format A'])
        ms.calls.clear()
        self.run_sync(ms, S)
        self.assertEqual(ms.writes(), [])  # the kept old title does not cause an update every run

    def test_dry_run_writes_nothing(self):
        ms = FakeMegasheet([imported('Old idea X')])
        log = MF.sync_market(ms, self.mk, 'camp', {}, dry=True, links=LINKS)
        self.assertEqual(ms.writes(), [])
        self.assertTrue(any(x.startswith('new: Format A') for x in log))
        self.assertTrue(any('Old idea X' in x for x in log))


if __name__ == '__main__':
    unittest.main()
