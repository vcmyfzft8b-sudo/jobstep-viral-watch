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
  reference); there is no "direction" cue any more; `notion.script_paragraphs` strips bracketed tips; a 📎 cue that
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
- Fourth market `sl` (Megasheet campaign *ParakeetAI - Slovenia*, Discord server 1560294285444780052). Its Notion tree
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

## Formats in Megasheet (16 Oct 2026, user: "the list changes up on what to make" in Megasheet)
- Creators read the formats in the Megasheet portal. Notion stays where the watcher builds, checks, tidies and orders
  pages; `watcher/megasheet_formats.py` copies each running market's Notion list into its campaign
  (`megasheet.CAMPAIGNS`) as its own workflow step after every run (never fails the run; Slack note at most once a day).
- One idea per page on the list, same order; hot formats (red card) first with a bold 🔥 hot_header line; title,
  script, visual hook (lab link dropped - the Visual Hook Lab is a guide on the same Megasheet page), ⚠️ note,
  resources and the example video come from the page. Ideas are compared with the page every run - only differences
  are sent (hand edits in Megasheet are put back: Notion is the source). Off the list -> archived (never deleted),
  back on the list -> the same idea published again. Hand-made Megasheet ideas are left alone, after ours.
- First copy of a campaign: ideas with the same title (the 15 Oct one-time import) are taken over (same example video
  = same file size -> not uploaded again), the other published ones archived. Titles used by creators' videos cannot
  be removed: they stay after ours (`keep_titles`). State: state/megasheet_formats.json (ids only).
- Needs the Megasheet login with write access (`mcp:write`, since 16 Oct 2026): `scripts/save_megasheet_login.sh`.
  Megasheet only has read / read+write-everything logins, so `megasheet.Client` limits it (user: "only write access
  for the formats, nothing else"): READ_TOOLS, WRITE_TOOLS (format ideas + their media only) and WRITE_CAMPAIGNS
  (France, Spain, Slovenia ids - never DACH); a write must name the campaign and may only touch ideas/media read from
  or created in it. Anything else raises `NotAllowed` before it is sent. DACH is never copied (`COPY_MARKETS`).
- Modes: `megasheet-formats` (only the copy), `megasheet-formats-dry` (prints what would change). DACH is not copied
  while the market is off. Page intro/rules/footer, the Visual Hook Lab guide and hook videos are campaign settings
  in Megasheet (set by hand, not by the watcher).
