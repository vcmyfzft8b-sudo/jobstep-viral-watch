"""Inspiration videos in the creators' language: every market's format page gets a JobStep video of THAT format in
the market's language (DE page -> German video, FR -> French, ES -> Spanish).

For each active format and market:
1. The page's current inspiration video is kept if it already comes from a creator in that language.
2. Otherwise our best JobStep videos of the format from creators in that language are checked by Claude (right
   language? same format? promotes JobStep?) and the first that passes replaces the video on the page; the
   "Original on TikTok" link next to it is updated. Nothing else on the page changes.
3. Formats/markets without a suitable video are reported (Slack + printed).

Done formats are remembered in formats.json (fmt['inspo'][market]); the Monday run retries the missing ones.
"""
import re
import json
import os
import shutil
import tempfile
import time

from . import discover, llm, media, notion, soniox, tiktok
from .markets import TEXT

LANG_NAME = {'de': 'German', 'fr': 'French', 'es': 'Spanish'}
MIN_VIEWS = 10_000  # an inspiration video must be proven, not just in the right language
EMBEDDED_EVIDENCE = os.path.join(os.path.dirname(__file__), '..', 'registry', 'verified_embedded_examples.json')


def embedded_record(page_id):
    """Explicit evidence pinned to an upload; never infer verification from the presence of a video."""
    try:
        with open(EMBEDDED_EVIDENCE) as fh:
            records = json.load(fh).get('examples', [])
    except FileNotFoundError:
        return None
    record = next((r for r in records if r['page_id'].replace('-', '') == page_id.replace('-', '')), None)
    if record and record.get('format_id') and record.get('source_url'):
        from . import crosscheck  # evidence for a video the format's reference rejects belongs to the replaced example
        rejected = (crosscheck.reference(record['format_id']) or {}).get('rejected_sources') or {}
        if crosscheck.source_id(record['source_url']) in rejected:
            return None
    return record


def verified_embedded_example(page_id, source_url=None):
    record = embedded_record(page_id)
    if not record or not (record.get('speech') or record.get('transcript_corrections')) or not record.get('source_language'):
        return None
    video = next((b for b in notion.children(page_id) if b['type'] == 'video'), None)
    if not video or video['id'] != record.get('video_block_id') or not video.get('last_edited_time'):
        return None
    if record.get('source_url'):
        current = current_source(page_id)
        normalize = lambda url: (url or '').split('?', 1)[0].split('#', 1)[0].rstrip('/')
        expected = normalize(record['source_url'])
        if not current or normalize(current.get('url')) != expected:
            return None
        if source_url and normalize(source_url) != expected:
            return None
    return record if video['last_edited_time'] == record.get('video_last_edited_time') else None


def _handle(url):
    m = re.search(r'@([^/?]+)/video', url or '')
    return m.group(1).lower() if m else None


def current_source(page_id):
    """The page's inspiration video block and the TikTok link right after it (or None if the page has no video)."""
    blocks = notion.children(page_id)
    i = next((k for k, b in enumerate(blocks) if b['type'] == 'video'), None)
    if i is None:
        return None
    for b in blocks[i + 1:i + 4]:
        for x in (b.get(b['type'], {}) or {}).get('rich_text', []) or []:
            url = ((x.get('text') or {}).get('link') or {}).get('url', '')
            if 'tiktok.com/@' in url:
                return {'video': blocks[i]['id'], 'link_block': b, 'url': url}
    return {'video': blocks[i]['id'], 'link_block': None, 'url': None}


def confirm(d, fmt, lang, model):
    """Strict check with the strong model: the video must be the SAME format as our page (full script compared),
    in the market's language, and promote JobStep. Returns the verdict dict; ok() decides."""
    prompt = f"""OUR FORMAT: {fmt['title']}
What it is: {fmt.get('description', '')}
Full script on our page:
{(fmt.get('script') or '')[:2500]}

CANDIDATE TikTok video by @{d['handle']}:
CAPTION: {d.get('desc') or '-'}
ON-SCREEN TEXT: {d.get('sticker') or '-'}
SPEECH: {(d.get('subtitles') or '-')[:2500]}

Creators will copy this video's pacing, visuals and structure while saying OUR script, so it must really be the
same format: same premise, same hook idea, same story/structure (e.g. same "problem -> reveal -> app" beats). Same
topic alone (CVs, ATS, job search) is NOT enough. Be strict.
Return JSON {{"language": "<English name of the video's language>", "match": "same|similar|different",
"confidence": "high|medium|low", "jobstep": true, "reason": "<one sentence>"}}"""
    return llm.chat_json(model, 'You check TikTok videos for a marketing team. Reply with JSON only.', prompt, timeout=900)


