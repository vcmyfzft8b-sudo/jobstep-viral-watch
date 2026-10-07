"""Cross-country check: reference definitions, duplicates, cached group results, approval locks."""
import pytest

from watcher import align, audit, crosscheck, gate, llm, localize, reword

MKTS = [{'key': 'de', 'lang': 'de', 'T': {'flag': 'DE'}},
        {'key': 'fr', 'lang': 'fr', 'T': {'flag': 'FR'}},
        {'key': 'es', 'lang': 'es', 'T': {'flag': 'ES'}}]
CFG = {'models': {'build': 'opus', 'classify': 'sonnet'}, 'links': {'parakeet': 'p', 'linkedin': 'l'},
       'notion': {'radar_page': 'staging'}}

REFS = {
    'N10': {'canonical_source': '111', 'accepted_sources': ['111', '112'],
            'rejected_sources': {'999': 'repeated-rejection printed-CV story (X15)'},
            'source_urls': {'111': 'https://www.tiktok.com/@a/video/111'}, 'beats': ['hook', 'demo']},
    'X15': {'canonical_source': '999', 'accepted_sources': ['999'], 'rejected_sources': {}, 'beats': ['hook']},
    'N07': {'canonical_source': '700', 'accepted_sources': ['700'],
            'rejected_sources': {'701': "mother's HR friend criticises a Canva CV - different story"}, 'beats': ['x']},
    'L1': {'canonical_source': '500', 'accepted_sources': ['500', '501', '502'], 'rejected_sources': {},
           'allowed_localisation': ['country-specific company list'], 'beats': ['x']},
}


class World:
    """Fake live pages: page -> source id, fingerprint, video hash, example text; and a fake reviewer."""
    def __init__(self, monkeypatch, pages, refs=REFS, verdict=None, locked=()):
        self.pages, self.calls, self.rewrites, self.examples_put = pages, 0, [], []
        self.verdict = verdict or (lambda fid, market: True)
        monkeypatch.setattr(crosscheck, 'references', lambda: refs)
        monkeypatch.setattr(localize, 'current_source', lambda pid: {'url': f"https://www.tiktok.com/@x/video/{self.pages[pid]['src']}"})
        monkeypatch.setattr(audit, 'fingerprint', lambda pid: self.pages[pid].get('fp', 'fp-' + pid))
        monkeypatch.setattr(crosscheck, 'video_identity', lambda pid, cache=None: self.pages[pid].get('vid', 'sha:' + self.pages[pid]['src']))
        monkeypatch.setattr(localize, 'example_text', lambda url, page_id=None: self.pages.get(page_id, {}).get('example', 'SPEECH: words'))
        monkeypatch.setattr(reword, 'script_blocks', lambda pid: [])
        monkeypatch.setattr(reword, 'spoken_text', lambda blocks: 'our script')
        monkeypatch.setattr(reword, 'direction_blocks', lambda pid: [])
        monkeypatch.setattr(align, 'approved_script', lambda fid, lang: {'script': [], 'voiceover': True} if (fid, lang) in locked else None)
        monkeypatch.setattr(align, 'matches_approved', lambda pid, lang, links, spec: True)
        monkeypatch.setattr(align, 'align_page', lambda fmt, pid, lang, cfg, links, feedback='': (self.rewrites.append((fmt['id'], lang)) or ('ok', '')))
        monkeypatch.setattr(reword, 'fix_directions', lambda *a, **k: ('ok', ''))
        self.titles = {}
        monkeypatch.setattr(crosscheck, 'page_title', lambda pid: self.pages[pid].get('title', 'Titel'))
        monkeypatch.setattr(crosscheck, 'set_title', lambda pid, t: self.titles.__setitem__(pid, t) or True)

        def chat_json(model, system, prompt, **kw):
            self.calls += 1
            fid = prompt.split('format ', 1)[1].split(' ', 1)[0]
            return {'results': {d: {m: {'pass': self.verdict(fid, m), 'issue': '' if self.verdict(fid, m) else 'mismatch'}
                                    for m in ('de', 'fr', 'es')} for d in crosscheck.DIMENSIONS}, 'summary': 's'}
        monkeypatch.setattr(llm, 'chat_json', chat_json)


def page_of(fmt, m):
    return f"{fmt['id']}_{m}"


