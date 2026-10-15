"""The speaker of the original stays the speaker (15 Oct 2026: "Ich hab grad meinen Job im HR gekündigt" became
"Quelqu'un vient de quitter son job aux RH" on the French page)."""
from watcher import align, builder
from watcher.brands import LOCALISE, SPEAKER_PROBLEM, speaker_changed

ORIG = 'Ich hab grad meinen Job im HR gekündigt, also verrat ich euch jetzt alle ihre Geheimnisse. Der Grund ist simpel.'


def test_someone_instead_of_i_is_caught():
    assert speaker_changed(ORIG, "Quelqu'un vient de quitter son job aux RH, alors je vais te balancer tous leurs secrets.")
    assert speaker_changed(ORIG, '‼️Quelqu’un vient de quitter son job aux RH🤫‼️')
    assert speaker_changed(ORIG, 'Alguien acaba de dejar Recursos Humanos. Os cuento todo.')
    assert speaker_changed('I just quit my job in HR.', 'A friend just quit her job in HR.')


def test_the_same_speaker_is_fine():
    assert not speaker_changed(ORIG, 'Acabo de dejar mi trabajo en Recursos Humanos, así que os voy a contar sus secretos.')
    assert not speaker_changed(ORIG, "Je viens de quitter mon poste aux RH, donc je vous balance tous leurs secrets.")
    # the original itself talks about someone else
    assert not speaker_changed('Eine Freundin hat mir erzählt, dass HR keine Lebensläufe liest.',
                               'Une amie m’a raconté que les RH ne lisent pas les CV.')
    assert not speaker_changed(ORIG, '')


def test_writers_and_judges_are_told():
    assert 'WHO speaks never changes' in LOCALISE and 'title' in LOCALISE


def test_builder_rejects_a_changed_speaker():
    spec = {'page_title': 't', 'visual_hook_first': 'Copie le début.', 'title_hook': '‼️Quelqu’un vient de quitter les RH‼️',
            'script': [{'cue': 'parakeet', 'text': "Je viens de quitter mon poste aux RH, donc je vous dis tout et vous "
                                                   "allez voir que le CV est le problème avec les filtres ATS de la plupart "
                                                   "des entreprises en ce moment."}]}
    probs = builder.validate(spec, {'text': ORIG, 'language': 'de'}, lang='fr')
    assert SPEAKER_PROBLEM in probs  # the title alone is enough
    spec['title_hook'] = '‼️J’ai quitté les RH, je vous dis tout‼️'
    assert SPEAKER_PROBLEM not in builder.validate(spec, {'text': ORIG, 'language': 'de'}, lang='fr')


def test_align_rejects_a_changed_speaker():
    spec = {'script': [{'cue': 'parakeet', 'text': "Quelqu'un vient de quitter son job aux RH, alors je vais te "
                                                   "balancer tous leurs secrets. Parakeet AI"}]}
    src = ORIG + ' Parakeet AI'
    n = len(src.split())
    assert align._validate(spec, n, source=src, translated=True) == SPEAKER_PROBLEM
