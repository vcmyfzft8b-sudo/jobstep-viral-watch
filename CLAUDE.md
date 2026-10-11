# JobStep viral watch – notes for Claude

Watches JobStep creators (TikTok) and turns their viral formats into Parakeet AI creator pages in three markets:
🇩🇪 DACH (`de`), 🇫🇷 France (`fr`), 🇪🇸 Spain (`es`). Runs every 6 hours on GitHub Actions; state on the `state`
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
- `renote` – current note text on every page.
- `verify` – read-only: lists = live formats (numbered), every page: no stage directions, current note; live pages
  also video, TikTok link, Parakeet link, no JobStep, short hook section. Prints "VERIFY PROBLEMS: none" when clean.
- `export` – every script as one Markdown file, encrypted to state/scripts_export.enc (same key as the Memo export);
  read it with `scripts/read_export.sh`.