def fmt(fid):
    return {'id': fid, 'title': fid, 'status': 'active'}


def test_n10_mismatched_and_duplicated_reference(monkeypatch):
    pages = {'N10_de': {'src': '999'}, 'N10_fr': {'src': '111'}, 'N10_es': {'src': '112'},
             'X15_de': {'src': '999'}, 'X15_fr': {'src': '999'}, 'X15_es': {'src': '999'}}
    World(monkeypatch, pages)
    meta = {}
    results, dups = crosscheck.run([fmt('N10'), fmt('X15')], MKTS, CFG, page_of, meta)
    assert any(d['kind'] == 'source_id' and d['value'] == '999' and d['formats'] == ['N10', 'X15'] for d in dups)
    assert results['N10']['status'] == 'fail' and not results['N10']['passed']
    assert results['N10']['results']['format_consistency']['de']['pass'] is False  # rejected source, whatever the model says
    assert any('duplicate' in r for r in results['X15']['reasons'])  # flagged for review, not deleted


def test_n07_materially_different_country_story_fails(monkeypatch):
    pages = {'N07_de': {'src': '700'}, 'N07_fr': {'src': '701'}, 'N07_es': {'src': '700', 'vid': 'sha:es-own-upload'}}
    World(monkeypatch, pages)
    res = crosscheck.check_group(fmt('N07'), MKTS, CFG, page_of, {}, dup_list=[])
    assert res['status'] == 'fail'
    assert 'Canva' in res['results']['format_consistency']['fr']['issue']
    assert res['results']['format_consistency']['de']['pass'] is True


def test_x15_spanish_ats_variant_fails_via_reviewer(monkeypatch):
    pages = {'X15_de': {'src': '999'}, 'X15_fr': {'src': '999', 'vid': 'sha:fr'}, 'X15_es': {'src': '998'}}
    World(monkeypatch, pages, verdict=lambda fid, m: m != 'es')
    res = crosscheck.check_group(fmt('X15'), MKTS, CFG, page_of, {}, dup_list=[])
    assert res['status'] == 'fail'
    assert all(not res['results'][d]['es']['pass'] for d in crosscheck.DIMENSIONS)


def test_legitimate_localisation_passes(monkeypatch):
    pages = {'L1_de': {'src': '500'}, 'L1_fr': {'src': '501'}, 'L1_es': {'src': '502'}}
    World(monkeypatch, pages)
    res = crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, {}, dup_list=[])
    assert res['status'] == 'pass' and res['passed'] and res['reasons'] == []


def test_missing_evidence_prevents_publication(monkeypatch):
    pages = {'L1_de': {'src': '500'}, 'L1_fr': {'src': '501'}, 'L1_es': {'src': '502', 'example': ''}}
    w = World(monkeypatch, pages)
    meta = {}
    res = crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert res['status'] == 'unverified' and not res['passed'] and w.calls == 0
    # through the gate: every page passes on its own, the group is unverified -> not published, attempt not counted
    monkeypatch.setattr(audit, 'fix_page', lambda *a, **k: ('ok', []))
    f = {**fmt('L1'), 'status': 'pending'}
    ok, reasons = gate.check(f, MKTS, CFG, {}, {}, meta, page_of, None, None, None)
    assert not ok and any('unverified' in r for r in reasons)
    assert gate.has_unknown(f, MKTS, meta)


def test_missing_reference_is_unverified(monkeypatch):
    pages = {'ZZ_de': {'src': '1'}, 'ZZ_fr': {'src': '1'}, 'ZZ_es': {'src': '1'}}
    World(monkeypatch, pages)
    res = crosscheck.check_group(fmt('ZZ'), MKTS, CFG, page_of, {}, dup_list=[])
    assert res['status'] == 'unverified' and not res['passed']


def test_changes_invalidate_cached_group_result(monkeypatch):
    pages = {'L1_de': {'src': '500'}, 'L1_fr': {'src': '501'}, 'L1_es': {'src': '502'}}
    w = World(monkeypatch, pages)
    meta = {}
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 1
    assert crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[]).get('cached')
    assert w.calls == 1
    pages['L1_fr']['fp'] = 'edited'            # one page edited
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 2
    pages['L1_es']['src'] = '501'              # example swapped
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 3
    pages['L1_de']['vid'] = 'sha:new-upload'   # same source, different uploaded bytes
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 4
    refs = {**REFS, 'L1': {**REFS['L1'], 'beats': ['x', 'y']}}   # reference definition changed
    monkeypatch.setattr(crosscheck, 'references', lambda: refs)
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 5
    monkeypatch.setattr(crosscheck, 'AUDIT_VERSION', 'group-next')  # audit version changed
    crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert w.calls == 6


