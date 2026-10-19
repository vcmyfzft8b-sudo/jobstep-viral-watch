# JobStep viral watch – notes for Claude

Watches JobStep creators (TikTok) and turns their viral formats into Parakeet AI creator pages in four markets:
🇩🇪 DACH (`de`, campaign stopped 12 Oct 2026 – `enabled: false`), 🇫🇷 France (`fr`), 🇪🇸 Spain (`es`), 🇸🇮 Slovenia (`sl`,
since 15 Oct 2026). Runs every 2 hours on GitHub Actions (full every 6 h, light in between); state on the `state`
branch. Read README.md first. The Memo AI watcher (~/dev/memo-viral-watch) is a separate copy – never touch it from
here (repo, Notion, Discord, secrets, state are all separate).

## Rules
- Explain things to the user in very simple, short sentences.
- Work flow: branch + PR + merge. Run modes with `gh workflow run watch.yml -f mode=...`, one run at a time (wait
  until the queue is empty).
- Secrets: never write keys into the repo or GitHub yourself – the user saves them with `scripts/save_*.sh`.
- Never delete pages/data the user did not name; before any page rebuild list the user-made blocks first.
- Approved scripts (registry/approved_scripts.json) are locked – only change with the user's OK, then `apply-approved`.

## Script rules
- A script is the example video's own words (since 10 Oct 2026): same language -> transcript word for word, other
  language -> close translation. Only JobStep -> Parakeet AI (and missing features, scores -> X/Y) change. No
  rewording. Mode `align` re-transcribes every page.
- No stage directions (user's decision, 11 Oct 2026): a script holds only what is said (or the on-screen texts of a
  silent video). The only brackets are the link cues "(Parakeet AI · Resume Maker)" / LinkedIn and the 📎 material
  cues "(📎 … – siehe Ressourcen)". How to film, act and edit comes from the example video and the visual hook
  section. `brands.NO_DIRECTIONS` is in every writer/checker prompt (builder, align, audit, crosscheck judge +
  reference); there is no "direction" cue any more; `pages.script_paragraphs` strips bracketed tips; a 📎 cue that
  points to nothing in the resources is removed. Generated format references carry `rules` = `crosscheck.REF_RULES`
  and are rebuilt when it changes (reviewed ones never). `mode=strip-directions` cleans every page (old text in
  state/script_backup.json; approval-locked scripts only via the registry + `apply-approved`); `verify` flags leftovers.
- Visual hook section = one hook sentence (copy what the example does in its first seconds, or pick from the Visual
  Hook Lab) + the 🚨 line + the Visual Hook Lab link. Nothing else.
- The ⚠️ note under the inspiration video (markets.TEXT `inspo_note` / `inspo_note_same`): another brand's video, NOT
  the video to make – copy vibe, camera angles, filming, editing and the demo moments as closely as possible; film your
  own video from the script. The second line names no app ("another app is used – do the same with Parakeet AI").
  Keep the first ~30 characters of both variants (`localize.note_is_same` tells them apart). `mode=renote` puts the
  current text on every page; `verify` checks it.

## Modes added 11 Oct 2026
- `strip-directions` – bracketed tips leave every script (live, waiting, archived).
- `renote` – current note text on every page (old pages without a note under the video get one added).
- `refs` – generated format references rebuilt now where the script rules changed (else on their next check).
- `verify` – read-only: lists = live formats (numbered), every page: no stage directions, current note; live pages
  also video, TikTok link, Parakeet link, no JobStep, short hook section. Prints "VERIFY PROBLEMS: none" when clean.
- `export` – every script as one Markdown file, encrypted to state/scripts_export.enc (same key as the Memo export);
  read it with `scripts/read_export.sh`.

## Our formats and comebacks (12 Oct 2026)
- `registry/own_formats.json` = hand-checked format of every Spain/France video of ours up to 12 Oct (TikTok ids +
  Instagram `ig_<shortcode>`); `own.apply_hand_tags` applies it on every load and in tiers/ranking. Newer videos are
  sorted automatically as before.
