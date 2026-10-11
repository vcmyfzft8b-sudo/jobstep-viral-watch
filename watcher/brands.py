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

# User's decision (11 Oct 2026): a script has NO stage directions / acting tips in brackets.
NO_DIRECTIONS = ("Scripts have NO stage directions or acting/filming tips in brackets (by design): only the spoken words "
                 "(or the on-screen texts of a silent video) plus the link cues where the app, LinkedIn or a material is "
                 "shown. How to film, act and edit comes from the example video, which creators copy as closely as "
                 "possible, and from the visual hook section. Never ask for stage directions and never fail a page because "
                 "it has none.")
