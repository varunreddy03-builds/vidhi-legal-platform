"""Canonical VIDHI Pydantic models. Each has a hand-mirrored TS interface in frontend/src/lib/types.ts."""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- auth ----------
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456789", "1234567890", "12345678910", "qwertyuiop",
    "iloveyou12", "welcome123", "admin12345", "letmein123", "vidhi12345", "changeme123",
}


def password_problem(password: str, email: str) -> str | None:
    """Why this password is not acceptable, or None. Shared by signup, invitations and resets."""
    pw = password.lower()
    if pw in _COMMON_PASSWORDS or len(set(pw)) < 4:
        return "password is too easy to guess - choose a longer, less common one"
    local = str(email).split("@", 1)[0].lower()
    if len(local) >= 4 and local in pw:
        return "password must not contain your email name"
    return None


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    organization_name: str = Field(min_length=1, max_length=200)
    accept_privacy: bool = False  # the user has read how VIDHI handles data (/privacy)
    turnstile_token: str | None = Field(default=None, max_length=4096)  # Cloudflare Turnstile answer, required when bot protection is configured
    website: str = Field(default="", max_length=200)  # a field real people never see; bots fill it in
    invite_code: str | None = Field(default=None, max_length=100)  # the pilot invitation (only needed when SIGNUP_MODE=invite)
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)  # how long the form was open

    @model_validator(mode="after")
    def _checks(self) -> "SignupIn":
        problem = password_problem(self.password, str(self.email))
        if problem:
            raise ValueError(problem)
        if not self.accept_privacy:
            raise ValueError("please confirm you have read how VIDHI handles your data")
        return self


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    accept_privacy: bool = False


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    new_password: str = Field(min_length=10, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["OWNER", "ADMIN", "LAWYER", "MEMBER"] = "LAWYER"


class RoleIn(BaseModel):
    role: Literal["OWNER", "ADMIN", "LAWYER", "MEMBER"]

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)
    otp: str | None = Field(default=None, max_length=20)  # the 6-digit code (or a recovery code) when two-step sign-in is on


class UserOut(BaseModel):
    id: str
    email: str
    email_verified: bool = False
    capabilities: list[str] = []  # what this user's role allows (the server enforces it; the UI uses it to hide buttons)
    full_name: str
    role: Literal["OWNER", "ADMIN", "LAWYER", "MEMBER", "CLIENT"]
    organization_id: str
    organization_name: str
    language: str | None = None
    theme: Literal["dark", "light", "system"] | None = None
    two_factor: bool = False  # two-step sign-in is on for this account
    platform_admin: bool = False  # may open the operator's admin console (the server checks again on every admin call)
    two_step_required: bool = False  # owner/admin of a team: two-step sign-in is required
    two_step_due_at: datetime | None = None  # when it becomes enforced
    pilot: bool = False  # the account was made with a pilot invitation: sample or public drafts only, never client papers


# ---------- matter ----------
class MatterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    jurisdiction_id: str = Field(default="IN", max_length=10)
    parties: str = Field(default="", max_length=5000)


class Matter(BaseModel):
    id: str = Field(default_factory=_id)
    organization_id: str
    title: str
    description: str = ""
    jurisdiction_id: str = "IN"
    plugin_version: str = "1.0.0"
    parties: str = ""
    client_id: str | None = None  # the firm's client record this matter belongs to (routers/clients.py)
    status: Literal["OPEN", "ON_HOLD", "CLOSED"] = "OPEN"
    legal_hold: bool = False
    closed_at: datetime | None = None
    deletion_notice_at: datetime | None = None
    created_by: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MatterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    parties: str | None = Field(default=None, max_length=5000)
    client_id: str | None = Field(default=None, max_length=64)  # "" removes the link
    status: Literal["OPEN", "ON_HOLD", "CLOSED"] | None = None


