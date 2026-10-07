"""Page audit: every active format page in every market must check out - and is fixed until it does.

For each page Claude (strong model) compares three things: the FORMAT, the page's EXAMPLE VIDEO (what is said and
shown in it) and the page's SCRIPT.
  1. Is the example video really this format?
  2. Does the script follow the example's beats (same story, same order)?
  3. Is the script reworded (not a 1:1 transcription), in the market's language, without JobStep or guarantees?
Fixes, then the page is checked again (max 3 rounds):
  - wrong example -> a strictly checked same-language JobStep video of the format, else the format's original
    JobStep video (registry/originals.json, the video the script was built from)
  - script off -> reworded again against the example video
Pages that still fail after 3 rounds are reported with the reason.
"""
import json
import hashlib
import os
import re
from urllib.parse import urlsplit

from . import align, llm, localize, notion, reword, state, tiktok
from .builder import PARAKEET_FACTS

ORIGINALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'registry', 'originals.json')


def originals():
    try:
        with open(ORIGINALS) as f:
            return json.load(f)['originals']
    except FileNotFoundError:
        return {}


def fingerprint(page_id):
    """Bind a successful check to live content, including edits made outside this watcher.

    Signed download URLs expire without an edit; retain media identity paths and block edit timestamps.
    """
    def content_of(blocks):
        out = []
        for b in blocks:
            item = {k: b.get(k) for k in ('id', 'type', 'last_edited_time', 'has_children')}
            data = dict(b.get(b['type']) or {})
            if isinstance(data.get('file'), dict):
                media_file = dict(data['file'])
                media_file.pop('expiry_time', None)
                if media_file.get('url'):
                    media_file['url'] = urlsplit(media_file['url']).path
                data['file'] = media_file
            item['content'] = data
            if b.get('has_children') and b['type'] not in ('child_page', 'child_database'):
                item['children'] = content_of(notion.children(b['id']))
            out.append(item)
        return out
    content = content_of(notion.children(page_id))
    with open(align.APPROVED) as fh:
        approvals = json.load(fh)
    return hashlib.sha256(json.dumps({'policy': 2, 'blocks': content, 'approvals': approvals,
                                     'embedded_evidence': localize.embedded_record(page_id)},
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def nested_instructions(blocks):
    """Include nested callout/list resources in the review, but do not traverse separate pages/databases."""
    out = []
    def describe(b):
        data = b[b['type']]
        rich = data.get('rich_text', []) + data.get('caption', []) + [x for cell in data.get('cells', []) for x in cell]
        return ''.join(x.get('plain_text', x.get('text', {}).get('content', '')) +
                       (f" ({x['text']['link']['url']})" if (x.get('text', {}).get('link') or {}).get('url') else '')
                       for x in rich)
    for b in blocks:
        if b.get('has_children') and b['type'] not in ('child_page', 'child_database'):
            children = notion.children(b['id'])
            out.append(describe(b) + ':\n' + '\n'.join(describe(c) for c in children))
            out.extend(nested_instructions(children))
    return out


def check(fmt, page_id, lang, model, links=None):
    """Returns (passed, verdict dict, example url)."""
    observed_fingerprint = fingerprint(page_id)
    src = localize.current_source(page_id)
    url = src['url'] if src else None
    embedded = localize.verified_embedded_example(page_id, source_url=url) if src else None
    example = localize.example_text(url, page_id=page_id)
    match = re.search(r'/video/(\d+)', url or '')
    detail = tiktok.video_detail(localize._handle(url), match.group(1)) if match else None
    legacy_exemption = bool(embedded and embedded.get('views_policy') == 'legacy_original_unavailable')
    views_known = detail and isinstance(detail.get('views'), (int, float)) and detail['views'] >= 0
    if not example or not (views_known or legacy_exemption):
        return False, {'unverified': True, 'script_issues': [], 'direction_issues': [],
                       'example_issue': ('uploaded example exists; transcript or source evidence unverified' if src and not url
                                         else 'example transcript or view count unavailable; retry required')}, url
    script = '\n'.join(reword._plain(b) for b in reword.script_blocks(page_id))
    directions = '\n'.join(reword._plain(b) for b in reword.direction_blocks(page_id))
    blocks_all = notion.children(page_id)
    ti = next((k for k, b in enumerate(blocks_all) if b['type'].startswith('heading') and '📲' in reword._plain(b)), None)
    title_block = next((b for b in blocks_all[ti + 1:ti + 3] if b['type'] == 'paragraph' and reword._plain(b).strip()), None) if ti is not None else None
    title = reword._plain(title_block) if title_block else ''
    note = next((reword._plain(b) for b in notion.children(page_id) if b['type'] == 'callout' and '⚠' in str(b['callout'].get('icon'))), '')
    if not script.strip():
        return False, {'missing_script': True, 'script_issues': ['no script section found']}, url
    lang_name = localize.LANG_NAME[lang]
    prompt = f"""FORMAT: {fmt['title']}
What the format is: {fmt.get('description', '')}

EXAMPLE VIDEO on the page ({url or 'verified uploaded legacy video'}):
{example[:3000] or '(no example video)'}

SCRIPT on the page (creators say this, in {lang_name}):
{script[:4000]}

FILMING DIRECTIONS on the page:
{directions[:2000]}

NESTED INSTRUCTIONS AND RESOURCES (also check these against the script and the actual product):
{chr(10).join(nested_instructions(blocks_all))}

Check strictly:
1. example_same_format: is the example video really THIS format (same premise, hook idea and structure - same topic
   alone is not enough)? false if there is no example video.
2. script_follows_example: does the script tell the same story with the same beats in the same order as the example?
3. script_reworded: is the script reworded rather than a transcription/translation of the example? Very similar
   story is good, but if more than about a third of the sentences are direct translations/transcriptions of the
   example's sentences (same structure, same images), it is NOT reworded. Be strict - a native viewer must not
   recognise the example's sentences.
5. directions_ok: do the filming directions match the script - no duplicate or contradicting lines, X/Y mentioned
   only as they appear in the script, every quoted line really in the script?
6. example_language: the language of the example video (English name).
4. script_ok: natural {lang_name}, never mentions JobStep, no promises nobody can guarantee; scores and
   percentages the app shows are ALWAYS the placeholders X / Y, never concrete numbers (e.g. "64 %", "40 sobre 100"
   is wrong); one consistent form of address ({ {'de': 'du', 'fr': 'tu', 'es': 'tú (never vosotros)'}[lang] });
   no stray formatting characters (backticks, asterisks) in what is said or shown.
   Mirror the original's spoken brand mentions in count and story position: substitute Parakeet AI only where the
   original says JobStep, and the Parakeet URL only where it says the JobStep URL. If the original never names the
   brand, our spoken script must not name it either. Parenthesized linked cue labels are filming instructions,
   not spoken words. For silent videos compare on-screen text instead. Never add a CTA or website if the original
   has none; preserve its placement when one exists.
7. title_ok: the on-screen TITLE ({title!r}) makes no promise nobody can guarantee (e.g. 'a job in 24h') and is not a
   word-for-word copy of the example's on-screen text when the example is in {lang_name}.
{PARAKEET_FACTS}
script_ok is false if the script or directions show/mention a feature Parakeet AI does not have.
Note: X and Y in the script are intentional placeholders - the creator says the score the app shows them. They are
correct; never ask to replace them with numbers.
Return JSON {{"example_same_format": true, "script_follows_example": true, "script_reworded": true, "script_ok": true,
"directions_ok": true, "title_ok": true, "example_language": "<language>", "example_issue": "<short, if any>",
"title_suggestion": "<if title_ok is false: a fixed title in the same style, else empty>",
"script_issues": ["<short>", ...], "direction_issues": ["<short>", ...]}}"""
    v = llm.chat_json(model, 'You are a strict QA reviewer for UGC creator instructions. Reply with JSON only.', prompt, timeout=1200)
    v['script_issues'] = [x for x in (v.get('script_issues') or []) if x]
    v['example_issue'] = v.get('example_issue') or ''
    v['direction_issues'] = [x for x in (v.get('direction_issues') or []) if x]
    v['note'] = note
    v['views'] = detail['views'] if views_known else None
    v['views_policy'] = 'legacy_original_unavailable' if legacy_exemption else 'verified_count'
    v['embedded_verified'] = bool(embedded)
    if embedded:
        v['example_language'] = embedded['source_language']
    same = localize.LANG_NAME[lang].lower() in str(v.get('example_language', '')).lower()
    v['note_ok'] = bool(note) and ((same and _note_is_same(note, lang)) or (not same and not _note_is_same(note, lang)))
    v['same_lang'] = same
    v['views_ok'] = legacy_exemption or v['views'] >= localize.MIN_VIEWS or url == originals().get(fmt['id'])
    v['title_block'] = title_block
    locked = align.approved_script(fmt['id'], lang)
    if locked and links is None:
        with open(os.path.join(os.path.dirname(__file__), '..', 'config.json')) as fh:
            links = json.load(fh)['links']
    v['approval_locked'] = bool(locked)
    v['approved'] = bool(align.approved(fmt['id'], lang, url))
    v['approved_matches'] = bool(v['approved'] and links and align.matches_approved(page_id, lang, links, locked))
    if v['approved_matches']:
        v.update({'script_follows_example': True, 'script_reworded': True, 'script_ok': True})
        v['script_issues'] = []
    base = align.source_script(example)
    spoken = reword.spoken_text(reword.script_blocks(page_id))
    v['length_ok'] = v['approved_matches'] or align._words(spoken) <= 1.10 * max(align._words(base), 1)
    want, have = len(align.JOBSTEP.findall(base)), len(re.findall(r'parakeet', spoken, re.I))
    v['brand_count_ok'] = v['approved_matches'] or have == want
    if not v['brand_count_ok']:
        v['script_issues'].append(f'spoken brand count is {have}; source requires {want}; linked filming cues do not count')
    if not title_block:
        v['title_ok'] = True
    passed = all(v.get(k) is True for k in ('example_same_format', 'script_follows_example', 'script_reworded', 'script_ok',
                                    'directions_ok', 'note_ok', 'views_ok', 'title_ok', 'length_ok', 'brand_count_ok'))
    if locked and not v['approved_matches']:
        passed = False
        v['script_issues'].append('live script or example differs from the approved version')
    if re.search(r'job\s*-?\s*step', script, re.I):
        passed = False
        v['script_issues'].append('JobStep is mentioned in the script')
    if passed and fingerprint(page_id) != observed_fingerprint:
        passed = False
        v['unverified'] = True
        v['example_issue'] = 'page changed during its audit; retry required'
    v['checked_fingerprint'] = observed_fingerprint
    return passed, v, url


def _note_is_same(note, lang):
    from .markets import TEXT
    return note.replace('**', '')[:30] == TEXT[lang]['inspo_note_same'].replace('**', '')[:30]


def _put_example(fmt, m, page_id, lang, url, same_lang):
    if align.approved_script(fmt['id'], lang):
        return False  # changing the example must never silently revoke a script approval
    h, vid = localize._handle(url), re.search(r'/video/(\d+)', url).group(1)
    d = tiktok.video_detail(h, vid)
    if not d:
        return False
    src = localize.current_source(page_id)
    if src:
        localize.replace_video(page_id, src, d, lang)
    else:
        localize.add_section(page_id, d, lang)
    localize.set_note(page_id, lang, same_lang)
    fmt.setdefault('inspo', {})[m] = {'url': url, 'views': d['views'], 'strict': True, 'audit': True}
    return True


def fix_page(fmt, mk, cfg, history, accounts, meta, page_of, rounds=5, rebuild=None):
    """Checks one page and fixes it until it passes. Returns (status, notes)."""
    m, lang, model = mk['key'], mk['lang'], cfg['models']['build']
    pid = page_of(fmt, m)
    notes, rejected, rebuilt = [], set(), False
    for r in range(rounds + 1):
        passed, v, url = check(fmt, pid, lang, model, cfg['links'])
        if v.get('unverified'):
            return 'unverified', notes + [v['example_issue']]
        if v.get('missing_script'):
            return 'failed', notes + v['script_issues']
        if passed:
            meta.setdefault('audit_fingerprints', {})[f"{fmt['id']}:{m}"] = v['checked_fingerprint']
            return ('ok' if r == 0 else 'fixed'), notes
        if r == rounds:
            break
        if v.get('embedded_verified') and not v.get('example_same_format'):
            return 'failed', notes + ['verified legacy example needs review; video preserved']
        if v.get('approval_locked'):
            if not v.get('approved'):
                return 'failed', notes + ['example differs from approved example; manual review required']
            if not v.get('approved_matches'):
                st, why = align.align_page(fmt, pid, lang, cfg, cfg['links'])
                notes.append(f'approved script restored: {why}' if st == 'ok' else why)
                continue
            if not v.get('example_same_format') or not v.get('views_ok'):
                return 'failed', notes + ['approved example needs review; script and example preserved']
        if not v.get('views_ok'):
            orig = originals().get(fmt['id'])
            notes.append(f"example has only {v['views']} views - original JobStep video put back")
            if url:
                rejected.add(url)
            if orig:
                _put_example(fmt, m, pid, lang, orig, same_lang=False)
                fmt.get('reworded', {}).pop(m, None)
            continue
        if not v.get('note_ok') and v.get('example_same_format'):
            localize.set_note(pid, lang, v['same_lang'])
            notes.append('note under the video corrected')
            continue
        if v.get('example_same_format') and (not v.get('length_ok') or not v.get('script_reworded')
                                             or not v.get('script_follows_example')) and not rebuilt:
            rebuilt = True  # script too long / too close / not following: mirror the example sentence by sentence
            st, why = align.align_page(fmt, pid, lang, cfg, cfg['links'])
            if st == 'ok':
                fmt.setdefault('reworded', {})[m] = True
            notes.append(f'script rewritten sentence by sentence ({why})' if st == 'ok' else f'rewrite refused: {why}')
            continue
        if not v.get('title_ok') and v.get('title_suggestion') and v.get('title_block'):
            tb = v['title_block']
            notion.api('PATCH', f"/blocks/{tb['id']}", {tb['type']: {'rich_text': [notion.rt(v['title_suggestion'], bold=True)]}})
            notes.append(f"title fixed: {v['title_suggestion'][:60]}")
            continue
        if not v.get('directions_ok') and v.get('example_same_format') and v.get('script_reworded') and v.get('script_follows_example'):
            st, why = reword.fix_directions(fmt, pid, lang, model, '; '.join(v['direction_issues']))
            notes.append('filming directions corrected' if st == 'ok' else f'directions not changed: {why}')
            continue
        if not v.get('example_same_format'):
            notes.append(f"example not this format ({(v.get('example_issue') or '')[:80]})")
            fmt.get('inspo', {}).pop(m, None)
            fmt.get('reworded', {}).pop(m, None)
            if url:
                rejected.add(url)
            rep = localize.run([fmt], [mk], history, accounts, meta, cfg, page_of, exclude=rejected)  # strict search
            if not (rep and rep[0][2] in ('replaced', 'kept') and (fmt.get('inspo') or {}).get(m, {}).get('strict')):
                orig = originals().get(fmt['id'])
                if orig and orig not in rejected:
                    _put_example(fmt, m, pid, lang, orig, same_lang=False)
                    notes.append('put back the original JobStep video')
            continue
        if not v.get('script_follows_example') and url and rebuild and not rebuilt:
            # the example tells the format in another order: build the page from the example (reworded script)
            rebuilt = True
            ok, why = rebuild(fmt, mk, url)
            notes.append('page rebuilt from its example video' if ok else f'rebuild refused: {why}')
            if ok:
                continue
        if v.get('approved') or all(v.get(k) for k in ('script_ok', 'script_reworded', 'script_follows_example', 'length_ok', 'brand_count_ok')):
            notes.append('nothing left that a rewrite could fix: ' + '; '.join(v['direction_issues'] + [v['example_issue']])[:120])
            continue
        notes.append('script reworded again: ' + '; '.join(v['script_issues'])[:120])
        status, why, changes = reword.reword_page(fmt, pid, lang, model, localize.example_text(url, page_id=pid),
                                                  feedback='; '.join(v['script_issues']))
        if status == 'ok':
            reword.apply(changes)
            fmt.setdefault('reworded', {})[m] = True
        else:
            notes.append(f'reword refused: {why}')
    return 'failed', notes + ['still failing: ' + '; '.join(v.get('script_issues', []) + v.get('direction_issues', []) + [v.get('example_issue', '')])[:200]]


def run(fmts, mkts, cfg, history, accounts, meta, page_of, workers=8, rebuild=None, only_failed=False):
    import concurrent.futures as cf
    last = meta.setdefault('audit', {})
    fingerprints = meta.setdefault('audit_fingerprints', {})
    jobs = [(f, mk) for f in fmts if f.get('status') == 'active' for mk in mkts]

    def one(job):
        f, mk = job
        key = f"{f['id']}:{mk['key']}"
        pid = page_of(f, mk['key'])
        try:
            before = fingerprint(pid) if pid else None
            if not pid:
                status, notes = 'no page', ['language page is missing']
            elif only_failed and last.get(key) in ('ok', 'fixed') and fingerprints.get(key) == before:
                return None
            else:
                status, notes = fix_page(f, mk, cfg, history, accounts, meta, page_of, rebuild=rebuild)
            checked_fingerprint = None
            if status in ('ok', 'fixed'):
                after = fingerprint(pid)
                if fingerprints.get(key) == after or before == after:
                    checked_fingerprint = after
                else:
                    status, notes = 'unverified', notes + ['page changed during audit; retry required']
        except Exception as e:
            status, notes = 'error', [str(e)[:200]]
            checked_fingerprint = None
        with state.LOCK:
            last[key] = status
            if checked_fingerprint:
                fingerprints[key] = checked_fingerprint
            else:
                fingerprints.pop(key, None)
            state.save('formats.json', fmts)
            state.save('meta.json', meta)
        print(f"{f['title'][:45]} | {mk['key']} | {status} | {' / '.join(notes)}", flush=True)
        return f['title'], mk['key'], status, notes
    with cf.ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(one, jobs) if r is not None]
