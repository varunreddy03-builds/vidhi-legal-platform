"""Which of the 22 languages still show English on each screen, and what share of each screen's text is translated. Reads the source only; calls nothing and translates nothing.

  python scripts/i18n_coverage.py [--out-dir docs/translation]

For every page in frontend/src/pages it follows the components the page imports, collects (a) the translation keys it uses (any string equal to a key of lib/i18n/en.ts) and (b) text typed
straight into the screen without a key (counted by a pattern, so approximate: the real number is usually a little higher, never lower for plain JSX text). A language shows English
for a key it has no entry for (the app falls back to English), and always for text typed without a key. Writes coverage-by-screen.csv and coverage-by-screen.md (never overwrites a
dated report: the files carry the date)."""
import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
KEY_LINE = re.compile(r'^\s*"?([\w.\-]+)"?\s*:\s*"', re.M)
IMPORT = re.compile(r'from\s+"(@/[^"]+|\.{1,2}/[^"]+)"')
STRING = re.compile(r'"([A-Za-z0-9_.\-]+\.[A-Za-z0-9_.\-]+)"')
JSX_TEXT = re.compile(r">\s*([A-Za-z][^<>{}\n]{2,}?)\s*<")
ATTR_TEXT = re.compile(r'\b(?:placeholder|aria-label|title|alt)="([A-Za-z][^"{}]{2,})"')


def keys_of(path: Path) -> set[str]:
    return set(KEY_LINE.findall(path.read_text(encoding="utf-8")))


def resolve(frm: Path, spec: str) -> Path | None:
    base = SRC / spec[2:] if spec.startswith("@/") else (frm.parent / spec)
    for cand in (base.with_suffix(".tsx"), base.with_suffix(".ts"), base / "index.tsx", base / "index.ts"):
        if cand.is_file():
            return cand
    return None


def closure(page: Path) -> list[Path]:
    """The page plus the components it imports, transitively (not libraries, not tests)."""
    seen: list[Path] = []
    todo = [page]
    while todo:
        p = todo.pop()
        if p in seen or ".test." in p.name:
            continue
        seen.append(p)
        for spec in IMPORT.findall(p.read_text(encoding="utf-8")):
            q = resolve(p, spec)
            if q and "components" in q.parts and q not in seen:
                todo.append(q)
    return seen


def scan_page(page: Path, en_keys: set[str]) -> tuple[set[str], int]:
    used: set[str] = set()
    typed: set[str] = set()
    for f in closure(page):
        text = f.read_text(encoding="utf-8")
        used |= {s for s in STRING.findall(text) if s in en_keys}
        for m in JSX_TEXT.findall(text) + ATTR_TEXT.findall(text):
            if len(m.split()) >= 2 or m[0].isupper():
                typed.add(m.strip())
    return used, len(typed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(SRC.parent.parent / "docs" / "translation"))
    a = ap.parse_args(argv)
    en = keys_of(SRC / "lib" / "i18n" / "en.ts")
    langs = {p.stem: keys_of(p) for p in sorted((SRC / "lib" / "i18n" / "locales").glob("*.ts"))}
    rows = []
    for page in sorted((SRC / "pages").glob("*.tsx")):
        if ".test." in page.name:
            continue
        used, typed = scan_page(page, en)
        for code, have in langs.items():
            missing = sorted(k for k in used if k not in have)
            total = len(used) + typed
            done = len(used) - len(missing)
            rows.append({"screen": page.stem, "language": code, "keys_used": len(used), "keys_translated": done, "keys_still_english": len(missing),
                         "typed_without_key": typed, "share_translated_pct": round(100 * done / total) if total else 100, "first_missing": ";".join(missing[:5])})
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    csv_path, md_path = out / f"coverage-by-screen-{stamp}.csv", out / f"coverage-by-screen-{stamp}.md"
    for p in (csv_path, md_path):
        if p.exists():
            print("A report for today already exists; not overwriting:", p, file=sys.stderr)
            return 2
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md = [f"# Translation coverage by screen, {stamp}", "",
          "Made by `scripts/i18n_coverage.py` from the source. **Share translated** = translated keys divided by (keys the screen uses + text typed straight into the screen without a key). "
          "A language shows English for every key it lacks and for all typed text. Typed text is counted by a pattern, so it is approximate. No text was machine-translated.", ""]
    for code in langs:
        mine = [r for r in rows if r["language"] == code]
        total_used = sum(r["keys_used"] for r in mine)
        total_done = sum(r["keys_translated"] for r in mine)
        total_typed = sum(r["typed_without_key"] for r in mine)
        md.append(f"- **{code}**: {total_done} of {total_used} keys translated across screens; share of all screen text translated {round(100 * total_done / max(total_used + total_typed, 1))}%.")
    md += ["", "## Screens, English first", "", "| Screen | Keys used | Typed without a key (approx.) | Languages complete on keys | Weakest language (share) |", "|---|---|---|---|---|"]
    for page in sorted({r["screen"] for r in rows}):
        mine = [r for r in rows if r["screen"] == page]
        complete = [r["language"] for r in mine if r["keys_still_english"] == 0]
        weakest = min(mine, key=lambda r: r["share_translated_pct"])
        md.append(f"| {page} | {mine[0]['keys_used']} | {mine[0]['typed_without_key']} | {len(complete)} of {len(langs)} | {weakest['language']} ({weakest['share_translated_pct']}%) |")
    md += ["", "The full table (every screen, every language, the first missing keys) is in the CSV next to this file."]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wrote", csv_path, md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
