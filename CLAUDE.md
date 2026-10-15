# JobStep viral watch – notes for Claude

Watches JobStep creators (TikTok) and turns their viral formats into Parakeet AI creator pages in three markets:
🇩🇪 DACH (`de`, campaign stopped 12 Oct 2026 – `enabled: false`), 🇫🇷 France (`fr`), 🇪🇸 Spain (`es`). Runs every 6 hours on GitHub Actions; state on the `state`
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
  sites (Spain InfoJobs; France France Travail / Welcome to the Jungle), and details only the original creator can say
  (their industry, a salary) become neutral. Allowed by the judges, so it is never "reworded" back.

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
- `ready_page` rebuilds now go through `audit.fix_page` like new pages. One page can be rebuilt with the workflow
  input `example=FORMAT_ID:market:rebuild`.