# ---------- documents ----------
class DocumentOut(BaseModel):
    id: str
    matter_id: str
    organization_id: str
    filename: str
    document_type: str
    size_bytes: int
    page_count: int = 0
    processing_status: Literal["PROCESSING", "READY", "FAILED", "UNSUPPORTED"]
    failure_reason: str | None = None
    checksum: str
    doc_class: str = "OTHER"
    doc_class_source: Literal["AUTO", "USER"] = "AUTO"
    media_kind: Literal["TEXT", "IMAGE", "VIDEO", "AUDIO"] = "TEXT"
    description: str = ""  # user-written description, essential for video/audio which have no extractable text
    security_note: str | None = None  # set when the file contains instruction-like text (it is still treated as data)
    reading_note: str | None = None  # set when the text was read from a scan by AI and may contain mistakes
    text_available: bool = True
    page_meta: list[dict] = []  # per page: engine, languages, confidence (only when the engine reported one), warnings, uncertain
    uncertain_pages: list[int] = []  # pages that are empty, low-confidence or contain unreadable words: a claim resting on them cannot be called verified
    has_file: bool = False
    citations: list[dict[str, Any]] = []
    dates: list[dict[str, Any]] = []
    created_at: datetime


class DocumentDetail(DocumentOut):
    pages: list[str] = []


class ClauseFlag(BaseModel):
    clause: str
    risk: Literal["HIGH", "MEDIUM", "LOW"]
    why: str
    page: int | None = None
    quote: str = ""
    quote_verified: bool | None = None


class KeyFact(BaseModel):
    fact: str
    page: int | None = None
    quote: str = ""
    quote_verified: bool = False


class PersonRef(BaseModel):
    name: str
    role: str = "not stated"
    page: int | None = None
    quote: str = ""
    quote_verified: bool = False


class Anomaly(BaseModel):
    what: str
    page: int | None = None
    quote: str = ""
    quote_verified: bool = False


class DocumentAnalysis(BaseModel):
    document_id: str
    doc_class: str = "OTHER"
    summary: str
    flags: list[ClauseFlag] = []  # contracts only
    key_facts: list[KeyFact] = []  # evidence documents
    people: list[PersonRef] = []
    anomalies: list[Anomaly] = []
    evidence_items_found: int = 0
    unclear: list[str] = []
    coverage_note: str = ""
    neutral_adjusted: bool = False
    disclaimer: str = "Research tool only. Not legal advice."
    created_at: datetime = Field(default_factory=_now)


# ---------- evidence items, people, inconsistencies ----------
EvidenceKind = Literal[
    "FINGERPRINT", "FOOTPRINT", "DNA", "CCTV_SIGHTING", "WITNESS_STATEMENT", "DEVICE_RECORD", "DOCUMENT", "OTHER"
]
EvidenceStatus = Literal["MATCHED", "UNMATCHED", "UNIDENTIFIED", "UNKNOWN"]


class EvidenceItemCreate(BaseModel):
    kind: EvidenceKind = "OTHER"
    label: str = Field(min_length=2, max_length=200)
    status: EvidenceStatus = "UNKNOWN"
    identified_as: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    document_id: str | None = None
    page: int | None = None
    quote: str = Field(default="", max_length=1000)


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=_id)
    matter_id: str
    organization_id: str
    kind: EvidenceKind = "OTHER"
    label: str
    status: EvidenceStatus = "UNKNOWN"
    identified_as: str | None = None
    location: str | None = None
    document_id: str | None = None
    page: int | None = None
    quote: str = ""
    quote_verified: bool = False
    source: Literal["AI_EXTRACTED", "USER"] = "USER"
    created_at: datetime = Field(default_factory=_now)


class EvidenceUpdate(BaseModel):
    status: EvidenceStatus | None = None
    identified_as: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, min_length=2, max_length=200)


class Appearance(BaseModel):
    document_id: str
    doc_label: str
    page: int | None = None
    quote: str


class Entity(BaseModel):
    id: str = Field(default_factory=_id)
    matter_id: str
    organization_id: str
    name: str
    role: str = "not stated"
    aliases: list[str] = []
    appearances: list[Appearance] = []
    created_at: datetime = Field(default_factory=_now)


class Inconsistency(BaseModel):
    id: str = Field(default_factory=_id)
    matter_id: str
    organization_id: str
    description: str  # neutral wording only
    a: Appearance
    b: Appearance
    created_at: datetime = Field(default_factory=_now)


# ---------- facts / timeline / evidence ----------
FactStatus = Literal[
    "DIRECT",
    "DOCUMENT_SUPPORTED",
    "LAWYER_PROVIDED",
    "INFERRED",
    "CONTESTED",
    "CONTRADICTED",
    "MISSING",
]


