"""Cross-country check: the three countries of a format compared TOGETHER against its reference definition.

The page audit (audit.py) checks each page against its own example. This module checks the GROUP: for every format
there is a reference definition (registry/format_references.json: hook, premise, ordered beats, filming and
demonstration sequence, product introduction / spoken brand / CTA, allowed localisation differences). Each
country's actual example video (transcript + on-screen text) and script are compared against that definition and
against each other. A similar topic alone never makes two videos the same format.

Results are reported per dimension and country, separately:
  format_consistency      - example + script follow the reference (same hook, beats, order, demo, product timing)
  script_matches_example  - the script tells what the example shows
  independent_wording     - wording is independently written (not translated sentences with the brand swapped)
  features_claims         - only real Parakeet AI features, no invented testimonials / guaranteed ATS or hiring
  directions_match        - filming directions match the script
  approval                - approval-lock status (preserved / changed / not locked) - NEVER part of 'passed'

A group result is cached under a key built from all three pages' content fingerprints, their example source IDs and
uploaded-video identities, the reference definition and AUDIT_VERSION. Any change to one of these invalidates it.
Missing evidence (no page, unreadable example, no reference) makes the group 'unverified' - never a pass.
Duplicate references (the same source video ID or uploaded video under different format IDs) are flagged for
review; nothing is deleted.
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

from . import align, audit, llm, localize, notion, reword
from .builder import PARAKEET_FACTS
from .markets import TEXT

AUDIT_VERSION = 'group-2026-10-08.1'
REFERENCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'format_references.json')
DIMENSIONS = ('format_consistency', 'script_matches_example', 'independent_wording', 'features_claims',
              'directions_match')


def references():
    """Reviewed definitions from the repository; formats without one (new or revived) use the definition generated from
    their source video (state/format_references.json). A reviewed definition always wins."""
    from . import state
    try:
        with open(REFERENCES) as f:
            reviewed = json.load(f).get('formats', {})
    except FileNotFoundError:
        reviewed = {}
    return {**state.load('format_references.json', {}), **reviewed}


def ensure_reference(fmt, page_of, cfg):
    """A format without a reference definition (a new viral format, or one revived from the archive) gets one built
    from its source video. Returns the reference or None (then the group stays unverified and is tried again)."""
    from . import state
    ref = reference(fmt['id'])
    if ref:
        return ref
    url = fmt.get('source_video') or (fmt.get('revived') or {}).get('because')
    pid = page_of(fmt, 'de')
    if not url and pid:
        url = (localize.current_source(pid) or {}).get('url')
    vid = source_id(url)
    if not vid:
        return None
    example = localize.example_text(url)
    if not example:
        return None
    prompt = f"""A JobStep TikTok video defines a UGC format we adapt for Parakeet AI in Germany, France and Spain.
Format: {fmt.get('title', '')} - {fmt.get('description', '')[:600]}
VIDEO ({url}):
{example[:4000]}

{PARAKEET_FACTS}

Write the format's reference definition that all three countries must follow. Return JSON {{"title_en": "", "hook": "",
"premise": "", "beats": ["<beat 1>", "..."], "filming": "<length, shots, demo sequence>",
"product": {{"introduced_at_beat": <number>, "spoken_brand": "<where the brand/URL is said, or 'not spoken'>",
"cta": "<the call to action, or 'none'>", "features_used": ["<only real Parakeet AI features>"]}},
"allowed_localisation": ["<what may differ per country>"], "not_allowed": ["<what would make it another format,
and claims we must not make>"]}}"""
    try:
        r = llm.chat_json(cfg['models']['build'], 'You define UGC video formats precisely. Reply with JSON only.', prompt,
                          timeout=900)
    except Exception:
        return None
    if not (isinstance(r.get('beats'), list) and r['beats'] and r.get('hook') and isinstance(r.get('product'), dict)):
        return None
    ref = {**r, 'canonical_source': vid, 'accepted_sources': [vid], 'rejected_sources': {}, 'source_urls': {vid: url},
           'generated': int(time.time())}
    with state.LOCK:
        generated = state.load('format_references.json', {})
        generated[fmt['id']] = ref
        state.save('format_references.json', generated)
    return ref


def reference(fid):
    return references().get(fid)


def source_id(url):
    m = re.search(r'/video/(\d+)', url or '')
    return m.group(1) if m else None


def video_identity(page_id, cache=None):
    """SHA-256 of the uploaded example video's bytes (the same video uploaded twice has different Notion paths, so
    the path alone cannot find duplicates). Cached per Notion file path in meta['video_hashes']."""
    import requests
    cache = {} if cache is None else cache
    for b in notion.children(page_id):
        if b['type'] != 'video':
            continue
        data = b['video']
        f = data.get('file') or data.get('external') or {}
        url = f.get('url') or ''
        path = urlsplit(url).path or b['id']
        if path in cache:
            return cache[path]
        if not url:
            return None
        try:
            h = hashlib.sha256()
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 16):
                    h.update(chunk)
            cache[path] = 'sha256:' + h.hexdigest()
        except Exception:
            return None  # unknown identity: the group can't be confirmed as duplicate-free
        return cache[path]
    return None


