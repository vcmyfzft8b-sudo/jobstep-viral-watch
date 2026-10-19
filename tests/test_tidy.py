from watcher import pages, tidy

LINKS = {'parakeet': 'https://p', 'linkedin': 'https://l'}


def cue(url, label='Parakeet AI · Resume Maker'):
    return [pages.rt('('), pages.rt(label, link=url), pages.rt(') ')]


def text(items):
    return ''.join(x['text']['content'] for x in items)


def test_one_cue_per_paragraph_and_at_most_three():
    paras = [cue('https://p') + [pages.rt('Upload. ')] + cue('https://p') + [pages.rt('Score. ')],
             cue('https://p') + [pages.rt('A. ')], cue('https://p') + [pages.rt('B. ')],
             cue('https://p') + [pages.rt('C. ')]]
    out, removed = tidy.trim_cues(paras, LINKS)
    assert removed == 2  # the 2nd cue of paragraph 1 and the 4th Parakeet AI cue
    assert text(out[0]) == '(Parakeet AI · Resume Maker) Upload. Score. '
    assert text(out[3]) == 'C. '  # the 4th Parakeet AI cue is dropped
    assert sum(1 for p in out for x in p if tidy._url(x)) == 3


def test_linkedin_and_parakeet_cues_both_stay_in_one_paragraph():
    out, removed = tidy.trim_cues([cue('https://l', 'LinkedIn') + [pages.rt('Copy. ')] + cue('https://p') +
                                   [pages.rt('Paste. ')]], LINKS)
    assert removed == 0


def test_merged_brackets_are_removed_too():
    paras = [[pages.rt('('), pages.rt('P', link='https://p'), pages.rt(') One. ('), pages.rt('P', link='https://p'),
              pages.rt(') Two.')]]
    out, _ = tidy.trim_cues(paras, LINKS)
    assert text(out[0]) == '(P) One. Two.'


def test_hook_must_name_the_title_or_a_script_line():
    title = 'POV : refusée pour un job de caissière avec un bac+5 🤡'
    hook = 'Affiche le texte « POV : refusée comme caissière avec un bac+5 🤡 ».'
    assert tidy.hook_fixes(hook, title, 'Non, je suis au chômage.') == [('POV : refusée comme caissière avec un bac+5 🤡', title)]
    assert tidy.hook_fixes('Dis « Refusé, refusé, refusé. »', title, 'Refusé, refusé, refusé. Imaginez') == []
    assert tidy.hook_fixes(f'Titre « {title} »', title, '') == []


def test_page_name_keeps_its_number():
    assert tidy.wanted_name('1. Carrefour vient de me refuser', 'POV : refusée') == '1. POV : refusée'
    assert tidy.wanted_name('Draft', 'Titre') == 'Titre'


def test_renderer_uses_the_same_cue_rule():
    spec = {'script': [{'cue': 'parakeet', 'text': f'S{i}.'} for i in range(6)]}
    paras = pages.script_paragraphs(spec, LINKS, 'fr')
    links = [x for p in paras for x in p['paragraph']['rich_text'] if tidy._url(x)]
    assert len(links) == 1  # one paragraph -> one cue


def test_judges_know_cues_are_sparse_and_localisation_is_allowed():
    import inspect
    from watcher import audit, crosscheck
    for src in (inspect.getsource(audit.check), inspect.getsource(crosscheck)):
        assert '{FEW_CUES}' in src and '{LOCALISE}' in src


def test_dates_are_part_of_the_localisation_rule():
    from watcher.brands import LOCALISE
    assert '12 October' in LOCALISE and 'timeless' in LOCALISE


def test_old_hand_written_page_is_left_alone():
    # 15 Oct 2026: an old page's first bold line ("Choisis une de ces phrases.") was taken as its title and the page renamed
    from unittest import mock
    blocks = [{'type': 'heading_3', 'heading_3': {'rich_text': [{'plain_text': '📲 TEXTE ÉCRIT'}]}},
              {'type': 'paragraph', 'paragraph': {'rich_text': [{'plain_text': 'Choisis une de ces phrases.'}]}}]
    script = [{'type': 'paragraph', 'paragraph': {'rich_text': [{'plain_text': 'Je viens de quitter mon poste en RH.'}]}}]
    with mock.patch.object(tidy.reword, 'script_blocks', return_value=script), \
            mock.patch.object(tidy.pages, 'children', return_value=blocks), \
            mock.patch.object(tidy.pages, 'api') as api:
        ch = tidy.tidy_page('pid', LINKS)
    assert ch and ch[0].startswith('old layout')
    api.assert_not_called()  # no rename, no edits


