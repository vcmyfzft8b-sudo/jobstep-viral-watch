// Records the demo at exact lengths – each live format gets the length its JobStep example shows the app
// (format_lengths.json → demo_seconds), within ±1 s, for every market language and device:
//   out/final/<France|Spain|Slovenia>/Parakeet AI demo (<n> s) – <Mac|Windows|iPhone|Android> (<market>).mp4
//
//   node make_targets.mjs                      every length format_lengths.json needs (12 s = the short version)
//   node make_targets.mjs --targets 15,42      only these
//   node make_targets.mjs --redo               record again even when the file exists
//
// How: a calibration take per version and device (French, pace 1) gives the video's length D and the part of it the
// pace stretches B (looks, holds, waiting screens). pace = 1 + (target − D) / B, choosing the version that needs the
// most natural pace (0.75–1.6, long 0.55–1.6): the whole flow, then with the plan/template/colour jump-cut, then also
// the job ad cut.
// A take more than 0.8 s off is recorded again with the pace corrected.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const OUT = path.join(HERE, "out");
const APP = process.env.DEMO_APP ?? "http://localhost:3557";
const LANGS = { fr: "France", es: "Spain", sl: "Slovenia" };
const DEVICES = { mac: "Mac", windows: "Windows", phone: "iPhone", android: "Android" };
const PACE_FILE = path.join(HERE, "pace.json");
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
};
const lengths = JSON.parse(fs.readFileSync(path.join(HERE, "format_lengths.json"), "utf8"));
const TARGETS = (arg("targets", "") || [...new Set(Object.values(lengths.formats).map((f) => f.demo_seconds))].join(","))
  .split(",")
  .map(Number)
  .sort((a, b) => a - b);
const calibration = fs.existsSync(PACE_FILE) ? JSON.parse(fs.readFileSync(PACE_FILE, "utf8")) : {};

function take({ device, lang, variant, content, pace, name }) {
  const out = execFileSync(
    process.execPath,
    ["record.mjs", "--device", device, "--lang", lang, "--variant", variant, "--content", content, "--pace", pace.toFixed(3), "--name", name, "--no-warm", "--app", APP],
    { cwd: HERE, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
  );
  const line = out.split("\n").find((l) => l.startsWith("CALIBRATION "));
  if (!line) throw new Error(`no calibration line for ${device} ${lang} ${name}`);
  return { ...JSON.parse(line.slice(12)), file: path.join(OUT, `parakeet-ai-demo-${device}-${lang}-${name}.mp4`) };
}

function calibrated(device, variant, content) {
  const key = `${content}/${variant}/${device}`;
  if (!calibration[key]) {
    console.log(`  calibrating ${key}`);
    const r = take({ device, lang: "fr", variant, content, pace: 1, name: `cal-${content}-${variant}` });
    calibration[key] = { D: r.D, B: r.B };
    fs.writeFileSync(PACE_FILE, JSON.stringify(calibration, null, 1) + "\n");
  }
  return calibration[key];
}

/** The version and pace for a target length on a device. */
function plan(target, device) {
  if (target <= 13) return { variant: "short", content: "standard", pace: 1 };
  const content = target >= 28 ? "long" : "standard";
  // the long version's looks are 1.8× the standard ones, so its pace may go lower and still read naturally
  const lowest = content === "long" ? 0.55 : 0.75;
  const tries = [];
  for (const variant of ["full", "designcut", "medium"]) {
    const { D, B } = calibrated(device, variant, content);
    const pace = 1 + (target - D) / B;
    tries.push({ variant, content, pace });
    if (pace >= lowest && pace <= 1.6) return tries.at(-1);
  }
  const best = tries.sort((a, b) => Math.abs(a.pace - 1) - Math.abs(b.pace - 1))[0];
  return { ...best, pace: Math.min(2, Math.max(0.55, best.pace)) };
}

const report = [];
for (const target of TARGETS) {
  for (const [device, label] of Object.entries(DEVICES)) {
    const p = plan(target, device);
    for (const [lang, market] of Object.entries(LANGS)) {
      const dir = path.join(OUT, "final", market);
      fs.mkdirSync(dir, { recursive: true });
      const final = path.join(dir, `Parakeet AI demo (${target} s) – ${label} (${market}).mp4`);
      if (fs.existsSync(final) && !process.argv.includes("--redo")) continue;
      let r;
      if (target <= 13) {
        // the short version: all four changes accepted, ~12 s (user's choice for formats that only show a glimpse)
        r = take({ device, lang, ...p, name: `${target}s` });
      } else {
        let pace = p.pace;
        r = take({ device, lang, ...p, pace, name: `${target}s` });
        for (let i = 0; i < 2 && Math.abs(r.D - target) > 0.8; i++) {
          pace = Math.min(2.2, Math.max(0.5, pace + (target - r.D) / Math.max(r.B, 1)));
          console.log(`  ${device} ${lang} ${target}s was ${r.D}s – again at pace ${pace.toFixed(2)}`);
          r = take({ device, lang, ...p, pace, name: `${target}s` });
        }
      }
      fs.copyFileSync(r.file, final);
      report.push({ target, device, lang, variant: p.variant, content: p.content, pace: +r.pace.toFixed(3), seconds: r.D });
      console.log(`${target}s ${device} ${lang}: ${r.D}s (${p.variant}, ${p.content}, pace ${r.pace.toFixed(2)})`);
    }
  }
}
const reportFile = path.join(OUT, "targets_report.json");
const old = fs.existsSync(reportFile) ? JSON.parse(fs.readFileSync(reportFile, "utf8")) : [];
const merged = [...old.filter((o) => !report.some((n) => n.target === o.target && n.device === o.device && n.lang === o.lang)), ...report];
fs.writeFileSync(reportFile, JSON.stringify(merged, null, 1) + "\n");
console.log("ALL-DONE");
