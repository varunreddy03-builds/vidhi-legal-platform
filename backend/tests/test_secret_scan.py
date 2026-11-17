"""The secret scanner finds key-like text, says where and which rule, and never prints the value."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("secret_scan", Path(__file__).resolve().parents[2] / "scripts" / "secret_scan.py")
ss = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ss)

FAKE = "abcdefghij0123456789ABCDEFGH"


def test_known_key_shapes_are_found():
    assert "apify-token" in ss.scan_line("t = 'apify_api_" + FAKE + "'")
    assert "google-api-key" in ss.scan_line("k = 'AIza" + "A" * 35 + "'")
    assert "private-key-block" in ss.scan_line("-----BEGIN RSA PRIVATE KEY-----")  # secret-scan: ok (fake test value)
    assert "assigned-secret" in ss.scan_line("MY_API_TOKEN=" + FAKE)
    assert "url-with-password" in ss.scan_line("MONGO_URL=mongodb://app:hunter2hunter2@db.example.in/x")  # secret-scan: ok (fake test value)


def test_placeholders_lookups_and_marked_lines_are_not_flagged():
    assert ss.scan_line("MY_API_TOKEN=") == []
    assert ss.scan_line("MY_API_TOKEN=${MY_API_TOKEN}") == []
    assert ss.scan_line('token = os.environ.get("MY_API_TOKEN")') == []
    assert ss.scan_line("MONGO_URL=mongodb://${USER}:${PASS}@mongo:27017/db") == []
    assert ss.scan_line("MY_API_TOKEN=" + FAKE + "  # secret-scan: ok (fake test value)") == []


def test_the_report_never_contains_the_value(capsys):
    ss.report([("some/file.py", "3", "assigned-secret", "")])
    out = capsys.readouterr().out
    assert "some/file.py:3" in out and FAKE not in out


def test_env_files_are_blocked_by_name_but_examples_are_not():
    assert ss.BLOCK_NAMES.search("backend/.env") and ss.BLOCK_NAMES.search("x/.env.production")
    assert not ss.BLOCK_NAMES.search("backend/.env.example")