def page_inputs(fmt, mkts, page_of, meta=None):
    """What a group result depends on, per market (None for a missing page)."""
    out = {}
    for mk in mkts:
        pid = page_of(fmt, mk['key'])
        if not pid:
            out[mk['key']] = None
            continue
        src = localize.current_source(pid)
        url = src['url'] if src else None
        out[mk['key']] = {'page_id': pid, 'fingerprint': audit.fingerprint(pid), 'url': url,
                          'source_id': source_id(url),
                          'video_identity': video_identity(pid, (meta or {}).setdefault('video_hashes', {}))}
    return out


def group_key(fid, inputs, ref):
    payload = {'version': AUDIT_VERSION, 'format': fid, 'reference': ref,
               'pages': {m: (None if x is None else {k: x[k] for k in ('fingerprint', 'source_id', 'video_identity')})
                         for m, x in sorted(inputs.items())}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def duplicates(groups):
    """groups: {format_id: inputs}. Returns [{'kind', 'value', 'formats', 'pages'}] for IDs used by >1 format."""
    seen = {}
    for fid, inputs in groups.items():
        for m, x in inputs.items():
            if not x:
                continue
            for kind in ('source_id', 'video_identity'):
                if x.get(kind):
                    seen.setdefault((kind, x[kind]), []).append((fid, m))
    out = []
    for (kind, value), uses in sorted(seen.items()):
        fids = sorted({f for f, _ in uses})
        if len(fids) > 1:
            out.append({'kind': kind, 'value': value, 'formats': fids, 'pages': [f'{f}:{m}' for f, m in uses]})
    return out


def approval_status(fmt, mkts, page_of, links):
    """Separate from quality: is approved wording locked, and is it preserved on the live page?"""
    out = {}
    for mk in mkts:
        locked = align.approved_script(fmt['id'], mk['lang'])
        pid = page_of(fmt, mk['key'])
        if not locked:
            out[mk['key']] = 'not_locked'
        elif pid and align.matches_approved(pid, mk['lang'], links, locked):
            out[mk['key']] = 'locked_preserved'
        else:
            out[mk['key']] = 'locked_changed'
    return out


def _evidence(fmt, mk, inp):
    pid = inp['page_id']
    example = localize.example_text(inp['url'], page_id=pid) if inp['url'] else ''
    blocks = reword.script_blocks(pid)
    script = reword.spoken_text(blocks)
    marked = '\n'.join(cue_text(b) for b in blocks)
    directions = '\n'.join(reword._plain(b) for b in reword.direction_blocks(pid))
    return {'example': example, 'script': script, 'marked': marked, 'directions': directions, 'title': page_title(pid),
            'source_id': inp['source_id']}


def _title_block(page_id):
    blocks = notion.children(page_id)
    i = next((k for k, b in enumerate(blocks) if b['type'].startswith('heading') and '📲' in reword._plain(b)), None)
    if i is None:
        return None
    return next((b for b in blocks[i + 1:i + 3] if b['type'] == 'paragraph' and reword._plain(b).strip()), None)


def page_title(page_id):
    """The on-screen title creators put on the video (📲 section)."""
    b = _title_block(page_id)
    return reword._plain(b).strip() if b else ''


def set_title(page_id, text):
    b = _title_block(page_id)
    if not b or reword._plain(b).strip() == text.strip():
        return False
    notion.api('PATCH', f"/blocks/{b['id']}", {b['type']: {'rich_text': [notion.rt(text, bold=True)]}})
    return True


def cue_text(b):
    """Script line as the creator sees it: link labels are filming cues ("show the app here"), not spoken words."""
    out = []
    for x in b[b['type']].get('rich_text', []):
        t = x.get('plain_text', x.get('text', {}).get('content', ''))
        out.append(f'[CUE: {t.strip()}]' if ((x.get('text') or {}).get('link') or {}).get('url') else t)
    return ''.join(out)


def _deterministic(ref, inputs):
    """Hard facts that need no model: a country whose example is a rejected source is a material mismatch."""
    issues = {}
    for m, x in inputs.items():
        if x and x['source_id'] in (ref.get('rejected_sources') or {}):
            issues[m] = f"example {x['source_id']} is a different story: {ref['rejected_sources'][x['source_id']]}"
    return issues


def judge(fmt, ref, evidence, model):
    blocks = []
    for m, ev in evidence.items():
        blocks.append(f"=== COUNTRY {m.upper()} ({TEXT[m]['lang_name']}) ===\n"
                      f"EXAMPLE VIDEO {ev['source_id']}:\n{ev['example'][:3500]}\n\n"
                      f"OUR SCRIPT (spoken/on-screen text only):\n{ev['script'][:3500]}\n\n"
                      f"THE SAME SCRIPT WITH ITS FILMING CUES ([CUE: ...] = a link marker telling the creator to show "
                      f"the app/asset there, NOT spoken; (...) = stage direction):\n{ev.get('marked', '')[:4000]}\n\n"
                      f"OUR FILMING DIRECTIONS:\n{ev['directions'][:4000]}\n\n"
                      f"OUR ON-SCREEN TITLE: {ev.get('title', '')}")
    prompt = f"""REFERENCE DEFINITION of format {fmt['id']} ("{fmt.get('title', '')}"):
{json.dumps(ref, ensure_ascii=False, indent=1)}

{PARAKEET_FACTS}

Below are the three countries' pages of this format. Compare them TOGETHER against the reference and against each
other. Be strict:
- format_consistency: does this country's example video AND script follow the reference - same hook idea and premise,
  the same beats in the same order, the same filming/demonstration sequence, the product introduced at the same beat,
  the brand/URL spoken only where the reference says so, the same CTA? Only the listed allowed localisation
  differences may differ. A similar topic (CV, ATS, job search) alone is NOT the same format.
- script_matches_example: does the script tell what this country's example shows (beats, order, product timing)?
- independent_wording: is the script independently written? FAIL if most sentences are translations or light
  rewrites of the example's sentences with the brand swapped. Same beats are expected; same sentences are not.
- features_claims (script AND on-screen title): only real Parakeet AI features; X/Y score placeholders kept; no invented testimonials, no
  guaranteed ATS passage, no guaranteed interviews/jobs.
- directions_match: do the filming directions match the script (no quotes of lines that are not in the script, no
  contradictions, no features Parakeet AI lacks) and cover the reference's filming/demonstration sequence? Cue
  markers the directions refer to are the [CUE: ...] markers. The brand counts as spoken only where it is in the
  spoken text; a [CUE: ...] marker shows it on screen.

{chr(10).join(blocks)}

Never put the character " inside an issue text (write ' or « » instead) - the answer must be valid JSON.
If a country's on-screen title makes a claim we can't make (an invented number of interviews, a time promise, a
guaranteed result), put a fixed title for it in "titles" (same language and style, same hook idea), else leave it out.
Return JSON {{"titles": {{"<country>": "<fixed title>"}}, "results": {{"<dimension>": {{"<country>": {{"pass": true, "issue": "<short, empty if pass>"}}}}}},
"summary": "<one sentence>"}} with every dimension {list(DIMENSIONS)} for every country {sorted(evidence)}."""
    for attempt in range(3):  # an unreadable answer is asked again, never guessed
        try:
            r = llm.chat_json(model, 'You are a strict QA reviewer for UGC creator formats across countries. Reply with '
                              'JSON only (valid JSON: escape quotes inside strings).', prompt, timeout=1500)
        except ValueError as e:  # includes json.JSONDecodeError
            err = e
            continue
        results = r.get('results') or {}
        if all(isinstance((results.get(d) or {}).get(m), dict) for d in DIMENSIONS for m in evidence):
            titles = {m: t for m, t in (r.get('titles') or {}).items() if m in evidence and isinstance(t, str) and t.strip()}
            return results, r.get('summary', ''), titles
        err = ValueError('incomplete review answer')
    raise err


def check_group(fmt, mkts, cfg, page_of, meta, dup_list=None, force=False):
    """Returns the group result (also cached in meta['group_audit'][format_id])."""
    store = meta.setdefault('group_audit', {})
    ref = reference(fmt['id']) or ensure_reference(fmt, page_of, cfg)
    inputs = page_inputs(fmt, mkts, page_of, meta)
    approval = approval_status(fmt, mkts, page_of, cfg['links'])
    dups = [d for d in (dup_list or []) if fmt['id'] in d['formats']]
    summary_inputs = {m: (None if x is None else {'source_id': x['source_id'], 'video_identity': x['video_identity']})
                      for m, x in inputs.items()}
    if dup_list is None:
        dups = [d for d in known_duplicates(fmt['id'], summary_inputs, meta) if fmt['id'] in d['formats']]
    base = {'version': AUDIT_VERSION, 'checked_at': int(time.time()), 'approval': approval, 'duplicates': dups,
            'inputs': summary_inputs}
    if not ref:
        res = {**base, 'status': 'unverified', 'passed': False, 'reasons': ['no reference definition for this format']}
        store[fmt['id']] = {**res, 'key': None}
        return res
    key = group_key(fmt['id'], inputs, ref)
    cached = store.get(fmt['id'])
    if not force and cached and cached.get('key') == key and cached.get('status') in ('pass', 'fail'):
        return {**cached, 'duplicates': dups, 'cached': True}
    reasons = []
    missing = [m for m, x in inputs.items() if not x]
    if missing:
        reasons.append('missing page: ' + ', '.join(missing))
    hard = _deterministic(ref, inputs)
    evidence = {}
    for mk in mkts:
        x = inputs[mk['key']]
        if not x:
            continue
        ev = _evidence(fmt, mk, x)
        if not ev['example']:
            reasons.append(f"{mk['key']}: example video could not be read (no evidence)")
        if not x.get('video_identity'):
            reasons.append(f"{mk['key']}: uploaded example video could not be fingerprinted (no evidence)")
        evidence[mk['key']] = ev
    if missing or any('no evidence' in r for r in reasons):
        res = {**base, 'status': 'unverified', 'passed': False, 'reasons': reasons, 'deterministic': hard}
        store[fmt['id']] = {**res, 'key': key}
        return res
    try:
        results, summary, titles = judge(fmt, ref, evidence, cfg['models']['build'])
    except Exception as e:  # no verdict -> unverified (stays in staging), and checked again next time (no cache key)
        res = {**base, 'status': 'unverified', 'passed': False, 'deterministic': hard,
               'reasons': reasons + [f'reviewer failed: {str(e)[:160]}']}
        store[fmt['id']] = {**res, 'key': None}
        return res
    for m, issue in hard.items():  # a rejected source is a mismatch whatever the model says
        results.setdefault('format_consistency', {})[m] = {'pass': False, 'issue': issue}
    complete = all(isinstance((results.get(d) or {}).get(m), dict) for d in DIMENSIONS for m in inputs)
    failed = [(d, m, results[d][m].get('issue', '')) for d in DIMENSIONS for m in inputs
              if complete and not results[d][m].get('pass')]
    if not complete:
        reasons.append('incomplete review answer')
    reasons += [f'{d} {m}: {i}' for d, m, i in failed]
    if dups:
        reasons += [f"possible duplicate ({d['kind']} {d['value']}) shared with {', '.join(x for x in d['formats'] if x != fmt['id'])}"
                    for d in dups]
    status = 'unverified' if not complete else ('pass' if not failed and not dups else 'fail')
    res = {**base, 'status': status, 'passed': status == 'pass', 'reasons': reasons, 'results': results,
           'summary': summary, 'deterministic': hard, 'title_fixes': titles}
    store[fmt['id']] = {**res, 'key': key}
    return res


def run(fmts, mkts, cfg, page_of, meta, force=False):
    """All active (and pending) formats; returns {format_id: result} plus the duplicate list."""
    groups = {f['id']: page_inputs(f, mkts, page_of, meta) for f in fmts if f.get('status') in ('active', 'pending')}
    dups = duplicates(groups)
    meta['group_duplicates'] = dups
    out = {}
    for f in [f for f in fmts if f['id'] in groups]:
        try:
            out[f['id']] = check_group(f, mkts, cfg, page_of, meta, dups, force=force)
        except Exception as e:
            out[f['id']] = {'status': 'unverified', 'passed': False, 'reasons': [f'error: {str(e)[:200]}']}
    return out, dups


def report(results, dups, fmts):
    """Plain text report with the six result types kept separate."""
    by = {f['id']: f.get('title', f['id']) for f in fmts}
    lines = []
    for dim in DIMENSIONS:
        ok = sum(1 for r in results.values() for m, x in ((r.get('results') or {}).get(dim) or {}).items() if x.get('pass'))
        total = sum(len((r.get('results') or {}).get(dim) or {}) for r in results.values())
        lines.append(f'{dim}: {ok}/{total} pages pass')
    appr = [s for r in results.values() for s in (r.get('approval') or {}).values()]
    lines.append(f"approval locks: {appr.count('locked_preserved')} preserved, {appr.count('locked_changed')} changed, "
                 f"{appr.count('not_locked')} not locked")
    lines.append(f"groups: {sum(r['status'] == 'pass' for r in results.values())} pass, "
                 f"{sum(r['status'] == 'fail' for r in results.values())} fail, "
                 f"{sum(r['status'] == 'unverified' for r in results.values())} unverified")
    for fid, r in results.items():
        if r['status'] != 'pass':
            lines.append(f"- {by.get(fid, fid)} [{r['status']}]: " + '; '.join(r.get('reasons', []))[:400])
    for d in dups:
        lines.append(f"- duplicate {d['kind']} {d['value']}: {', '.join(d['pages'])} (review, nothing deleted)")
    return '\n'.join(lines)


def known_duplicates(fid, inputs, meta):
    """Gate: compare one format's pages with the stored inputs of every other format (no full re-scan needed)."""
    groups = {k: v.get('inputs') or {} for k, v in meta.get('group_audit', {}).items() if k != fid}
    groups[fid] = inputs
    return duplicates(groups)


def blocked_sources(fid, meta):
    """Videos that must never become this format's example: rejected in the reference definition, or rejected by an
    earlier cross-country check (so the Monday language search can't put a wrong-story video back)."""
    ref = reference(fid) or {}
    return set(ref.get('rejected_sources') or {}) | set((meta or {}).get('group_rejected', {}).get(fid, []))


def source_url(ref, vid):
    return (ref.get('source_urls') or {}).get(vid)


def default_put_example(fmt, m, pid, lang, url):
    from . import discover
    same = discover.language(localize._handle(url)) == lang
    audit._put_example(fmt, m, pid, lang, url, same_lang=same)


def group_cycle(fmt, mkts, cfg, page_of, meta, put_example=None):
    """Check the group; if it fails, repair what may be repaired automatically and check again (once).
    Returns (result, changed, awaiting_approval)."""
    res = check_group(fmt, mkts, cfg, page_of, meta)
    if res['status'] != 'fail' and not res.get('title_fixes'):
        return res, [], []
    changed, awaiting = fix_group(fmt, mkts, cfg, page_of, meta, res, put_example or default_put_example, cfg['links'])
    if changed:
        res = check_group(fmt, mkts, cfg, page_of, meta, force=True)
    return res, changed, awaiting


def fix_group(fmt, mkts, cfg, page_of, meta, res, put_example, links):
    """Automatic repairs for a failed group - never on approval-locked pages (those are reported for approval).
    1. a country whose example is not this format -> the reference's canonical example
    2. script not following the example / not independently worded / wrong claims -> rewritten (align_page)
    3. directions not matching -> directions rewritten
    Returns (changed, awaiting_approval)."""
    ref = reference(fmt['id']) or {}
    results = res.get('results') or {}
    changed, awaiting = [], []
    for m, t in (res.get('title_fixes') or {}).items():
        pid = page_of(fmt, m)
        if pid and set_title(pid, t):  # a title is not part of a script approval
            changed.append(f'{m}: title -> {t[:60]}')
    for mk in mkts:
        m, lang = mk['key'], mk['lang']
        pid = page_of(fmt, m)
        if not pid:
            continue
        fails = {d: ((results.get(d) or {}).get(m) or {}) for d in DIMENSIONS}
        failing = [d for d, x in fails.items() if x and not x.get('pass')]
        if m in (res.get('deterministic') or {}) and 'format_consistency' not in failing:
            failing.append('format_consistency')
        if not failing:
            continue
        if align.approved_script(fmt['id'], lang):
            awaiting.append(f"{m}: approved script - needs your approval to change ({', '.join(failing)})")
            continue
        issues = '; '.join(x.get('issue', '') for d, x in fails.items() if d in failing and x.get('issue'))
        if reword.fix_asset_cues(pid):
            changed.append(f'{m}: repeated asset cue cleaned')
        if 'format_consistency' in failing:
            canon = ref.get('canonical_source')
            url = source_url(ref, canon)
            cur = localize.current_source(pid)
            cur_id = source_id((cur or {}).get('url'))
            if cur_id and cur_id not in (ref.get('accepted_sources') or []):
                rejected = meta.setdefault('group_rejected', {}).setdefault(fmt['id'], [])
                if cur_id not in rejected:
                    rejected.append(cur_id)
            if url and (not cur or cur_id not in (ref.get('accepted_sources') or [])):
                put_example(fmt, m, pid, lang, url)
                changed.append(f'{m}: example -> canonical {canon}')
        if set(failing) & {'format_consistency', 'script_matches_example', 'independent_wording', 'features_claims'}:
            st, why = align.align_page(fmt, pid, lang, cfg, links, feedback=issues)
            changed.append(f'{m}: script rewritten' if st == 'ok' else f'{m}: rewrite refused ({why})')
        if set(failing) & {'format_consistency', 'directions_match'}:
            st, why = reword.fix_directions(fmt, pid, lang, cfg['models']['build'], issues)
            changed.append(f'{m}: directions fixed' if st == 'ok' else f'{m}: directions not changed ({why})')
    return changed, awaiting


def approval_drafts(fmts, mkts, cfg, page_of, meta):
    """Approval-locked scripts that fail the group check get a replacement DRAFT (nothing is written to Notion): same
    beats and product timing as the reference's canonical example, independently worded. Stored in
    meta['approval_drafts'] for the user to approve."""
    out = meta.setdefault('approval_drafts', {})
    for f in fmts:
        res = (meta.get('group_audit') or {}).get(f['id']) or {}
        ref = reference(f['id']) or {}
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            pid = page_of(f, m)
            if not pid or not align.approved_script(f['id'], lang):
                continue
            fails = {d: x for d, per in (res.get('results') or {}).items() for mm, x in per.items()
                     if mm == m and not x.get('pass')}
            if not fails:
                continue
            cur = source_id(((localize.current_source(pid) or {}).get('url')))
            vid = cur if cur in (ref.get('accepted_sources') or []) else ref.get('canonical_source')
            url = source_url(ref, vid)
            if not url:
                continue
            prev = out.get(f"{f['id']}:{m}") or {}
            if prev.get('status') == 'draft' and prev.get('example') == url:
                continue  # a draft for this example is already waiting for approval
            try:
                st, spec = align.align_page(f, pid, lang, cfg, cfg['links'],
                                            feedback='; '.join(x.get('issue', '') for x in fails.values()), draft_url=url)
            except Exception as e:
                st, spec = 'error', str(e)[:200]
            out[f"{f['id']}:{m}"] = {'status': st, 'fails': sorted(fails), 'example': url,
                                     'example_changes': vid != cur, 'draft': spec if st == 'draft' else None,
                                     'why': '' if st == 'draft' else spec, 'at': int(time.time())}
            print(f"{f['id']} {m}: {st}", flush=True)
    return out


def apply_approvals(fmts, mkts, cfg, page_of, meta, put_example=None):
    """After the user approved new locked scripts (registry/approved_scripts.json): the page gets the approved example
    (if it differs) and the approved script; directions are matched to it. Only approved entries are touched."""
    put_example = put_example or default_put_example
    out = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            pid, ok = page_of(f, m), align.approved_script(f['id'], lang)
            if not pid or not ok:
                continue
            cur = (localize.current_source(pid) or {}).get('url') or ''
            if cur.split('?')[0] != ok['example'].split('?')[0]:
                put_example(f, m, pid, lang, ok['example'])
                out.append(f"{f['id']} {m}: example -> {ok['example']}")
            if ok.get('title') and set_title(pid, ok['title']):
                out.append(f"{f['id']} {m}: title -> {ok['title']}")
            st, why = align.align_page(f, pid, lang, cfg, cfg['links'])
            if why != 'approved script unchanged':
                out.append(f"{f['id']} {m}: {st} ({why})")
    for line in out:
        print(line, flush=True)
    return out
