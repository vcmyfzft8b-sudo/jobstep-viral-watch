// Records each format's own demo (scenarios.json: what its JobStep example shows), at its length (±0.8 s), for every
// device, in one market language:
//   out/final/<Market>/formats/<FORMAT_ID>/Parakeet AI demo – <Mac|Windows|iPhone|Android>.mp4
//
//   node make_scenarios.mjs --lang sl                 every format in scenarios.json (skips existing, --redo again)
//   node make_scenarios.mjs --lang sl --only N02,X03  only these
//
// How: one take at pace 1 gives the length D and the part the pace stretches B; pace = 1 + (target − D) / B; a take
// more than 0.8 s off is recorded again with the pace corrected (twice at most).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const OUT = path.join(HERE, "out");
const APP = process.env.DEMO_APP ?? "http://localhost:3557";
const MARKETS = { fr: "France", es: "Spain", sl: "Slovenia" };
const DEVICES = { mac: "Mac", windows: "Windows", phone: "iPhone", android: "Android" };
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
};
const LANG = arg("lang", "sl");
const ONLY = arg("only", "") ? arg("only").split(",") : null;
const { formats } = JSON.parse(fs.readFileSync(path.join(HERE, "scenarios.json"), "utf8"));
let warm = false;

function take(id, device, pace) {
  const out = execFileSync(
    process.execPath,
    ["record.mjs", "--device", device, "--lang", LANG, "--scenario", id, "--pace", pace.toFixed(3), "--name", `sc-${id}`,
      ...(warm ? ["--no-warm"] : []), "--app", APP],
    { cwd: HERE, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
  );
  warm = true;
  const line = out.split("\n").find((l) => l.startsWith("CALIBRATION "));
  if (!line) throw new Error(`no calibration line for ${id} ${device}`);
  return { ...JSON.parse(line.slice(12)), file: path.join(OUT, `parakeet-ai-demo-${device}-${LANG}-sc-${id}.mp4`) };
}

const report = [];
for (const [id, sc] of Object.entries(formats)) {
  if (ONLY && !ONLY.includes(id)) continue;
  const dir = path.join(OUT, "final", MARKETS[LANG], "formats", id);
  fs.mkdirSync(dir, { recursive: true });
  for (const [device, label] of Object.entries(DEVICES)) {
    const final = path.join(dir, `Parakeet AI demo – ${label}.mp4`);
    if (fs.existsSync(final) && !process.argv.includes("--redo")) continue;
    const target = sc.seconds;
    let r;
    try {
      r = take(id, device, 1);
    let pace = Math.min(2.4, Math.max(0.45, 1 + (target - r.D) / Math.max(r.B, 1)));
    for (let i = 0; i < 3 && Math.abs(r.D - target) > 0.8; i++) {
      console.log(`  ${id} ${device}: ${r.D}s – again at pace ${pace.toFixed(2)}`);
      r = take(id, device, pace);
      pace = Math.min(2.4, Math.max(0.45, pace + ((target - r.D) * pace) / Math.max(r.B, 1))); // B = the stretched part at this pace
    }
    } catch (e) {
      console.log(`${id} ${device} ${LANG}: FAILED – ${e.message.split("\n")[0]}`);
      continue;
    }
    fs.copyFileSync(r.file, final);
    report.push({ id, device, lang: LANG, target, seconds: r.D, pace: r.pace });
    console.log(`${id} ${device} ${LANG}: ${r.D}s (target ${target}s, pace ${r.pace.toFixed(2)})${Math.abs(r.D - target) > 1 ? "  OFF" : ""}`);
  }
}
const reportFile = path.join(OUT, `scenarios_report_${LANG}.json`);
const old = fs.existsSync(reportFile) ? JSON.parse(fs.readFileSync(reportFile, "utf8")) : [];
fs.writeFileSync(reportFile, JSON.stringify([...old.filter((o) => !report.some((n) => n.id === o.id && n.device === o.device)), ...report], null, 1) + "\n");
console.log("ALL-DONE");
