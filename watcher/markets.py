"""Markets (DACH / France / Spain): Notion pages, language texts and per-market data keys.

There is ONE shared format list (formats.json), fed by the creators of all markets. Every format has a page in
each market's language (DE/FR/ES); all lists get the same order and the same 🚀 hot section, and each market gets
its own Discord announcement in its language.
"""
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

TEXT = {
    'de': {
        'flag': '🇩🇪', 'name': 'DACH', 'lang_name': 'German',
        'style': 'casual spoken German like a real TikTok creator (du-Form, natural, not formal, not a literal translation)',
        'video_heading': 'Inspirationsvideo', 'source': 'Original auf TikTok',
        'inspo_note': [
            '**Wichtig:** Dreh dein Video nach dem deutschen Skript unten. Das Inspirationsvideo zeigt dir nur Tempo, Vibe, '
            'Licht und Kamerawinkel – und was du auf dem Bildschirm zeigst und wie du die App zeigst.',
            'Im Video wird JobStep genutzt. Mach es genau gleich, nur mit Parakeet AI: Zeig alles, was im Inspirationsvideo '
            'gezeigt wird – öffne Parakeet AI an den Stellen, an denen JobStep geöffnet wird, und zeig es genauso. JobStep darf '
            'in deinem Video nirgends zu sehen oder zu hören sein.'],
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
                   'Aufrufen in den letzten 7 Tagen. 👉 Dreh es **jetzt als Nächstes** – du findest es ganz oben in deiner '
                   'Formatliste im Creator-Portal: https://megasheet.app/portal/login',
        'hot_header': '🚀 GEHT GERADE VIRAL – DREH DIESE FORMATE JETZT ZUERST',
        'rest_header': 'Danach: alle weiteren Formate der Reihe nach',
        'stopwords': 'der das und ist ich nicht ein eine zu mit auf für den dem es sie wir ihr mein dein was wie hab habe hat '
                     'sind auch noch dann so aber wenn schon mal einfach jetzt hier da',
    },
    'fr': {
        'flag': '🇫🇷', 'name': 'France', 'lang_name': 'French',
        'style': 'casual spoken French like a real TikTok creator (tutoiement, natural, not formal, not a literal translation)',
        'video_heading': 'Vidéo d’inspiration', 'source': 'Original sur TikTok',
        'inspo_note': [
            '**Important :** Tourne ta vidéo d’après le script en français ci-dessous. La vidéo d’inspiration te montre '
            'seulement le rythme, l’ambiance, la lumière et les angles de caméra – ce que tu montres à l’écran et comment '
            'tu montres l’app.',
            'Dans la vidéo, c’est JobStep qui est utilisé. Fais exactement pareil, mais avec Parakeet AI : montre tout ce '
            'qui est montré dans la vidéo d’inspiration – ouvre Parakeet AI aux moments où JobStep est ouvert et montre-le '
            'de la même façon. JobStep ne doit apparaître ni être entendu nulle part dans ta vidéo.'],
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
                   '100 000 vues ces 7 derniers jours. 👉 Tourne-le **maintenant, en priorité** – tu le trouves tout en haut '
                   'de ta liste de formats dans le portail créateur : https://megasheet.app/portal/login',
        'hot_header': '🚀 EN TRAIN DE DEVENIR VIRAL – TOURNE CES FORMATS EN PREMIER',
        'rest_header': 'Ensuite : tous les autres formats dans l’ordre',
        'stopwords': 'le la les et est je tu pas un une de des du pour avec sur que qui mon ton ce cette mais si on en au aux '
                     'il elle vous nous ça c’est',
    },
    'es': {
        'flag': '🇪🇸', 'name': 'España', 'lang_name': 'Spanish',
        'style': 'casual spoken Spanish from Spain like a real TikTok creator (tú, natural, not formal, not a literal translation)',
        'video_heading': 'Vídeo de inspiración', 'source': 'Original en TikTok',
        'inspo_note': [
            '**Importante:** Graba tu vídeo con el guion en español de abajo. El vídeo de inspiración solo te muestra el '
            'ritmo, el ambiente, la luz y los ángulos de cámara – qué enseñas en pantalla y cómo enseñas la app.',
            'En el vídeo se usa JobStep. Hazlo exactamente igual, pero con Parakeet AI: enseña todo lo que se ve en el vídeo '
            'de inspiración – abre Parakeet AI en los momentos en que se abre JobStep y enséñalo de la misma forma. JobStep no '
            'puede verse ni oírse en ningún momento de tu vídeo.'],
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
                   '100.000 visualizaciones en los últimos 7 días. 👉 Grábalo **ahora, el siguiente** – lo tienes arriba del '
                   'todo en tu lista de formatos del portal de creadores: https://megasheet.app/portal/login',
        'hot_header': '🚀 SE ESTÁN HACIENDO VIRALES – GRABA ESTOS FORMATOS PRIMERO',
        'rest_header': 'Después: todos los demás formatos en orden',
        'stopwords': 'el la los las y es yo tu tú no un una de del para con en que mi este esta pero si se lo al por me te '
                     'muy ya',
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
