from watcher import notion, tidy

LINKS = {'parakeet': 'https://p', 'linkedin': 'https://l'}


def cue(url, label='Parakeet AI · Resume Maker'):
    return [notion.rt('('), notion.rt(label, link=url), notion.rt(') ')]


def text(items):
    return ''.join(x['text']['content'] for x in items)


def test_one_cue_per_paragraph_and_at_most_three():
    paras = [cue('https://p') + [notion.rt('Upload. ')] + cue('https://p') + [notion.rt('Score. ')],
             cue('https://p') + [notion.rt('A. ')], cue('https://p') + [notion.rt('B. ')],
             cue('https://p') + [notion.rt('C. ')]]
    out, removed = tidy.trim_cues(paras, LINKS)
    assert removed == 2  # the 2nd cue of paragraph 1 and the 4th Parakeet AI cue
    assert text(out[0]) == '(Parakeet AI · Resume Maker) Upload. Score. '
    assert text(out[3]) == 'C. '  # the 4th Parakeet AI cue is dropped
    assert sum(1 for p in out for x in p if tidy._url(x)) == 3


def test_linkedin_and_parakeet_cues_both_stay_in_one_paragraph():
    out, removed = tidy.trim_cues([cue('https://l', 'LinkedIn') + [notion.rt('Copy. ')] + cue('https://p') +
                                   [notion.rt('Paste. ')]], LINKS)
    assert removed == 0


def test_merged_brackets_are_removed_too():
    paras = [[notion.rt('('), notion.rt('P', link='https://p'), notion.rt(') One. ('), notion.rt('P', link='https://p'),
              notion.rt(') Two.')]]
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
    paras = notion.script_paragraphs(spec, LINKS, 'fr')
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
            mock.patch.object(tidy.notion, 'children', return_value=blocks), \
            mock.patch.object(tidy.notion, 'api') as api:
        ch = tidy.tidy_page('pid', LINKS)
    assert ch and ch[0].startswith('old layout')
    api.assert_not_called()  # no rename, no edits
