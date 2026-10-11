"""Scripts without stage directions (user's decision, 11 Oct 2026): a script holds only what is said (or the on-screen
texts of a silent video); the only brackets are the link cues (Parakeet AI, LinkedIn) and 📎 material cues. Plus the
note under the inspiration video (copy the example as closely as possible) and the modes renote / verify."""
import os

from watcher import align, audit, builder, crosscheck, llm, localize, notion, reword, state, verify
from watcher.brands import NO_DIRECTIONS
from watcher.markets import TEXT

LINKS = {'parakeet': 'https://www.parakeet-ai.com/resume-maker', 'linkedin': 'https://www.linkedin.com/jobs/'}
WARN = {'type': 'emoji', 'emoji': '⚠️'}


def _text(b):
    return ''.join(x['text']['content'] for x in b[b['type']]['rich_text'])


def _live(blocks):
    """Blocks as Notion returns them (plain_text on every rich text, an id per block)."""
    for n, b in enumerate(blocks):
        b.setdefault('id', f'b{n}')
        for x in (b.get(b['type']) or {}).get('rich_text', []) or []:
            x['plain_text'] = x['text']['content']
    return blocks


def _blk(*parts, bid='b'):
    rich = [{'type': 'text', 'plain_text': t, 'text': {'content': t, 'link': {'url': u} if u else None},
             'annotations': {}} for t, u in parts]
    return {'id': bid, 'type': 'paragraph', 'paragraph': {'rich_text': rich}}


def test_script_paragraphs_render_no_stage_directions():
    spec = {'voiceover': True, 'script': [
        {'cue': 'direction', 'asset_name': 'lächelnd in die Kamera', 'text': '(zeigt auf den Laptop) Erster Satz.',
         'new_paragraph': True},
        {'cue': 'direction', 'asset_name': 'Musik', 'text': '(Pause)', 'new_paragraph': False},
        {'cue': 'parakeet', 'asset_name': '', 'text': 'Das ist Parakeet AI.', 'new_paragraph': True},
        {'cue': 'asset', 'asset_name': 'Gmail-Postfach', 'text': 'Schau dir das an.', 'new_paragraph': False}]}
    paras = [_text(b) for b in notion.script_paragraphs(spec, LINKS, 'de')]
    assert paras == ['Erster Satz. ', '(Parakeet AI · Resume Maker) Das ist Parakeet AI. '
                     '(📎 Gmail-Postfach – siehe Ressourcen) Schau dir das an. ']


def test_strip_directions_keeps_link_and_material_cues_and_backs_up(monkeypatch):
    page = [_blk(('(lächelt in die Kamera) Hallo. (', None), ('Parakeet AI · Resume Maker', LINKS['parakeet']),
                 (') Das ist die App. (📎 Gmail – siehe Ressourcen) Schau. (zeigt den CV)', None), bid='p1'),
            _blk(('(Musik, Übergang)', None), bid='p2'),
            _blk(('Ganz normaler Satz.', None), bid='p3')]
    sent, saved = [], {}
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: page)
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: sent.append((method, path, body)))
    monkeypatch.setattr(state, 'load', lambda name, default: dict(saved))
    monkeypatch.setattr(state, 'save', lambda name, data: saved.update(data))
    assert reword.directions_left('p') == ['(lächelt in die Kamera)', '(zeigt den CV)', '(Musik, Übergang)']
    assert reword.strip_directions('p') == 2
    (m1, path1, body1), (m2, path2, _) = sent
    assert (m1, path1) == ('PATCH', '/blocks/p1')
    assert ''.join(x['text']['content'] for x in body1['paragraph']['rich_text']) == \
        'Hallo. (Parakeet AI · Resume Maker) Das ist die App. (📎 Gmail – siehe Ressourcen) Schau. '
    assert body1['paragraph']['rich_text'][1]['text']['link'] == {'url': LINKS['parakeet']}
    assert (m2, path2) == ('DELETE', '/blocks/p2')  # the paragraph was only a direction
    assert set(saved) == {'directions:p1', 'directions:p2'}  # old rich text backed up first


def test_builder_turns_direction_cues_into_null(monkeypatch, tmp_path):
    from watcher import media
    seen = {}
    monkeypatch.setattr(media, 'contact_sheets', lambda frames, work: [])
    monkeypatch.setattr(llm, 'chat_json', lambda model, system, content, **k: seen.update(prompt=content[0]['text']) or {
        'script': [{'cue': 'direction', 'asset_name': 'lacht', 'text': 'Satz.'}, {'cue': 'null', 'text': 'Zwei.'}]})
    video = {'handle': 'a', 'views': 1, 'duration': 10}
    spec = builder.build_spec(video, {'segments': []}, [(0, str(tmp_path / 'f.jpg'))], 'opus')
    assert [(s['cue'], s.get('asset_name')) for s in spec['script']] == [(None, ''), (None, None)]
    assert NO_DIRECTIONS in seen['prompt'] and '|direction|' not in seen['prompt']


