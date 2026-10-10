import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from watcher import align, audit, gate, localize, main, notion, reword, state
from watcher.markets import TEXT


URL = 'https://www.tiktok.com/@example/video/123'
OTHER_URL = 'https://www.tiktok.com/@example/video/456'
LINKS = {'parakeet': 'https://parakeet-ai.com/resume-maker', 'linkedin': 'https://linkedin.com/jobs'}
CFG = {'models': {'build': 'test', 'classify': 'test'}, 'links': LINKS, 'notion': {'radar_page': 'staging'}}
MK = {'key': 'de', 'lang': 'de', 'holder_page': 'holder', 'T': {'flag': 'DE'}}
SPEC = {'example': URL, 'voiceover': True, 'script': [
    {'text': 'Das ist der genehmigte Text.', 'cue': 'parakeet', 'new_paragraph': False, 'asset_name': ''}]}


def live(blocks):
    blocks = copy.deepcopy(blocks)
    for i, b in enumerate(blocks):
        b['id'] = f'block-{i}'
        b['last_edited_time'] = '2026-10-07T00:00:00Z'
        for x in b[b['type']].get('rich_text', []):
            x['plain_text'] = x['text']['content']
    return blocks


def page():
    return live([
        notion.block('heading_2', [notion.rt('💬 SKRIPT')]),
        *notion.script_paragraphs(SPEC, LINKS, 'de'),
        notion.block('divider'),
        notion.block('heading_2', [notion.rt('🎬 Directions')]),
        notion.para([notion.rt('Zeige die App.')]),
        notion.block('callout', [notion.rt(TEXT['de']['inspo_note_same'])], icon={'type': 'emoji', 'emoji': '⚠️'}),
    ])


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(state, 'DIR', tmp))
        approved_path = Path(tmp) / 'approvals.json'
        approved_path.write_text(json.dumps({'de': {'LOCKED': SPEC}}))
        self.stack.enter_context(patch.object(align, 'APPROVED', str(approved_path)))
        self.stack.enter_context(patch('requests.request', side_effect=AssertionError('No network in tests')))
        self.stack.enter_context(patch('requests.post', side_effect=AssertionError('No network in tests')))
        def read_parent(method, path, *args, **kwargs):
            if method == 'GET' and path.startswith('/pages/'):
                return {'parent': {'type': 'page_id', 'page_id': 'staging'}}
            raise AssertionError('Unexpected Notion write')
        self.api = self.stack.enter_context(patch.object(notion, 'api', side_effect=read_parent))
        self.stack.enter_context(patch.object(notion, 'children', return_value=page()))
        self.llm = self.stack.enter_context(patch.object(audit.llm, 'chat_json', side_effect=AssertionError('Unexpected LLM call')))
        self.push = self.stack.enter_context(patch.object(gate.notify, 'push'))
        self.fmt = {'id': 'LOCKED', 'title': 'Example', 'status': 'active', 'page_id': 'page'}
        self.stack.enter_context(patch.dict(main.CTX, {'meta': {}, 'accounts': {}}, clear=True))

    def patch(self, obj, name, **kwargs):
        return self.stack.enter_context(patch.object(obj, name, **kwargs))

    def readable_example(self, blocks=None, url=URL):
        self.patch(localize, 'current_source', return_value={'url': url})
        self.patch(localize, 'example_text', return_value='ON-SCREEN: Tool\nSPEECH: ' + 'Original Satz. ' * 30)
        self.patch(audit.tiktok, 'video_detail', return_value={'views': 20000})
        self.patch(notion, 'children', return_value=blocks or page())
        verdict = {k: True for k in ('example_same_format', 'script_follows_example', 'script_faithful',
                                    'script_ok', 'directions_ok', 'title_ok')}
        verdict.update(example_language='German', script_issues=[], direction_issues=[], example_issue='')
        self.llm.side_effect = None
        self.llm.return_value = verdict

    def test_unreadable_example_never_passes_or_writes(self):
        self.patch(localize, 'current_source', return_value={'url': URL})
        self.patch(localize, 'example_text', return_value='')
        self.patch(audit.tiktok, 'video_detail', return_value={'views': 20000})
        status, _ = audit.fix_page(self.fmt, MK, CFG, {}, {}, {}, main.page_of)
        self.assertEqual(status, 'unverified')
        self.api.assert_not_called()
        self.llm.assert_not_called()

    def test_unknown_views_never_pass(self):
        self.readable_example()
        self.patch(audit.tiktok, 'video_detail', return_value=None)
        passed, verdict, _ = audit.check(self.fmt, 'page', 'de', 'test', LINKS)
        self.assertFalse(passed)
        self.assertTrue(verdict['unverified'])

    def test_approved_live_content_passes_without_rewrite(self):
        self.readable_example()
        passed, verdict, _ = audit.check(self.fmt, 'page', 'de', 'test', LINKS)
        self.assertTrue(passed)
        self.assertTrue(verdict['approved_matches'])
        self.assertEqual(align.align_page(self.fmt, 'page', 'de', CFG, LINKS)[0], 'ok')
        self.api.assert_not_called()

    def test_same_example_does_not_approve_drifted_text_or_cues(self):
        for field in ('text', 'link'):
            with self.subTest(field=field):
                blocks = page()
                rich = blocks[1]['paragraph']['rich_text']
                if field == 'text':
                    rich[-1]['text']['content'] = rich[-1]['plain_text'] = 'Changed text.'
                else:
                    rich[1]['text']['link']['url'] = 'https://wrong.example'
                with patch.object(notion, 'children', return_value=blocks):
                    self.assertFalse(align.matches_approved('page', 'de', LINKS, SPEC))
        self.readable_example(blocks)
        passed, verdict, _ = audit.check(self.fmt, 'page', 'de', 'test', LINKS)
        self.assertFalse(passed)
        self.assertFalse(verdict['approved_matches'])

    def test_approval_survives_different_example_without_writing(self):
        self.readable_example(url=OTHER_URL)
        self.assertEqual(align.align_page(self.fmt, 'page', 'de', CFG, LINKS)[0], 'skipped')
        status, notes = audit.fix_page(self.fmt, MK, CFG, {}, {}, {}, main.page_of)
        self.assertEqual(status, 'failed')
        self.assertIn('manual review', notes[-1])
        self.assertFalse(audit._put_example(self.fmt, 'de', 'page', 'de', OTHER_URL, True))
        self.api.assert_not_called()

    def test_reword_and_write_cannot_overwrite_approved_script(self):
        self.assertEqual(reword.reword_page(self.fmt, 'page', 'de', 'test')[0], 'skipped')
        changed = copy.deepcopy(SPEC)
        changed['script'][0]['text'] = 'Changed'
        self.assertEqual(align._write(self.fmt, 'page', 'de', CFG, LINKS, changed, '')[0], 'skipped')
        self.api.assert_not_called()
        self.llm.assert_not_called()

    def test_full_rebuild_refuses_approved_page_before_prepare(self):
        self.patch(main, 'load_formats', return_value=[self.fmt])
        prep = self.patch(main, '_prepare')
        result = main.make_page({}, MK, CFG, None, replace_page='page')
        self.assertIsNone(result[0])
        self.assertIn('locked', result[2][0])
        prep.assert_not_called()

    def test_standardize_and_revive_preserve_approved_script(self):
        self.patch(main, 'load_formats', return_value=[self.fmt])
        self.patch(main, 'load_config', return_value=CFG)
        self.patch(main.M, 'load', return_value=[MK])
        self.patch(notion, 'children', return_value=page())  # missing resources -> rebuild path
        self.patch(audit, 'originals', return_value={'LOCKED': URL})
        self.patch(main.tiktok, 'video_detail', return_value={'url': URL})
        prepare = self.patch(main, '_prepare')
        report = main.standardize()
        self.assertEqual(report[0][2], 'not rebuilt')
        self.patch(main, '_gate', return_value=(False, None, ['held']))
        self.patch(main, 'set_format')
        main.revive_format(self.fmt, {'id': '123', 'url': OTHER_URL, 'views': 50000}, [MK], [self.fmt], {}, CFG)
        prepare.assert_not_called()
        self.api.assert_not_called()

    def test_localize_does_not_change_approved_example(self):
        self.patch(localize, 'current_source', return_value={'url': OTHER_URL})
        replace = self.patch(localize, 'replace_video')
        result = localize.run([self.fmt], [MK], {}, {}, {}, CFG, main.page_of)
        self.assertEqual(result[0][2], 'error')
        self.fmt['inspo'] = {'de': {'url': OTHER_URL, 'views': 20000}}
        localize.recheck([self.fmt], [MK], {}, {}, {}, CFG, main.page_of)
        replace.assert_not_called()
        self.llm.assert_not_called()

    def test_only_failed_requires_matching_fingerprint_and_existing_page(self):
        meta = {'audit': {'LOCKED:de': 'ok'}, 'audit_fingerprints': {'LOCKED:de': 'before'}}
        self.patch(audit, 'fingerprint', return_value='after')
        fix = self.patch(audit, 'fix_page', return_value=('ok', []))
        self.assertEqual(len(audit.run([self.fmt], [MK], CFG, {}, {}, meta, main.page_of, only_failed=True)), 1)
        fix.assert_called_once()
        self.assertEqual(meta['audit_fingerprints']['LOCKED:de'], 'after')
        self.assertEqual(audit.run([self.fmt], [MK], CFG, {}, {}, meta, main.page_of, only_failed=True), [])
        self.fmt['page_id'] = None
        result = audit.run([self.fmt], [MK], CFG, {}, {}, meta, main.page_of, only_failed=True)
        self.assertEqual(result[0][2], 'no page')
        self.assertNotIn('LOCKED:de', meta['audit_fingerprints'])

    def test_legacy_cached_ok_without_fingerprint_is_audited(self):
        meta = {'audit': {'LOCKED:de': 'ok'}}
        self.patch(audit, 'fingerprint', return_value='now')
        fix = self.patch(audit, 'fix_page', return_value=('unverified', ['unreadable']))
        audit.run([self.fmt], [MK], CFG, {}, {}, meta, main.page_of, only_failed=True)
        fix.assert_called_once()
        self.assertEqual(meta['audit']['LOCKED:de'], 'unverified')
        self.assertEqual(state.load('meta.json', {})['audit']['LOCKED:de'], 'unverified')

    def test_duplicate_titles_keep_independent_audit_status(self):
        other = {**self.fmt, 'id': 'SECOND', 'page_id': 'page2'}
        self.patch(audit, 'fingerprint', return_value='now')
        self.patch(audit, 'fix_page', side_effect=lambda f, *a, **k: ('ok' if f['id'] == 'LOCKED' else 'failed', []))
        meta = {}
        audit.run([self.fmt, other], [MK], CFG, {}, {}, meta, main.page_of)
        self.assertEqual(meta['audit'], {'LOCKED:de': 'ok', 'SECOND:de': 'failed'})

    def test_fingerprint_changes_for_text_but_not_expiring_video_url(self):
        blocks = page() + live([notion.block('video', type='file', file={'url': 'https://signed.example/asset?token=1'})])
        self.patch(notion, 'children', side_effect=lambda _: blocks)
        initial = audit.fingerprint('page')
        blocks[-1]['video']['file']['url'] = 'https://signed.example/asset?token=2'
        self.assertEqual(initial, audit.fingerprint('page'))
        blocks[1]['paragraph']['rich_text'][-1]['plain_text'] = 'Changed'
        self.assertNotEqual(initial, audit.fingerprint('page'))

    def test_image_and_file_expiry_do_not_invalidate_cache_but_identity_changes_do(self):
        for kind in ('image', 'file', 'audio', 'pdf'):
            with self.subTest(kind=kind):
                blocks = live([notion.block(kind, type='file', file={'url': 'https://signed.example/asset?token=1',
                                                                    'expiry_time': 'today'})])
                with patch.object(notion, 'children', return_value=blocks):
                    before = audit.fingerprint('page')
                    blocks[0][kind]['file'].update(url='https://another-signer.example/asset?token=2', expiry_time='tomorrow')
                    self.assertEqual(before, audit.fingerprint('page'))
                    blocks[0][kind]['file']['url'] = 'https://signed.example/another-asset?token=2'
                    self.assertNotEqual(before, audit.fingerprint('page'))

    def test_failed_missing_page_is_staged_and_reused_until_passes(self):
        fmt = {'id': 'NEW', 'title': 'New', 'status': 'active'}
        build = self.patch(main, 'make_page', return_value=('staged-page', {}, []))
        fix = self.patch(audit, 'fix_page', return_value=('unverified', []))
        move = self.patch(notion, 'move_page')
        rerank = self.patch(main, 'rerank')
        self.assertEqual(main.ensure_market_pages(fmt, {}, [MK], [fmt], {}, CFG, None), [])
        self.assertIsNone(main.page_of(fmt, 'de'))
        self.assertEqual(fmt['pending_pages']['de'], 'staged-page')
        self.assertEqual(build.call_args.kwargs['parent'], 'staging')
        move.assert_not_called()
        rerank.assert_not_called()
        fix.return_value = ('ok', [])
        self.assertEqual(main.ensure_market_pages(fmt, {}, [MK], [fmt], {}, CFG, None), ['DE'])
        build.assert_called_once()
        move.assert_called_once_with('staged-page', 'holder')
        self.assertEqual(main.page_of(fmt, 'de'), 'staged-page')

    def test_missing_page_audit_exception_does_not_expose_page(self):
        fmt = {'id': 'NEW', 'title': 'New', 'status': 'active'}
        self.patch(main, 'make_page', return_value=('staged-page', {}, []))
        self.patch(audit, 'fix_page', side_effect=RuntimeError('service unavailable'))
        with self.assertRaises(RuntimeError):
            main.ensure_market_pages(fmt, {}, [MK], [fmt], {}, CFG, None)
        self.assertIsNone(main.page_of(fmt, 'de'))
        self.assertEqual(fmt['pending_pages']['de'], 'staged-page')

    def test_missing_page_move_failure_does_not_expose_page(self):
        fmt = {'id': 'NEW', 'title': 'New', 'status': 'active'}
        self.patch(main, 'make_page', return_value=('staged-page', {}, []))
        self.patch(audit, 'fix_page', return_value=('ok', []))
        self.patch(notion, 'move_page', side_effect=RuntimeError('move unavailable'))
        with self.assertRaises(RuntimeError):
            main.ensure_market_pages(fmt, {}, [MK], [fmt], {}, CFG, None)
        self.assertIsNone(main.page_of(fmt, 'de'))

    def test_fill_market_uses_staging_gate(self):
        fmt = {'id': 'NEW', 'title': 'New', 'status': 'active', 'source_video': URL}
        self.patch(main, 'load_config', return_value={**CFG, 'markets': {'de': {}}})
        self.patch(main.M, 'load', return_value=[MK])
        self.patch(main, 'load_formats', return_value=[fmt])
        self.patch(main, 'source_video', return_value=URL)
        self.patch(main.tiktok, 'video_detail', return_value={'url': URL})
        ensure = self.patch(main, 'ensure_market_pages', return_value=[])
        self.patch(main, 'rerank')
        main.fill_market('de')
        ensure.assert_called_once()
        self.assertIsNone(main.page_of(fmt, 'de'))

    def test_publish_does_not_mark_active_if_one_move_fails(self):
        fmt = {**self.fmt, 'status': 'pending', 'pages': {'fr': 'page-fr'}}
        mkts = [MK, {**MK, 'key': 'fr', 'holder_page': 'fr-holder'}]
        parents = {'page': 'staging', 'page-fr': 'archive'}
        self.api.side_effect = lambda method, path: {'parent': {'type': 'page_id', 'page_id': parents[path.split('/')[-1]]}}
        def move(pid, parent):
            if pid == 'page-fr' and parent == 'fr-holder':
                raise RuntimeError('Notion unavailable')
            parents[pid] = parent
        self.patch(notion, 'move_page', side_effect=move)
        with self.assertRaises(RuntimeError):
            gate.publish(fmt, mkts, main.page_of)
        self.assertEqual(fmt['status'], 'pending')
        self.assertNotIn('listed_at', fmt)
        self.assertEqual(parents, {'page': 'staging', 'page-fr': 'archive'})
        self.assertEqual(state.load('publication_journal.json', {}), {})

    def test_publish_rejects_missing_language_before_moving(self):
        move = self.patch(notion, 'move_page')
        with self.assertRaises(RuntimeError):
            gate.publish(self.fmt, [MK, {**MK, 'key': 'fr'}], main.page_of)
        move.assert_not_called()

    def test_unknown_audit_prevents_gate_publication(self):
        self.patch(audit, 'fix_page', return_value=('unverified', ['unreadable']))
        meta = {}
        passed, reasons = gate.check(self.fmt, [MK], CFG, {}, {}, meta, main.page_of, main.set_page, Mock(), Mock())
        self.assertFalse(passed)
        self.assertTrue(reasons)
        self.assertTrue(gate.has_unknown(self.fmt, [MK], meta))

    def test_one_pending_exception_does_not_block_next_format(self):
        first = {**self.fmt, 'status': 'pending'}
        second = {**self.fmt, 'id': 'SECOND', 'status': 'pending', 'page_id': 'second-page'}
        self.patch(gate, 'check', side_effect=[RuntimeError('quota exhausted'), (True, [])])
        self.patch(notion, 'move_page')
        rerank = Mock(return_value=['SECOND'])
        gate.retry_pending([first, second], [MK], CFG, {}, {}, {}, main.page_of, main.set_page, Mock(), Mock(), rerank)
        self.assertEqual(first['status'], 'pending')
        self.assertEqual(first['pending']['tries'], 0)
        self.assertEqual(second['status'], 'active')
        self.push.assert_called_once()
        self.assertEqual(state.load('formats.json', [])[1]['status'], 'active')

    def test_unknown_does_not_exhaust_quality_attempts(self):
        fmt = {**self.fmt, 'status': 'pending', 'pending': {'tries': 3, 'kind': 'new'}}
        self.patch(gate, 'check', return_value=(False, ['unreadable']))
        meta = {'audit': {'LOCKED:de': 'unverified'}}
        gate.retry_pending([fmt], [MK], CFG, {}, {}, meta, main.page_of, main.set_page, Mock(), Mock(), Mock())
        self.assertEqual(fmt['status'], 'pending')
        self.assertEqual(fmt['pending']['tries'], 3)
        self.push.assert_not_called()

    def embedded_example(self):
        blocks = page()
        blocks[-1]['callout']['rich_text'] = [{'type': 'text', 'text': {'content': TEXT['es']['inspo_note_same']},
                                              'plain_text': TEXT['es']['inspo_note_same']}]
        video = live([notion.block('video', type='file', file={'url': 'https://signed.example/upload'})])[0]
        video['id'] = 'verified-video'
        blocks.insert(0, video)
        record = {'format_id': 'LEGACY', 'market': 'es', 'page_id': 'page', 'video_block_id': video['id'],
                  'video_last_edited_time': video['last_edited_time'], 'source_language': 'Spanish',
                  'speech': 'Original frase. ' * 30, 'views_policy': 'legacy_original_unavailable'}
        path = Path(state.DIR) / 'embedded.json'
        path.write_text(json.dumps({'examples': [record]}))
        self.patch(localize, 'EMBEDDED_EVIDENCE', new=str(path))
        self.patch(notion, 'children', return_value=blocks)
        self.patch(localize, 'current_source', return_value={'video': video['id'], 'url': None})
        self.llm.side_effect = None
        self.llm.return_value = {k: True for k in ('example_same_format', 'script_follows_example', 'script_faithful',
                                                  'script_ok', 'directions_ok', 'title_ok')}
        self.llm.return_value.update(example_language='Spanish', script_issues=[], direction_issues=[], example_issue='')
        return blocks, record

    def test_pinned_legacy_upload_is_checked_with_explicit_unknown_views_exemption(self):
        self.embedded_example()
        passed, verdict, url = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
        self.assertTrue(passed)
        self.assertIsNone(url)
        self.assertIsNone(verdict['views'])
        self.assertEqual(verdict['views_policy'], 'legacy_original_unavailable')
        self.assertTrue(verdict['embedded_verified'])
        self.assertIn('verified uploaded legacy video', self.llm.call_args.args[2])
        self.assertNotIn('no video on the page', self.llm.call_args.args[2])

    def test_changed_legacy_video_pin_requires_new_evidence(self):
        blocks, _ = self.embedded_example()
        for key, value in (('id', 'replacement'), ('last_edited_time', '2026-10-08T00:00:00Z')):
            with self.subTest(key=key):
                changed = copy.deepcopy(blocks)
                changed[0][key] = value
                with patch.object(notion, 'children', return_value=changed):
                    passed, verdict, _ = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
                    self.assertFalse(passed)
                    self.assertTrue(verdict['unverified'])
                    self.assertIn('uploaded example exists', verdict['example_issue'])
        self.llm.assert_not_called()

    def public_pinned_example(self):
        blocks, record = self.embedded_example()
        record.update(source_url=URL, views_policy='verified_public_count', observed_views=2600000)
        record.pop('speech')
        record['transcript_corrections'] = [{'from': 'Jobs t punto i o', 'to': 'JobStep.io'}]
        Path(localize.EMBEDDED_EVIDENCE).write_text(json.dumps({'examples': [record]}))
        rich = blocks[2]['paragraph']['rich_text'][-1]
        rich['text']['content'] = rich['plain_text'] = 'Parakeet AI.'
        source = self.patch(localize, 'current_source', return_value={'video': 'verified-video', 'url': URL})
        detail = self.patch(audit.tiktok, 'video_detail', return_value={'views': 2600000,
                           'subtitles': 'Original frase. ' * 30 + 'Jobs t punto i o'})
        return blocks, record, source, detail

    def test_exact_public_source_uses_reviewed_transcript_and_live_views(self):
        _, record, _, _ = self.public_pinned_example()
        text = localize.example_text(URL, page_id='page')
        self.assertIn('JobStep.io', text)
        self.assertEqual(len(align.JOBSTEP.findall(text)), 1)
        passed, verdict, _ = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
        self.assertTrue(passed)
        self.assertEqual(verdict['views'], 2600000)
        self.assertEqual(verdict['views_policy'], 'verified_count')
        self.assertTrue(verdict['brand_count_ok'])

    def test_wrong_or_missing_public_source_cannot_reuse_pinned_transcript(self):
        _, _, source, _ = self.public_pinned_example()
        for url in (OTHER_URL, None):
            with self.subTest(url=url):
                source.return_value = {'video': 'verified-video', 'url': url}
                self.assertEqual(localize.example_text(url, page_id='page'), '')
                passed, verdict, _ = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
                self.assertFalse(passed)
                self.assertTrue(verdict['unverified'])

    def test_public_source_historical_views_do_not_replace_unavailable_live_views(self):
        _, _, _, detail = self.public_pinned_example()
        detail.return_value = None
        passed, verdict, _ = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
        self.assertFalse(passed)
        self.assertTrue(verdict['unverified'])

    def test_missing_or_changed_public_asr_is_not_reconstructed_from_evidence(self):
        _, _, _, detail = self.public_pinned_example()
        for speech in ('', 'Original changed brand recognition', 'Jobs t punto i o Jobs t punto i o'):
            with self.subTest(speech=speech):
                detail.return_value = {'views': 2600000, 'subtitles': speech}
                self.assertEqual(localize.example_text(URL, page_id='page'), '')
                passed, verdict, _ = audit.check({**self.fmt, 'id': 'LEGACY'}, 'page', 'es', 'test', LINKS)
                self.assertFalse(passed)
                self.assertTrue(verdict['unverified'])

    def test_localize_preserves_pinned_legacy_video(self):
        self.embedded_example()
        replace = self.patch(localize, 'replace_video')
        result = localize.run([{**self.fmt, 'id': 'LEGACY'}], [MK], {}, {}, {}, CFG, main.page_of)
        self.assertEqual(result[0][2], 'kept')
        replace.assert_not_called()
        self.llm.assert_not_called()

    def test_page_changed_during_llm_check_cannot_pass(self):
        blocks = page()
        self.readable_example(blocks)
        verdict = copy.deepcopy(self.llm.return_value)
        def during_check(*args, **kwargs):
            blocks[1]['paragraph']['rich_text'][-1]['text']['content'] = 'Changed after review started.'
            return verdict
        self.llm.side_effect = during_check
        passed, result, _ = audit.check({**self.fmt, 'id': 'UNLOCKED'}, 'page', 'de', 'test', LINKS)
        self.assertFalse(passed)
        self.assertTrue(result['unverified'])
        self.assertIn('changed during', result['example_issue'])

    def test_alignment_enforces_110_percent_and_real_source_brand_count(self):
        source = 'Wort ' * 100
        spec = {'jobstep_mentions_in_original': 0, 'script': [{'text': 'Wort ' * 110, 'cue': 'parakeet'}]}
        self.assertEqual(align._validate(spec, 100, source), '')
        spec['script'][0]['text'] += 'Wort'
        self.assertIn('111 words', align._validate(spec, 100, source))
        spec['script'][0]['text'] = 'Parakeet AI ' + 'Wort ' * 98
        spec['jobstep_mentions_in_original'] = 1  # an LLM cannot invent its own target count
        self.assertIn('original names JobStep 0 times', align._validate(spec, 100, source))

    def test_audit_excludes_linked_cues_but_rejects_extra_spoken_brand(self):
        blocks = page()
        self.readable_example(blocks)
        passed, verdict, _ = audit.check({**self.fmt, 'id': 'UNLOCKED'}, 'page', 'de', 'test', LINKS)
        self.assertTrue(passed)
        self.assertTrue(verdict['brand_count_ok'])
        rt = blocks[1]['paragraph']['rich_text'][-1]
        rt['text']['content'] = rt['plain_text'] = 'Parakeet AI ist hier.'
        passed, verdict, _ = audit.check({**self.fmt, 'id': 'UNLOCKED'}, 'page', 'de', 'test', LINKS)
        self.assertFalse(passed)
        self.assertFalse(verdict['brand_count_ok'])

    def test_reword_validation_counts_spoken_text_separately_from_cues(self):
        blocks = live(notion.script_paragraphs(SPEC, LINKS, 'de'))
        enc = [(b, *reword.encode(b)) for b in blocks]
        original = 'ON-SCREEN:\nSPEECH: ' + 'Wort ' * 30
        why, _ = reword._validate(enc, [enc[0][1]], original)
        self.assertEqual(why, '')
        changed = enc[0][1].replace('genehmigte Text', 'Parakeet AI Text')
        why, _ = reword._validate(enc, [changed], original)
        self.assertIn('spoken brand count', why)

    def test_failed_rollback_is_durable_and_recovered_before_new_moves(self):
        fmt = {**self.fmt, 'status': 'pending', 'pages': {'fr': 'page-fr'}}
        mkts = [MK, {**MK, 'key': 'fr', 'holder_page': 'fr-holder'}]
        parents = {'page': 'staging', 'page-fr': 'archive'}
        self.api.side_effect = lambda method, path: {'parent': {'type': 'page_id', 'page_id': parents[path.split('/')[-1]]}}
        calls = []
        failing = True
        def move(pid, parent):
            calls.append((pid, parent))
            if failing and ((pid == 'page-fr' and parent == 'fr-holder') or (pid == 'page' and parent == 'staging')):
                raise RuntimeError('temporary move failure')
            parents[pid] = parent
        self.patch(notion, 'move_page', side_effect=move)
        with self.assertRaises(RuntimeError):
            gate.publish(fmt, mkts, main.page_of)
        self.assertEqual(parents['page'], 'holder')
        self.assertEqual(state.load('publication_journal.json', {})['LOCKED']['attempted'], ['page'])
        # Simulate a process restart whose main format snapshot predates the publication journal.
        restarted = {**self.fmt, 'status': 'pending', 'pages': {'fr': 'page-fr'}}
        failing = False
        calls.clear()
        gate.publish(restarted, mkts, main.page_of)
        self.assertEqual(calls[0], ('page', 'staging'))
        self.assertEqual(parents, {'page': 'holder', 'page-fr': 'fr-holder'})
        self.assertEqual(restarted['status'], 'active')
        self.assertIn('list_repair_pending', restarted)
        self.assertEqual(state.load('publication_journal.json', {}), {})

    def test_partial_list_failure_stays_active_then_repairs_without_removing_public_pages(self):
        fmt = {**self.fmt, 'status': 'pending', 'pages': {'fr': 'page-fr'}}
        mkts = [MK, {**MK, 'key': 'fr', 'holder_page': 'fr-holder'}]
        parents, lists = {'page': 'staging', 'page-fr': 'archive'}, {'de': [], 'fr': []}
        self.api.side_effect = lambda method, path: {'parent': {'type': 'page_id', 'page_id': parents[path.split('/')[-1]]}}
        move = self.patch(notion, 'move_page', side_effect=lambda pid, parent: parents.update({pid: parent}))
        check = self.patch(gate, 'check', return_value=(True, []))
        attempts = 0
        def rerank(*args):
            nonlocal attempts
            attempts += 1
            lists['de'] = ['LOCKED']
            if attempts == 1:
                raise RuntimeError('French list unavailable')
            lists['fr'] = ['LOCKED']
            return ['LOCKED']
        gate.retry_pending([fmt], mkts, CFG, {}, {}, {}, main.page_of, main.set_page, Mock(), Mock(), rerank)
        self.assertEqual(fmt['status'], 'active')
        self.assertIn('list_repair_pending', state.load('formats.json', [])[0])
        self.assertEqual(parents, {'page': 'holder', 'page-fr': 'fr-holder'})
        self.assertEqual(lists, {'de': ['LOCKED'], 'fr': []})
        self.push.assert_not_called()
        gate.retry_pending([fmt], mkts, CFG, {}, {}, {}, main.page_of, main.set_page, Mock(), Mock(), rerank)
        self.assertEqual(lists, {'de': ['LOCKED'], 'fr': ['LOCKED']})
        self.assertNotIn('list_repair_pending', fmt)
        self.assertEqual(move.call_count, 2)
        check.assert_called_once()
        self.push.assert_called_once()

    def test_immediate_gate_keeps_durable_list_repair_after_rank_failure(self):
        fmt = {**self.fmt, 'status': 'pending'}
        self.patch(gate, 'check', return_value=(True, []))
        self.patch(notion, 'move_page')
        self.patch(main, 'rerank', side_effect=RuntimeError('list unavailable'))
        result = main._gate(fmt, [MK], [fmt], {}, CFG, 'new')
        self.assertFalse(result[0])
        self.assertEqual(fmt['status'], 'active')
        saved = state.load('formats.json', [])[0]
        self.assertEqual(saved['status'], 'active')
        self.assertIn('list_repair_pending', saved)

    def test_nested_resources_affect_fingerprint_and_are_reviewed_without_following_child_pages(self):
        blocks = page()
        blocks[-1]['has_children'] = True
        root_id = blocks[-1]['id']
        blocks.append({'id': 'unrelated-page', 'type': 'child_page', 'has_children': True,
                       'child_page': {'title': 'Separate page'}})
        children = live([notion.para([notion.rt('Gmail recording', link='https://example.invalid/gmail')])])
        def read(pid):
            if pid == 'page':
                return blocks
            if pid == root_id:
                return children
            raise AssertionError('Must not traverse unrelated child pages')
        self.patch(notion, 'children', side_effect=read)
        before = audit.fingerprint('page')
        children[0]['paragraph']['rich_text'][0]['text']['link']['url'] = 'https://example.invalid/updated'
        self.assertNotEqual(before, audit.fingerprint('page'))
        self.assertIn('https://example.invalid/updated', '\n'.join(audit.nested_instructions(blocks)))


if __name__ == '__main__':
    unittest.main()
