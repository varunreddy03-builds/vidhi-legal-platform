"""The OCR measuring tool: accuracy per file, failures named, the dangerous case (wrong but not marked uncertain) counted, reports never overwritten, and a clear message when Tesseract is absent.
Uses an injected reader and invented text; no scan or Tesseract is needed."""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import ocr_eval as oe

BACKEND = Path(__file__).resolve().parent.parent
TRUTH = "The tenant shall pay rent on the first day of each month."


def make(tmp_path, name, truth=TRUTH):
    (tmp_path / name).write_bytes(b"x")
    (tmp_path / name).with_suffix(".txt").write_text(truth, encoding="utf-8")
    return tmp_path / name


def test_tags_from_file_name(tmp_path):
    assert oe.tags_of(Path("a.clean.hin.png")) == ("hin", "clean")
    assert oe.tags_of(Path("b.lowq.tel.pdf")) == ("tel", "low quality")
    assert oe.tags_of(Path("c.png")) == ("unknown", "unknown")


def test_pairs_need_the_text_file(tmp_path):
    make(tmp_path, "a.clean.eng.png")
    (tmp_path / "lonely.png").write_bytes(b"x")
    assert [p.name for p in oe.pairs(tmp_path)] == ["a.clean.eng.png"]


def test_accuracy_ignores_unicode_form_and_zero_width():
    assert oe.accuracy("क़िताब", "क़ि\u200dताब") >= 0.99
    assert oe.accuracy(TRUTH, TRUTH) == 1.0
    assert oe.accuracy(TRUTH, "zzz") < 0.2


def test_good_read_has_nothing_to_flag(tmp_path):
    p = make(tmp_path, "a.clean.eng.png")
    r = oe.judge(p, TRUTH, [(TRUTH, 92.0)], None)
    assert r["accuracy"] == 1.0 and not r["fails"] and not r["dangerous"] and r["uncertain_pages"] == []


def test_wrong_and_flagged_is_not_dangerous(tmp_path):
    p = make(tmp_path, "a.lowq.eng.png")
    r = oe.judge(p, TRUTH, [("Tha tenxnt sh pa rnt", 41.0)], None)
    assert r["uncertain_pages"] == [1] and not r["dangerous"]
    assert "scan" in r["user_sees"].lower()


def test_wrong_but_confident_is_the_dangerous_case(tmp_path):
    p = make(tmp_path, "a.skewed.eng.png")
    r = oe.judge(p, TRUTH, [("A landlord may evict at will on any day whatever.", 88.0)], None)
    assert r["dangerous"] and r["uncertain_pages"] == []
    assert "NOTHING warns" in r["user_sees"]


def test_empty_text_and_reader_error(tmp_path):
    p = make(tmp_path, "a.photo.tel.png")
    e = oe.judge(p, TRUTH, [("", None)], None)
    assert "no text was found" in e["fails"][0] and not e["dangerous"]
    f = oe.judge(p, TRUTH, None, "RuntimeError")
    assert f["error"] == "RuntimeError" and f["accuracy"] is None


def test_one_failing_file_does_not_stop_the_rest(tmp_path):
    a, b = make(tmp_path, "a.clean.eng.png"), make(tmp_path, "b.clean.eng.png")

    def reader(p):
        if p.name.startswith("a"):
            raise ValueError("secret client text must not appear")
        return [(TRUTH, 90.0)]

    rows = oe.evaluate([a, b], reader)
    assert rows[0]["error"] == "ValueError" and rows[1]["accuracy"] == 1.0
    assert "secret" not in str(rows)


def test_summary_and_report(tmp_path):
    rows = [oe.judge(make(tmp_path, "a.clean.eng.png"), TRUTH, [(TRUTH, 95.0)], None),
            oe.judge(make(tmp_path, "b.skewed.hin.png"), TRUTH, [("A landlord may evict at will on any day.", 90.0)], None)]
    s = oe.summarise(rows)
    assert s["all"]["files"] == 2 and s["all"]["dangerous"] == 1 and s["by_language"]["hin"]["dangerous"] == 1
    text = oe.render(rows, {"date": "d", "folder": "f", "languages": "eng"})
    assert "dangerous case first" in text and "b.skewed.hin.png" in text and "What the person sees" in text


def test_reports_are_never_overwritten(tmp_path):
    now = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
    one = oe.save("first", {}, tmp_path, now)
    two = oe.save("second", {}, tmp_path, now)
    assert one != two and one.read_text(encoding="utf-8") == "first" and two.read_text(encoding="utf-8") == "second"


def test_cli_says_what_to_install_when_tesseract_is_missing(tmp_path):
    make(tmp_path, "a.clean.eng.png")
    env = {"PATH": "", "SYSTEMROOT": "C:/Windows", "TESSERACT_CMD": ""}
    r = subprocess.run([sys.executable, "-I", str(BACKEND / "scripts" / "ocr_eval.py"), str(tmp_path)], capture_output=True, text=True, cwd=BACKEND, env=env)
    assert r.returncode == 2 and "Tesseract was not found" in r.stdout and "hin, tel" in r.stdout


def test_hosted_is_plan_only(tmp_path):
    make(tmp_path, "a.clean.eng.png")
    r = subprocess.run([sys.executable, "-I", str(BACKEND / "scripts" / "ocr_eval.py"), str(tmp_path), "--hosted"], capture_output=True, text=True, cwd=BACKEND)
    assert r.returncode == 0 and "Nothing is sent" in r.stdout
