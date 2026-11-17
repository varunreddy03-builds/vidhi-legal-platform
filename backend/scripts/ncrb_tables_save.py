"""Saves the raw rows of the Home Ministry (NCRB Sankalan portal) comparison tables as JSON, exactly as published: nothing is interpreted, classified or loaded into the database.
Input: the three saved HTML pages (see docs); output: data/mapping_tables/ncrb_<bns|bnss|bsa>.json. The rows become unreviewed code mappings only through
POST /admin/legal/mappings/import after the two Acts are loaded, and count as verified only after a named reviewer signs them off.

    python scripts/ncrb_tables_save.py <folder holding ncrb_BNS.html, ncrb_BNSS.html, ncrb_BSA.html>
"""

import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "mapping_tables"
PAGES = {"BNS": ("Bharatiya Nyaya Sanhita, 2023", "Indian Penal Code, 1860"), "BNSS": ("Bharatiya Nagarik Suraksha Sanhita, 2023", "Code of Criminal Procedure, 1973"),
         "BSA": ("Bharatiya Sakshya Adhiniyam, 2023", "Indian Evidence Act, 1872")}


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.row, self.cell, self.in_cell = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.in_cell = [], True
        elif tag == "br" and self.in_cell:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.in_cell = False
        elif tag == "tr" and self.row is not None and self.tables:
            self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, d):
        if self.in_cell:
            self.cell.append(d)


def main(folder: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (new_title, legacy_title) in PAGES.items():
        p = Tables()
        p.feed((folder / f"ncrb_{key}.html").read_text(encoding="utf-8", errors="replace"))
        a, b = p.tables[0], p.tables[1]
        data = {
            "source": f"https://www.ncrb.mha.gov.in/uploads/SankalanPortal/SectionTable{key}.html",
            "publisher": "National Crime Records Bureau, Ministry of Home Affairs (NCRB Sankalan portal)",
            "retrieved_on": date.today().isoformat(),
            "status": "RAW, UNREVIEWED: rows exactly as published. Not interpreted, not loaded, not verified.",
            "new_instrument": new_title, "legacy_instrument": legacy_title,
            "new_to_legacy": [{"new": r[0], "legacy": r[1]} for r in a[1:] if len(r) == 2],
            "legacy_to_new": [{"legacy": r[0], "new": r[1]} for r in b[1:] if len(r) == 2],
            "rows_not_two_cells": [r for r in a[1:] + b[1:] if len(r) != 2],
        }
        (OUT / f"ncrb_{key.lower()}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(key, len(data["new_to_legacy"]), len(data["legacy_to_new"]), "odd rows:", len(data["rows_not_two_cells"]))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
