"""Reads a pytest --junitxml file and prints pass / fail / error per campaign phase, and the distinct failure reasons.

    python scripts/campaign_report.py report.xml [--prefix I|R]

Test ids look like  test_campaign_case[I07-severe-012-y1998]  or  test_recovery_campaign[R03-...]."""

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict


def main(path: str, prefix: str | None) -> None:
    root = ET.parse(path).getroot()
    per = defaultdict(lambda: Counter())
    reasons = defaultdict(Counter)
    examples = {}
    for tc in root.iter("testcase"):
        m = re.search(r"\[((?:I|R|OPEN)[\w-]*?)(?:-\d{3})?(?:-y\d{4})?(?:-fic)?\]", tc.get("name", ""))
        label = m.group(1) if m else None
        if not label or (prefix and not label.startswith(prefix)):
            continue
        phase = "-".join(label.split("-")[:2]) if not label.startswith("OPEN") else "OPEN"
        bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        if bad is None:
            per[phase]["pass"] += 1
            continue
        kind = "fail" if tc.find("failure") is not None else "error"
        per[phase][kind] += 1
        msg = (bad.get("message") or "").splitlines()[0][:160] if bad.get("message") else ""
        reasons[phase][msg] += 1
        examples.setdefault((phase, msg), tc.get("name"))
    total = Counter()
    print(f"{'phase':32} {'pass':>5} {'fail':>5} {'error':>5}")
    for phase in sorted(per):
        c = per[phase]
        total.update(c)
        print(f"{phase:32} {c['pass']:5} {c['fail']:5} {c['error']:5}")
    print(f"{'TOTAL':32} {total['pass']:5} {total['fail']:5} {total['error']:5}")
    for phase in sorted(reasons):
        print(f"\n{phase}")
        for msg, n in reasons[phase].most_common(6):
            print(f"  {n:4} x {msg}   e.g. {examples[(phase, msg)]}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pre = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else None
    main(args[0], pre)