class FactCreate(BaseModel):
    value: str = Field(min_length=1)
    fact_type: Literal["EVENT", "DATE", "PARTY", "AMOUNT", "NOTE"] = "NOTE"
    status: FactStatus = "LAWYER_PROVIDED"
    document_id: str | None = None
    page_reference: int | None = None
    evidence: str = ""


class Fact(BaseModel):
    id: str = Field(default_factory=_id)
    matter_id: str
    organization_id: str
    value: str
    fact_type: str
    status: FactStatus
    document_id: str | None = None
    page_reference: int | None = None
    evidence: str = ""
    created_by: str
    created_at: datetime = Field(default_factory=_now)


class TimelineCreate(BaseModel):
    event_date: str = Field(min_length=4)
    description: str = Field(min_length=1)
    actor: str = ""
    document_id: str | None = None
    page_reference: int | None = None
    status: FactStatus = "LAWYER_PROVIDED"

    @field_validator("event_date")
    @classmethod
    def _real_date(cls, v: str) -> str:
        """The timeline sorts by this text, so it must be a real calendar date: 2026, 2026-05 or 2026-05-03 (a time after it is allowed). Found by the feature walk: 'not-a-date' used to be stored."""
        v = v.strip()
        # the exact shape first (ASCII digits only, two-digit month and day), then the calendar: strptime alone would also accept '2026-5-3', which sorts after '2026-12-01'
        shape = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?)?)?", v, re.ASCII)
        ok = False
        if shape:
            year, month, day, hour, minute, second = shape.groups()
            try:
                if month is None:
                    ok = 1900 <= int(year) <= 2200
                else:
                    datetime(int(year), int(month), int(day or 1), int(hour or 0), int(minute or 0), int(second or 0))
                    ok = 1900 <= int(year) <= 2200
            except ValueError:
                ok = False
        if not ok:
            raise ValueError("Use a real date such as 2026-05-03 (a year or a year and month is also fine).")
        return v


class TimelineEvent(BaseModel):
    id: str = Field(default_factory=_id)
    matter_id: str
    organization_id: str
    event_date: str
    description: str
    actor: str = ""
    document_id: str | None = None
    page_reference: int | None = None
    status: FactStatus
    created_at: datetime = Field(default_factory=_now)


# ---------- research ----------
class ResearchIn(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    matter_id: str | None = None
    mode: Literal["QUICK", "STANDARD", "MATTER", "DEEP"] = "STANDARD"
    language: str | None = Field(default=None, max_length=5)  # reply language (a code from lib/languages.py); English if unset


class Citation(BaseModel):
    citation: str
    authority_level: Literal["PRIMARY", "SECONDARY", "MATTER_DOCUMENT", "UNKNOWN"] = "UNKNOWN"
    verification_status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "UNAVAILABLE"] = (
        "UNVERIFIED"
    )
    passage: str = ""
    document_id: str | None = None
    page: int | None = None
    library_id: str | None = None  # set when this resolved to a verified-library entry
    doc_label: str | None = None
    quote_verified: bool = False  # the quoted words were found EXACTLY in the source
    source_name: str = ""  # a library citation: who published the text (from the verified entry, never from the model)
    source_url: str = ""
    version: str = ""
    verified_by: str = ""  # the named person who compared the entry with the source
    verified_on: str = ""
    source_text: str = ""  # the entry's own text (capped), so the screen can show the passage in its place
    authority_note: str = ""  # why the authority level is what it is, when it is not simply "primary legislation" (e.g. a case: weight depends on the forum)


class Claim(BaseModel):
    id: str = Field(default_factory=_id)
    text: str
    claim_type: Literal["LEGAL", "FACTUAL", "PROCEDURAL"] = "LEGAL"
    claim_kind: Literal["LEGAL", "FACTUAL", "PROCEDURAL", "ABSENCE"] = "LEGAL"
    verification_status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNSUPPORTED"] = "UNSUPPORTED"
    note: str = ""  # plain-language reason for the status, written by the server
    citations: list[Citation] = []
    conflicts: list[dict[str, Any]] = []  # exact passages elsewhere in the matter that disagree
    human_review_required: bool = False


