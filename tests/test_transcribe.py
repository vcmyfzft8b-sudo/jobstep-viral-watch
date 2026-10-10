"""Scripts are transcribed (no rewording) and the visual hook section is short (1-2 sentences + Visual Hook Lab)."""
from watcher import align, builder, crosscheck, llm, notion, reword, state
from watcher.markets import TEXT

LINKS = {'parakeet': 'https://www.parakeet-ai.com/resume-maker', 'linkedin': 'https://linkedin.com/jobs',
         'visual_hook_lab': 'https://notion.so/lab'}
SPEC = {'page_title': 'Titel 🎯', 'title_hook': 'DEIN CV', 'voiceover': True,
        'visual_hook_first': 'Halte deinen alten CV in die Kamera, wie im Beispielvideo.',
        'script': [{'cue': None, 'text': 'Das ist mein alter Lebenslauf.'},
                   {'cue': 'parakeet', 'text': 'Ich lade ihn bei Parakeet AI hoch.'}]}


def _plain(b):
    return ''.join(x['text']['content'] for x in b[b['type']].get('rich_text', []))


def test_rewording_is_off():
    assert reword.reword_page({'id': 'X'}, 'page', 'de', 'opus', 'SPEECH: text')[0] == 'skipped'


def test_hook_section_is_one_line_plus_lab():
    blocks = notion.page_blocks(SPEC, {'url': 'https://www.tiktok.com/@a/video/1'}, None, LINKS, lang='de')
    texts = [_plain(b) for b in blocks]
    i = texts.index(TEXT['de']['hook_h'])
    section = texts[i + 1:texts.index('', i + 1)]  # until the divider
    assert section == [SPEC['visual_hook_first'], TEXT['de']['required_line'], 'Visual Hook Lab']


def test_validate_rejects_long_hook():
    spec = dict(SPEC, visual_hook_first='Eins. Zwei. Drei.')
    assert 'visual hook is longer than 2 sentences' in builder.validate(spec, {'text': ''}, 'de')
    assert 'visual hook is longer than 2 sentences' not in builder.validate(SPEC, {'text': ''}, 'de')


def test_translation_may_be_a_bit_longer():
    orig = {'text': ' '.join(['wort'] * 100), 'language': 'de'}
    spec = dict(SPEC, script=[{'cue': 'parakeet', 'text': ' '.join(['der'] * 120)}])
    assert any('script length' in p for p in builder.validate(spec, orig, 'de'))  # same language: max 110%
    assert not any('script length' in p for p in builder.validate(spec, dict(orig, language='pl'), 'de'))


def test_max_words_translation():
    assert align.max_words(100) == 110
    assert align.max_words(100, translated=True) == 135


def test_crosscheck_checks_transcript_not_rewording():
    assert 'faithful_transcript' in crosscheck.DIMENSIONS
    assert 'independent_wording' not in crosscheck.DIMENSIONS


def test_fix_directions_keeps_one_short_line(monkeypatch):
    lines = [notion.para([notion.rt(t)]) for t in ('Halte den CV hoch.', 'Film den Laptop.', 'X und Y vorlesen.')]
    for k, b in enumerate(lines):
        b['id'] = f'b{k}'
        b[b['type']]['rich_text'][0]['plain_text'] = _plain(b)
    calls = []
    monkeypatch.setattr(reword, 'direction_blocks', lambda pid: lines)
    monkeypatch.setattr(crosscheck, 'reference', lambda fid: {})
    monkeypatch.setattr(llm, 'chat_json', lambda *a, **k: {'hook': 'Halte deinen alten CV in die Kamera.'})
    monkeypatch.setattr(notion, 'api', lambda method, path, body=None: calls.append((method, path, body)))
    monkeypatch.setattr(state, 'load', lambda name, default: {})
    monkeypatch.setattr(state, 'save', lambda name, data: None)
    assert reword.fix_directions({'id': 'X', 'title': 't'}, 'page', 'de', 'sonnet') == ('ok', '')
    assert calls[0][0] == 'PATCH' and calls[0][1] == '/blocks/b0'
    assert calls[0][2]['paragraph']['rich_text'][0]['text']['content'] == 'Halte deinen alten CV in die Kamera.'
    assert [(m, p) for m, p, _ in calls[1:]] == [('DELETE', '/blocks/b1'), ('DELETE', '/blocks/b2')]


def test_fix_directions_refuses_long_hook(monkeypatch):
    line = notion.para([notion.rt('Alt.')])
    line['id'] = 'b0'
    line['paragraph']['rich_text'][0]['plain_text'] = 'Alt.'
    monkeypatch.setattr(reword, 'direction_blocks', lambda pid: [line])
    monkeypatch.setattr(crosscheck, 'reference', lambda fid: {})
    monkeypatch.setattr(llm, 'chat_json', lambda *a, **k: {'hook': 'Eins. Zwei. Drei.'})
    monkeypatch.setattr(notion, 'api', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not write')))
    assert reword.fix_directions({'id': 'X'}, 'page', 'de', 'sonnet')[0] == 'skipped'


def test_old_line_mentioning_the_lab_is_a_direction(monkeypatch):
    blocks = [notion.block('heading_2', [notion.rt(TEXT['de']['hook_h'])]),
              notion.para([notion.rt('Such dir einen Hook aus dem Visual Hook Lab aus.')]),
              notion.para([notion.rt('Starte als Selfie.')]),
              notion.para([notion.rt(TEXT['de']['required_line'])]),
              notion.para([notion.rt('Visual Hook Lab', link='https://notion.so/lab')]),
              notion.divider()]
    for b in blocks:
        for x in b.get(b['type'], {}).get('rich_text', []):
            x['plain_text'] = x['text']['content']
    monkeypatch.setattr(notion, 'children', lambda pid: blocks)
    assert [_plain(b) for b in reword.direction_blocks('page')] == [
        'Such dir einen Hook aus dem Visual Hook Lab aus.', 'Starte als Selfie.']
