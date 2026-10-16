"""Markets (DACH / France / Spain / Slovenia): Notion pages, language texts and per-market data keys.

There is ONE shared format list (formats.json), fed by the creators of all markets. Every format has a page in
each market's language (DE/FR/ES/SL); all lists get the same order and the same "going viral" section, and each market gets
its own Discord announcement in its language.
"""
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

TEXT = {
    'de': {
        'flag': '🇩🇪', 'name': 'DACH', 'lang_name': 'German',
        'style': 'natural spoken German as a TikTok creator would say it (du-Form)',
        'video_heading': 'Inspirationsvideo', 'source': 'Original auf TikTok',
        # The first ~30 characters of 'inspo_note'[0] and 'inspo_note_same' tell "other language" and "same language"
        # apart (audit._note_is_same) - keep those starts as they are. 'inspo_note_own' (example = our own creator's video)
        # starts like 'inspo_note_same'.
        'inspo_note': [
            '**Wichtig:** Dreh dein Video nach dem Skript unten. Das Inspirationsvideo ist von einer anderen Marke und '
            'NICHT das Video, das du drehen sollst. Übernimm davon SO GENAU WIE MÖGLICH den Vibe, die Kamerawinkel, wie '
            'gefilmt wird, den Schnitt und die Momente, in denen die App gezeigt wird (Demo) – genau dafür sind '
            'Inspirationsvideos da.',
            'Im Video wird eine andere App genutzt. Mach alles genauso, nur mit Parakeet AI: Öffne Parakeet AI an den '
            'Stellen, an denen im Video diese App geöffnet wird, und zeig es genauso. Diese App darf in deinem Video '
            'nirgends zu sehen oder zu hören sein.'],
        'inspo_note_own': '**Wichtig:** Das Inspirationsvideo ist von einem unserer eigenen Creator (mit Parakeet AI) und '
                          'lief sehr gut – es ist trotzdem NICHT das Video, das du 1:1 kopieren sollst. Übernimm davon SO '
                          'GENAU WIE MÖGLICH den Vibe, die Kamerawinkel, wie gefilmt wird, den Schnitt und die Momente, in '
                          'denen Parakeet AI gezeigt wird (Demo). Dreh dein eigenes Video nach dem Skript unten.',
        'inspo_note_same': '**Wichtig:** Das Inspirationsvideo ist auf Deutsch und zeigt genau dieses Format, ist aber von '
                           'einer anderen Marke und NICHT das Video, das du drehen sollst. Übernimm davon SO GENAU WIE '
                           'MÖGLICH den Vibe, die Kamerawinkel, wie gefilmt wird, den Schnitt und die Momente, in denen die '
                           'App gezeigt wird (Demo) – genau dafür sind Inspirationsvideos da. Dreh dein eigenes Video nach '
                           'dem Skript unten.',
        'title_h': 'TITEL', 'script_h': '💬SKRIPT', 'hook_h': '🎬 VISUELLER HOOK', 'res_h': 'RESSOURCEN',
        'sub_voice': 'Automatische Untertitel', 'sub_silent': 'Musik aus der Plattform-Bibliothek, kein Voiceover',
        'silent_label': 'Texteinblendungen – nicht sprechen:',
        'cue_linkedin': 'LinkedIn-Jobsuche', 'asset_cue': '(📎 {name} – siehe Ressourcen) ', 'asset_todo': 'wird noch erstellt',
        'app_line': 'Sobald Parakeet AI ins Spiel kommt, filmst du dich selbst, wie du die App am Laptop nutzt – an jeder Stelle '
                    'mit Link im Skript. Ladezeiten schneidest du raus.',
        'linkedin_line': 'Beim LinkedIn-Link filmst du, wie du eine Stellenanzeige kopierst. ',
        'return_line': 'Für den letzten Satz wieder zurück in die Kamera.',
        'scores_line': 'X und Y im Skript: Lies die Punktzahl vor, die dir die App anzeigt.',
        'required_line': '🚨👇 Ein visueller Hook ist für jedes Video Pflicht!',
        'draft_prefix': 'ENTWURF – ',
        'list_heading': 'JETZT DREHEN: Diese Formate',
        'list_fire': ['Dreh die Formate der Reihe nach, von oben nach unten, und geh die ganze Liste durch. Halte dich an das '
                      'Skript, den visuellen Hook und die Ressourcen auf der jeweiligen Seite.',
                      '**Nur wenn ein Video über 100.000 Aufrufe bekommt**, drehst du dieses Format immer wieder neu – so lange, '
                      'wie es weiter viral geht. Danach machst du mit der Liste weiter.'],
        'visual_rule': '**Ein Visual Hook ist für jedes Video Pflicht!** Ideen findest du im ',
        'hot_prefix': 'GEHT GERADE VIRAL – DREH DAS JETZT ZUERST: ',
        'hot_suffix': '  ({n} Videos mit über 100.000 Aufrufen in den letzten 7 Tagen)',
        'holder': 'Alle Formatseiten',
        'discord': '@everyone 🔥 **Dieses Format geht gerade viral!**\n\n**{title}**\n\n{n} Videos mit über 100.000 '
                   'Aufrufen in den letzten 7 Tagen. 👉 Dreh es **jetzt als Nächstes**.\n\nDu findest es im Creator-Portal ganz '
                   'oben in deiner Formatliste – unter genau diesem Titel: <https://megasheet.app/portal/login>',
        'hot_header': 'Geht gerade viral – dreh das jetzt zuerst',
        'stopwords': 'der das und ist ich nicht ein eine zu mit auf für den dem es sie wir ihr mein dein was wie hab habe hat '
                     'sind auch noch dann so aber wenn schon mal einfach jetzt hier da',
    },
    'fr': {
        'flag': '🇫🇷', 'name': 'France', 'lang_name': 'French',
        'style': 'natural spoken French as a TikTok creator would say it (tutoiement)',
        'video_heading': 'Vidéo d’inspiration', 'source': 'Original sur TikTok',
        'inspo_note': [
            '**Important :** Tourne ta vidéo d’après le script ci-dessous. La vidéo d’inspiration vient d’une autre '
            'marque et ce n’est PAS la vidéo à faire. Reprends-en LE PLUS FIDÈLEMENT POSSIBLE l’ambiance (vibe), les '
            'angles de caméra, la façon de filmer, le montage et les moments où l’app est montrée (démo) – c’est à ça que '
            'servent les vidéos d’inspiration.',
            'Dans la vidéo, c’est une autre app qui est utilisée. Fais tout pareil, mais avec Parakeet AI : ouvre Parakeet '
            'AI aux moments où cette app est ouverte dans la vidéo et montre-le de la même façon. Cette app ne doit '
            'apparaître ni être entendue nulle part dans ta vidéo.'],
        'inspo_note_own': '**Important :** La vidéo d’inspiration vient d’un de nos créateurs (avec Parakeet AI) et a très '
                          'bien marché – mais ce n’est PAS une vidéo à recopier telle quelle. Reprends-en LE PLUS FIDÈLEMENT '
                          'POSSIBLE l’ambiance (vibe), les angles de caméra, la façon de filmer, le montage et les moments où '
                          'Parakeet AI est montré (démo). Tourne ta propre vidéo d’après le script ci-dessous.',
        'inspo_note_same': '**Important :** La vidéo d’inspiration est en français et montre exactement ce format, mais elle '
                           'vient d’une autre marque et ce n’est PAS la vidéo à faire. Reprends-en LE PLUS FIDÈLEMENT '
                           'POSSIBLE l’ambiance (vibe), les angles de caméra, la façon de filmer, le montage et les moments '
                           'où l’app est montrée (démo) – c’est à ça que servent les vidéos d’inspiration. Tourne ta propre '
                           'vidéo d’après le script ci-dessous.',
        'title_h': 'TITRE', 'script_h': '💬SCRIPT', 'hook_h': '🎬 ACCROCHE VISUELLE', 'res_h': 'RESSOURCES',
        'sub_voice': 'Sous-titres automatiques', 'sub_silent': 'Musique de la bibliothèque de la plateforme, sans voix off',
        'silent_label': 'Textes à l’écran – ne pas parler :',
        'cue_linkedin': 'Recherche d’emploi LinkedIn', 'asset_cue': '(📎 {name} – voir Ressources) ', 'asset_todo': 'à préparer',
        'app_line': 'Dès que Parakeet AI entre en jeu, filme-toi en train d’utiliser l’app sur ton ordinateur – à chaque lien '
                    'dans le script. Coupe les temps de chargement.',
        'linkedin_line': 'Au lien LinkedIn, filme-toi en train de copier une offre d’emploi. ',
        'return_line': 'Pour la dernière phrase, reviens face caméra.',
        'scores_line': 'X et Y dans le script : lis le score que l’app t’affiche.',
        'required_line': '🚨👇 Un visual hook est obligatoire sur chaque vidéo !',
        'draft_prefix': 'BROUILLON – ',
        'list_heading': 'À TOURNER MAINTENANT : ces formats',
        'list_fire': ['Tourne les formats dans l’ordre, de haut en bas, et fais toute la liste. Suis le script, l’accroche '
                      'visuelle et les ressources de chaque page.',
                      '**Seulement si une vidéo dépasse 100 000 vues**, tu refais ce format encore et encore – tant qu’il '
                      'continue à devenir viral. Ensuite, tu reprends la liste.'],
        'visual_rule': '**Un visual hook est obligatoire sur chaque vidéo !** Des idées dans le ',
        'hot_prefix': 'EN TRAIN DE DEVENIR VIRAL – TOURNE-LE EN PREMIER : ',
        'hot_suffix': '  ({n} vidéos à plus de 100 000 vues ces 7 derniers jours)',
        'holder': 'Tous les formats',
        'discord': '@everyone 🔥 **Ce format est en train de devenir viral !**\n\n**{title}**\n\n{n} vidéos à plus de '
                   '100 000 vues ces 7 derniers jours. 👉 Tourne-le **maintenant, en priorité**.\n\nTu le trouves dans le '
                   'portail créateur, tout en haut de ta liste de formats – sous ce titre exact : '
                   '<https://megasheet.app/portal/login>',
        'hot_header': 'En train de devenir viral – à tourner en premier',
        'stopwords': 'le la les et est je tu pas un une de des du pour avec sur que qui mon ton ce cette mais si on en au aux '
                     'il elle vous nous ça c’est',
    },
    'es': {
        'flag': '🇪🇸', 'name': 'España', 'lang_name': 'Spanish',
        'style': 'natural spoken Spanish from Spain as a TikTok creator would say it (tú)',
        'video_heading': 'Vídeo de inspiración', 'source': 'Original en TikTok',
        'inspo_note': [
            '**Importante:** Graba tu vídeo con el guion de abajo. El vídeo de inspiración es de otra marca y NO es el '
            'vídeo que tienes que hacer. Cópiale LO MÁS FIELMENTE POSIBLE el ambiente (vibe), los ángulos de cámara, '
            'cómo está grabado, el montaje y los momentos en que se enseña la app (demo) – para eso sirven los vídeos de '
            'inspiración.',
            'En el vídeo se usa otra app. Hazlo todo igual, pero con Parakeet AI: abre Parakeet AI en los momentos en que '
            'se abre esa app en el vídeo y enséñalo de la misma forma. Esa app no puede verse ni oírse en ningún momento '
            'de tu vídeo.'],
        'inspo_note_own': '**Importante:** El vídeo de inspiración es de uno de nuestros creadores (con Parakeet AI) y '
                          'funcionó muy bien, pero NO es un vídeo para copiar tal cual. Cópiale LO MÁS FIELMENTE POSIBLE el '
                          'ambiente (vibe), los ángulos de cámara, cómo está grabado, el montaje y los momentos en que se '
                          'enseña Parakeet AI (demo). Graba tu propio vídeo con el guion de abajo.',
        'inspo_note_same': '**Importante:** El vídeo de inspiración está en español y muestra exactamente este formato, '
                           'pero es de otra marca y NO es el vídeo que tienes que hacer. Cópiale LO MÁS FIELMENTE POSIBLE '
                           'el ambiente (vibe), los ángulos de cámara, cómo está grabado, el montaje y los momentos en que '
                           'se enseña la app (demo) – para eso sirven los vídeos de inspiración. Graba tu propio vídeo con '
                           'el guion de abajo.',
        'title_h': 'TÍTULO', 'script_h': '💬GUION', 'hook_h': '🎬 GANCHO VISUAL', 'res_h': 'RECURSOS',
        'sub_voice': 'Subtítulos automáticos', 'sub_silent': 'Música de la biblioteca de la plataforma, sin voz en off',
        'silent_label': 'Textos en pantalla – no hablar:',
        'cue_linkedin': 'Búsqueda de empleo en LinkedIn', 'asset_cue': '(📎 {name} – ver Recursos) ', 'asset_todo': 'por preparar',
        'app_line': 'En cuanto entre Parakeet AI, grábate usando la app en el portátil – en cada enlace del guion. Corta los '
                    'tiempos de carga.',
        'linkedin_line': 'En el enlace de LinkedIn, grábate copiando una oferta de empleo. ',
        'return_line': 'Para la última frase, vuelve a mirar a cámara.',
        'scores_line': 'X e Y en el guion: lee la puntuación que te muestra la app.',
        'required_line': '🚨👇 ¡Un visual hook es obligatorio en cada vídeo!',
        'draft_prefix': 'BORRADOR – ',
        'list_heading': 'GRABA AHORA: estos formatos',
        'list_fire': ['Graba los formatos en orden, de arriba abajo, y haz toda la lista. Sigue el guion, el gancho visual y '
                      'los recursos de cada página.',
                      '**Solo si un vídeo supera las 100.000 visualizaciones**, vuelves a grabar ese formato una y otra vez – '
                      'mientras siga haciéndose viral. Después, sigues con la lista.'],
        'visual_rule': '**¡Un visual hook es obligatorio en cada vídeo!** Ideas en el ',
        'hot_prefix': 'SE ESTÁ HACIENDO VIRAL – GRÁBALO PRIMERO: ',
        'hot_suffix': '  ({n} vídeos con más de 100.000 visualizaciones en los últimos 7 días)',
        'holder': 'Todos los formatos',
        'discord': '@everyone 🔥 **¡Este formato se está haciendo viral!**\n\n**{title}**\n\n{n} vídeos con más de '
                   '100.000 visualizaciones en los últimos 7 días. 👉 Grábalo **ahora, el siguiente**.\n\nLo tienes en el '
                   'portal de creadores, arriba del todo en tu lista de formatos – con este mismo título: '
                   '<https://megasheet.app/portal/login>',
        'hot_header': 'Se está haciendo viral – grábalo primero',
        'stopwords': 'el la los las y es yo tu tú no un una de del para con en que mi este esta pero si se lo al por me te '
                     'muy ya',
    },
    'sl': {
        'flag': '🇸🇮', 'name': 'Slovenija', 'lang_name': 'Slovenian',
        'style': 'natural spoken Slovenian as a TikTok creator would say it (tikanje)',
        'video_heading': 'Video za navdih', 'source': 'Original na TikToku',
        'inspo_note': [
            '**Pomembno:** Svoj video posnemi po spodnjem scenariju. Video za navdih je od druge znamke in NI video, ki ga '
            'moraš posneti. Od njega čim BOLJ NATANČNO prevzemi vzdušje (vibe), kote kamere, način snemanja, montažo in '
            'trenutke, ko je prikazana aplikacija (demo) – prav za to so videi za navdih.',
            'V videu je uporabljena druga aplikacija. Naredi vse enako, samo s Parakeet AI: odpri Parakeet AI v trenutkih, '
            'ko se v videu odpre ta aplikacija, in ga pokaži na enak način. Te aplikacije v tvojem videu ne sme biti nikjer '
            'videti ali slišati.'],
        'inspo_note_own': '**Pomembno:** Video za navdih zgoraj je od enega od naših ustvarjalcev (s Parakeet AI) in je '
                          'bil zelo uspešen – a vseeno NI video, ki ga kopiraš 1:1. Od njega čim BOLJ NATANČNO prevzemi vzdušje '
                          '(vibe), kote kamere, način snemanja, montažo in trenutke, ko je prikazan Parakeet AI (demo). Svoj '
                          'video posnemi po spodnjem scenariju.',
        'inspo_note_same': '**Pomembno:** Video za navdih zgoraj je v slovenščini in prikazuje točno ta format, vendar je od druge '
                           'znamke in NI video, ki ga moraš posneti. Od njega čim BOLJ NATANČNO prevzemi vzdušje (vibe), kote '
                           'kamere, način snemanja, montažo in trenutke, ko je prikazana aplikacija (demo) – prav za to so '
                           'videi za navdih. Svoj video posnemi po spodnjem scenariju.',
        'title_h': 'NASLOV', 'script_h': '💬SCENARIJ', 'hook_h': '🎬 VIZUALNI HOOK', 'res_h': 'VIRI',
        'sub_voice': 'Samodejni podnapisi', 'sub_silent': 'Glasba iz knjižnice platforme, brez glasu',
        'silent_label': 'Besedilo na zaslonu – ne govori:',
        'cue_linkedin': 'Iskanje zaposlitve na LinkedInu', 'asset_cue': '(📎 {name} – glej Viri) ', 'asset_todo': 'še v pripravi',
        'app_line': 'Ko pride na vrsto Parakeet AI, posnemi, kako uporabljaš aplikacijo na prenosniku – pri vsaki povezavi '
                    'v scenariju. Nalaganje izreži.',
        'linkedin_line': 'Pri povezavi do LinkedIna posnemi, kako kopiraš oglas za delo. ',
        'return_line': 'Za zadnji stavek se spet obrni v kamero.',
        'scores_line': 'X in Y v scenariju: preberi oceno, ki ti jo pokaže aplikacija.',
        'required_line': '🚨👇 Visual hook je obvezen v vsakem videu!',
        'draft_prefix': 'OSNUTEK – ',
        'list_heading': 'POSNEMI ZDAJ: te formate',
        'list_fire': ['Snemaj formate po vrsti, od zgoraj navzdol, in naredi celoten seznam. Drži se scenarija, vizualnega '
                      'hooka in virov na vsaki strani.',
                      '**Samo če video preseže 100.000 ogledov**, ta format posnameš znova in znova – dokler je še viralen. '
                      'Nato nadaljuješ s seznamom.'],
        'visual_rule': '**Visual hook je obvezen v vsakem videu!** Ideje najdeš v ',
        'hot_prefix': 'POSTAJA VIRALNO – POSNEMI NAJPREJ TO: ',
        'hot_suffix': '  ({n} videov z več kot 100.000 ogledi v zadnjih 7 dneh)',
        'holder': 'Vsi formati',
        'discord': '@everyone 🔥 **Ta format postaja viralen!**\n\n**{title}**\n\n{n} videov z več kot 100.000 ogledi v '
                   'zadnjih 7 dneh. 👉 Posnemi ga **zdaj, kot naslednjega**.\n\nNajdeš ga v portalu za ustvarjalce, čisto na '
                   'vrhu seznama formatov – pod točno tem naslovom: <https://megasheet.app/portal/login>',
        'hot_header': 'Postaja viralno – posnemi najprej',
        # Words Slovenian uses and Croatian/Serbian/Bosnian do not (discover.language must not take Balkan accounts).
        'stopwords': 'in ki sem tudi že zelo tega lahko kot zdaj če več službo zaposlitev delo iščeš dobiš',
    },
}