class ResearchResult(BaseModel):
    id: str = Field(default_factory=_id)
    organization_id: str
    matter_id: str | None = None
    question: str
    mode: str
    answer: str
    claims: list[Claim] = []
    contrary_authority: list[str] = []
    uncertainty: str = ""
    matter_context_used: list[str] = []
    coverage: dict[str, Any] = {}  # exactly what the model was and was not shown
    missing_information: list[str] = []
    unresolved_evidence: list[str] = []  # evidence items the answer must not ignore (server-added)
    unverified_references: list[str] = []  # legal references in the text that are not in the verified library
    judgments: list[dict[str, Any]] = []  # High Court judgments that look relevant (NOT reviewed), for lookup only; never used to verify a claim
    draft_law: list[dict[str, Any]] = []  # draft (NOT reviewed) provisions that look relevant, found by search and shown for lookup only; never used to verify a claim
    neutral_adjusted: bool = False
    capabilities_used: list[str] = []
    source_versions: list[dict[str, Any]] = []  # every source the answer drew on: kind, link, version, hash of the exact text, who checked it and when, status (lib/verified_store.py)
    disclaimer: str = "Research tool only. Not legal advice."
    created_by: str
    created_at: datetime = Field(default_factory=_now)


class VerifyIn(BaseModel):
    citation: str = Field(min_length=2, max_length=500)
    claim: str = Field(default="", max_length=4000)
    jurisdiction_id: str = "IN"


class VerifyCheck(BaseModel):
    label: str
    status: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    detail: str


class VerifyResult(BaseModel):
    id: str = Field(default_factory=_id)
    citation: str
    normalized_citation: str | None = None
    verification_status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "UNAVAILABLE"]
    checks: list[VerifyCheck] = []
    contrary_authority: list[str] = []
    library_id: str | None = None
    source_text: str | None = None  # the EXACT text from the verified library
    source_name: str | None = None
    source_url: str | None = None
    version: str | None = None
    verified_by: str | None = None
    verified_on: str | None = None
    suggestions: list[dict[str, str]] = []
    source_versions: list[dict[str, Any]] = []  # the version of the source that was shown (lib/verified_store.py)
    notes: str = ""
    human_review_required: bool = True
    created_at: datetime = Field(default_factory=_now)


# ---------- drafts ----------
class DraftCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    matter_id: str | None = None


class DraftUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    autosave: bool = False  # a background save while the person is typing: it updates the text in place and makes no new version and no audit entry (a manual save still does)


class Draft(BaseModel):
    id: str = Field(default_factory=_id)
    organization_id: str
    matter_id: str | None = None
    title: str
    body: str = ""
    version: int = 1
    linked_sources: list[str] = []
    template_id: str | None = None  # set when the draft was made from a template (lib/templates.py)
    template_review: dict | None = None  # the template's review state when the draft was made: {status, reviewed, reviewed_by, reviewed_on}
    status: Literal["DRAFT", "WITH_REVIEWER", "APPROVED", "CHANGES_REQUESTED"] = "DRAFT"  # routers/draft_review.py; any change to the text returns it to DRAFT
    review: dict | None = None  # who sent it for review and who decided, when, and why (routers/draft_review.py)
    template_values: dict | None = None  # the answers given to the template (lib/draft_checks.py compares the text with them)
    created_by: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ---------- audit / graph ----------
class AuditEvent(BaseModel):
    id: str
    organization_id: str
    user_email: str
    matter_id: str | None = None
    operation: str
    result: str
    detail: str | None = None
    created_at: datetime


class GraphNode(BaseModel):
    id: str
    label: str
    sublabel: str | None = None  # e.g. a document's type, a person's role, a claim's verification status
    node_type: Literal["MATTER", "DOCUMENT", "FACT", "CLAIM", "SOURCE", "EVENT", "PERSON", "EVIDENCE"]


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: Literal[
        "SUPPORTS", "CITES", "DERIVED_FROM", "RELATES_TO", "EVIDENCES", "MENTIONS", "CONTRADICTS", "PART_OF", "IDENTIFIED_AS"
    ]


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class DashboardStats(BaseModel):
    matters: int
    documents: int
    research_sessions: int
    drafts: int
    unverified_claims: int


