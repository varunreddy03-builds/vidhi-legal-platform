"""Document templates (rent agreement, loan agreement, NDA, cheque-return legal notice, employment letter) with a lawyer-review gate.

Templates are plain data files in backend/data/templates/:  pending/ (written, NOT reviewed) and <COUNTRY>/ (reviewed by a named lawyer).
* A file in pending/ is always shown as "UNVERIFIED - pending lawyer review", whatever the file says about itself.
* A file in a country folder counts as reviewed only if it names the reviewer and date AND its content hash still matches what was reviewed:
  a template edited after its review goes back to unreviewed.
* Text is filled in by CODE from the person's answers (no AI). Anything that is law, a statutory period, a stamp-duty or registration point stays as a visible
  [LAWYER TO CONFIRM: ...] placeholder: this module and these files contain no statute names or section numbers (a test enforces that).
* A template is available only for a country VIDHI actually covers (lib/jurisdictions.py); today that is India only.

Template file:  id, title, description, jurisdiction, language, version, kind, fields[], clauses[], body, lawyer_checks[]  (+ reviewed_by, reviewed_on, content_sha256 once reviewed).
Body markers:  {{field_key}}  and  {{clause:clause_id}}.  Field types: text, textarea, date, money, int, decimal, choice. An optional field prints nothing when left empty, unless it has "flag_if_empty" (then a visible
[... - to be filled] marker is printed, for values a clause needs)."""

import hashlib
import json
import logging
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lib.jurisdictions import REGISTRY

logger = logging.getLogger(__name__)
UNREVIEWED = "UNVERIFIED - pending lawyer review"
REVIEWED = "Template text reviewed by a lawyer"
TYPES = {"text": 200, "textarea": 2000, "date": 10, "money": 20, "int": 6, "decimal": 8, "choice": 80}
REQUIRED_KEYS = ("id", "title", "description", "jurisdiction", "language", "version", "kind", "fields", "body")
MARKER = re.compile(r"\{\{\s*(clause:)?([a-z0-9_]+)\s*\}\}")
OPEN = re.compile(r"\[(?:LAWYER[^\]\n]{0,200}|[^\]\n]{3,120} - to be filled)\]")
BANNER_UNREVIEWED = (
    "DRAFT FROM A TEMPLATE - NOT REVIEWED BY A LAWYER.\n"
    "Check every line against your facts and the law that applies before anyone signs or sends it. VIDHI has not verified any legal point in this document.\n"
    "Items in [square brackets] still need to be filled in or confirmed by a lawyer. Delete this note when the document is final.\n\n"
)
BANNER_REVIEWED = (
    "DRAFT FROM A TEMPLATE. The template text was reviewed by {name} on {on}. That review does not cover your facts: a lawyer should still check this document before it is signed or sent.\n"
    "Items in [square brackets] still need to be filled in or confirmed. Delete this note when the document is final.\n\n"
)


def templates_dir() -> Path:
    return Path(os.environ.get("TEMPLATES_DIR") or Path(os.path.abspath(__file__)).parent.parent / "data" / "templates")