def test_approved_scripts_untouched_and_approval_separate_from_quality(monkeypatch):
    pages = {'N10_de': {'src': '999'}, 'N10_fr': {'src': '111'}, 'N10_es': {'src': '112'}}
    w = World(monkeypatch, pages, verdict=lambda fid, m: m == 'es', locked={('N10', 'de')})
    meta = {}
    res, changed, awaiting = crosscheck.group_cycle(fmt('N10'), MKTS, CFG, page_of, meta,
                                                    put_example=lambda *a: w.examples_put.append(a[1]))
    assert ('N10', 'de') not in w.rewrites and 'de' not in w.examples_put   # approved wording never rewritten
    assert any(a.startswith('de: approved script') for a in awaiting)
    assert ('N10', 'fr') in w.rewrites                                        # unlocked page repaired
    assert res['approval']['de'] == 'locked_preserved' and not res['passed']  # preserved lock != passed


def test_duplicates_ignore_single_format_reuse():
    groups = {'A': {'de': {'source_id': '1', 'video_identity': 'sha:1'}, 'fr': {'source_id': '1', 'video_identity': 'sha:1'}},
              'B': {'de': {'source_id': '2', 'video_identity': 'sha:2'}}}
    assert crosscheck.duplicates(groups) == []


def test_rejected_sources_are_remembered_and_blocked(monkeypatch):
    pages = {'N07_de': {'src': '700'}, 'N07_fr': {'src': '701'}, 'N07_es': {'src': '700', 'vid': 'sha:es'}}
    w = World(monkeypatch, pages, verdict=lambda fid, m: m != 'fr')
    meta = {'group_rejected': {'N07': ['555']}}
    crosscheck.group_cycle(fmt('N07'), MKTS, CFG, page_of, meta, put_example=lambda *a: w.examples_put.append(a[1]))
    assert '701' in meta['group_rejected']['N07']           # the wrong-story video is remembered
    assert crosscheck.blocked_sources('N07', meta) >= {'701', '555'}  # reference + earlier checks: never re-added
    assert crosscheck.blocked_sources('L1', meta) == set()


def test_reviewer_sees_cue_markers_but_not_as_spoken_words():
    b = {'type': 'paragraph', 'paragraph': {'rich_text': [
        {'plain_text': 'Ich lade ihn hoch ', 'text': {'content': 'Ich lade ihn hoch '}},
        {'plain_text': '(Parakeet AI · Resume Maker)', 'text': {'content': '(Parakeet AI · Resume Maker)', 'link': {'url': 'p'}}}]}}
    assert crosscheck.cue_text(b) == 'Ich lade ihn hoch [CUE: (Parakeet AI · Resume Maker)]'
    from watcher import reword as rw
    assert 'Parakeet' not in rw.spoken_text([b])


def test_unreadable_reviewer_answer_is_retried_then_unverified(monkeypatch):
    import json as _json
    pages = {'L1_de': {'src': '500'}, 'L1_fr': {'src': '501'}, 'L1_es': {'src': '502'}}
    World(monkeypatch, pages)
    good = llm.chat_json
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise _json.JSONDecodeError('Expecting', 'x', 0)
        return good(*a, **k)
    monkeypatch.setattr(llm, 'chat_json', flaky)
    assert crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, {}, dup_list=[])['status'] == 'pass'
    monkeypatch.setattr(llm, 'chat_json', lambda *a, **k: (_ for _ in ()).throw(ValueError('No JSON')))
    meta = {}
    res = crosscheck.check_group(fmt('L1'), MKTS, CFG, page_of, meta, dup_list=[])
    assert res['status'] == 'unverified' and not res['passed'] and meta['group_audit']['L1']['key'] is None


