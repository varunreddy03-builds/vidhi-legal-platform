"""Roles and permissions: ONE table decides who may call what, enforced for every API route by a single
router-level dependency (see server.py). A handler cannot forget it, and tests/test_rbac.py fails if a route
becomes public by accident.

Capabilities
  read       view anything in the organisation
  write      create / edit matters, documents, facts, evidence, drafts, recovery cases, payments records
  ai         run AI features (they cost money and send matter text to the model provider)
  send_mail  email other people (debtors, accountants) from the platform
  advocate_review  record an advocate's review of a demand notice (shown as the reviewer's own declaration)
  approve_draft  approve a draft that its author sent for review, or ask for changes (the author cannot approve their own, except in a one-person firm)
  delete     delete matters, documents, drafts, cases
  admin      members, invitations, firm branding, retention settings, data export, org-wide audit log
  billing    buy / view the subscription
  owner      organisation-level: erase the whole organisation
  account    your own sign-in settings, sessions and data requests (every role, clients included)
  portal     the read-only client portal (CLIENT only)

Roles (a user has exactly one)
  OWNER   everything
  ADMIN   everything except billing and organisation erasure
  LAWYER  work on matters and cases, use AI, email third parties; cannot delete or administer
  MEMBER  read and add/edit records; no AI, no emailing third parties, no deleting
  CLIENT  a client of the firm: sees ONLY what a lawyer shared with them through the portal (updates and chosen documents of the matters they were
          given access to). Everything else is refused because CLIENT holds no "read" or "write": the policy table below denies by default.
"""

import re

ROLES = ("OWNER", "ADMIN", "LAWYER", "MEMBER")  # the firm's own people; a CLIENT is a different kind of user (see ROLE_CAPS)

ROLE_CAPS: dict[str, frozenset[str]] = {
    "OWNER": frozenset({"read", "write", "ai", "send_mail", "delete", "admin", "billing", "owner", "advocate_review", "approve_draft", "account"}),
    "ADMIN": frozenset({"read", "write", "ai", "send_mail", "delete", "admin", "advocate_review", "approve_draft", "account"}),
    "LAWYER": frozenset({"read", "write", "ai", "send_mail", "advocate_review", "approve_draft", "account"}),
    "MEMBER": frozenset({"read", "write", "account"}),
    "CLIENT": frozenset({"account", "portal"}),
}

# Roles a given role may grant, change or remove (an ADMIN cannot create or touch owners/admins).
MANAGEABLE_BY: dict[str, frozenset[str]] = {
    "OWNER": frozenset(ROLES) | {"CLIENT"},
    "ADMIN": frozenset({"LAWYER", "MEMBER", "CLIENT"}),
}


def caps_for(role: str | None) -> list[str]:
    return sorted(ROLE_CAPS.get(role or "", frozenset()))


def can(user: dict, cap: str) -> bool:
    return cap in ROLE_CAPS.get(user.get("role", ""), frozenset())