# ---------- entitlement (Division 1 is paid-gated; Division 2 is free) ----------
class Entitlement(BaseModel):
    plan: Literal["PRO", "FREE", "FIRM"]
    tier: Literal["pro", "free", "firm"] = "free"
    intelligence_access: bool
    recovery_access: bool
    trial_days_left: int = 0
    pro_until: datetime | None = None
    subscription_status: str | None = None
    cancel_at_period_end: bool = False
    ai_used_today: int = 0
    ai_limit_today: int | None = None  # free plan only
    usage: dict = {}  # every plan: ai_used_today, ai_limit_today, members_used, members_limit (lib/plans.usage_today)
    limits: dict = {}  # the plan comparison (lib/plans.summary): what free and pro include and what they cost


# ---------- Division 2: Legal Recovery ----------
RecoveryStatus = Literal[
    "DRAFT",
    "PROOF_ADDED",
    "TIMELINE_READY",
    "NOTICE_READY",
    "SENT_FOR_REVIEW",
    "RESOLVED",
]


class RecoveryTimelineItem(BaseModel):
    date: str = ""
    description: str = ""
    amount: float | None = None


class PaymentEntry(BaseModel):
    id: str = Field(default_factory=_id)
    amount: float
    date: datetime = Field(default_factory=_now)


class StatementLogEntry(BaseModel):
    id: str = Field(default_factory=_id)
    email: str
    date: datetime = Field(default_factory=_now)
    via: str = "manual"  # "manual" | "scheduled"
    owed: float = 0
    received: float = 0
    balance: float = 0
    cc: list[str] = []
    cc_failed: list[str] = []


class AccountantContact(BaseModel):
    """Someone the owner wants copied on statements. They only receive anything after THEY confirm."""

    email: str
    status: Literal["PENDING", "CONFIRMED", "DECLINED", "BOUNCED"] = "PENDING"
    requested_at: datetime = Field(default_factory=_now)
    responded_at: datetime | None = None


Tri = Literal["yes", "no", "unsure"]


class PromiseToPay(BaseModel):
    text: str = Field(default="", max_length=1000)  # what the customer wrote/said, in the owner's words
    date: str | None = Field(default=None, max_length=10)


class Disputes(BaseModel):
    invoice: bool = False
    quality: bool = False
    delivery: bool = False
    amount: bool = False
    note: str = Field(default="", max_length=1000)


class RouteAnswers(BaseModel):
    """The owner's own answers; None means not answered yet. Used only to raise plain warnings (lib/route_checks.py)."""

    cheque_given: Tri | None = None
    cheque_bounced: Tri | None = None
    msme: Tri | None = None  # is the owner's business a micro/small enterprise?
    existing_proceedings: Tri | None = None
    insolvency: Tri | None = None


class CaseIntake(BaseModel):
    invoice_number: str = Field(default="", max_length=60)
    invoice_date: str | None = Field(default=None, max_length=10)
    supply_description: str = Field(default="", max_length=1000)  # goods or services supplied
    payment_terms: str = Field(default="", max_length=500)
    creditor_email: str = Field(default="", max_length=200)
    creditor_phone: str = Field(default="", max_length=30)
    debtor_phone: str = Field(default="", max_length=30)
    promise_to_pay: PromiseToPay = PromiseToPay()
    disputes: Disputes = Disputes()
    route: RouteAnswers = RouteAnswers()
    response_days: int = Field(default=15, ge=7, le=60)  # how long the notice gives the customer to respond


def whole_paise(v: float) -> float:
    """Money entered by a person is kept to whole paise; something that rounds to nothing is refused."""
    q = round(float(v), 2)
    if q < 0.01:
        raise ValueError("Enter an amount of at least 0.01.")
    return q


class Charge(BaseModel):
    """An extra amount claimed on top of the invoice. Counts only with a written basis."""

    id: str = Field(default_factory=_id)
    label: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    basis: str = Field(default="", max_length=300)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: float) -> float:
        return whole_paise(v)


class Credit(BaseModel):
    """A credit note, discount or return that reduces what is owed."""

    id: str = Field(default_factory=_id)
    label: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    reason: str = Field(default="", max_length=300)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: float) -> float:
        return whole_paise(v)


