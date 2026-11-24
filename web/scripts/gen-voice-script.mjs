// Generates packages/falcon_core/src/falcon_core/i18n/voice_script.yaml and docs/VOICE_SCRIPT_REVIEW.md
// from web/lib/voice-script.ts (the source of truth). Run: node scripts/gen-voice-script.mjs  (Node 22.6+ strips types).
// `--check` fails if the generated files are out of date.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { CLIPS, SCRIPT, SCRIPT_KEYS, VOICE_LANGS } from "../lib/voice-script.ts";

const yamlOut = fileURLToPath(new URL("../../packages/falcon_core/src/falcon_core/i18n/voice_script.yaml", import.meta.url));
const docOut = fileURLToPath(new URL("../../docs/VOICE_SCRIPT_REVIEW.md", import.meta.url));
const q = (s) => JSON.stringify(s); // a JSON string is a valid YAML double-quoted scalar

const y = [
  "# GENERATED from web/lib/voice-script.ts by web/scripts/gen-voice-script.mjs. Do not edit by hand.",
  "# Every SPOKEN line of the Hey Falcon assistant. ar_ae = Emirati spoken Arabic (screen text stays formal MSA).",
  "# Every spoken output is a concatenation of the clips below; ids are stable: <lang>.<key>.",
  "version: 1",
  `clip_count: ${CLIPS.length}`,
  "languages: [ar_ae, en]",
];
for (const lang of VOICE_LANGS) {
  y.push(`${lang}:`);
  for (const key of SCRIPT_KEYS) y.push(`  ${q(key)}: ${q(SCRIPT[lang][key])}`);
}
y.push("clips:");
for (const c of CLIPS) y.push(`  - {id: ${q(c.id)}, lang: ${c.lang}, text: ${q(c.text)}}`);

const esc = (s) => s.replace(/\|/g, "\\|");
const d = [
  "# Voice script review (Emirati Arabic)",
  "",
  "<!-- GENERATED from web/lib/voice-script.ts by web/scripts/gen-voice-script.mjs. Edit the script, not this file. -->",
  "",
  "For a native Emirati reviewer. Left: the line the assistant SPEAKS. Right: its English meaning. Please mark the last column",
  "`OK`, or write the correction. Screen text stays formal Arabic and is not part of this review.",
  "Rules for the lines: short, natural Emirati speech, respectful to an elderly listener, never the word for \"safe\",",
  "never asking for personal, bank or ID details, no phone numbers.",
  "",
  `Lines: ${SCRIPT_KEYS.length}. Digits are written out in words (\`num.0\` to \`num.100\`).`,
  "",
  "| Emirati line | English meaning | Reviewer / OK |",
  "|---|---|---|",
  ...SCRIPT_KEYS.map((k) => `| ${esc(SCRIPT.ar_ae[k])} | ${esc(SCRIPT.en[k])} |  |`),
  "",
];

const yText = `${y.join("\n")}\n`;
const dText = d.join("\n");
if (process.argv.includes("--check")) {
  if (readFileSync(yamlOut, "utf8") !== yText || readFileSync(docOut, "utf8") !== dText) {
    console.error("voice_script.yaml / VOICE_SCRIPT_REVIEW.md are out of date: run node scripts/gen-voice-script.mjs");
    process.exit(1);
  }
} else {
  writeFileSync(yamlOut, yText);
  writeFileSync(docOut, dText);
}
console.log(`clips: ${CLIPS.length} (${SCRIPT_KEYS.length} per language)`);
