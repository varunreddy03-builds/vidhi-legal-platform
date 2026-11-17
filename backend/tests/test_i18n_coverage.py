"""The language-coverage report: reads the real sources, never overwrites a report, and counts a missing key as English."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import i18n_coverage as cov  # noqa: E402


def test_keys_are_read_from_the_english_catalog_and_a_language():
    en = cov.keys_of(cov.SRC / "lib" / "i18n" / "en.ts")
    hi = cov.keys_of(cov.SRC / "lib" / "i18n" / "locales" / "hi.ts")
    assert "nav.home" in en and "nav.home" in hi
    assert "toolkit.ac.title" in en and "toolkit.ac.title" not in hi  # a text Hindi still shows in English


def test_a_page_uses_keys_through_the_components_it_imports():
    en = cov.keys_of(cov.SRC / "lib" / "i18n" / "en.ts")
    used, typed = cov.scan_page(cov.SRC / "pages" / "Start.tsx", en)
    assert "nav.home" in used and "start.morning" in used and typed >= 0


def test_report_is_written_and_a_second_run_the_same_day_refuses(tmp_path, capsys):
    assert cov.main(["--out-dir", str(tmp_path)]) == 0
    files = sorted(tmp_path.iterdir())
    assert len(files) == 2
    with next(f for f in files if f.suffix == ".csv").open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert {"screen", "language", "keys_used", "keys_still_english", "share_translated_pct"} <= set(rows[0])
    assert len({r["language"] for r in rows}) == 22
    assert all(0 <= int(r["share_translated_pct"]) <= 100 for r in rows)
    before = [f.read_bytes() for f in files]
    assert cov.main(["--out-dir", str(tmp_path)]) == 2 and "not overwriting" in capsys.readouterr().err
    assert [f.read_bytes() for f in files] == before
