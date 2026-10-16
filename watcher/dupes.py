"""The same format twice on a list (user, 16 Oct 2026: "these 2 are the same - fix it and make sure it doesn't happen
again"). X16 and A202610061332 had come out of two JobStep videos with the same hook ("I quit my HR job, now I'll tell
you all their secrets") and ended up with near-identical titles in every language.

- similar(): two page titles say the same thing (number, emojis and punctuation ignored; difflib ratio >= THRESHOLD).
- find(): live formats whose pages in one market have near-identical titles.
- lineup.merge_duplicates() keeps the one with the better score and archives the other as "duplicate of <kept>"
  (main.resolve follows that, so its future videos count for the kept format); its videos count for the kept one.
  Every Monday before the clean-up and with mode dedupe.
- gate.check holds a new / revived format whose title is near-identical to a live one in the same market.
- verify reports such pairs.
"""
import difflib
import re

THRESHOLD = 0.75


def norm(t):
    t = re.sub(r'^\s*\d+\.\s*', '', t or '')  # list number "4. "
    t = re.sub(r'[^\w\s]', ' ', t.lower())
    return ' '.join(t.split())


def similar(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and difflib.SequenceMatcher(None, a, b).ratio() >= THRESHOLD


def page_title(page_id):
    from .verify import _title
    return _title(page_id)


def titles(formats, mkts, page_of, title=page_title):
    """{market: {format_id: page title}} of the live formats in each market."""
    from .markets import for_format
    out = {}
    for mk in mkts:
        for f in formats:
            if f.get('status') != 'active' or not for_format([mk], f) or not page_of(f, mk['key']):
                continue
            try:
                out.setdefault(mk['key'], {})[f['id']] = title(page_of(f, mk['key']))
            except Exception as e:
                print('dupes: title unreadable', mk['key'], f['id'], str(e)[:100])
    return out


def find(formats, mkts, page_of, title=page_title, by_market=None):
    """[(format_id_a, format_id_b, market, title_a, title_b)] - pairs of live formats with near-identical titles."""
    by_market = by_market if by_market is not None else titles(formats, mkts, page_of, title)
    pairs, seen = [], set()
    for m, ts in by_market.items():
        ids = sorted(ts)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if (a, b) not in seen and similar(ts[a], ts[b]):
                    seen.add((a, b))
                    pairs.append((a, b, m, ts[a], ts[b]))
    return pairs


def clash(fmt, formats, mkts, page_of, title=page_title):
    """Reasons a new / revived format would put the same title twice on a list ([] = none)."""
    out = []
    by_market = titles(formats, mkts, page_of, title)
    from .markets import for_format
    for mk in for_format(mkts, fmt):
        pid = page_of(fmt, mk['key'])
        if not pid:
            continue
        try:
            mine = title(pid)
        except Exception:
            continue
        for fid, t in (by_market.get(mk['key']) or {}).items():
            if fid != fmt['id'] and similar(mine, t):
                out.append(f"{mk['T']['flag']} same title as the live format {fid} (\"{norm(t)[:60]}\") - a duplicate")
    return out