CUE = '(🎥 Demo – see resources)'
FOLDER = 'https://drive.google.com/drive/folders/F'


def test_demo_cue_is_plain_text_right_before_the_first_app_cue_once():
    paras = [[pages.rt('Hi. ')], cue('https://p') + [pages.rt('Upload. ')], cue('https://p') + [pages.rt('Score. ')]]
    out, changed = tidy.place_demo(paras, LINKS, CUE)
    assert changed
    assert text(out[0]) == 'Hi. '
    assert text(out[1]) == '(🎥 Demo – see resources) (Parakeet AI · Resume Maker) Upload. '
    assert text(out[2]) == '(Parakeet AI · Resume Maker) Score. '
    assert [tidy._url(x) for p in out for x in p if tidy._url(x)] == ['https://p', 'https://p']  # no Drive link
    assert tidy.place_demo(out, LINKS, CUE) == (out, False)  # already right: nothing to write
    trimmed, removed = tidy.trim_cues(out, LINKS)
    assert removed == 0 and trimmed == out
    assert pages.strip_directions(text(out[1])).startswith('(🎥 Demo')  # not taken for a stage direction


def test_old_linked_demo_cue_becomes_the_plain_cue():
    paras = [cue('https://p') + [pages.rt('Upload. ')] + cue(FOLDER, '🎥 Old') + [pages.rt('Score. (🎥 x) Again.')]]
    out, changed = tidy.place_demo(paras, LINKS, CUE)
    assert changed
    assert text(out[0]) == '(🎥 Demo – see resources) (Parakeet AI · Resume Maker) Upload. Score. Again.'
    assert not any(tidy._url(x) == FOLDER for x in out[0])


def test_cue_kept_after_a_megasheet_round_trip():
    out, _ = tidy.place_demo([cue('https://p') + [pages.rt('Upload.')]], LINKS, CUE)
    back = pages.md(pages.to_md(out[0]))  # Megasheet merges plain text pieces
    assert tidy.place_demo([back], LINKS, CUE)[1] is False


def test_no_app_cue_no_demo_cue():
    paras = [[pages.rt('Hi.')]]
    assert tidy.place_demo(paras, LINKS, CUE) == (paras, False)


def test_demo_folder_goes_into_the_resources_after_parakeet():
    rich = [pages.rt('Parakeet AI · Resume Maker', link='https://p'), pages.rt('\n'), pages.rt('Gmail', link='https://g'),
            pages.rt('\n'), pages.rt('- some line')]
    out, changed = tidy.place_demo_resource(rich, LINKS, '🎥 Demo', FOLDER)
    assert changed
    assert [(text([x]), tidy._url(x)) for x in out][:4] == [('Parakeet AI · Resume Maker', 'https://p'), ('\n', ''),
                                                            ('🎥 Demo', FOLDER), ('\n', '')]
    assert tidy.place_demo_resource(out, LINKS, '🎥 Demo', FOLDER) == (out, False)
    again, _ = tidy.place_demo_resource(out, LINKS, '🎥 New', FOLDER + 'X')  # repointed, still one
    assert sum(1 for x in again if tidy._url(x).startswith('https://drive.google.com/drive/folders/')) == 1
    assert text(again).count('\n\n') == 0


def test_demo_folder_in_empty_resources():
    out, _ = tidy.place_demo_resource([], LINKS, '🎥 Demo', FOLDER)
    assert [tidy._url(x) for x in out] == [FOLDER]


def test_demo_note_only_in_markets_with_recordings():
    from watcher.markets import TEXT
    assert pages.inspo_note('sl')[-1] == TEXT['sl']['demo_note']
    assert pages.inspo_note('sl', own=True)[-1] == TEXT['sl']['demo_note']
    assert len(pages.inspo_note('fr')) == 2 and len(pages.inspo_note('es')) == 2
