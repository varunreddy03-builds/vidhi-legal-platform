"""Which countries' law VIDHI actually covers. A country is "live" only after its verified law library, privacy requirements, payment
arrangements and operational readiness have been checked: until then nothing in the product may imply it supports that country's law."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    status: str  # "live" or "planned"
    currency: str
    note: str


REGISTRY = {
    "IN": Jurisdiction("IN", "India", "live", "INR", "Launch market. Coverage is limited to what is in the verified library."),
    "AE": Jurisdiction("AE", "United Arab Emirates", "planned", "AED", "Next: Indian-law questions for NRIs and cross-border documents."),
    "UK": Jurisdiction("UK", "United Kingdom", "planned", "GBP", "Needs a UK-law library and jurisdiction safeguards."),
    "US": Jurisdiction("US", "United States", "planned", "USD", "Needs US-law coverage; state-level differences."),
    "SG": Jurisdiction("SG", "Singapore", "planned", "SGD", "Needs Singapore-law coverage and business workflows."),
}


def live() -> set[str]:
    return {c for c, j in REGISTRY.items() if j.status == "live"}


def is_live(code: str) -> bool:
    return code in live()