def test_align_prompt_and_write_have_no_directions(monkeypatch):
    seen, written = {}, []
    monkeypatch.setattr(localize, 'current_source', lambda pid: {'url': 'https://www.tiktok.com/@a/video/1'})
    monkeypatch.setattr(localize, 'example_text', lambda url, page_id=None: 'ON-SCREEN: x\nSPEECH: ' + 'Wort ' * 20)
    monkeypatch.setattr(align, 'approved_script', lambda fid, lang: None)
    monkeypatch.setattr(crosscheck, 'reference', lambda fid: None)
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: [_blk(('alt', None), bid='old')])
    monkeypatch.setattr(reword, 'resources_text', lambda pid: 'parakeet ai')
    monkeypatch.setattr(reword, 'fix_directions', lambda *a, **k: ('ok', ''))
    monkeypatch.setattr(notion, 'children', lambda pid: [])
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: written.append(body))
    monkeypatch.setattr(state, 'load', lambda name, default: {})
    monkeypatch.setattr(state, 'save', lambda name, data: None)
    spec = {'original_language': 'German', 'script': [
        {'cue': 'direction', 'asset_name': 'lacht', 'text': 'Wort ' * 10},
        {'cue': 'asset', 'asset_name': 'InfoJobs', 'text': 'Wort ' * 9},
        {'cue': 'parakeet', 'asset_name': '', 'text': 'Wort'}]}
    monkeypatch.setattr(llm, 'chat_json', lambda model, system, prompt, **k: seen.update(prompt=prompt) or spec)
    status, _ = align.align_page({'id': 'F1', 'title': 't'}, 'page', 'de', {'models': {'build': 'o', 'classify': 's'}}, LINKS)
    assert status == 'ok'
    assert NO_DIRECTIONS in seen['prompt'] and '|direction|' not in seen['prompt']
    new = [_text(b) for b in written[0]['children']]
    assert '(' not in new[0].replace('(Parakeet AI · Resume Maker)', '')  # no direction, no cue to missing material


def test_checkers_get_the_rule(monkeypatch):
    prompts = []
    monkeypatch.setattr(llm, 'chat_json', lambda model, system, prompt, **k: prompts.append(prompt) or {
        'results': {d: {'de': {'pass': True}} for d in crosscheck.DIMENSIONS}})
    ev = {'de': {'source_id': '1', 'example': 'e', 'script': 's', 'marked': 'm', 'directions': 'd', 'title': 't'}}
    crosscheck.judge({'id': 'F1'}, {'beats': ['a']}, ev, 'opus')
    assert NO_DIRECTIONS in prompts[0] and 'stage direction):' not in prompts[0]
    import inspect
    assert '{NO_DIRECTIONS}' in inspect.getsource(audit.check)


def test_generated_reference_is_rebuilt_once_for_the_new_rules(monkeypatch):
    stored = {'G1': {'beats': ['old'], 'hook': 'h', 'generated': 1, 'canonical_source': '5'},
              'R1': {'beats': ['reviewed'], 'hook': 'h'}}
    prompts = []
    monkeypatch.setattr(crosscheck, 'references', lambda: stored)
    monkeypatch.setattr(localize, 'example_text', lambda url, page_id=None: 'SPEECH: hi')
    monkeypatch.setattr(state, 'load', lambda name, default: stored)
    monkeypatch.setattr(state, 'save', lambda name, data: None)
    monkeypatch.setattr(llm, 'chat_json', lambda model, system, prompt, **k: prompts.append(prompt) or {
        'beats': ['new'], 'hook': 'h', 'product': {}})
    page_of = lambda f, m: None
    fmt = {'id': 'G1', 'source_video': 'https://www.tiktok.com/@a/video/5'}
    ref = crosscheck.ensure_reference(fmt, page_of, {'models': {'build': 'opus'}})
    assert ref['beats'] == ['new'] and ref['rules'] == crosscheck.REF_RULES and NO_DIRECTIONS in prompts[0]
    assert crosscheck.ensure_reference(fmt, page_of, {'models': {'build': 'opus'}})['beats'] == ['new']
    assert crosscheck.ensure_reference({'id': 'R1'}, page_of, {})['beats'] == ['reviewed']  # reviewed: never rebuilt
    assert len(prompts) == 1
    assert crosscheck.AUDIT_VERSION != 'group-2026-10-10.transcribe'


