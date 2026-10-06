# JobStep viral watch

Every 6 hours (GitHub Actions) this watcher:

1. **Pulls every new video** posted by all active JobStep creator accounts (89 on 6 Oct 2026, list in the `state`
   branch → `state/accounts.json`) and keeps each video on a 7-day watchlist.
2. **Re-checks every watchlist video** (views, likes, shares, saves) and stores a snapshot, so growth over time is known.
3. **Alerts** (phone push via [ntfy](https://ntfy.sh) + a log line on the private Notion page *JobStep Viral-Radar*):
   - 🟡 **taking off** – 5k views within 6 h, 20k within 24 h, 50k within 48 h, or 10× the creator's usual views
   - 🟢 **viral** – 100k+ views
   - "weak" is added when shares + saves are below 1.5 % of views
4. **Builds a new format page** when a viral video (good engagement) uses a format that is not on the DACH
   instructions page yet:
   video download → Soniox transcription → frames → Claude writes the German page (casual German, JobStep → Parakeet AI,
   Parakeet links at every app moment, title, visual hook, resources) → automatic checks → Notion page in exactly the
   same layout as the existing ones → added to the numbered list at its ranked position.
   If a check fails (e.g. "JobStep" left in the text, not German, script length off by more than 25 %), the page is
   created as a private draft on the radar page instead and you get a notification with the reason.
5. **Every 3 days – complete account list**: Lightreel is asked for every account promoting JobStep; each new handle
   is verified on TikTok (posted in the last 30 days + JobStep in captions or videos) and added. Accounts without
   JobStep posts for 30 days are paused and re-checked every 3 days, so they come back automatically. You get a push
   when new accounts are added.
6. **Weekly (Monday)**: re-ranks the DACH list from the data (share of videos with 100k+ and 20k+ views per format,
   smoothed for small samples, German creators count double).

## Setup

1. Secrets (run once on your Mac – reads the keys from your local `.env` files, prints nothing but the ntfy topic):
   ```
   ./scripts/set_secrets.sh
   ```
   | Secret | Used for |
   |---|---|
   | `NOTION_TOKEN` | writing format pages, the list and the radar log |
   | `OPENROUTER_API_KEY` | Claude (format matching: Sonnet 5.5, page writing: Opus 5.5) |
   | `SONIOX_API_KEY` | speech-to-text |
   | `NTFY_TOPIC` | phone push notifications (subscribe to the topic in the ntfy app) |
   | `LIGHTREEL_API_KEY` | finding new JobStep accounts every 3 days |
2. The `state` branch holds the watchlist, history and format registry; the workflow commits to it after every run.

## Run manually

GitHub → Actions → *JobStep viral watch* → Run workflow (`normal`, `only-detect`, `dry-run`).

Locally: `STATE_DIR=/tmp/state python -m watcher.main --dry-run` (needs the same environment variables).

## Files

- `watcher/tiktok.py` – creator embed (latest videos) + video page (stats, on-screen text, subtitles)
- `watcher/detect.py` – taking off / viral rules
- `watcher/classify.py` – existing format or new one (Claude)
- `watcher/soniox.py`, `watcher/media.py` – transcription, download, frames
- `watcher/builder.py` – German page spec + checks
- `watcher/notion.py` – page layout, video upload, numbered list
- `watcher/rank.py` – list order
- `registry/formats.json` – the formats on the DACH page (copied into the state branch on first run)
