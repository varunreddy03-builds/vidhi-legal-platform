"""Secret scan. Finds things that look like keys, tokens, passwords or private keys, and prints WHERE (file, line, commit) and WHICH RULE, never the value.

    python scripts/secret_scan.py --staged      # what is about to be committed (the pre-commit hook runs this)
    python scripts/secret_scan.py --tree        # every tracked file as it is now
    python scripts/secret_scan.py --history     # every line ever added in any commit (slow on a big history)

Exit code 1 when something is found. A line that is deliberately fine can end with `# secret-scan: ok`. Real keys belong only in backend/.env (git-ignored) or the host's secret store."""

import argparse
import re
import subprocess
import sys

RULES = [
    ("apify-token", re.compile(r"apify_api_[A-Za-z0-9]{20,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{32,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("stripe-live-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("url-with-password", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:(?!\$|\{|<|x{3,}|password|changeme|secret|\*)[^\s:/@$]{6,}@[^\s/]+")),
    # NAME_KEY=long-value, NAME_TOKEN: "long-value" ... where the value is not a placeholder or an environment lookup
    ("assigned-secret", re.compile(r"""(?i)\b[A-Z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY)[A-Z0-9_]*\s*[=:]\s*["']?(?![\s"'$<{]|your|example|change|dummy|test|xxx|none|null|true|false|os\.|process\.|env)[A-Za-z0-9_\-/+=.]{20,}["']?\s*$""")),
]
SKIP_PATH = re.compile(r"(^|/)(yarn\.lock|package-lock\.json|requirements\.lock|.*\.svg|.*\.png|.*\.jpg|.*\.ico|.*\.apk|.*\.pdf|.*\.docx|.*\.xlsx|node_modules/|venv|artifacts/|docs/translation-review/)")
BLOCK_NAMES = re.compile(r"(^|/)(\.env|\.env\.[a-z]+(?<!\.example)|[^/]*\.(jks|keystore|pem|p12|pfx))$")
OK_MARK = "secret-scan: ok"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def scan_line(line: str) -> list[str]:
    if OK_MARK in line:
        return []
    return [name for name, rx in RULES if rx.search(line)]


def report(found: list[tuple[str, str, str, str]]) -> int:
    for path, where, rule, commit in found:
        print(f"{rule:<24} {path}:{where}" + (f"  (commit {commit})" if commit else ""))
    if found:
        print(f"\n{len(found)} possible secret(s). Values are not printed. Move real keys to backend/.env or the host's secret store; if one was committed, treat it as exposed and rotate it.")
        return 1
    print("No secrets found.")
    return 0


def staged() -> int:
    found = []
    for path in git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines():
        if BLOCK_NAMES.search(path) and not path.endswith(".example"):
            found.append((path, "-", "secret-file-name", ""))
    cur, ln = "", 0
    for line in git("diff", "--cached", "-U0", "--no-color").splitlines():
        if line.startswith("+++ b/"):
            cur, ln = line[6:], 0
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            ln = int(m.group(1)) - 1 if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            ln += 1
            if cur and not SKIP_PATH.search(cur):
                found += [(cur, str(ln), r, "") for r in scan_line(line[1:])]
    return report(found)


def tree() -> int:
    found = []
    for path in git("ls-files").splitlines():
        if BLOCK_NAMES.search(path) and not path.endswith(".example"):
            found.append((path, "-", "secret-file-name", ""))
        if SKIP_PATH.search(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            found += [(path, str(n), r, "") for r in scan_line(line)]
    return report(found)


def history() -> int:
    found, commit, path = [], "", ""
    log = git("log", "--all", "-p", "-U0", "--no-color", "--format=@@COMMIT %h")
    for line in log.splitlines():
        if line.startswith("@@COMMIT "):
            commit = line[9:]
        elif line.startswith("+++ b/"):
            path = line[6:]
            if BLOCK_NAMES.search(path) and not path.endswith(".example"):
                found.append((path, "-", "secret-file-name", commit))
        elif line.startswith("+") and not line.startswith("+++") and path and not SKIP_PATH.search(path):
            found += [(path, "-", r, commit) for r in scan_line(line[1:])]
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return report(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true")
    g.add_argument("--tree", action="store_true")
    g.add_argument("--history", action="store_true")
    a = ap.parse_args()
    sys.exit(staged() if a.staged else tree() if a.tree else history())
