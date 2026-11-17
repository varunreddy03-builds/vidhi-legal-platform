"""OCR language choice, the installed-language list, and the silent-failure guard for a Tesseract data folder without its configs."""
import subprocess
from types import SimpleNamespace

import pytest

from lib import ocr_engine as o


def test_default_is_the_three_tested_languages_and_tamil_is_opt_in(monkeypatch):
    monkeypatch.delenv("OCR_LANGUAGES", raising=False)
    assert o.configured_languages() == ("eng", "tel", "hin")
    monkeypatch.setenv("OCR_LANGUAGES", "eng+tel+hin+tam")
    assert o.configured_languages() == ("eng", "tel", "hin", "tam")
    monkeypatch.setenv("OCR_LANGUAGES", "eng, tam")
    assert o.configured_languages() == ("eng", "tam")


@pytest.mark.parametrize("raw", ["", "  ", "../../x", "ENG", "a;b", "123"])
def test_junk_in_the_setting_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("OCR_LANGUAGES", raw)
    assert o.configured_languages() == o.DEFAULT_LANGUAGES


def test_installed_languages_ignores_the_header_line(monkeypatch):
    out = 'List of available languages in "C:/x/tessdata/" (3):\neng\nhin\nosd\n'
    monkeypatch.setattr(o.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out))
    assert o.installed_languages("tesseract") == {"eng", "hin", "osd"}


def test_plain_text_instead_of_word_data_is_an_error_not_an_empty_page(monkeypatch):
    monkeypatch.setattr(o.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="This is plain text\n"))
    with pytest.raises(RuntimeError, match="word data"):
        o.run_tesseract("tesseract", b"x", "eng")


def test_word_data_passes_through(monkeypatch):
    tsv = "level\tpage_num\ttext\n5\t1\thello\n"
    monkeypatch.setattr(o.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=tsv))
    assert o.run_tesseract("tesseract", b"x", "eng") == tsv


def test_a_language_folder_setting_is_passed_to_tesseract_only_when_the_folder_exists(monkeypatch, tmp_path):
    monkeypatch.delenv("OCR_TESSDATA_DIR", raising=False)
    assert o.tessdata_args() == []
    monkeypatch.setenv("OCR_TESSDATA_DIR", str(tmp_path / "missing"))
    assert o.tessdata_args() == []  # a wrong path is ignored, never passed on
    monkeypatch.setenv("OCR_TESSDATA_DIR", str(tmp_path))
    assert o.tessdata_args() == ["--tessdata-dir", str(tmp_path)]
    seen = {}
    monkeypatch.setattr(o.subprocess, "run", lambda cmd, **k: seen.setdefault("cmd", cmd) and SimpleNamespace(stdout="level\ttext\n"))
    o.run_tesseract("tesseract", b"png", "hin")
    assert "--tessdata-dir" in seen["cmd"] and seen["cmd"][seen["cmd"].index("-l") + 1] == "hin"
