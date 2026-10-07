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

from . import audit, crosscheck, notify, notion, state, tiktok

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
                meta.setdefault('audit', {})[f"{fmt['id']}:{mk['key']}"] = 'unverified'
                reasons.append(why)
                continue
        status, notes = audit.fix_page(fmt, mk, cfg, history, accounts, meta, page_of, rebuild=rebuild)
        meta.setdefault('audit', {})[f"{fmt['id']}:{mk['key']}"] = status
        if status not in ('ok', 'fixed'):
            reasons.append(f"{mk['T']['flag']} {' / '.join(notes)[:160]}")
    if not reasons:  # every page passed on its own - now all countries TOGETHER against the reference definition
        res, changed, awaiting = crosscheck.group_cycle(fmt, mkts, cfg, page_of, meta)
        if not res['passed']:
            reasons.append(f"cross-country check {res['status']}: " + '; '.join(res.get('reasons', []))[:300])
            reasons += awaiting
    return not reasons, reasons


def _checkpoint(fmt, checkpoint=None):
    """Keep a recovery journal even if execution stops between two Notion writes."""
    with state.LOCK:
        journal = state.load('publication_journal.json', {})
        if fmt.get('publication'):
            journal[fmt['id']] = fmt['publication']
        else:
            journal.pop(fmt['id'], None)
        state.save('publication_journal.json', journal)
        if checkpoint:
            checkpoint()


def _rollback(fmt, checkpoint=None):
    publication = fmt['publication']
    publication['stage'] = 'rollback_pending'
    fmt['status'] = 'pending'
    _checkpoint(fmt, checkpoint)
    errors = []
    for pid in list(reversed(publication['attempted'])):
        try:
            notion.move_page(pid, publication['parents'][pid])
            publication['attempted'].remove(pid)
            _checkpoint(fmt, checkpoint)
        except Exception as e:
            errors.append(f'{pid}: {str(e)[:120]}')
    if not errors:
        fmt.pop('publication', None)
    _checkpoint(fmt, checkpoint)
    return errors


def publish(fmt, mkts, page_of, checkpoint=None):
    """Move all pages or compensate every attempted move; persist recovery before side effects."""
    missing = [mk['key'] for mk in mkts if not page_of(fmt, mk['key'])]
    if missing:
        raise RuntimeError('publish: missing pages: ' + ', '.join(missing))
    previous = fmt.get('publication') or state.load('publication_journal.json', {}).get(fmt['id'])
    if previous:
        fmt['publication'] = previous
        errors = _rollback(fmt, checkpoint)
        if errors:
            raise RuntimeError('publish: rollback still pending: ' + '; '.join(errors))
    parents = {}
    for mk in mkts:
        pid = page_of(fmt, mk['key'])
        parent = notion.api('GET', f'/pages/{pid}').get('parent', {})
        if parent.get('type') != 'page_id' or not parent.get('page_id'):
            raise RuntimeError(f'publish: cannot safely restore parent for {pid}')
        parents[pid] = parent['page_id']
    fmt['publication'] = {'stage': 'moving', 'parents': parents, 'attempted': []}
    _checkpoint(fmt, checkpoint)
    for mk in mkts:
        pid = page_of(fmt, mk['key'])
        # A timed-out move may have succeeded remotely. Journal it before the request so recovery restores it too.
        fmt['publication']['attempted'].append(pid)
        _checkpoint(fmt, checkpoint)
        try:
            notion.move_page(pid, mk['holder_page'])
        except Exception as e:
            errors = _rollback(fmt, checkpoint)
            raise RuntimeError(f'publish: move failed: {e}; rollback ' +
                               ('pending: ' + '; '.join(errors) if errors else 'complete')) from e
    fmt['status'] = 'active'
    fmt.pop('pending', None)
    fmt.pop('archived_reason', None)
    fmt.pop('publication', None)
    fmt['list_repair_pending'] = {'reason': 'pages moved; lists still need updating'}
    _checkpoint(fmt, checkpoint)


def finish_listing(fmt, mkts, fmts, history, cfg, rerank, checkpoint=None):
    """Keep a successfully moved format active when listing fails; retry without undoing public list writes."""
    try:
        pos = rerank(mkts, fmts, history, cfg).index(fmt['id']) + 1
    except Exception as e:
        fmt['list_repair_pending'] = {'reason': str(e)[:200]}
        _checkpoint(fmt, checkpoint)
        return False, None, ['list update needs retry: ' + str(e)[:200]]
    fmt.pop('list_repair_pending', None)
    fmt['listed_at'] = int(time.time())
    _checkpoint(fmt, checkpoint)
    return True, pos, []


def has_unknown(fmt, mkts, meta):
    return (any(meta.get('audit', {}).get(f"{fmt['id']}:{mk['key']}") in ('unverified', 'error', None) for mk in mkts)
            or meta.get('group_audit', {}).get(fmt['id'], {}).get('status') == 'unverified')


def hold(fmt, reasons, kind, count_attempt=True):
    p = fmt.setdefault('pending', {'since': int(time.time()), 'tries': 0, 'kind': kind})
    p['tries'] += int(count_attempt)
    p['reasons'] = reasons
    fmt['status'] = 'pending'
    state.log({'type': 'format_held', 'format': fmt['id'], 'tries': p['tries'], 'reasons': reasons})


def retry_pending(fmts, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild, rerank):
    """Every run: formats waiting at the gate are checked again; published -> Slack, given up after MAX_TRIES."""
    checkpoint = lambda: (state.save('formats.json', fmts), state.save('meta.json', meta))
    for f in [f for f in fmts if f.get('status') == 'pending' or f.get('list_repair_pending')]:
        try:
            repair = f.get('status') == 'active' and f.get('list_repair_pending')
            ok, reasons = (True, []) if repair else check(f, mkts, cfg, history, accounts, meta, page_of, set_page, make_page, rebuild)
            if ok:
                if not repair:
                    publish(f, mkts, page_of, checkpoint)
                listed, pos, reasons = finish_listing(f, mkts, fmts, history, cfg, rerank, checkpoint)
                if not listed:
                    continue
                notify.push('✅ Format passed the check – now live', f"*{f['title']}* is now in all lists as #{pos} "
                            '(every language page checked: example, script, note, directions, title).')
                state.log({'type': 'format_published', 'format': f['id'], 'position': pos})
                continue
            count_attempt = not has_unknown(f, mkts, meta)
            hold(f, reasons, f.get('pending', {}).get('kind', 'new'), count_attempt=count_attempt)
            if count_attempt and f['pending']['tries'] >= MAX_TRIES:
                f['status'] = 'archived'
                f['archived_reason'] = 'did not pass the page check: ' + '; '.join(reasons)[:200]
                notify.push('❌ Format held back for good', f"*{f['title']}* did not pass the page check after "
                            f"{MAX_TRIES} runs:\n" + '\n'.join(reasons) + '\nIt stays in the archive and comes back if it '
                            'goes viral again.')
        except Exception as e:
            if f.get('status') == 'active':
                state.log({'type': 'publication_notification_error', 'format': f['id'], 'error': str(e)[:200]})
            else:
                hold(f, [str(e)[:200]], f.get('pending', {}).get('kind', 'new'), count_attempt=False)
        finally:
            state.save('formats.json', fmts)
            state.save('meta.json', meta)
