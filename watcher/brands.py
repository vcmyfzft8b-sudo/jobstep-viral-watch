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
