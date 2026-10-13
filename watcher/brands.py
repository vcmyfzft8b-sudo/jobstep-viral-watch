"""The app name that must be replaced in a source video: JobStep (incl. speech-to-text mishearings) - or another app
whose format was added by hand (config.json "other_apps", e.g. Studyflash). Counting both keeps the brand rule
(Parakeet AI exactly where the original names the app) right for hand-added formats too."""
import json
import os
import re

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.json')) as _f:
    OTHER_APPS = json.load(_f).get('other_apps', {})

SOURCE_RE = re.compile('|'.join([r'job\s*-?\s*st[ae]p|jopstep|jobset|jobster|job stay|jobs beget']
                                + list(OTHER_APPS.values())), re.I)
OTHER_NOTE = (f" Some originals promote another app instead of JobStep ({', '.join(OTHER_APPS)}): treat that app exactly "
              "like JobStep - Parakeet AI replaces it at the same spots and as often, and it must never appear."
              if OTHER_APPS else '')

# User's decision (13 Oct 2026): word for word, but in the MARKET's language variant, with its job sites, and nothing
# only the original creator could say about themself.
LOCALISE = ("Localisation that is required, not rewording: (1) the market's own variant of the language - an original "
            "in Latin-American Spanish becomes Spain Spanish (no 'ahorita', 'chamba', 'la neta', 'recién', '¡éxitos!', "
            "'okay', 'laboral' as filler; Spain says 'curro/trabajo', 'vale', 'ahora mismo', 'presentarse a una oferta', "
            "'¡suerte!'), Canadian/Belgian/Swiss French becomes France French; (2) job sites, companies and places of "
            "the market (Spain: InfoJobs, LinkedIn, Indeed; France: France Travail, Welcome to the Jungle, Indeed, "
            "LinkedIn - never Bumeran, Computrabajo, OCC); (3) a detail only the original creator can say about "
            "themself (their industry such as 'finance', an exact salary, a 'six-figure' job) becomes neutral words "
            "any creator can say; (4) a calendar date or month of the original ('12 October', 'October is the best "
            "month') is left out or made timeless ('now'), so the script never gets out of date. Change only those "
            "words.")

# User's decision (13 Oct 2026, tidy.MAX_CUES): few link cues, so scripts stay readable while filming.
FEW_CUES = ("Link cues are sparse by design: a cue marks where the app (or LinkedIn) first comes on screen in a paragraph "
            "and it stays on screen for the rest of that paragraph; a script has at most 3 Parakeet AI cues. Never fail "
            "or change a page because a later app moment in the same paragraph has no cue of its own.")

# User's decision (11 Oct 2026): a script has NO stage directions / acting tips in brackets.
NO_DIRECTIONS = ("Scripts have NO stage directions or acting/filming tips in brackets (by design): only the spoken words "
                 "(or the on-screen texts of a silent video) plus the link cues where the app, LinkedIn or a material is "
                 "shown. How to film, act and edit comes from the example video, which creators copy as closely as "
                 "possible, and from the visual hook section. Never ask for stage directions and never fail a page because "
                 "it has none.")