def test_approval_drafts_never_write(monkeypatch):
    pages = {'N10_de': {'src': '999'}, 'N10_fr': {'src': '111'}, 'N10_es': {'src': '112'}}
    World(monkeypatch, pages, locked={('N10', 'de')})
    seen = []
    monkeypatch.setattr(align, 'align_page', lambda fmt, pid, lang, cfg, links, feedback='', draft_url=None:
                        (seen.append((pid, draft_url)) or ('draft', {'script': [{'text': 'neu'}]})))
    meta = {'group_audit': {'N10': {'results': {'format_consistency': {'de': {'pass': False, 'issue': 'X15 story'},
                                                                       'fr': {'pass': True}}}}}}
    out = crosscheck.approval_drafts([fmt('N10')], MKTS, CFG, page_of, meta)
    assert seen == [('N10_de', 'https://www.tiktok.com/@a/video/111')]   # canonical example, locked page only
    assert out['N10:de']['example_changes'] and out['N10:de']['draft']['script'][0]['text'] == 'neu'


def test_align_draft_mode_returns_spec_without_writing(monkeypatch):
    monkeypatch.setattr(localize, 'current_source', lambda pid: {'url': 'https://www.tiktok.com/@x/video/999'})
    monkeypatch.setattr(align, 'approved_script', lambda fid, lang: {'script': [], 'voiceover': True, 'example': 'old'})
    monkeypatch.setattr(localize, 'example_text', lambda url, page_id=None: 'SPEECH: ' + ' '.join(['wort'] * 20) + ' JobStep')
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: [{'type': 'paragraph', 'paragraph': {'rich_text': []}}])
    monkeypatch.setattr(reword, '_plain', lambda b: 'alt')
    monkeypatch.setattr(crosscheck, 'references', lambda: REFS)
    spec = {'voiceover': True, 'script': [{'cue': 'parakeet', 'text': ' '.join(['neu'] * 19) + ' Parakeet AI'}]}
    monkeypatch.setattr(llm, 'chat_json', lambda *a, **k: spec)
    monkeypatch.setattr(align, '_write', lambda *a, **k: pytest.fail('draft mode must not write'))
    st, out = align.align_page(fmt('N10'), 'N10_de', 'de', CFG, {}, draft_url='https://www.tiktok.com/@a/video/111')
    assert st == 'draft' and out['example'].endswith('/111')


def test_evidence_pin_of_a_rejected_source_is_inactive(monkeypatch, tmp_path):
    import json as _json
    reg = tmp_path / 'ev.json'
    reg.write_text(_json.dumps({'examples': [
        {'format_id': 'N07', 'page_id': 'p-1', 'source_url': 'https://www.tiktok.com/@m/video/701'},
        {'format_id': 'N07', 'page_id': 'p-2', 'source_url': 'https://www.tiktok.com/@z/video/700'}]}))
    monkeypatch.setattr(localize, 'EMBEDDED_EVIDENCE', str(reg))
    monkeypatch.setattr(crosscheck, 'references', lambda: REFS)
    assert localize.embedded_record('p1') is None          # pinned to the rejected different-story video
    assert localize.embedded_record('p2')['page_id'] == 'p-2'  # Codex's verified pins stay in force


def test_asset_cue_is_not_decorated_twice():
    from watcher import notion
    assert notion.asset_label('📎 📎 📎 Bandeja de Gmail – ver Recursos – ver Recursos – ver Recursos') == 'Bandeja de Gmail'
    assert notion.asset_label('(📎 Gmail-Aufnahme – siehe Ressourcen)') == 'Gmail-Aufnahme'
    assert notion.asset_label('Gmail inbox') == 'Gmail inbox'


def test_fix_asset_cues_repairs_piled_up_decoration(monkeypatch):
    from watcher import notion
    t = 'Y ahora (📎 📎 📎 Bandeja de Gmail – ver Recursos – ver Recursos – ver Recursos) Y ahora echa un ojo.'
    blk = {'id': 'b1', 'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'plain_text': t, 'text': {'content': t}}]}}
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: [blk])
    sent = []
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: sent.append(body))
    assert reword.fix_asset_cues('p') == 1
    assert sent[0]['paragraph']['rich_text'][0]['text']['content'] == 'Y ahora (📎 Bandeja de Gmail – ver Recursos) Y ahora echa un ojo.'