def fkey(m):
    """Field holding a video's format id for this market ('format' for DACH, for backwards compatibility)."""
    return 'format' if m == 'de' else f'format_{m}'


def jkey(m):
    return 'judged' if m == 'de' else f'judged_{m}'


def ckey(m):
    return 'format_checked' if m == 'de' else f'format_checked_{m}'


def formats_file(m):
    return 'formats.json' if m == 'de' else f'formats_{m}.json'


def load(cfg):
    """[{key, lang, list_page, holder_page, archive_page, visual_hook_lab, discord_env, T}] for the enabled markets."""
    out = []
    for key, m in cfg['markets'].items():
        if not m.get('enabled', True):
            continue
        out.append({'key': key, **m, 'T': TEXT[m['lang']]})
    return out


def for_format(mkts, fmt):
    """The markets a format belongs in: a market's `skip_formats` (config.json) keeps formats out of it for good - no
    page is built, listed or checked there (Slovenia: the study-app format 'hardest schools' - not a JobStep format).
    The format's own `off_markets` (lineup.apply, 16 Oct 2026: not among that market's best 12) keeps it out of those
    markets until a Monday clean-up puts it back."""
    fid = (fmt or {}).get('id')
    off = set((fmt or {}).get('off_markets') or ())
    return [mk for mk in mkts if fid not in (mk.get('skip_formats') or ()) and mk['key'] not in off]