def content_hash(entry: dict) -> str:
    """Hash of what a reviewer actually reads: the wording, the questions and the checklist (not the review fields themselves)."""
    keep = {k: entry.get(k) for k in ("id", "jurisdiction", "version", "kind", "fields", "clauses", "body", "lawyer_checks")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _problems(t: dict) -> list[str]:
    bad = [f"missing {k}" for k in REQUIRED_KEYS if not t.get(k)]
    keys = [f.get("key") for f in t.get("fields", [])]
    if len(keys) != len(set(keys)):
        bad.append("duplicate field keys")
    for f in t.get("fields", []):
        if not f.get("key") or not f.get("label") or f.get("type") not in TYPES:
            bad.append(f"bad field {f.get('key')!r}")
        if f.get("type") == "choice" and not f.get("choices"):
            bad.append(f"choice field {f.get('key')!r} has no choices")
    clause_ids = {c.get("id") for c in t.get("clauses", [])}
    text = t.get("body", "") + " ".join(c.get("text", "") for c in t.get("clauses", []))
    for is_clause, name in MARKER.findall(text):
        if is_clause and name not in clause_ids:
            bad.append(f"unknown clause {name}")
        if not is_clause and name not in keys:
            bad.append(f"unknown field {name}")
    if t.get("jurisdiction") not in REGISTRY:
        bad.append("unknown jurisdiction")
    return bad


def load_all() -> list[dict]:
    """Every usable template with its review state worked out. Broken files are skipped and logged."""
    out, seen = [], set()
    root = templates_dir()
    for folder in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        for path in sorted(folder.glob("*.json")):
            try:
                t = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.error("template %s is not valid JSON; skipped", path.name)
                continue
            if t.get("id") in seen or (problems := _problems(t)):
                logger.error("template %s skipped: %s", path.name, "duplicate id" if t.get("id") in seen else problems)
                continue
            seen.add(t["id"])
            reviewed = folder.name != "pending" and bool(t.get("reviewed_by") and t.get("reviewed_on")) and t.get("content_sha256") == content_hash(t)
            note = None
            if folder.name != "pending" and not reviewed:
                note = "This template changed after its review (or the review record is incomplete), so it counts as not reviewed."
            t["review"] = {"status": REVIEWED if reviewed else UNREVIEWED, "reviewed": reviewed, "reviewed_by": t.get("reviewed_by") if reviewed else None,
                           "reviewed_on": t.get("reviewed_on") if reviewed else None, "note": note}
            out.append(t)
    return out


def get(template_id: str) -> dict | None:
    return next((t for t in load_all() if t["id"] == template_id), None)


def listing(jurisdiction: str | None = None) -> dict:
    items = [t for t in load_all() if not jurisdiction or t["jurisdiction"] == jurisdiction]
    summary = [{"id": t["id"], "title": t["title"], "description": t["description"], "jurisdiction": t["jurisdiction"], "kind": t["kind"], "language": t["language"],
                "review": t["review"], "fields": len(t["fields"])} for t in items]
    j = REGISTRY.get(jurisdiction or "")
    note = None
    if jurisdiction and (not j or j.status != "live"):
        note = f"VIDHI does not cover {j.name if j else jurisdiction} law yet, so there are no templates for it. Nothing here should be read as covering that country."
    elif jurisdiction and not summary:
        note = "No templates for this country yet."
    return {"items": summary, "jurisdiction": jurisdiction, "note": note}


# ---- filling in ----

def _clean(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()


def inr(amount: Decimal) -> str:
    """Rs 1,25,000 with Indian digit grouping (the PDF base fonts have no rupee glyph, so 'Rs' as elsewhere in VIDHI)."""
    whole, _, frac = f"{amount:.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "Rs " + ",".join(groups + [tail]) + ("" if frac == "00" else "." + frac)


def format_value(field: dict, raw) -> str:
    kind, label = field["type"], field["label"]
    text = _clean(str(raw))
    if len(text) > TYPES[kind]:
        raise ValueError(f"{label} is too long.")
    if kind == "date":
        try:
            return date.fromisoformat(text).strftime("%d %B %Y")
        except ValueError as exc:
            raise ValueError(f"{label} must be a date like 2026-11-05.") from exc
    if kind == "money":
        try:
            amount = Decimal(text.replace(",", "").replace("Rs", "").strip())
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be an amount in rupees, like 25000.") from exc
        if amount < 0 or amount > Decimal("1000000000000"):
            raise ValueError(f"{label} is out of range.")
        return inr(amount)
    if kind == "int":
        if not re.fullmatch(r"\d{1,6}", text):
            raise ValueError(f"{label} must be a whole number.")
        n = int(text)
        if not field.get("min", 0) <= n <= field.get("max", 100000):
            raise ValueError(f"{label} must be between {field.get('min', 0)} and {field.get('max', 100000)}.")
        return str(n)
    if kind == "decimal":
        try:
            n = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a number like 12.5.") from exc
        if not Decimal(field.get("min", 0)) <= n <= Decimal(field.get("max", 1000)) or n.as_tuple().exponent < -2:
            raise ValueError(f"{label} must be between {field.get('min', 0)} and {field.get('max', 1000)}, with at most two decimals.")
        return format(n.normalize(), "f")
    if kind == "choice":
        if text not in field["choices"]:
            raise ValueError(f"{label} must be one of: {', '.join(field['choices'])}.")
        return text
    return text


def render(t: dict, values: dict, clauses: list[str] | None = None) -> dict:
    """{text, open_placeholders, clauses_used}. Raises ValueError (one plain message) when required answers are missing or wrong."""
    fields = {f["key"]: f for f in t["fields"]}
    unknown = [k for k in values if k not in fields]
    if unknown:
        raise ValueError(f"Unknown answer(s): {', '.join(sorted(unknown))}.")
    shown: dict[str, str] = {}
    missing = []
    for key, f in fields.items():
        raw = values.get(key)
        if raw is None or _clean(str(raw)) == "":
            if f.get("required"):
                missing.append(f["label"])
            shown[key] = f"[{f['label']} - to be filled]" if f.get("required") or f.get("flag_if_empty") else ""
        else:
            shown[key] = format_value(f, raw)
    if missing:
        raise ValueError("Please fill in: " + "; ".join(missing) + ".")
    available = {c["id"]: c for c in t.get("clauses", [])}
    chosen = [c["id"] for c in t.get("clauses", []) if c.get("default")] if clauses is None else clauses
    bad = [c for c in chosen if c not in available]
    if bad:
        raise ValueError(f"Unknown clause(s): {', '.join(bad)}.")

    def expand_clauses(m: re.Match) -> str:
        return available[m.group(2)]["text"] if m.group(1) and m.group(2) in chosen else ("" if m.group(1) else m.group(0))

    body = MARKER.sub(expand_clauses, t["body"])
    # one pass: a value that itself contains {{...}} is inserted as plain text and never expanded again
    body = MARKER.sub(lambda m: shown[m.group(2)] if not m.group(1) else m.group(0), body)
    body = re.sub(r"(?<=[^\s_]) {2,}(?=[^\s_])", " ", body)  # an empty optional answer must not leave a double space (signature lines keep theirs)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    banner = BANNER_REVIEWED.format(name=t["review"]["reviewed_by"], on=t["review"]["reviewed_on"]) if t["review"]["reviewed"] else BANNER_UNREVIEWED
    return {"text": banner + body, "open_placeholders": sorted(set(OPEN.findall(body))), "clauses_used": [c for c in chosen if c in available]}