def test_notes_keep_their_starts_and_name_no_app():
    starts = {'de': ('Wichtig: Dreh dein Video nach ', 'Wichtig: Das Inspirationsvideo'),
              'fr': ('Important : Tourne ta vidéo d’', 'Important : La vidéo d’inspira'),
              'es': ('Importante: Graba tu vídeo con', 'Importante: El vídeo de inspir')}
    for lang, (other, same) in starts.items():
        T = TEXT[lang]
        assert T['inspo_note'][0].replace('**', '')[:30] == other
        assert T['inspo_note_same'].replace('**', '')[:30] == same
        assert localize.note_is_same(T['inspo_note_same'], lang) and not localize.note_is_same(T['inspo_note'][0], lang)
        assert 'JobStep' not in ' '.join(T['inspo_note']) + T['inspo_note_same']
        assert 'Parakeet AI' in T['inspo_note'][1]


def _page_with_note(note, extra=()):
    return _live([notion.block('heading_1', [notion.rt('Inspirationsvideo')]),
                  notion.block('video', type='file', file={'url': 'https://x'}),
                  notion.para([notion.rt('Original auf TikTok', link='https://www.tiktok.com/@a/video/1')]),
                  notion.block('callout', [notion.rt(note)], icon=WARN), *extra])


def test_renote_puts_the_current_text_and_keeps_the_kind(monkeypatch):
    old_same = 'Wichtig: Das Inspirationsvideo ist auf Deutsch – nimm es als Vorbild.\nIm Video wird JobStep genutzt.'
    blocks = _page_with_note(old_same)
    sent = []
    monkeypatch.setattr(notion, 'children', lambda pid: blocks)
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: sent.append(body))
    assert verify.note_problem(blocks, 'de') == 'note under the inspiration video is not the current text'
    assert localize.refresh_note('p', 'de') is True
    new = ''.join(x['text']['content'] for x in sent[0]['callout']['rich_text'])
    assert new == '\n'.join(notion.inspo_note('de', True)).replace('**', '')
    current = _page_with_note('\n'.join(notion.inspo_note('fr', False)).replace('**', ''))
    monkeypatch.setattr(notion, 'children', lambda pid: current)
    assert localize.refresh_note('p', 'fr') is False and verify.note_problem(current, 'fr') is None


def test_verify_reports_stage_directions(monkeypatch):
    blocks = _page_with_note('\n'.join(notion.inspo_note('de', False)).replace('**', ''))
    monkeypatch.setattr(notion, 'children', lambda pid: blocks)
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: [_blk(('(lacht) Hallo. ', None), ('Parakeet AI · Resume Maker', LINKS['parakeet']))])
    monkeypatch.setattr(reword, 'direction_blocks', lambda pid: [_blk(('Halte deinen CV in die Kamera.', None))])
    out = verify.check_page('p', 'de', LINKS, live=False)
    assert out == ['stage directions in the script: (lacht)']


def test_new_modes_are_in_the_workflow():
    with open(os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'watch.yml')) as f:
        wf = f.read()
    for mode in ('strip-directions', 'renote', 'refs', 'verify', 'export'):
        assert f'{mode})' in wf and f'--{mode}' in wf


def test_renote_adds_a_missing_note_under_the_video_and_leaves_other_boxes_alone(monkeypatch):
    user_box = notion.block('callout', [notion.rt('Für alle App-Demos nutz bitte diesen Link')], icon=WARN)
    blocks = _live([user_box, notion.block('video', type='file', file={'url': 'https://x'}),
                    notion.para([notion.rt('Original sur TikTok', link='https://www.tiktok.com/@a/video/1')]),
                    notion.block('heading_2', [notion.rt('📲 TEXTE')])])
    sent = []
    monkeypatch.setattr(notion, 'children', lambda pid: blocks)
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: sent.append((method, path, body)))
    assert verify.note_problem(blocks, 'fr') == 'no note under the inspiration video'
    assert localize.refresh_note('p', 'fr') is True
    (method, path, body), = sent
    assert (method, path, body['after']) == ('PATCH', '/blocks/p/children', 'b2')  # right after the TikTok link
    added = ''.join(x['text']['content'] for x in body['children'][0]['callout']['rich_text'])
    assert added == '\n'.join(notion.inspo_note('fr', False)).replace('**', '')


def test_verify_accepts_the_visual_hook_lab_as_a_sub_page(monkeypatch):
    blocks = _page_with_note('\n'.join(notion.inspo_note('es', False)).replace('**', '')) + [
        {'id': 'lab', 'type': 'child_page', 'child_page': {'title': 'Visual Hook Lab'}}]
    script = [_blk(('Hola. ', None), ('Parakeet AI · Resume Maker', LINKS['parakeet']))]
    monkeypatch.setattr(notion, 'children', lambda pid: blocks)
    monkeypatch.setattr(reword, 'script_blocks', lambda pid: script)
    monkeypatch.setattr(reword, 'direction_blocks', lambda pid: [_blk(('Empieza en plano selfie.', None))])
    assert verify.check_page('p', 'es', LINKS) == []
