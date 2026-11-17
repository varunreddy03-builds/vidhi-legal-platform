"""Create a verified-library entry file with the text hash filled in. See data/legal_library/README.md.

The text must be copied EXACTLY from the official source. This tool does not know any law; it only packages
what you give it and computes the SHA-256 so later corruption is detected.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.library import DEFAULT_DIR, KINDS, sha256_text, validate_entry  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--citation", required=True)
    p.add_argument("--alias", action="append", default=[])
    p.add_argument("--title", default="")
    p.add_argument("--text-file", required=True, help="UTF-8 file containing the exact source text")
    p.add_argument("--source-name", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--verified-by", required=True)
    p.add_argument("--verified-on", required=True, help="YYYY-MM-DD")
    p.add_argument("--out-dir", default=str(DEFAULT_DIR))
    a = p.parse_args()

    text = Path(a.text_file).read_text(encoding="utf-8").strip()
    entry = {
        "id": a.id,
        "kind": a.kind,
        "citation": a.citation,
        "aliases": a.alias,
        "title": a.title,
        "text": text,
        "text_sha256": sha256_text(text),
        "source_name": a.source_name,
        "source_url": a.source_url,
        "version": a.version,
        "verified_by": a.verified_by,
        "verified_on": a.verified_on,
    }
    errs = validate_entry(entry)
    if errs:
        print("Not written:", "; ".join(errs))
        return 1
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.id}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}. Commit it, then restart the server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
