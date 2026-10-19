# Parakeet AI demo recordings

The app demo creators play while filming, like the demo moments in the JobStep videos: a creator opens it on their
laptop or phone, plays it while they talk, and films the screen. Made the way the Memo AI demos are made
(`memo-viral-watch/demo`): a screen recording of the real app that moves like a person, with the device's own bars
around it.

The walkthrough is JobStep's demo, in Parakeet AI's Resume Maker (the real Upload Resume flow):

1. "Make every application count" → upload the CV (a made-up, weak "before" CV)
2. reading + scoring → the low score (19/50) next to the uploaded CV
3. the plan → a template (Modern) → a colour (green)
4. paste the job ad → the AI rewrites the CV
5. review the changes card by card (the CV updates on the right); the AI asks one question – answered on laptops
   ("+1 200 followers in 5 months"), passed on phones
6. "Review complete" → page fit → rescoring → the new score: the gauge climbs from 46 to ~92/100, "Download"

Waiting screens play 3× faster. Laptops: a real-size cursor on curved, uneven paths with a small overshoot, uneven
pauses. Phones: taps and a finger swipe on the template carousel. No sound (creators talk over it).

## Where they are

`out/final/<France|Spain|Slovenia>/` (French, Spanish (Spain), Slovenian app and CV):

| file | looks like | size |
|---|---|---|
| `Parakeet AI demo – Mac (…).mp4` | MacBook Pro 16", Safari bar with parakeet-ai.com, macOS cursor | 1920×1240 |
| `Parakeet AI demo – Windows (…).mp4` | 1080p laptop at 100 %, Chrome window with parakeet-ai.com, Windows cursor | 1920×1080 |
| `Parakeet AI demo – iPhone (…).mp4` | iPhone, iOS status bar + Safari address bar parakeet-ai.com | 1080×2342 |
| `Parakeet AI demo – Android (…).mp4` | Samsung Galaxy, Android status bar, Chrome address bar, gesture bar | 1080×2340 |

## How it works

It records ParakeetAI's prod code (branch `main` of `ParakeetAI/parakeetai`), not the live site, so it needs no
account and runs no AI:

- `~/dev/parakeetai-demo` is a clone of `main` with one local commit (branch `demo/resume-maker-creator-demo`,
  never pushed): the route `/resumeMaker/demo` renders the real `UploadOnboarding` with a tRPC client whose every
  call is answered in the browser (`apps/web/src/lib/creatorDemo/api.ts`). The "AI answers" are prepared per
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
node make_all.mjs                 # all 12 (skips ones already in out/, --redo records them again)
node make_all.mjs phone,android   # only the phones
node record.mjs --device mac --lang fr --debug   # one take, screenshots of every step in out/
```

After a fresh server start, the first take compiles every screen (run one without `--no-warm`).
To update the app: `git -C ~/dev/parakeetai-demo pull --rebase origin main` (with the `nace-race` GitHub login),
then record again.