def ok(c, lang):
    return (c.get('match') == 'same' and c.get('confidence') == 'high' and c.get('jobstep')
            and LANG_NAME[lang].lower() in str(c.get('language', '')).lower())


def _relink(block, url):
    """Same text, every TikTok link pointing to the new video."""
    rich = []
    for x in block[block['type']].get('rich_text', []):
        link = ((x.get('text') or {}).get('link') or {}).get('url')
        if link and 'tiktok.com/@' in link:
            link = url
        rich.append({'type': 'text', 'text': {'content': x.get('plain_text', ''), 'link': {'url': link} if link else None},
                     'annotations': x.get('annotations', {})})
    notion.api('PATCH', f"/blocks/{block['id']}", {block['type']: {'rich_text': rich}})


def replace_video(page_id, src, d, lang):
    work = tempfile.mkdtemp(prefix='inspo-')
    try:
        upload = notion.upload_video(media.for_notion(media.download(d['url'], work), work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    r = notion.api('PATCH', f'/blocks/{page_id}/children', {
        'children': [notion.block('video', type='file_upload', file_upload={'id': upload})], 'after': src['video']})
    new_video = r['results'][-1]['id']
    notion.api('DELETE', f"/blocks/{src['video']}")
    if src['link_block']:
        _relink(src['link_block'], d['url'])
    else:
        notion.api('PATCH', f'/blocks/{page_id}/children', {
            'children': [notion.para([notion.rt(TEXT[lang]['source'], link=d['url'])])], 'after': new_video})


def add_section(page_id, d, lang):
    """Page without an inspiration video (older FR/ES pages): add the whole section at the top in its language."""
    T = TEXT[lang]
    if any(b['type'] == 'video' for b in notion.children(page_id)):
        return  # never add a second section
    work = tempfile.mkdtemp(prefix='inspo-')
    try:
        upload = notion.upload_video(media.for_notion(media.download(d['url'], work), work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    section = [notion.block('heading_1', [notion.rt(T['video_heading'])]),
               notion.block('video', type='file_upload', file_upload={'id': upload}),
               notion.para([notion.rt(T['source'], link=d['url'])]),
               notion.block('callout', notion.md('\n'.join(T['inspo_note'])), icon={'type': 'emoji', 'emoji': '⚠️'},
                            color='gray_background'),
               notion.block('divider')]
    try:
        notion.api('PATCH', f'/blocks/{page_id}/children', {'children': section, 'position': {'type': 'start'}},
                   version='2025-09-03')
    except Exception as e:  # if inserting at the top is refused: put it at the end of the page instead
        print('top insert refused, adding at the end:', str(e)[:150])
        notion.api('PATCH', f'/blocks/{page_id}/children', {'children': section})


def example_text(url, page_id=None):
    """What is said / written in an example video (TikTok subtitles, else Soniox), for transcribing it into a script."""
    if page_id:
        record = verified_embedded_example(page_id, source_url=url)
        if record:
            if record.get('transcript_corrections'):
                # Fetch public subtitles at runtime; the registry stores only a reviewed ASR correction,
                # never a copy of a third-party transcript. Do not infer text when public subtitles are absent.
                source_url = record.get('source_url')
                match = re.search(r'/video/(\d+)', source_url or '')
                if not match:
                    return ''
                detail = tiktok.video_detail(_handle(source_url), match.group(1)) or {}
                speech = detail.get('subtitles') or ''
                if not speech.strip():
                    return ''
                for correction in record['transcript_corrections']:
                    old, new = correction.get('from'), correction.get('to')
                    if not old or not new or speech.count(old) != 1:
                        return ''  # changed public ASR needs another review, not a broader replacement
                    speech = speech.replace(old, new, 1)
                return f"ON-SCREEN: {detail.get('sticker', '')}\nSPEECH: {speech}"
            return f"ON-SCREEN: {record.get('on_screen', '')}\nSPEECH: {record['speech']}"
        if embedded_record(page_id):
            return ''  # stale media/source pins require review, not silent fallback to lower-quality ASR
    h, vid = _handle(url), re.search(r'/video/(\d+)', url or '')
    if not h or not vid:
        return ''
    d = tiktok.video_detail(h, vid.group(1)) or {}
    text = d.get('subtitles', '')
    if len(text) < 40:
        work = tempfile.mkdtemp(prefix='ex-')
        try:
            text = soniox.transcribe(media.audio(media.download(url, work), work)).get('text', '') or text
        except Exception:
            pass
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if not (text or '').strip() and not (d.get('sticker') or '').strip():
        return ''  # nothing could be read (TikTok/Tor hiccup) - callers treat this as 'unknown', never as 'wrong'
    return f"ON-SCREEN: {d.get('sticker', '')}\nSPEECH: {text}"


def note_block(page_id):
    """The ⚠️ note callout right under the inspiration video (old pages may have another ⚠️ box at the top);
    without one there, the first ⚠️ callout of the page."""
    blocks = notion.children(page_id)
    i = next((k for k, b in enumerate(blocks) if b['type'] == 'video'), None)
    under = next((b for b in blocks[i + 1:i + 4] if b['type'] == 'callout'), None) if i is not None else None
    return under or next((b for b in blocks if b['type'] == 'callout' and '⚠' in str(b['callout'].get('icon'))), None)


def note_text(page_id):
    b = note_block(page_id)
    return ''.join(x.get('plain_text', '') for x in b['callout'].get('rich_text', [])) if b else ''


def set_note(page_id, lang, same_lang, own=False):
    """The ⚠️ note under the inspiration video, matching the video (same language = 'use it as the model')."""
    blocks = notion.children(page_id)
    i = next((k for k, x in enumerate(blocks) if x['type'] == 'video'), None)
    b = next((x for x in blocks[i + 1:i + 4] if x['type'] == 'callout'), None) if i is not None else None
    if not b:  # only the note right under the video is ever rewritten
        return
    if b.get('has_children'):  # older pages keep the 2nd note line as a child block -> it would show twice
        for c in notion.children(b['id']):
            notion.api('DELETE', f"/blocks/{c['id']}")
    notion.api('PATCH', f"/blocks/{b['id']}", {'callout': {'rich_text': notion.md('\n'.join(
        notion.inspo_note(lang, same_lang, own)))}})


def refresh_note(page_id, lang):
    """Rewrite the ⚠️ note in the current wording, keeping its kind (same-language example or not, JobStep line or not)."""
    note = note_text(page_id)
    if not note:
        return
    same = note.replace('**', '')[:30] == TEXT[lang]['inspo_note_same'].replace('**', '')[:30]
    set_note(page_id, lang, same, own='JobStep' not in note)


def finish(f, m, pid, lang, url, cfg):
    """After a same-language example is on the page: note says so, script mirrors that example sentence by sentence."""
    from . import align
    set_note(pid, lang, True)
    status, why = align.align_page(f, pid, lang, cfg, cfg['links'])
    if status == 'ok':
        f.setdefault('reworded', {})[m] = True
    return status, why


def run(fmts, mkts, history, accounts, meta, cfg, page_of, now=None, tries=4, exclude=()):
    """Returns [(format title, market, status, detail)]. status: kept | replaced | missing | no page | error."""
    now = now or time.time()
    langs = meta.setdefault('handle_lang', {})
    for h, a in accounts.items():
        if a.get('lang'):
            langs.setdefault(h, a['lang'])
    report = []
    for f in [f for f in fmts if f.get('status') in ('active', 'pending')]:
        ranked = sorted(((vid, v) for vid, v in history.items() if v.get('format') == f['id']), key=lambda x: -x[1]['views'])[:60]
        for h in {v['handle'] for _, v in ranked} - set(langs):
            langs[h] = discover.language(h)
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            pid = page_of(f, m)
            if not pid:
                report.append((f['title'], m, 'no page', ''))
                continue
            if embedded_record(pid):
                record = verified_embedded_example(pid)
                report.append((f['title'], m, 'kept' if record else 'error',
                               ('verified uploaded example and transcript retained' if record.get('source_url') else
                                'verified legacy upload retained; views unavailable') if record else
                               'uploaded example or source changed since verification; audit required'))
                continue
            from . import align
            if align.approved_script(f['id'], lang):
                src = current_source(pid)
                url = src.get('url') if src else None
                report.append((f['title'], m, 'kept' if align.approved(f['id'], lang, url) else 'error',
                               'approved script/example locked; audit verifies the live content'))
                continue
            from . import crosscheck
            blocked = crosscheck.blocked_sources(f['id'], meta)  # wrong-story videos never come back
            accepted = set((crosscheck.reference(f['id']) or {}).get('accepted_sources') or [])
            src = current_source(pid)
            if src and crosscheck.source_id(src.get('url')) in accepted:
                report.append((f['title'], m, 'kept', 'example matches the reference definition of this format'))
                continue  # the agreed example for all three countries; a same-language search could pick another story
            if crosscheck.source_id(((f.get('inspo') or {}).get(m) or {}).get('url')) in blocked:
                f['inspo'].pop(m, None)
            if (f.get('inspo') or {}).get(m, {}).get('strict'):
                if not (f.get('reworded') or {}).get(m) and langs.get(_handle(f['inspo'][m]['url'])) == lang:
                    try:
                        finish(f, m, pid, lang, f['inspo'][m]['url'], cfg)
                    except Exception as e:
                        print('finish failed', f['title'], m, str(e)[:150])
                report.append((f['title'], m, 'kept', f['inspo'][m]['url']))
                continue  # entries from before the strict check are looked at again
            try:
                src = current_source(pid)
                if src and src['url'] and src['url'] not in exclude and crosscheck.source_id(src['url']) not in blocked \
                        and langs.get(_handle(src['url'])) == lang:
                    cur = tiktok.video_detail(_handle(src['url']), re.search(r'/video/(\d+)', src['url']).group(1))
                    if cur and cur['views'] >= MIN_VIEWS and ok(confirm(cur, f, lang, cfg['models']['build']), lang):
                        f.setdefault('inspo', {})[m] = {'url': src['url'], 'views': cur['views'], 'at': int(now), 'strict': True}
                        if not (f.get('reworded') or {}).get(m):
                            finish(f, m, pid, lang, src['url'], cfg)
                        report.append((f['title'], m, 'kept', src['url']))
                        continue  # right language and proven; otherwise look for a better one below
                found = None
                for vid, v in [(vid, v) for vid, v in ranked if langs.get(v['handle']) == lang and v['views'] >= MIN_VIEWS
                                and vid not in blocked
                                and f"https://www.tiktok.com/@{v['handle']}/video/{vid}" not in exclude][:tries]:
                    d = tiktok.video_detail(v['handle'], vid)
                    if not d:
                        continue
                    c = confirm(d, f, lang, cfg['models']['build'])
                    if ok(c, lang) and d['views'] >= MIN_VIEWS:
                        found = d
                        break
                if not found:
                    report.append((f['title'], m, 'missing', f'no {LANG_NAME[lang]} JobStep video of this format yet'))
                    continue
                if src:
                    replace_video(pid, src, found, lang)
                else:
                    add_section(pid, found, lang)
                f.setdefault('inspo', {})[m] = {'url': found['url'], 'views': found['views'], 'at': int(now),
                                                'prev': src['url'] if src else None, 'strict': True}
                f.setdefault('reworded', {}).pop(m, None)
                meta.setdefault('audit', {}).pop(f"{f['id']}:{m}", None)  # page changed -> audited again on Monday
                rw = finish(f, m, pid, lang, found['url'], cfg)  # note + script now follow this example
                report.append((f['title'], m, 'replaced', f"{found['url']} ({found['views'] // 1000}k views)"
                               + ('' if rw[0] == 'ok' else f" – script not reworded: {rw[1]}")))
            except Exception as e:
                report.append((f['title'], m, 'error', str(e)[:150]))
    return report


def recheck(fmts, mkts, history, accounts, meta, cfg, page_of, now=None):
    """Re-checks every video an earlier (less strict) run put on a page. If it does not pass the strict check it is
    replaced by one that does, or - if there is none - the page gets its previous video back (format first,
    language second). Returns the report like run()."""
    now = now or time.time()
    report = []
    for f in [f for f in fmts if f.get('status') == 'active']:
        for mk in mkts:
            m, lang = mk['key'], mk['lang']
            from . import align
            if align.approved_script(f['id'], lang) or (page_of(f, m) and embedded_record(page_of(f, m))):
                continue
            x = (f.get('inspo') or {}).get(m)
            if not x or x.get('strict') or 'views' not in x:
                continue  # nothing replaced, or already strictly checked
            h = _handle(x['url'])
            vid = re.search(r'/video/(\d+)', x['url']).group(1)
            d = tiktok.video_detail(h, vid)
            c = confirm(d, f, lang, cfg['models']['build']) if d else {}
            if d and ok(c, lang) and d['views'] >= MIN_VIEWS:
                x['strict'] = True
                report.append((f['title'], m, 'confirmed', x['url']))
                continue
            print('failed strict check:', f['title'], m, x['url'], c.get('reason', ''))
            prev = x.get('prev')
            f['inspo'].pop(m)
            r = run([f], [mk], history, accounts, meta, cfg, page_of, now, exclude={x['url']})  # next candidates (strict)
            if r and r[0][2] in ('replaced', 'kept'):
                report.append(r[0])
                continue
            back = prev or f.get('source_video')
            pid = page_of(f, m)
            src = current_source(pid)
            bd = tiktok.video_detail(_handle(back), re.search(r'/video/(\d+)', back).group(1)) if back else None
            if bd and src:
                replace_video(pid, src, bd, lang)
                report.append((f['title'], m, 'restored', f"{back} (no {LANG_NAME[lang]} video passed the strict check)"))
            else:
                report.append((f['title'], m, 'error', 'failed strict check and the previous video could not be restored'))
    return report
