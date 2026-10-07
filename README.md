# JobStep viral watch

Every 6 hours (GitHub Actions) this watcher:

1. **Pulls every new video** posted by all active JobStep creator accounts (89 on 6 Oct 2026, list in the `state`
   branch → `state/accounts.json`) and keeps each video on a 7-day watchlist.
2. **Re-checks every watchlist video** (views, likes, shares, saves) and stores a snapshot, so growth over time is known.
3. **Alerts** (Slack message via `SLACK_WEBHOOK_URL`, optional phone push via ntfy, + a log line on the private Notion page *JobStep Viral-Radar*):
   - 🟡 **taking off** – 5k views within 6 h, 20k within 24 h, 50k within 48 h, or 10× the creator's usual views
   - 🟢 **viral** – 100k+ views (counts the moment it gets there – after 1 day or 6 hours – as long as the video is from the last 7 days)
   - "weak" is added when shares + saves are below 1.5 % of views
4. **Builds a new format page** when a viral video (good engagement) uses a format that is not on the DACH
   instructions page yet:
   video download → Soniox transcription → frames → Claude writes the German page (casual German, JobStep → Parakeet AI,
   Parakeet links at every app moment, title, visual hook, resources) → automatic checks → Notion page in exactly the
   same layout as the existing ones → added to the numbered list at its ranked position.
   If a check fails (e.g. "JobStep" left in the text, not German, script length off by more than 25 %), the page is
   created as a private draft on the radar page instead and you get a notification with the reason.
5. **Hot formats**: every format with 5+ viral videos posted in the last 7 days gets a 🚀 box at the top of the DACH
   list (several formats possible) and one German @everyone announcement in the DACH Discord #announcements.
6. **Every 3 days – complete account list**: Lightreel is asked for every account promoting JobStep; each new handle
   is verified on TikTok (posted in the last 30 days + JobStep in captions or videos) and added. Accounts without
   JobStep posts for 30 days are paused and re-checked every 3 days, so they come back automatically. You get a push
   when new accounts are added.
7. **Weekly (Monday)**: re-ranks the DACH list from the data (share of videos with 100k+ and 20k+ views per format,
   smoothed for small samples, German creators count double).

## Setup

1. Secrets (run once on your Mac – reads the keys from your local `.env` files, prints nothing but the ntfy topic):
   ```
   ./scripts/set_secrets.sh
   ```
   | Secret | Used for |
   |---|---|
   | `NOTION_TOKEN` | writing format pages, the list and the radar log |
   | `CLAUDE_CODE_OAUTH_TOKEN` | Claude via Claude Code on your Claude subscription (create once with `claude setup-token`) – sorting: Sonnet, duplicate check + page writing: Opus |
   | `SONIOX_API_KEY` | speech-to-text |
   | `SLACK_WEBHOOK_URL` | Slack messages (Incoming Webhook of a Slack app, one channel) |
| `NTFY_TOPIC` | optional phone push via the ntfy app |
   | `LIGHTREEL_API_KEY` | finding new JobStep accounts every 3 days |
2. The `state` branch holds the watchlist, history and format registry; the workflow commits to it after every run.

## Run manually

GitHub → Actions → *JobStep viral watch* → Run workflow (`normal`, `only-detect`, `dry-run`).

Locally: `STATE_DIR=/tmp/state python -m watcher.main --dry-run` (needs the same environment variables).

## Page quality checks

New and missing language pages remain in staging until their audit passes. Unavailable source evidence is
`unverified`, never a pass, and does not exhaust the four quality-rejection attempts. Successful audit results
are tied to live page content; external edits and changes during an audit require another check. Each completed
page audit saves its state immediately.

`registry/approved_scripts.json` locks exact approved scripts and their examples. Automation can restore the
approved rendering but cannot rewrite it or replace its example. Source-aligned scripts have at most 110% of the
source word count and preserve spoken brand mentions; linked filming cues do not count as speech.

`registry/verified_embedded_examples.json` records reviewed evidence pinned to the video block ID and
edit timestamp. A record with `source_url` additionally requires that exact live TikTok source and a verified live
view count. Public subtitles are fetched at runtime; the registry stores only narrow verified ASR corrections,
not full third-party transcripts. Missing subtitles or a correction that no longer matches require review. An explicitly
recorded `legacy_original_unavailable` exemption is supported for uploads without a known source; it records unknown
views without claiming a view threshold was met. The SHA-256 is provenance, not a substitute for the live pins.
Replacing the upload or changing its known source requires new evidence.

State pushes retry the same non-force push four times. A failed push leaves a GitHub Actions recovery artifact
containing only the state directory; restore it after reviewing concurrent state, without overwriting other work.

Offline regression checks (no Notion, Claude or other live service calls):

```sh
python -m unittest discover -s tests -v
```

## Files

- `watcher/tiktok.py` – creator embed (latest videos) + video page (stats, on-screen text, subtitles)
- `watcher/detect.py` – taking off / viral rules
- `watcher/classify.py` – existing format or new one (Claude)
- `watcher/soniox.py`, `watcher/media.py` – transcription, download, frames
- `watcher/builder.py` – German page spec + checks
- `watcher/notion.py` – page layout, video upload, numbered list
- `watcher/rank.py` – list order
- `registry/formats.json` – the formats on the DACH page (copied into the state branch on first run)

## Cross-country format check

`watcher/crosscheck.py` compares the three countries of every format **together** against the format's reference
definition in `registry/format_references.json` (hook and premise, ordered story beats, filming and demonstration
sequence, product introduction with spoken brand/URL placement and CTA, allowed localisation differences). Results are
reported separately per dimension and country: format consistency, script matching its example, independent
wording, Parakeet features and claims, filming directions; approval-lock status is reported on its own and never
counts as a pass.

- A group result is cached under a key built from all three pages' content fingerprints, their example source IDs,
  the SHA-256 of the uploaded example videos, the reference definition and `AUDIT_VERSION`; any change invalidates it.
- Missing evidence (no page, unreadable example, unknown video bytes, no reference) makes the group `unverified`.
- The same source video or uploaded video under different format IDs is flagged as a possible duplicate (never deleted).
- New and changed groups stay in staging (quality gate) until the group passes. Failing groups are repaired
  automatically where allowed (canonical example, independently worded rewrite, directions); approval-locked scripts
  are only reported for approval.
- Modes: `group-audit` (report), `group-audit-force` (ignore cache), `group-fix` (repair + re-check). The Monday run
  does the cached check with repairs.
