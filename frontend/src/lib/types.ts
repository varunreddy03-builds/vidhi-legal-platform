// Hand-mirrored TS interfaces for backend/models/schemas.py. Keep both sides in sync.

export interface UserOut {
  id: string;
  email: string;
  email_verified: boolean;
  full_name: string;
  role: "OWNER" | "ADMIN" | "LAWYER" | "MEMBER" | "CLIENT";
  /** What this role may do: read, write, ai, send_mail, delete, admin, billing, owner. The server enforces it; this only hides buttons. */
  capabilities: string[];
  organization_id: string;
  organization_name: string;
  two_factor?: boolean;
  platform_admin?: boolean;
  two_step_required?: boolean;
  two_step_due_at?: string | null;
  language?: string | null;
  theme?: "dark" | "light" | "system" | null;
  /** The account was made with a pilot invitation: sample or public drafts only, never client papers. */
  pilot?: boolean;
}

export interface Matter {
  id: string;
  organization_id: string;
  title: string;
  description: string;
  jurisdiction_id: string;
  plugin_version: string;
  parties: string;
  client_id?: string | null;
  status: "OPEN" | "ON_HOLD" | "CLOSED";
  kind?: "MATTER" | "VAULT";
  area?: "" | "tax";
  legal_hold: boolean;
  closed_at: string | null;
  deletion_notice_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DocEntity {
  text: string;
  page: number;
}

export interface DocumentOut {
  id: string;
  matter_id: string;
  organization_id: string;
  filename: string;
  document_type: string;
  size_bytes: number;
  page_count: number;
  processing_status: "PROCESSING" | "READY" | "FAILED" | "UNSUPPORTED";
  failure_reason: string | null;
  checksum: string;
  doc_class: string;
  doc_class_source: "AUTO" | "USER";
  media_kind: "TEXT" | "IMAGE" | "VIDEO" | "AUDIO";
  description: string;
  text_available: boolean;
  /** Set when the text was read from a scan or a photo by a program and may contain mistakes. */
  reading_note?: string | null;
  /** Pages that are empty, read with low confidence or contain unreadable words: a statement resting on them is never shown as verified. */
  uncertain_pages?: number[];
  /** How each page was read: the engine, its own confidence when it gave one, and warnings. */
  page_meta?: { page: number; engine: string; confidence: number | null; uncertain: boolean; warnings: string[] }[];
  has_file: boolean;
  citations: DocEntity[];
  dates: DocEntity[];
  created_at: string;
}

export interface ClauseFlag {
  clause: string;
  risk: "HIGH" | "MEDIUM" | "LOW";
  why: string;
  page: number | null;
  quote: string;
  quote_verified: boolean | null;
}

export interface KeyFact {
  fact: string;
  page: number | null;
  quote: string;
  quote_verified: boolean;
}

export interface PersonRef {
  name: string;
  role: string;
  page: number | null;
  quote: string;
  quote_verified: boolean;
}

export interface Anomaly {
  what: string;
  page: number | null;
  quote: string;
  quote_verified: boolean;
}

export interface DocumentAnalysis {
  document_id: string;
  doc_class: string;
  summary: string;
  flags: ClauseFlag[]; // contracts only
  key_facts: KeyFact[];
  people: PersonRef[];
  anomalies: Anomaly[];
  evidence_items_found: number;
  unclear: string[];
  coverage_note: string;
  neutral_adjusted: boolean;
  disclaimer: string;
  created_at: string;
}

export type EvidenceKind =
  | "FINGERPRINT" | "FOOTPRINT" | "DNA" | "CCTV_SIGHTING" | "WITNESS_STATEMENT" | "DEVICE_RECORD" | "DOCUMENT" | "OTHER";
export type EvidenceStatus = "MATCHED" | "UNMATCHED" | "UNIDENTIFIED" | "UNKNOWN";

export interface EvidenceItem {
  id: string;
  matter_id: string;
  kind: EvidenceKind;
  label: string;
  status: EvidenceStatus;
  identified_as: string | null;
  location: string | null;
  document_id: string | null;
  page: number | null;
  quote: string;
  quote_verified: boolean;
  source: "AI_EXTRACTED" | "USER";
  created_at: string;
}

export interface Appearance {
  document_id: string;
  doc_label: string;
  page: number | null;
  quote: string;
}

export interface Entity {
  id: string;
  matter_id: string;
  name: string;
  role: string;
  aliases: string[];
  appearances: Appearance[];
}

export interface Inconsistency {
  id: string;
  matter_id: string;
  description: string;
  a: Appearance;
  b: Appearance;
}

export interface CoverageReport {
  documents_total: number;
  documents_with_text: number;
  documents_fully_read: number;
  documents_partly_read: string[];
  documents_not_read: string[];
  documents_without_text: string[];
  complete: boolean;
  summary: string;
}

export interface SynthesisResult {
  entities: Entity[];
  inconsistencies: Inconsistency[];
  unclear: string[];
  dropped_unverified: number;
  coverage: CoverageReport;
  neutral_adjusted: boolean;
}

export interface LibraryEntrySummary {
  id: string;
  citation: string;
  kind: string;
  source_name: string;
  version: string;
  verified_by: string;
  verified_on: string;
}

export interface LibraryStatus {
  count: number;
  note: string;
  entries: LibraryEntrySummary[];
}

export type FactStatus =
  | "DIRECT"
  | "DOCUMENT_SUPPORTED"
  | "LAWYER_PROVIDED"
  | "INFERRED"
  | "CONTESTED"
  | "CONTRADICTED"
  | "MISSING";

export interface Fact {
  id: string;
  matter_id: string;
  organization_id: string;
  value: string;
  fact_type: string;
  status: FactStatus;
  document_id: string | null;
  page_reference: number | null;
  evidence: string;
  created_by: string;
  created_at: string;
}

export interface TimelineEvent {
  id: string;
  matter_id: string;
  organization_id: string;
  event_date: string;
  description: string;
  actor: string;
  document_id: string | null;
  page_reference: number | null;
  status: FactStatus;
  created_at: string;
}

export interface Citation {
  citation: string;
  authority_level: "PRIMARY" | "SECONDARY" | "MATTER_DOCUMENT" | "UNKNOWN";
  authority_note?: string;
  verification_status: "VERIFIED" | "PARTIALLY_VERIFIED" | "UNVERIFIED" | "UNAVAILABLE";
  passage: string;
  document_id: string | null;
  page: number | null;
  library_id: string | null;
  doc_label: string | null;
  quote_verified: boolean;
  source_name?: string;
  source_url?: string;
  version?: string;
  verified_by?: string;
  verified_on?: string;
  source_text?: string;
}

export interface ClaimConflict {
  doc_label: string;
  filename: string;
  document_id: string;
  page: number;
  quote: string;
}

export interface Claim {
  id: string;
  text: string;
  claim_type: "LEGAL" | "FACTUAL" | "PROCEDURAL";
  claim_kind: "LEGAL" | "FACTUAL" | "PROCEDURAL" | "ABSENCE";
  verification_status: "VERIFIED" | "PARTIALLY_VERIFIED" | "UNSUPPORTED";
  note: string;
  citations: Citation[];
  conflicts: ClaimConflict[];
  human_review_required: boolean;
}

export interface DraftLawEntry {
  id: string;
  citation: string;
  heading: string;
  act_id: string;
  act_title: string;
  excerpt: string;
  text_length: number;
  source_name: string;
  source_url: string;
  version: string;
  commencement: string;
  legal_currency: string;
  historical: boolean;
  text_source?: string;
  coverage_note?: string;
  in_force_from?: string | null;
  in_force_until?: string | null;
  checked_on?: string;
  in_force_on_date?: "IN_FORCE" | "NOT_YET_IN_FORCE" | "PART_IN_FORCE" | "REPEALED" | "UNKNOWN";
  date_note?: string;
  status: string;
  note: string;
}

export interface JudgmentEntry {
  id: string;
  court_code: string;
  court_name: string;
  bench: string;
  year: number | null;
  case_title: string | null;
  judge: string | null;
  cnr: string | null;
  decision_date: string | null;
  disposal: string | null;
  source_url: string;
  text_kind: "TEXT" | "OCR" | "UNREADABLE" | "NOT_LOADED" | "NO_TEXT_LAYER";
  citation?: string | null;
  text_chars: number;
  excerpt: string;
  status: string;
  note: string;
}

export interface ResearchResult {
  id: string;
  organization_id: string;
  matter_id: string | null;
  question: string;
  mode: string;
  answer: string;
  claims: Claim[];
  contrary_authority: string[];
  uncertainty: string;
  matter_context_used: string[];
  coverage: Partial<CoverageReport>;
  missing_information: string[];
  unresolved_evidence: string[];
  unverified_references: string[];
  draft_law?: DraftLawEntry[];
  judgments?: JudgmentEntry[];
  neutral_adjusted: boolean;
  capabilities_used: string[];
  disclaimer: string;
  created_by: string;
  created_at: string;
}

export interface VerifyCheck {
  label: string;
  status: "PASS" | "WARN" | "FAIL" | "UNKNOWN";
  detail: string;
}

export interface VerifyResult {
  id: string;
  citation: string;
  normalized_citation: string | null;
  verification_status: "VERIFIED" | "PARTIALLY_VERIFIED" | "UNVERIFIED" | "UNAVAILABLE";
  checks: VerifyCheck[];
  contrary_authority: string[];
  library_id: string | null;
  source_text: string | null;
  source_name: string | null;
  source_url: string | null;
  version: string | null;
  verified_by: string | null;
  verified_on: string | null;
  suggestions: { id: string; citation: string }[];
  notes: string;
  human_review_required: boolean;
  created_at: string;
}

export interface Draft {
  id: string;
  organization_id: string;
  matter_id: string | null;
  title: string;
  body: string;
  version: number;
  linked_sources: string[];
  template_id: string | null;
  template_review: { status: string; reviewed: boolean; reviewed_by: string | null; reviewed_on: string | null } | null;
  template_values?: Record<string, string | number> | null;
  status?: "DRAFT" | "WITH_REVIEWER" | "APPROVED" | "CHANGES_REQUESTED";
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: string;
  organization_id: string;
  user_email: string;
  matter_id: string | null;
  operation: string;
  result: string;
  detail: string | null;
  created_at: string;
}

export interface GraphNode {
  id: string;
  label: string;
  sublabel?: string | null;
  node_type: "MATTER" | "DOCUMENT" | "FACT" | "CLAIM" | "SOURCE" | "EVENT" | "PERSON" | "EVIDENCE";
}

export interface GraphEdge {
  source: string;
  target: string;
  relation:
    | "SUPPORTS" | "CITES" | "DERIVED_FROM" | "RELATES_TO" | "EVIDENCES"
    | "MENTIONS" | "CONTRADICTS" | "PART_OF" | "IDENTIFIED_AS";
}

export interface GraphOut {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface DashboardStats {
  matters: number;
  documents: number;
  research_sessions: number;
  drafts: number;
  unverified_claims: number;
}

export interface SearchItem {
  id: string;
  label: string;
  href: string;
}
export interface SearchGroup {
  type: string;
  items: SearchItem[];
}
export interface SearchResponse {
  query: string;
  groups: SearchGroup[];
}

// ---------- entitlement (Division 1 paid-gated; Division 2 free) ----------
export interface PlanLimits {
  price: { amount: number; currency: string; interval: string };
  free: { ai_per_day: number; locked: string[]; reads_at_once_chars: number | null; models: string };
  pro: { ai_per_day: number; locked: string[]; reads_at_once_chars: number | null; models: string };
  firm?: { ai_per_day: number; locked: string[]; reads_at_once_chars: number | null; members_max: number | null; price: { amount: number; currency: string; interval: string } | null; models: string };
}

export interface Entitlement {
  plan: "PRO" | "FREE" | "FIRM";
  tier: "pro" | "free" | "firm";
  intelligence_access: boolean;
  recovery_access: boolean;
  pro_until: string | null;
  subscription_status: string | null;
  cancel_at_period_end: boolean;
  ai_used_today: number;
  ai_limit_today: number | null;
  usage?: { ai_used_today: number; ai_limit_today: number; members_used: number; members_limit: number | null };
  limits?: PlanLimits;
}

// ---------- Division 2: Legal Recovery ----------
export type RecoveryStatus =
  | "DRAFT"
  | "PROOF_ADDED"
  | "TIMELINE_READY"
  | "NOTICE_READY"
  | "SENT_FOR_REVIEW"
  | "RESOLVED";

export interface RecoveryTimelineItem {
  date: string;
  description: string;
  amount: number | null;
}

export interface PaymentEntry {
  id: string;
  amount: number;
  date: string;
}

export interface StatementLogEntry {
  id: string;
  email: string;
  date: string;
  via: string;
  owed: number;
  received: number;
  balance: number;
  cc: string[];
  cc_failed: string[];
}

export interface RecoveryCase {
  id: string;
  organization_id: string;
  created_by: string;
  creditor_name: string;
  debtor_name: string;
  amount: number;
  currency: string;
  description: string;
  debtor_email: string;
  status: RecoveryStatus;
  guide?: {
    stage?: "NOT_STARTED" | "PORTAL_FILED" | "NOTICE_SENT" | "ESCALATED";
    stage_changed_at?: string;
    delivery_method?: "downloaded" | "emailed" | "lawyer";
    portal_reference?: string;
    tracker?: { notice_date?: string; due_date?: string; next_date?: string };
    answers?: { udyam?: "yes" | "no" | "not_sure"; buyer?: "business" | "individual"; has_documents?: boolean; overdue?: "under_15" | "15_to_45" | "over_45"; amount?: number };
  };
  summary: string;
  detected_amount: number | null;
  timeline: RecoveryTimelineItem[];
  notice_body: string;
  linked_matter_id: string | null;
  reminders_enabled: boolean;
  reminder_cadence_days: number;
  snooze_until: string | null;
  last_reminded_at: string | null;
  paid_amount: number;
  payments: PaymentEntry[];
  statement_schedule: "OFF" | "MONTHLY" | "FORTNIGHTLY";
  statement_day: number;
  last_statement_sent_at: string | null;
  statement_paused_until: string | null;
  accountant_emails: string[]; // confirmed accountants only
  accountants: AccountantContact[];
  creditor_address: string;
  debtor_address: string;
  due_date: string | null;
  interest_rate_pct: number | null;
  debtor_email_status: string | null;
  notice_check: NoticeCheck | Record<string, never>;
  statement_log: StatementLogEntry[];
  intake: CaseIntake;
  charges: CaseCharge[];
  credits: CaseCredit[];
  notice_meta: Record<string, unknown>;
  workflow?: { state?: string };
  created_at: string;
  updated_at: string;
}

export type Tri = "yes" | "no" | "unsure";

export interface DeliveryInfo {
  display_status: string;
  emails: { id: string; to: string; status: string; at: string; version: number | null; events: { type: string; at: string }[] }[];
  postal: {
    id: string;
    service: string;
    tracking_no: string;
    sent_on: string;
    version: number | null;
    updates: { status: string; date: string }[];
  }[];
  correspondence: {
    id: string;
    direction: "IN" | "OUT";
    channel: string;
    occurred_on: string;
    summary: string;
    is_response: boolean;
  }[];
  evidence: { what_we_have: string[]; not_confirmed: string[] };
  legal_note: string;
}

export interface NoticeApproval {
  kind: "OWNER" | "ADVOCATE" | "ADVOCATE_CHANGES_REQUESTED";
  name: string;
  email: string;
  at: string;
  version: number;
  comments?: string;
  enrolment_no_stated_by_reviewer?: string;
}

export interface NoticeVersion {
  id: string;
  number: number;
  origin: string;
  body: string;
  created_at: string;
  created_by: { name: string; email: string } | null;
  approvals: NoticeApproval[];
  is_current: boolean;
}

export interface NoticeWorkflow {
  state: string;
  label: string;
  current_version: { id: string; number: number; origin: string; sha: string } | null;
  approved: NoticeApproval | null;
  review_request: { name: string; email: string; note: string; at: string } | null;
  last_review: { name: string; email: string; comments: string; at: string } | null;
  sent: { at: string; to: string; version: number | null } | null;
  history: { at: string; event: string; note?: string; by?: { name: string; email: string } }[];
  needs_advocate: boolean;
  needs_advocate_reason: string | null;
  allowed: string[];
  advocate_declaration: string;
  notes: string[];
}

export interface CaseIntake {
  invoice_number: string;
  invoice_date: string | null;
  supply_description: string;
  payment_terms: string;
  creditor_email: string;
  creditor_phone: string;
  debtor_phone: string;
  promise_to_pay: { text: string; date: string | null };
  disputes: { invoice: boolean; quality: boolean; delivery: boolean; amount: boolean; note: string };
  route: {
    cheque_given: Tri | null;
    cheque_bounced: Tri | null;
    msme: Tri | null;
    existing_proceedings: Tri | null;
    insolvency: Tri | null;
  };
  response_days: number;
}

export interface CaseCharge {
  id: string;
  label: string;
  amount: number;
  basis: string;
}

export interface CaseCredit {
  id: string;
  label: string;
  amount: number;
  reason: string;
}

export type ProofKind =
  | "INVOICE"
  | "PURCHASE_ORDER"
  | "AGREEMENT"
  | "DELIVERY_PROOF"
  | "PAYMENT_RECORD"
  | "COMMUNICATION"
  | "OTHER";

export interface BalanceLine {
  kind: "INVOICE" | "CHARGE" | "CREDIT" | "PAYMENT";
  label: string;
  amount: number;
  sign: 1 | -1;
  basis?: string;
  reason?: string;
  date?: string;
}

export interface Readiness {
  balance: {
    currency: string;
    lines: BalanceLine[];
    ignored_charges: { label: string; amount: number; reason: string }[];
    invoice_amount: number;
    charges_total: number;
    credits_total: number;
    balance: number;
    overpaid: boolean;
    suggested_amount: number | null;
    warnings: string[];
    formula: string;
  };
  evidence: {
    items: { key: string; label: string; need: "required" | "recommended"; why: string; status: "PRESENT" | "MISSING"; files: string[] }[];
    facts_missing: { key: string; label: string }[];
    required_missing: string[];
    complete: boolean;
    note: string;
  };
  routes: {
    flags: { key: string; level: "INFO" | "WARN" | "STOP"; title: string; text: string; questions?: string[] }[];
    blocks_notice: boolean;
    advocate_recommended: boolean;
    disclaimer: string;
  };
  provenance: { label: string; value: string; source: "YOU_ENTERED" | "CALCULATED" | "READ_FROM_DOCUMENTS" | "AI_SUGGESTION" }[];
  draft_blockers: string[];
  can_draft: boolean;
  route_acknowledgement_needed: boolean;
  response_days: number;
  disclaimer: string;
}

export interface RecoveryProof {
  id: string;
  case_id: string;
  organization_id: string;
  filename: string;
  document_type: string;
  size_bytes: number;
  page_count: number;
  processing_status: "READY" | "FAILED" | "UNSUPPORTED";
  failure_reason: string | null;
  kind: ProofKind;
  has_file: boolean;
  excerpt: string;
  created_at: string;
}

// ---------- payments (Stripe one-time Pro unlock) ----------
export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

export interface PaymentStatusResponse {
  session_id: string;
  status: string;
  payment_status: string;
}

export interface PaymentTransaction {
  session_id: string;
  amount: number;
  currency: string;
  status: string;
  payment_status: string;
  package_id: string;
  card_brand: string | null;
  card_last4: string | null;
  created_at: string;
}

// ---------- payments: purchasable packages (price is owned by the server) ----------
// ---------- recovery: interest, limitation, notice checks, outbound email ----------
export interface AccountantContact {
  email: string;
  status: "PENDING" | "CONFIRMED" | "DECLINED" | "BOUNCED";
  requested_at: string;
  responded_at: string | null;
}

export interface NoticeCheck {
  placeholders: string[];
  legal_references: string[];
  risky_language?: string[];
  amount_mismatches?: string[];
  service_claims?: string[];
  statement_changed?: boolean;
  figures_changed?: boolean;
  blocked: boolean;
}

export interface InterestSegment {
  from: string;
  to: string;
  days: number;
  balance: number;
  interest: number;
}

export interface InterestResult {
  principal: number;
  rate_pct: number;
  start: string;
  as_of: string;
  days: number;
  interest: number;
  principal_remaining: number;
  total_due: number;
  payments_counted: number;
  segments: InterestSegment[];
  assumptions: string[];
  currency: string;
}

export interface LimitationRule {
  id: string;
  applies_to: string;
  period_years: number;
  citation: string;
  source_text: string;
  source_url: string;
  verified_by: string;
  verified_on: string;
  deadline: string;
  days_left: number;
  status: "OK" | "SOON" | "PASSED";
}

export interface LimitationResult {
  mode: "NEEDS_DUE_DATE" | "GENERIC" | "VERIFIED_RULES";
  message: string;
  age_days: number | null;
  age_text: string | null;
  rules: LimitationRule[];
}

export interface NoticePreview {
  confirmation_id: string;
  to: string;
  cc: string[];
  sender_copy_to: string;
  subject: string;
  cover_message?: string;
  notice_text: string;
  translation: { language: string; language_name: string; text: string } | null;
  attachment_name: string;
  expires_in_minutes: number;
}

export interface NoticeTranslation {
  id: string;
  language: string;
  language_name: string;
  body: string;
  checks: { ok: boolean; problems: string[] };
  edited: boolean;
  created_at: string;
  approved: { name: string; at: string } | null;
  stale: boolean;
  usable: boolean;
}

export interface TranslationList {
  languages: { code: string; name: string }[];
  translations: NoticeTranslation[];
  notes: string[];
}

export interface ConsentInfo {
  email: string;
  status: AccountantContact["status"];
  owner_name: string;
  owner_email: string;
  creditor_name: string;
  can_confirm: boolean;
  expired: boolean;
}
