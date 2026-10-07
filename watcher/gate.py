"""Quality gate: nothing reaches the creator lists before every language page has passed the full check.

A new format, a format coming back from the archive, or a missing language page is first built where creators
can't see it (new pages in the private staging page, revived pages stay in the archive). Every page then goes
through the page audit (audit.fix_page: example = this format, script sentence by sentence and not too long,
Parakeet AI where JobStep is named, only real Parakeet AI features, note, directions, title) - with automatic fixes.
Only when ALL markets pass are the pages moved into the format folders and the format goes into the lists.
Otherwise the format waits (status 'pending') and every run tries again; after MAX_TRIES runs it is given up.
"""
import re
import time

from . import audit, notify, notion, state, tiktok

MAX_TRIES = 4


def _build_missing(fmt, mk, cfg, make_page, set_page, staging):
    """A market without a page gets one (built in the staging page) from the format's source video."""
    url = fmt.get('source_video') or (fmt.get('revived') or {}).get('because')
    m = re.search(r'@([^/]+)/video/(\d+)', url or '')
    v = tiktok.video_detail(*m.groups()) if m else None
    if not v:
        return f"{mk['T']['flag']} no page and the source video is unavailable"
    pid, spec, problems = make_page(v, mk, cfg, None, parent=staging, attempts=3)
    if problems:
        return f"{mk['T']['flag']} page could not be built: {'; '.join(problems)[:120]}"
    set_page(fmt, mk['key'], pid)
    return None


def check(fmt, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild):
    """Builds missing pages and audits (and fixes) every market page. Returns (passed, reasons)."""
    staging = cfg['notion']['radar_page']
    reasons = []
    for mk in mkts:
        if not page_of(fmt, mk['key']):
            why = _build_missing(fmt, mk, cfg, make_page, set_page, staging)
            if why:
                reasons.append(why)
                continue
        status, notes = audit.fix_page(fmt, mk, cfg, history, accounts, meta, page_of, rebuild=rebuild)
        meta.setdefault('audit', {})[f"{fmt['id']}:{mk['key']}"] = status
        if status not in ('ok', 'fixed'):
            reasons.append(f"{mk['T']['flag']} {' / '.join(notes)[:160]}")
    return not reasons, reasons


def publish(fmt, mkts, page_of):
    """All pages passed: into every market's format folder, format becomes active (the re-sort lists it)."""
    for mk in mkts:
        pid = page_of(fmt, mk['key'])
        if pid:
            try:
                notion.move_page(pid, mk['holder_page'])
            except Exception as e:
                print('publish: move failed', mk['key'], str(e)[:120])
    fmt['status'] = 'active'
    fmt.pop('pending', None)
    fmt.pop('archived_reason', None)
    fmt['listed_at'] = int(time.time())


def hold(fmt, reasons, kind):
    p = fmt.setdefault('pending', {'since': int(time.time()), 'tries': 0, 'kind': kind})
    p['tries'] += 1
    p['reasons'] = reasons
    fmt['status'] = 'pending'
    state.log({'type': 'format_held', 'format': fmt['id'], 'tries': p['tries'], 'reasons': reasons})


def retry_pending(fmts, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild, rerank):
    """Every run: formats waiting at the gate are checked again; published -> Slack, given up after MAX_TRIES."""
    for f in [f for f in fmts if f.get('status') == 'pending']:
        ok, reasons = check(f, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild)
        if ok:
            publish(f, mkts, page_of)
            pos = rerank(mkts, fmts, history, cfg).index(f['id']) + 1
            notify.push('✅ Format passed the check – now live', f"*{f['title']}* is now in all lists as #{pos} "
                        '(every language page checked: example, script, note, directions, title).')
            state.log({'type': 'format_published', 'format': f['id'], 'position': pos})
            continue
        hold(f, reasons, f.get('pending', {}).get('kind', 'new'))
        if f['pending']['tries'] >= MAX_TRIES:
            f['status'] = 'archived'
            f['archived_reason'] = 'did not pass the page check: ' + '; '.join(reasons)[:200]
            notify.push('❌ Format held back for good', f"*{f['title']}* did not pass the page check after "
                        f"{MAX_TRIES} runs:\n" + '\n'.join(reasons) + '\nIt stays in the archive and comes back if it '
                        'goes viral again.')
