"""Deterministic document classification, so a WhatsApp export or a forensic report is never analysed as
if it were a contract. No AI is involved: scored keyword/structure cues on the filename and opening text.
The owner can always override the class (it is stored with source AUTO or USER)."""

import os
import re

DOC_CLASSES = (
    "CONTRACT",
    "CHAT",
    "BANK_STATEMENT",
    "FIR_POLICE",
    "FORENSIC_REPORT",
    "MEDICAL",
    "CCTV_LOG",
    "COURT_ORDER",
    "LETTER",
    "MEDIA",
    "OTHER",
)

MEDIA_KINDS = {
    ".png": "IMAGE", ".jpg": "IMAGE", ".jpeg": "IMAGE", ".webp": "IMAGE",
    ".mp4": "VIDEO", ".mov": "VIDEO", ".webm": "VIDEO",
    ".mp3": "AUDIO", ".wav": "AUDIO", ".m4a": "AUDIO",
}

_CHAT_LINE = re.compile(r"^\[?\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4},?\s+\d{1,2}:\d{2}", re.M)

_CUES: dict[str, list[str]] = {
    "BANK_STATEMENT": ["account statement", "statement of account", "closing balance", "opening balance", "ifsc", "debit", "credit", "narration", "cheque no", "txn"],
    "FIR_POLICE": ["first information report", "fir no", "police station", "investigating officer", "complainant", "cognizable", "seizure memo"],
    "FORENSIC_REPORT": ["fingerprint", "latent print", "forensic", "dna", "ballistic", "chain of custody", "scene of crime", "ridge", "specimen", "exhibit"],
    "MEDICAL": ["post-mortem", "postmortem", "autopsy", "cause of death", "medico-legal", "discharge summary", "injury report"],
    "CCTV_LOG": ["cctv", "footage", "camera", "dvr", "timestamp", "frame"],
    "COURT_ORDER": ["in the court of", "order sheet", "hon'ble", "judgment", "petitioner", "respondent", "cause title"],
    "CONTRACT": ["agreement", "whereas", "hereinafter", "party of the first part", "indemnif", "termination", "governing law", "witnesseth", "arbitration", "confidentiality"],
    "LETTER": ["dear sir", "dear madam", "yours faithfully", "yours sincerely", "subject:", "reference no"],
}
_NEED = {"CONTRACT": 3, "BANK_STATEMENT": 3, "FIR_POLICE": 2, "FORENSIC_REPORT": 2, "MEDICAL": 2, "CCTV_LOG": 3, "COURT_ORDER": 2, "LETTER": 2}


def media_kind(filename: str) -> str:
    return MEDIA_KINDS.get(os.path.splitext(filename.lower())[1], "TEXT")


def classify_document(filename: str, pages: list[str]) -> str:
    kind = media_kind(filename)
    name = filename.lower()
    if kind != "TEXT":
        return "CCTV_LOG" if ("cctv" in name or "footage" in name or "camera" in name) else "MEDIA"
    text = "\n".join(pages[:3])[:6000]
    low = (name + "\n" + text).lower()
    if "whatsapp" in low or len(_CHAT_LINE.findall(text)) >= 5:
        return "CHAT"
    scores = {}
    for cls, cues in _CUES.items():
        scores[cls] = sum(1 for c in cues if c in low)
    best = max(scores, key=lambda k: (scores[k], k != "LETTER"))
    return best if scores[best] >= _NEED.get(best, 2) else "OTHER"