# (HTTP method or "*", regex over the route TEMPLATE e.g. /api/matters/{matter_id}, capability or None)
# First match wins. None = the route is public or does its own authentication (verified by tests/test_rbac.py).
POLICY: list[tuple[str, str, str | None]] = [
    # ---- public / self-authenticating ----
    ("*", r"^/api/health(/ready)?$", None),
    ("POST", r"^/api/auth/(signup|login|logout|verify-email|forgot-password|reset-password|accept-invite)$", None),
    ("GET", r"^/api/auth/invites/\{token\}$", None),
    ("GET", r"^/api/auth/(options|google/start|google/callback)$", None),
    ("*", r"^/api/public/", None),
    ("POST", r"^/api/(webhook/stripe|webhook/razorpay|webhook/paypal|webhooks/resend|webhooks/sendgrid|webhooks/twilio)$", None),
    ("POST", r"^/api/cron/", None),
    ("GET", r"^/api/payments/status/\{session_id\}$", None),
    ("GET", r"^/api/org/logo/\{org_id\}$", None),
    # ---- any signed-in user ----
    ("GET", r"^/api/auth/me$", "account"),
    ("POST", r"^/api/auth/(verify-email/request|change-password|logout-all)$", "account"),
    ("PATCH", r"^/api/auth/preferences$", "account"),
    ("*", r"^/api/auth/sessions(/\{session_id\})?$", "account"),  # your own sign-in sessions
    # ---- the client portal: clients only see what was shared with them; the people who share it need to be allowed to email third parties ----
    ("*", r"^/api/portal/", "portal"),
    ("*", r"^/api/matters/\{matter_id\}/portal(/|$)", "send_mail"),
    ("POST", r"^/api/voice/(transcribe|speak)", "ai"),  # paid speech services: members without the ai capability cannot spend the budget here
    ("*", r"^/api/voice/", "read"),
    ("*", r"^/api/decide/", "read"),
    ("*", r"^/api/support/", "account"),
    ("DELETE", r"^/api/documents/\{document_id\}/notes/\{note_id\}$", "write"),  # a page note is a remark, not a case record: anyone who can write one can remove it
    ("DELETE", r"^/api/deadlines/\{deadline_id\}$", "write"),  # a saved date is not a case record: anyone who can save one can remove it
    ("*", r"^/api/push/", "read"),  # your own devices for notifications  # your own support messages
    ("*", r"^/api/admin/", "read"),  # any signed-in user reaches the route; require_platform_admin (lib/platform.py) is what lets only the operator in
    ("*", r"^/api/pilot/", "account"),  # a pilot lawyer's feedback form: any signed-in person
    ("*", r"^/api/privacy/", "account"),  # your own data-rights requests and your own data
    ("POST", r"^/api/images/generate$", "write"),  # makes a stored picture; Pro, capped, off by default
    ("GET", r"^/api/images/(status|\{image_id\})$", "read"),  # reads and sorts; changes nothing
    ("*", r"^/api/auth/phone(/start|/verify)?$", "read"),  # your own phone for alerts  # speaking a question / listening to an answer: no records are changed
    ("POST", r"^/api/auth/2fa/(setup|enable|disable|recovery-codes)$", "account"),  # your own account's two-step sign-in
    ("POST", r"^/api/verify-citation$", "read"),  # a library lookup, no AI
    ("POST", r"^/api/conflicts/check$", "read"),  # compares names with your own records; changes nothing
    ("POST", r"^/api/documents/compare$", "read"),  # compares two of your own documents; changes nothing
    ("*", r"^/api/directory/", "send_mail"),  # listing yourself publicly and reading requests from strangers: owner, admin and lawyer only
    ("GET", r"^/api/org/(branding|logo)$", "read"),  # everyone needs the letterhead
    # ---- AI ----
    ("POST", r"^/api/research$", "ai"),
    ("POST", r"^/api/analysis/\{kind\}$", "ai"),
    ("POST", r"^/api/legal-reasoning$", "ai"),
    ("POST", r"^/api/evidence/classify$", "read"),  # a code-only screen of pasted text; no AI, nothing stored
    ("*", r"^/api/research/\{research_id\}/feedback$", "read"),  # a thumbs up or down on your own organisation's answer
    ("POST", r"^/api/documents/\{document_id\}/analyze$", "ai"),
    ("POST", r"^/api/matters/\{matter_id\}/synthesize$", "ai"),
    ("POST", r"^/api/recovery/cases/\{case_id\}/(extract|notice|notice/translate)$", "ai"),
    ("POST", r"^/api/recovery/cases/\{case_id\}/notice/translations/\{tid\}/approve$", "send_mail"),
    # ---- email to other people ----
    ("POST", r"^/api/recovery/cases/\{case_id\}/(email|email/prepare|statement-email|statement-retry-cc|accountants/resend)$", "send_mail"),
    ("PUT", r"^/api/recovery/cases/\{case_id\}/accountants$", "send_mail"),
    ("POST", r"^/api/recovery/cases/\{case_id\}/notice/(approve|mark|postal|postal/[^/]+/update)$", "send_mail"),
    ("POST", r"^/api/recovery/cases/\{case_id\}/notice/review$", "advocate_review"),
    ("POST", r"^/api/drafts/\{draft_id\}/review$", "approve_draft"),
    # ---- billing ----
    ("*", r"^/api/payments/(checkout|history|receipt/|subscription/)", "billing"),
    # ---- organisation administration ----
    ("DELETE", r"^/api/org$", "owner"),
    ("*", r"^/api/org(/|$)", "admin"),
    ("PATCH", r"^/api/matters/\{matter_id\}/legal-hold$", "admin"),
    ("*", r"^/api/v1/katalyst/keys(/|$)", "account"),  # making, listing and removing your own add-in keys (the browser session only: a key cannot make a key)
    ("POST", r"^/api/v1/katalyst/(analyze-text|redline-docx)$", "read"),  # reads the text it is sent and answers; stores nothing and changes no record
    # ---- routine edits that are not "deleting a record of the matter" ----
    ("DELETE", r"^/api/matters/\{matter_id\}/(facts|timeline|evidence)/", "write"),
    ("DELETE", r"^/api/recovery/cases/\{case_id\}/payment/", "write"),
    ("DELETE", r"^/api/(datelists|defectchecks|oldcodechecks|authority/checks)/\{[a-z_]+\}$", "write"),  # a Toolkit report holds sentences from a draft: whoever may make one may remove it
    # ---- defaults by method ----
    ("DELETE", r".*", "delete"),
    ("POST", r".*", "write"),
    ("PATCH", r".*", "write"),
    ("PUT", r".*", "write"),
    ("GET", r".*", "read"),
]
_COMPILED = [(m, re.compile(p), cap) for m, p, cap in POLICY]


def required_cap(method: str, path_template: str) -> str | None:
    for m, rx, cap in _COMPILED:
        if m in ("*", method.upper()) and rx.match(path_template):
            return cap
    return "admin"  # unknown method: the strictest sensible default
