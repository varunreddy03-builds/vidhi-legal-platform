"""Electronic signing and e-stamping: an EXTENSION POINT only. Nothing here signs, stamps or sends anything, and VIDHI makes no claim that any document is signed.

A provider (for example Digio or Leegality, both Indian e-sign services) can be added later by implementing ESignProvider and registering it in PROVIDERS. Until then
the active provider is NotConfigured, every call raises ESignNotAvailable, and callers must show "e-signing is not available" instead of a signature step.

Before a real provider is switched on a person (not code) must decide, with a lawyer:
  * which kinds of signature are valid for which kinds of document in which state, and which documents cannot be e-signed at all;
  * how stamp duty is paid for each document type and state (e-stamping is a separate service from signing);
  * who the signers are, how their identity is checked, and how the signed file and its audit trail are kept (DATA_STORAGE.md) and for how long;
  * the provider's contract, price, data location and sub-processors (RESIDENCY_CHECK.md).
Nothing in this file answers those questions."""

from dataclasses import dataclass, field
from typing import Protocol


class ESignNotAvailable(Exception):
    """No e-sign provider is configured (the only state VIDHI ships in)."""


@dataclass(frozen=True)
class Signer:
    name: str
    email: str


@dataclass(frozen=True)
class SignRequest:
    document_name: str
    content: bytes  # the exact file to be signed
    signers: tuple[Signer, ...]
    reference: str = ""  # VIDHI's own id for the draft or matter, never the signers' personal data


@dataclass
class SignStatus:
    request_id: str
    state: str  # "pending" | "signed" | "declined" | "expired" | "failed" - as REPORTED BY THE PROVIDER, never inferred
    detail: str = ""
    signed_file: bytes | None = None
    audit_trail: list[dict] = field(default_factory=list)


class ESignProvider(Protocol):
    name: str

    async def create_request(self, request: SignRequest) -> str:
        """Start signing; returns the provider's request id."""

    async def status(self, request_id: str) -> SignStatus:
        """Ask the provider. Never guess: if the provider cannot be reached, raise."""


class NotConfigured:
    name = "none"

    async def create_request(self, request: SignRequest) -> str:
        raise ESignNotAvailable("e-signing is not available")

    async def status(self, request_id: str) -> SignStatus:
        raise ESignNotAvailable("e-signing is not available")


PROVIDERS: dict[str, ESignProvider] = {"none": NotConfigured()}  # a future provider registers itself here under its own name


def active() -> ESignProvider:
    """The provider in use. Only "none" exists today."""
    return PROVIDERS["none"]


def available() -> bool:
    return not isinstance(active(), NotConfigured)