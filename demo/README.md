# Parakeet AI demo recordings

The app demo creators play while filming, like the demo moments in the JobStep videos: a creator opens it on their
laptop or phone, plays it while they talk, and films the screen. Made the way the Memo AI demos are made
(`memo-viral-watch/demo`): a screen recording of the real app that moves like a person, with the device's own bars
around it.

Three lengths, because the JobStep examples show the app for very different times (measured 19 Oct 2026: top JobStep
videos 10–26 s, ~20 typical; our 14 live formats' examples 2–42 s):

| length | ~ | what it shows | for formats whose example shows the app |
|---|---|---|---|
| short | 12 s | upload → low score (19/50) → *cut* → all 4 AI changes accepted → *cut* → new score (92/100) | ≤ 12 s |
| standard | 20–24 s | upload → low score → template → colour → paste the job ad → 4 AI changes, card by card → page fit → new score | 13–27 s |
| long | 36–44 s | the standard flow at a relaxed pace, 8 AI changes and the AI's question (answered on laptops, passed on phones) | > 27 s |

`format_lengths.json` says which length each live format needs (its example's app seconds, device, markets).
Phones run a bit shorter than laptops (taps vs cursor travel), like in the JobStep videos.

Waiting screens (the app holds them ≥ 5 s) play sped up; the short version's middle and end are jump cuts, as the
creators cut their demos. Laptops: a real-size cursor on curved, uneven paths with a small overshoot, uneven pauses.
Phones: taps and a finger swipe on the template carousel. No sound (creators talk over it).

## Where they are

`out/final/<France|Spain|Slovenia>/` (French, Spanish (Spain), Slovenian app and CV), each length per device:
`Parakeet AI demo – <device> (<market>).mp4` (standard), `Parakeet AI demo (short) – …`, `Parakeet AI demo (long) – …`

| device | looks like | size |
|---|---|---|
| Mac | MacBook Pro 16", Safari bar with parakeet-ai.com, macOS cursor | 1920×1242 |
| Windows | 1080p laptop at 100 %, Chrome window with parakeet-ai.com, Windows cursor | 1920×1080 |
| iPhone | iPhone, iOS status bar + Safari address bar parakeet-ai.com | 1080×2342 |
| Android | Samsung Galaxy, Android status bar, Chrome address bar, gesture bar | 1080×2340 |

## On the Parakeet Drive

Uploaded 19 Oct 2026 to the Parakeet Google Drive (rclone remote `gdrive`, owner nace@parakeet-ai.com); every folder and
video: anyone with the link can view (user's request). Links: `drive_links.md`.
`Parakeet AI – Demo videos/<France|Spain|Slovenia>/`:

- one folder per published format page, named like the page (its title in that market), holding
  `Parakeet AI demo – iPhone|Android|Mac|Windows.mp4` in the length that format needs (`format_lengths.json`);
  the two hand-made "job in 2026" pages (France, Slovenia) count as ESX28 (short);
- `_All lengths/` – all 12 of the market (`Parakeet AI demo (short ~12 s|standard ~20 s|long ~40 s) – <device>.mp4`),
  for formats added later.

`drive_folders.json` maps every page (market, format, Megasheet idea id) to its folder, Drive folder id and link.
Uploading again: replace files in place (`rclone copyto` onto the same name) and run `rclone dedupe --dedupe-mode newest`
afterwards – Drive is slow to list new files, and a parallel copy once made duplicate folders/files.

## How it works

It records ParakeetAI's prod code (branch `main` of `ParakeetAI/parakeetai`), not the live site, so it needs no
account and runs no AI:

- `~/dev/parakeetai-demo` is a clone of `main` with one local commit (branch `demo/resume-maker-creator-demo`,
  never pushed): the route `/resumeMaker/demo` renders the real `UploadOnboarding` with a tRPC client whose every
  call is answered in the browser (`apps/web/src/lib/creatorDemo/api.ts`; `?long=1` = the long demo's 8 changes and
  question, else 4 changes). The "AI answers" are prepared per
  language in `apps/web/src/lib/creatorDemo/content/{fr,es,sl}.ts` and go through the app's own scoring and
  change-card code (`buildAtsScore`, `validateProposals`), so the numbers and cards are what prod would show.
  `apps/web/.env.local` holds placeholders only (no real keys).
- `samples.mjs` = the made-up people (Camille Laurent, Lucía Martín Gómez, Nina Kovač): their CV
  (`assets/CV_*.pdf`, `node samples.mjs` rebuilds them) and the job ad that gets pasted. The demo content files
  above say the same things.
- `record.mjs` drives Chromium (Playwright), captures the screencast, speeds up the waiting screens and draws the
  device bars. The button texts come from the app's own copy (`onboardingCopy.<lang>.ts`).

## Make them again

Needs the local copy running (`.claude/launch.json` → `parakeet-creator-demo`, port 3557; it runs
`next dev` with `SKIP_ENV_VALIDATION=1` and Node 24), and ffmpeg.

```bash
cd demo && npm install && npx playwright install chromium
node make_all.mjs                     # all 12 standard (skips ones already in out/, --redo records them again)
node make_all.mjs --length short      # all 12 short (--length long: all 12 long)
node make_all.mjs phone,android       # only the phones
node record.mjs --device mac --lang fr --length long --debug   # one take, screenshots of every step in out/
```

After a fresh server start, the first take compiles every screen (run one without `--no-warm`).
To update the app: `git -C ~/dev/parakeetai-demo pull --rebase origin main` (with the `nace-race` GitHub login),
then record again.
