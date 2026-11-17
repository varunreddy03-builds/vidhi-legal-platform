// Writes one review sheet per language to docs/translation-review/<code>.csv (columns: key, english, translation, ok, correction).
// Give the sheet to a native speaker; they fill "ok" (yes/no) and "correction". Run:  node scripts/export-translations.mjs
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
const dir = "frontend/src/lib/i18n";
const parse = (file) => {
  const out = new Map();
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/);
    if (m) out.set(m[1], JSON.parse(`"${m[2]}"`));
  }
  return out;
};
const en = parse(`${dir}/en.ts`);
const q = (s) => `"${String(s).replaceAll('"', '""')}"`;
mkdirSync("docs/translation-review", { recursive: true });
let n = 0;
for (const f of readdirSync(`${dir}/locales`).filter((x) => x.endsWith(".ts"))) {
  const code = f.slice(0, -3);
  const tr = parse(`${dir}/locales/${f}`);
  const rows = ["key,english,translation,ok (yes/no),correction"];
  for (const [k, v] of tr) rows.push([k, en.get(k) ?? "", v, "", ""].map(q).join(","));
  writeFileSync(`docs/translation-review/${code}.csv`, "\ufeff" + rows.join("\r\n") + "\r\n");
  n++;
}
console.log(`wrote ${n} sheets`);