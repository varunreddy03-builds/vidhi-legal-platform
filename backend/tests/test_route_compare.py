"""route_compare: cheaper-but-worse never recommends a default change; different case sets are refused; claim-check keeps research's chain by default."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import route_compare as rc  # noqa: E402

from lib import ai  # noqa: E402


def report(passes: dict, universal=()):
    res = [{"id": i, "passed": ok, "score": 100 if ok else 40} for i, ok in passes.items()]
    return {"label": "x", "summary": {"universal_rules_broken_in": list(universal), "answered": f"{len(res)} of {len(res)}"}, "results": res}


def test_equal_quality_is_allowed():
    q = rc.quality(report({"a": True, "b": False}))
    assert rc.verdict(q, q)[0].startswith("QUALITY EQUAL")


def test_regression_keeps_old_default():
    b, a = rc.quality(report({"a": True, "b": True})), rc.quality(report({"a": True, "b": False}))
    v, why = rc.verdict(b, a)
    assert v.startswith("KEEP THE OLD DEFAULT") and "b" in why[0]


def test_new_universal_rule_broken_keeps_old_default():
    b, a = rc.quality(report({"a": True})), rc.quality(report({"a": True}, universal=["a"]))
    assert rc.verdict(b, a)[0].startswith("KEEP THE OLD DEFAULT")


def test_different_cases_refused(tmp_path, capsys):
    (tmp_path / "b.json").write_text(json.dumps(report({"a": True})), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(report({"z": True})), encoding="utf-8")
    assert rc.main(["--before", str(tmp_path / "b.json"), "--after", str(tmp_path / "a.json")]) == 2
    assert "same cases" in capsys.readouterr().err


def test_no_database_says_not_measured(tmp_path, capsys):
    f = tmp_path / "r.json"
    f.write_text(json.dumps(report({"a": True})), encoding="utf-8")
    assert rc.main(["--before", str(f), "--after", str(f)]) == 0
    assert "not measured" in capsys.readouterr().out


def test_claim_check_default_chain_equals_research():
    assert ai.DEFAULT_ROUTES["claim-check"] == ai.DEFAULT_ROUTES["research"]


def test_claim_check_route_can_be_set_alone(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("AI_ROUTE", raising=False)
    monkeypatch.setenv("AI_ROUTE_CLAIM_CHECK", "sonnet,gemini")
    monkeypatch.delenv("AI_ROUTE_RESEARCH", raising=False)
    assert ai.route_for("claim-check")[0] == "sonnet"
    assert ai.route_for("research")[0] == "haiku"
