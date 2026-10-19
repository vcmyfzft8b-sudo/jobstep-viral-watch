// Records every demo – one per market language and device:
//   out/final/<France|Spain|Slovenia>/Parakeet AI demo – <Mac|Windows|iPhone|Android> (<market>).mp4
//   node make_all.mjs                 all 12 (skips ones already in out/, --redo records them again)
//   node make_all.mjs phone,android   only those devices
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const RAW = path.join(HERE, "out");
const APP = process.env.DEMO_APP ?? "http://localhost:3557";
const LANGS = { fr: "France", es: "Spain", sl: "Slovenia" };
const DEVICES = { mac: "Mac", windows: "Windows", phone: "iPhone", android: "Android" };
const pick = process.argv.slice(2).find((a) => !a.startsWith("--"));
const devices = pick ? pick.split(",") : Object.keys(DEVICES);
const failed = [];

for (const lang of Object.keys(LANGS)) {
  for (const device of devices) {
    const file = path.join(RAW, `parakeet-ai-demo-${device}-${lang}.mp4`);
    if (fs.existsSync(file) && !process.argv.includes("--redo")) continue;
    console.log(`=== ${lang} ${device}`);
    try {
      execFileSync(process.execPath, ["record.mjs", "--device", device, "--lang", lang, "--no-warm", "--app", APP], {
        cwd: HERE,
        stdio: "inherit",
      });
    } catch {
      failed.push(`${lang} ${device}`);
    }
  }
}

for (const [lang, market] of Object.entries(LANGS)) {
  const dir = path.join(RAW, "final", market);
  fs.mkdirSync(dir, { recursive: true });
  for (const [device, label] of Object.entries(DEVICES)) {
    const src = path.join(RAW, `parakeet-ai-demo-${device}-${lang}.mp4`);
    if (fs.existsSync(src)) fs.copyFileSync(src, path.join(dir, `Parakeet AI demo – ${label} (${market}).mp4`));
  }
}
console.log(failed.length ? `FAILED: ${failed.join(", ")}` : "no failures");
console.log("ALL-DONE");
