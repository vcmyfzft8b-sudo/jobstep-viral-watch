# Parakeet AI demo recordings

The app demo creators play while filming, like the demo moments in the JobStep videos: a creator opens it on their
laptop or phone, plays it while they talk, and films the screen. Made the way the Memo AI demos are made
(`memo-viral-watch/demo`): a screen recording of the real app that moves like a person, with the device's own bars
around it.

Each format gets the length its JobStep example shows the app (measured twice, 19 Oct 2026, 1 frame per second:
examples 2–42 s). Lengths: **12, 15, 19, 22, 32, 42 s** – every format within ±1 s of its example; examples
showing the app ≤ 12 s get the 12 s version, which still accepts all 4 changes (user's choice).
`format_lengths.json` → `app_seconds` (example) and `demo_seconds` (its demo).

| length | what it shows |
|---|---|
| 12 s | upload → low score (19/50) → *cut* → all 4 AI changes → *cut* → new score (92/100) |
| 15 s | upload → low score → *cut* (laptops: also the job ad) → 4 AI changes → page fit → rescoring → new score |
| 19 s / 22 s | the whole flow with 4 AI changes (19 s on laptops: the plan/template/colour step jump-cut) |
| 32 s / 42 s | 8 AI changes and the AI's question (answered on laptops, passed on phones); 32 s on laptops with the plan/template/colour step cut |

`make_targets.mjs` makes them: a calibration take per version and device gives the length and the part the pace
stretches (`pace.json`); each take is recorded with the pace that hits the target and again if it is > 0.8 s off.
Every video checked: within ±1 s of its target.

Waiting screens (the app holds them ≥ 5 s) play sped up; the short version's middle and end are jump cuts, as the
creators cut their demos. Laptops: a real-size cursor on curved, uneven paths with a small overshoot, uneven pauses.
Phones: taps and a finger swipe on the template carousel. No sound (creators talk over it).

## Where they are

`out/final/<France|Spain|Slovenia>/Parakeet AI demo (<n> s) – <Mac|Windows|iPhone|Android> (<market>).mp4`

| device | looks like | size |
|---|---|---|
| Mac | MacBook Pro 16", Safari bar with parakeet-ai.com, macOS cursor | 1920×1242 |
| Windows | 1080p laptop at 100 %, Chrome window with parakeet-ai.com, Windows cursor | 1920×1080 |
| iPhone | iPhone, iOS status bar + Safari address bar parakeet-ai.com | 1080×2342 |
| Android | Samsung Galaxy, Android status bar, Chrome address bar, gesture bar | 1080×2340 |

## On the Parakeet Drive

The Parakeet Google Drive (rclone remote `gdrive`, owner nace@parakeet-ai.com), every folder and video: anyone with the
link can view. `Parakeet AI – Demo videos/<France|Spain|Slovenia>/`:

- one folder per published format page, named like the page, with `Parakeet AI demo – iPhone|Android|Mac|Windows.mp4`
  in that format's `demo_seconds` (the two hand-made "job in 2026" pages count as ESX28);
- `_All lengths/Parakeet AI demo (<n> s) – <device>.mp4` – every length, for formats added later.

`python3 demo/drive_sync.py` uploads what changed (one file at a time, in place, so links stay), moves unused
`_All lengths` files to the Drive trash, dedupes, and checks every file against Drive's MD5 and sharing; it writes
`drive_folders.json` (page → folder, length, link) and `drive_links.md`. `--check` only checks.

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
node make_targets.mjs                 # every length format_lengths.json needs (skips existing, --redo again)
node make_targets.mjs --targets 15,42 # only these lengths
python3 drive_sync.py                 # then put them on Drive and check
node record.mjs --device mac --lang fr --length long --debug   # one take, screenshots of every step in out/
```

After a fresh server start, the first take compiles every screen (run one without `--no-warm`).
To update the app: `git -C ~/dev/parakeetai-demo pull --rebase origin main` (with the `nace-race` GitHub login),
then record again.
