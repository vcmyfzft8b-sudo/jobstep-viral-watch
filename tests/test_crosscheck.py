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
        monkeypatch.setattr(localize, 'example_text', lambda url, page_id=None: self.pages[page_id].get('example', 'SPEECH: words'))
        monkeypatch.setattr(reword, 'script_blocks', lambda pid: [])
        monkeypatch.setattr(reword, 'spoken_text', lambda blocks: 'our script')
        monkeypatch.setattr(reword, 'direction_blocks', lambda pid: [])
        monkeypatch.setattr(align, 'approved_script', lambda fid, lang: {'script': [], 'voiceover': True} if (fid, lang) in locked else None)
        monkeypatch.setattr(align, 'matches_approved', lambda pid, lang, links, spec: True)
        monkeypatch.setattr(align, 'align_page', lambda fmt, pid, lang, cfg, links, feedback='': (self.rewrites.append((fmt['id'], lang)) or ('ok', '')))
        monkeypatch.setattr(reword, 'fix_directions', lambda *a, **k: ('ok', ''))

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