def test_direction_blocks_never_include_the_example_link(monkeypatch):
    from watcher import notion

    def blk(t, typ='paragraph', link=None):
        x = {'type': 'text', 'plain_text': t, 'text': {'content': t, 'link': {'url': link} if link else None}}
        return {'id': t[:8], 'type': typ, typ: {'rich_text': [x]}}
    page = [blk('🎬 BEISPIELVIDEO', 'heading_2'), {'id': 'v', 'type': 'video', 'video': {}},
            blk('Original auf TikTok', link='https://www.tiktok.com/@e/video/1'), blk('Ca. 32 Sekunden', 'bulleted_list_item'),
            blk('💬 SKRIPT', 'heading_2'), blk('Schon wieder eine Absage.'),
            blk('👀 VISUELLER EINSTIEG', 'heading_2'), blk('Halte die Lebensläufe in die Kamera.')]
    monkeypatch.setattr(notion, 'children', lambda pid: page)
    got = [reword._plain(b) for b in reword.direction_blocks('p')]
    assert got == ['Ca. 32 Sekunden', 'Halte die Lebensläufe in die Kamera.']


def test_apply_approvals_switches_example_then_writes_approved_script(monkeypatch):
    pages = {'N10_de': {'src': '999'}, 'N10_fr': {'src': '111'}, 'N10_es': {'src': '112'}}
    w = World(monkeypatch, pages)
    ok = {'example': 'https://www.tiktok.com/@a/video/111', 'script': [], 'voiceover': True}
    monkeypatch.setattr(align, 'approved_script', lambda fid, lang: ok if (fid, lang) == ('N10', 'de') else None)
    order = []
    monkeypatch.setattr(align, 'align_page', lambda f, pid, lang, cfg, links, feedback='': (order.append(('write', pid)) or ('ok', 'approved script')))
    out = crosscheck.apply_approvals([fmt('N10')], MKTS, CFG, page_of, {},
                                     put_example=lambda f, m, pid, lang, url: order.append(('example', pid, url)))
    assert order == [('example', 'N10_de', ok['example']), ('write', 'N10_de')]   # only the approved page
    assert len(out) == 2


def test_new_format_gets_a_reference_from_its_source_video(monkeypatch, tmp_path):
    from watcher import state
    monkeypatch.setattr(state, 'DIR', str(tmp_path))
    pages = {'NEW_de': {'src': '800'}, 'NEW_fr': {'src': '800', 'vid': 'sha:fr'}, 'NEW_es': {'src': '800', 'vid': 'sha:es'}}
    w = World(monkeypatch, pages, refs={})
    monkeypatch.setattr(crosscheck, 'references', lambda: {**state.load('format_references.json', {})})
    good = llm.chat_json

    def chat(model, system, prompt, **kw):
        if 'reference definition that all three' in prompt:
            return {'hook': 'h', 'beats': ['a', 'b'], 'product': {'introduced_at_beat': 2}}
        return good(model, system, prompt, **kw)
    monkeypatch.setattr(llm, 'chat_json', chat)
    f = {**fmt('NEW'), 'source_video': 'https://www.tiktok.com/@n/video/800'}
    res = crosscheck.check_group(f, MKTS, CFG, page_of, {}, dup_list=[])
    assert res['status'] == 'pass'
    saved = state.load('format_references.json', {})['NEW']
    assert saved['canonical_source'] == '800' and saved['accepted_sources'] == ['800']


def test_title_with_invented_result_is_fixed_even_on_a_locked_page(monkeypatch):
    pages = {'L1_de': {'src': '500', 'title': 'Ich habe 20 VORSTELLUNGSGESPRÄCHE bekommen?'},
             'L1_fr': {'src': '501'}, 'L1_es': {'src': '502'}}
    w = World(monkeypatch, pages, locked={('L1', 'de')})
    good = llm.chat_json
    monkeypatch.setattr(llm, 'chat_json', lambda *a, **k: {**good(*a, **k), 'titles': {'de': 'Plötzlich Einladungen? 😳'}})
    res, changed, awaiting = crosscheck.group_cycle(fmt('L1'), MKTS, CFG, page_of, {})
    assert w.titles == {'L1_de': 'Plötzlich Einladungen? 😳'} and ('L1', 'de') not in w.rewrites
    assert any('title' in c for c in changed)