- `main.own_comebacks`: archived + tier 1 for us in a running market -> pages move back to the format folders, status
  active (each normal run and `relist`). `lineup.never_revive` keeps formats out (X01 – user's choice, low signups).
- The Monday clean-up protects formats that are tier 1 for us.


## Alerts (12 Oct 2026)
- One Slack alert per video: only 🟢 VIRAL pings. 🟡 taking off goes on the Notion radar page only (user's request:
  no "taking off" today and "viral" tomorrow for the same video). A failed Claude check is retried quietly; after
  `main.JUDGE_TRIES` runs one basic alert, then no second one. add_format marks a watchlist video as alerted.

## Red card + old pages (12 Oct 2026)
- The red "going viral" card on each list holds only what goes viral NOW (`rank.going_viral`): JobStep-hot (5+ viral
  in 7 days) and not weak for us, or one of OUR videos in that market passed 100k in the last 7 days. Formats proven
  for us earlier come right under the card (user: only formats that really should be there).
- `mode=standardize` also rebuilds old hand-written pages (verify: no TikTok link / no Parakeet AI link / no script).
  Formats from our creators (no JobStep original) are rebuilt from our creators' best TikTok video of the format
  (`main.own_example`: that market's first) with the own note (`inspo_note_own`). Old text -> state/script_backup.json
  (`rebuild:<format>:<market>:<ts>`).
- Our creators' videos as examples: `localize.is_own_url` (handle in our own accounts) -> the own note everywhere
  (set_note, renote, audit); the brand count accepts "Parakeet AI" in our own source videos. `own_example` takes this
  market's video only if proven (>= localize.MIN_VIEWS), else the best of any market. `standardize` also builds a
  live format's missing market page (`missing_page`, checked before it is listed).

## Tidy rules + localisation (13 Oct 2026, user: "fix all problems and make sure they don't happen again")
- `watcher/tidy.py`, run on every normal run and as `mode=tidy`, checked by `verify`: one link cue of a kind per
  paragraph and at most 3 Parakeet AI cues per script (the renderer uses the same rule); a quoted on-screen text in the
  visual hook must be the 📲 title or a script line (else replaced by the title); title bold; page name = "<n>. <title>".
- `brands.LOCALISE` (in every writer and judge prompt): Spain pages in Spain Spanish (no LatAm words), market job
  sites (Spain InfoJobs; France France Travail / Welcome to the Jungle), dates/months made timeless. Since 16 Oct 2026
  (user: "a transcription, not shortened - change the app features and that is it") NOTHING else changes: the
  creator's details, numbers, claims and promises stay as said (no neutralising, no softening - writers and judges).

## Comebacks only with ready pages (15 Oct 2026)
- A format proven for our creators came back with no Spanish page and an old hand-written French page, and tidy
  renamed that page after a random bold line. Now `main.own_comebacks` first calls `main.ready_page` for every running
  market (missing page -> built + checked; old layout = `verify.layout_problems` -> rebuilt from its example video,
  old text in state/script_backup.json). Only when all pages are ready is the format listed; else it stays archived
  and is retried next run (`comeback_tries`; after `COMEBACK_TRIES` one Slack note, then only `mode=relist` retries).
- `tidy` never touches a page in the old layout (reports "old layout - not tidied"); `standardize` uses `ready_page`.

## The speaker stays (15 Oct 2026)
- The French page of the "Ex-HR" format said "Quelqu'un vient de quitter son job aux RH" for the original's "Ich hab
  grad meinen Job im HR gekündigt": LOCALISE (3) "neutral details" had been applied to the speaker. LOCALISE now says
  WHO speaks never changes (script and title, writers and judges). `brands.speaker_changed` checks it without Claude
  in `builder.validate` (script + title_hook), `align._validate` and `verify` (against formats.json `script`); the
  page judge's title_ok checks it too.
- `ready_page` rebuilds now go through `audit.fix_page` like new pages, and built/rebuilt pages are tidied at once
  (page name = new title). One page can be rebuilt with the workflow
  input `example=FORMAT_ID:market:rebuild`.

## Earlier formats, 2-hourly runs, failure notes (15 Oct 2026, user's choice)
- `detect` level `rising` (config thresholds.rising = 30k in 24 h; 4 of 5 reached 100k in our data, all 100k videos
  passed it): `handle_viral(rising=True)` builds a NEW format / brings back an archived one at once - the video's one
  Slack ping (notified rising + viral). A live format's video (or weak engagement / no video): only a 🚀 radar line;
  its Slack ping at 100k reuses the stored check (`v['verdict']`).
- Schedule every 2 h, MODE `auto` (`--auto`): full run when `meta.last_full_run` is ~6 h old (`is_light`), else light:
  new videos, full stats only for videos < 30 h or >= 50k (`LIGHT_DETAIL_VIEWS`), alerts. Skipped in light runs:
  sorting, re-judge, gate retry, own creators, Monday work, hot/re-sort, weekly report, discovery, tidy.
- Failures: steps that fail inside a run (`step_failed`) -> one Slack note (again only for other steps or after a
  day); no run for 12 h -> Slack note; a crashed/cancelled run -> Slack note from the workflow's last step.

## Slovenia (15 Oct 2026)
- Fourth market `sl` (Megasheet campaign *ParakeetAI - Slovenia*, Discord server 1560294285444780052). Its (old) Notion tree
  ("Navodila za ustvarjalce ParakeetAI SI" under ParakeetAI - EU) is a Notion copy of the France tree, translated into
  Slovenian; list/holder/Visual Hook Lab in `config.json → markets.sl`, archive = "Slovenia formats archive".
- `registry/market_adopt.json` maps each copied France format page to its Slovenian copy; `main.adopt_market_pages`
  (in `load_formats`) links them once (`pages.sl`, `adopted.sl`). The French example video is NOT copied into
  `inspo.sl`, so localize looks for a Slovenian JobStep video like for every market.
- Only JobStep formats in Slovenia (user, 15 Oct 2026: "nothing from Memo"): `markets.sl.skip_formats` keeps the
  study-app format A20261014173459 (hardest schools - @lern.mit.domi, also a Memo AI source) out for good;
  `markets.for_format` is used wherever pages are built, listed, audited or cross-checked. Its copy sits in the
  Slovenia archive. A future non-JobStep format that should stay out goes into that list too.
- Exception (user, 16 Oct 2026: "add the laptop"): A20261009204851 (laptop ad spot, also from @lern.mit.domi) IS on
  the Slovenian list - its page is built from its example video (`mode=fill-sl` = `--fill-market sl`, else the Monday
  run). Checked the same day: no other Slovenian format comes from a Memo AI source account.
- Slovenian letters (16 Oct 2026): `builder.validate` used to call č/š "non-Slovenian characters", so no Slovenian page
  could be BUILT (all live ones were copies). `builder.OWN_LETTERS['sl'] = 'čšž'` are allowed; ć/đ (Croatian/Serbian)
  and Polish/Czech letters still block. The language check's word pattern knows č/š/ž too.
- `markets.TEXT['sl']`: page headings NASLOV / 💬SCENARIJ / 🎬 VIZUALNI HOOK / 🔧 VIRI, notes, list texts.
  `discover.language` knows Slovenian (stopwords chosen so Croatian/Serbian accounts are not taken); when a market
  language is added, the next full run sorts the accounts without a language again (`meta.account_langs`).
- Slovenian job sites in `brands.LOCALISE`: MojeDelo, Zaposlitev.net, Zavod za zaposlovanje, LinkedIn.
- Discord announcements are off for Slovenia like France/Spain; a webhook can be saved with
  `scripts/save_discord_webhook.sh sl` (secret `DISCORD_WEBHOOK_URL_SI`).

## Saves decide (16 Oct 2026, user: "like Memo – conversion and virality both")
- `watcher/conversion.py` + `config.json → conversion`: the lists hold formats that CONVERT best (viewers save them)
  and still go viral. Score = conv × reach^0.5; conv = each video's save rate ÷ the typical rate of ITS market (creator
  language: accounts.json lang / meta.handle_lang; Spain ~2.8 %, France ~2 %, DACH ~0.6 %; < 10 measured videos → all
  markets), smoothed with 3 typical videos, recent weeks count most; reach = `rank.form`. Order inside each tier: hot
  (5+ viral in 7 days AND conv ≥ 1) → score → viral 7 d → viral 30 d.
- Paid ads (likes < 0.7 % of views, e.g. jobstep.io brand videos) are not measured and never build a format.
- Build gate (replaces the shares+saves 1.5 % rule): viral / rising needs saves ≥ 0.5 × market typical; level
  `converting` (30k+ views, 300+ saves, ≥ 2 % and ≥ 1.2 × market typical) builds like rising (its one Slack ping);
  an archived format comes back only with a video saved ≥ market typical; unknown saves → the alert waits ≤ 6 days.
- Proven for us (`own.tiers` tier 1) also needs our TikTok videos of it saved ≥ OUR creators' typical rate in that
  market (`conversion.own_rate` vs `conversion.own_typical`: median of our measured TikToks, 3k+ views, 60 days, ≥ 10
  videos, else views decide; Instagram = unknown). Not JobStep's rate (user, 16 Oct 2026): our videos are saved less
  overall (France ~1.1 % vs JobStep 2.3 %), and comparing with JobStep's rate took X06, our best French format, off
  the list. Saved less → tier 2 + `saves_low`. Our viral video counts for the red card only while the format is saved
  (not `saves_low`, conv ≥ 1).
- Monday clean-up: 2+ measured videos and score < 0.9 → archive, even when viral or new (protected: proven, hot,
  viral in 21 days with conv ≥ 1). History keeps likes/saves/shares (`conversion.record`); older videos are read 60 per
  full run (`read_saves`, then sorted into formats); `mode=conversion` reads up to 500 at once and prints every list.

## Only the best 12 per list (16 Oct 2026, user: "only the best converting and the most viral ones")
- Monday clean-up (`lineup.plan/apply`, also `mode=lineup` / `lineup-apply`): each running market's list keeps at most
  `lineup.list_size` = 12 formats by conversion score, PLUS in that market: proven for our creators (tier 1 = views AND
  saves), hot (5+ viral in 7 days, conv ≥ 1), the 3 most viral now (most JobStep 100k+ videos in 30 days, conv ≥ 1,
  `lineup.keep_most_viral`), the 3 best converting (highest conv with ≥ 3 measured videos, `keep_best_converting`) and
  pinned (`markets.<m>.pin_formats`; Slovenia: the laptop ad spot, user's choice). Viral-in-21-days and "new" no longer
  protect. `mode=lineup` shows each list with the reason for every format.
- Kept in no market → archived everywhere (`off_markets` cleared). Kept elsewhere only → that market's page moves to
  its archive and the market goes into the format's `off_markets`; `markets.for_format` then leaves it out there
  (list, pages, audit, crosscheck, tidy, localize, verify). Back among a market's best on a later Monday → page moves
  back, market removed from `off_markets`. New formats join right away (a list may exceed 12 until Monday).
- No ping-pong (16 Oct 2026, user: "bullet proof"): a viral / rising / converting video brings an archived format back
  or builds a new one only if `lineup.would_keep` says the format would stay on a list on Monday (the Monday plan played
  with it live and the video counted); else the alert says "would not stay on any list" (added by hand: always).
  The gate tidies every page of a held format before checking it (a hook quoting the title in other words held X06).

## 1:1 scripts and no duplicates (16 Oct 2026, user: "make sure it works in the future")
- Scripts are 1:1 with their example: `audit` length_ok is now 80 %-110 % of the example's words (135 % for a
  translation); before only "too long" failed, so French and Slovenian scripts cut to 25-60 % (Slovenia copied the
  French tree) passed. A failing page is re-transcribed from its example (`align.align_page`). `audit.RULES` is the
  rules version: when it changes, the next Monday audit checks EVERY page once (else only failed ones).
- The same format twice on a list (X16 + A202610061332 "I quit HR..."): `watcher/dupes.py` compares page titles per
  market (difflib ≥ 0.75). `lineup.merge_duplicates` (Monday before the cut, `mode=dedupe`) keeps the better score,
  archives the other as "duplicate of X" and its videos (history, own.json, hand tags via `own.aliases`) count for X.
  `gate.check` holds a new / revived format whose title matches a live one; `verify` reports pairs.
- Pure transcription (user, 16 Oct 2026: "transcribed and translated, not shortened - change the app features and that
  is it"): the only changes are the market language, JobStep → Parakeet AI (+ closest real feature), app scores → X/Y,
  market job sites and timeless dates (user kept those three). No softening of promises, no neutral details - writers
  (builder.TRANSCRIBE, brands.LOCALISE) and judges (audit, crosscheck) say so. `watcher/faithful.py` checks every live
  script against its video sentence by sentence (`mode=faithful-check` read-only, `mode=faithful-fix` transcribes the
  ones with changes again with the exact problems); the Monday run does faithful-fix and sends what is still off to Slack.

## Formats only in Megasheet (16 Oct 2026, user: "stop using Notion entirely" for the formats)
- The format pages and lists ARE Megasheet ideas now (`watcher/pages.py`); Notion is not read or written for formats
  any more (only the private radar log, `notify.radar` -> `watcher/notion.py`, needs NOTION_TOKEN). The old Notion
  pages stay in Notion (nothing deleted). The old copy step (`megasheet_formats.py`, modes megasheet-formats/-dry,
  the workflow step) and init-fr/init-es are gone.
- `pages.py` keeps the block interface every check uses (`children`, `api` PATCH/DELETE/insert, `create_page`,
  `replace_content`, `move_page`, `list_entries`, `set_order`): an idea is drawn as a page (video + TikTok link + ⚠️
  note, 📲 title + subtitle line, 💬 script paragraphs, 🎬 hook lines, 🔧 resources); every change is turned back into
  the idea's fields and sent at once - only fields that really changed (unchanged fields keep Megasheet's exact text).
  Nothing changed = nothing sent.
- `formats.json pages.<market>` = idea ids. Places in `state/pages.json` (`ideas.<id>`: market, place, fp, hand,
  media_ids, hand_media, keep_titles): `live` = published (on the list), `archive` / `staging` = archived (invisible).
  `markets.load` gives every market `list:<m>`, `live:<m>`, `archive:<m>`, `staging:<m>` (config has no Notion page
  ids any more). New pages are built as archived ideas in staging, the gate publishes them; a spec that fails its
  checks is not saved anywhere (no drafts).
- The list = our published ideas in Megasheet's order; `set_order` re-orders, puts the bold 🔥 hot_header line on
  the hot ones, publishes the listed ones and archives our others. Ideas made by hand in Megasheet stay after ours.
- Hand edits WIN (user, 16 Oct 2026): an idea whose content (or videos) differ from what the watcher last wrote
  (`fp`, read back from Megasheet at the end of each run) gets `hand` / `hand_media` and its content and videos are
  never written again (`pages.locked`; tidy, audit, align, faithful, localize, rebuilds skip it). Only its place in
  the list, the 🔥 line and published/archived follow the ranking. `verify` lists them.
- New example videos (local files) go up with `formats_createMediaUpload` (UploadThing grant -> POST + PUT).
  `megasheet.Client` allow-list: format ideas + their media of France/Spain/Slovenia only, ideas read/created in that
  campaign; never DACH, page settings, guides. DACH (stopped) keeps its Notion `page_id`s - restarting DACH needs work.
- One-time migration (`pages.migrate`, first load): every Notion page id with an idea in the old copy record
  (state/megasheet_formats.json) -> that idea id (16 Oct: fr 13, es 12, sl 12); others (archived formats, off-list
  pages without an idea) -> `notion_pages` (kept for reference). Such a format that comes back gets its page built
  from its example video (missing page). Old audit/crosscheck caches see new fingerprints -> everything is checked
  once more on the next Monday.
- Modes: `pages-dry` (read-only: re-sort + tidy with every write only printed, comebacks listed; must print ~0 writes),
  `verify` (reads Megasheet), every run prints "megasheet format writes: N". `test_video` builds an ARCHIVED
  "🧪 TEST –" idea (input "URL [market]", default fr) - delete it in Megasheet afterwards.
- One access token per process (`megasheet.access_token`, renewed once when refused).
- One update per fix (`pages.one_save` / `pages.batch`): align, directions, tidy, new example + note, asset cues and
  strip-directions send their changes to a page as ONE Megasheet update (creators never see a half-changed script).
- `monday-dry`: the whole Monday work (`main.monday_work`: clean-up, missing pages, examples, audit, 1:1 check,
  cross-country check) + re-sort with Claude, on a throw-away state copy, every Megasheet write / Slack message only
  printed. Rehearsed 16 Oct 2026: no step failed; it would make ~30 updates (real audit fixes: re-transcribed scripts,
  titles, hooks) and build NOTA UNIVERSIDAD's French + Slovenian pages (back among the best there).

## App demo recordings (19 Oct 2026, user: "like the JobStep videos, like the Memo AI demos")
- `demo/` records the Parakeet AI Resume Maker demo creators play and film (JobStep's demo moment: upload CV → low
  score → paste job ad → AI changes card by card → new high score), 4 devices (Mac, Windows, iPhone, Android) × 3
  markets (fr, es, sl): `demo/out/final/<France|Spain|Slovenia>/`. Built like `memo-viral-watch/demo` (human-like
  cursor/taps, device bars). See demo/README.md.
- Length = the JobStep demos' (user, 19 Oct 2026: "same length as the JobStep ones", "different length for different
  formats", "triple check"): each format's demo is within ±1 s of the app seconds in its example (re-measured twice);
  lengths 12/15/19/22/32/42 s, examples ≤ 12 s → 12 s (all 4 changes accepted). `demo/format_lengths.json`
  (`app_seconds`, `demo_seconds`), `demo/make_targets.mjs` records them (pace calibration in `demo/pace.json`).
- On the Parakeet Drive (rclone `gdrive`, anyone with the link can view): `Parakeet AI – Demo videos/<market>/<page
  title>/` with the 4 devices in the format's length, plus `_All lengths/`. `python3 demo/drive_sync.py` uploads (one
  at a time, in place) and checks every file by MD5; `demo/drive_folders.json` = page → folder, length, link;
  `demo/drive_links.md` = the list.