class RecoveryCaseCreate(BaseModel):
    creditor_name: str = Field(min_length=1, max_length=200)
    debtor_name: str = Field(min_length=1, max_length=200)
    amount: float = Field(default=0, ge=0, le=1_000_000_000_000, allow_inf_nan=False)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    description: str = Field(default="", max_length=5000)
    debtor_email: str = Field(default="", max_length=200)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: float) -> float:
        return round(v, 2)


class RecoveryCase(BaseModel):
    id: str = Field(default_factory=_id)
    organization_id: str
    created_by: str
    creditor_name: str
    debtor_name: str
    amount: float = 0
    currency: str = "INR"
    description: str = ""
    debtor_email: str = ""
    creditor_address: str = ""
    debtor_address: str = ""
    intake: CaseIntake = CaseIntake()
    charges: list[Charge] = []
    credits: list[Credit] = []
    due_date: str | None = None  # ISO date the money fell due (user-entered)
    interest_rate_pct: float | None = None  # user-entered rate; never defaulted
    debtor_email_status: str | None = None  # last known delivery state of the notice email
    status: RecoveryStatus = "DRAFT"
    summary: str = ""
    detected_amount: float | None = None
    timeline: list[RecoveryTimelineItem] = []
    notice_body: str = ""
    postal: list[dict] = []  # postal dispatches of the notice and their tracking updates, as typed in by the owner
    workflow: dict = {}  # notice approval state, current version, history (lib/notice_workflow.py)
    notice_meta: dict = {}  # how the current notice text was made (when, balance, enclosures, AI drafted)
    linked_matter_id: str | None = None
    reminders_enabled: bool = True
    reminder_cadence_days: int = 3
    snooze_until: datetime | None = None
    last_reminded_at: datetime | None = None
    resolved_at: datetime | None = None
    deletion_notice_at: datetime | None = None
    paid_amount: float = 0
    payments: list[PaymentEntry] = []
    statement_schedule: Literal["OFF", "MONTHLY", "FORTNIGHTLY"] = "MONTHLY"
    statement_day: int = 1
    last_statement_sent_at: datetime | None = None
    statement_paused_until: datetime | None = None
    accountant_emails: list[str] = []  # derived: CONFIRMED contacts only (see validator)
    accountants: list[AccountantContact] = []
    statement_log: list[StatementLogEntry] = []
    notice_check: dict = {}  # derived: blanks / legal references still in the notice
    guide: dict = {}  # the guided flow: stage, the five eligibility answers, how the notice was delivered (routers/recovery.py set_guide)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _derive(self) -> "RecoveryCase":
        # Legacy cases stored raw accountant_emails with no consent: they are NOT trusted.
        self.accountant_emails = [a.email for a in self.accountants if a.status == "CONFIRMED"]
        from lib.notice_checks import blockers_for

        self.notice_check = blockers_for(self.model_dump(exclude={"notice_check"})) if self.notice_body else {}
        return self


class PaymentTransactionOut(BaseModel):
    session_id: str
    amount: float
    currency: str
    status: str
    payment_status: str
    package_id: str = ""
    card_brand: str | None = None
    card_last4: str | None = None
    created_at: datetime


class RecoveryProof(BaseModel):
    id: str = Field(default_factory=_id)
    case_id: str
    organization_id: str
    filename: str
    document_type: str
    size_bytes: int
    page_count: int = 0
    processing_status: Literal["READY", "FAILED", "UNSUPPORTED"]
    failure_reason: str | None = None
    kind: str = "OTHER"  # INVOICE / PURCHASE_ORDER / AGREEMENT / DELIVERY_PROOF / PAYMENT_RECORD / COMMUNICATION / OTHER
    page_meta: list[dict] = []  # per page: engine, languages, confidence (only when the engine reported one), warnings, uncertain
    uncertain_pages: list[int] = []  # pages that are empty, low-confidence or contain unreadable words: a claim resting on them cannot be called verified
    has_file: bool = False  # the original file is kept (so it can be listed, downloaded and preserved)
    checksum: str = ""
    excerpt: str = ""
    created_at: datetime = Field(default_factory=_now)