- It records ParakeetAI's prod code, not the live site (user: "do it with code", no browser sign-in): a local clone
  of `main` at `~/dev/parakeetai-demo` (local branch `demo/resume-maker-creator-demo`, never pushed) with
  `/resumeMaker/demo` answering every call in the browser from prepared content; no account, no AI. The repo is
  reachable with the `nace-race` GitHub login only.

## Demo recordings in the Slovenian scripts (19 Oct 2026, user: "one link per script, where they should start playing it")
- `watcher/demo.py`: a market whose `markets.TEXT` has `demo_cue` (only `sl` for now) gets ONE "(🎥 Tukaj predvajaj demo
  posnetek)" link cue in every live script, to the page's Drive folder from `demo/drive_folders.json` (by idea id, else
  format), right before the first Parakeet AI cue. tidy (`tidy.place_demo`) adds/moves/re-points it on every normal run
  and after rebuilds; trim_cues leaves it alone; judges never see it (spoken_text skips link labels); verify reports it.
- How to film it is the last line of the ⚠️ note (`demo_note`, added by `pages.inspo_note`; `mode=renote` puts it on
  the pages): download (not played in Drive), full screen without player controls, best played on a laptop and filmed
  as if clicking through the app, no laptop → phone recording as an overlay in the edit.
- Hand-edited ideas (pages.is_hand) are never written - their cue is added by hand. New format pages get a cue only
  once their folder exists: run `demo/drive_sync.py` (then commit drive_folders.json).
