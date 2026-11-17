import { useEffect, useRef, useState } from "react";
import { fileLinkProps, openApiFile } from "@/lib/files";
import { formatDate, formatDateText, toDate } from "@/lib/format";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiGet, apiPost, apiPatch, apiDelete, apiUpload } from "@/lib/api";
import type { ProofKind, RecoveryCase, RecoveryProof } from "@/lib/types";
import { describe } from "@/lib/interaction";
import { useMe, useCan } from "@/lib/useMe";
import ConfirmDeleteDialog from "@/components/ConfirmDeleteDialog";
import AccountantsCard from "@/components/recovery/AccountantsCard";
import CaseDetailsCard from "@/components/recovery/CaseDetailsCard";
import IntakeCard from "@/components/recovery/IntakeCard";
import ReadinessPanel, { useReadiness } from "@/components/recovery/ReadinessPanel";
import InterestLimitationCard from "@/components/recovery/InterestLimitationCard";
import NoticeBlock from "@/components/recovery/NoticeBlock";
import NextStepCard from "@/components/recovery/NextStepCard";
import NoticeWorkflowCard from "@/components/recovery/NoticeWorkflowCard";
import DeliveryCard from "@/components/recovery/DeliveryCard";
import TranslationCard from "@/components/recovery/TranslationCard";
import VerifyEmailBanner from "@/components/VerifyEmailBanner";

const STEP_INDEX: Record<string, number> = {
  DRAFT: 0,
  PROOF_ADDED: 1,
  TIMELINE_READY: 2,
  NOTICE_READY: 3,
  SENT_FOR_REVIEW: 4,
  RESOLVED: 5,
};


const KIND_OPTIONS: { value: ProofKind; label: string }[] = [
  { value: "INVOICE", label: "Invoice or bill" },
  { value: "PURCHASE_ORDER", label: "Purchase order" },
  { value: "AGREEMENT", label: "Agreement or quotation" },
  { value: "DELIVERY_PROOF", label: "Delivery or completion proof" },
  { value: "PAYMENT_RECORD", label: "Payment record" },
  { value: "COMMUNICATION", label: "Messages or emails" },
  { value: "OTHER", label: "Other" },
];

function money(n: number, currency: string) {
  return currency === "INR" ? `₹${n.toLocaleString("en-IN")}` : `${n.toLocaleString()} ${currency}`;
}

function nextNudge(c: RecoveryCase): string {
  if (c.status === "RESOLVED") return "";
  if (!c.reminders_enabled) return "Reminders off";
  const now = Date.now();
  const base = (toDate(c.last_reminded_at ?? c.updated_at) ?? new Date()).getTime();
  let next = base + c.reminder_cadence_days * 86400000;
  if (c.snooze_until) next = Math.max(next, (toDate(c.snooze_until) ?? new Date()).getTime());
  if (next <= now) return "Next nudge: due now";
  const days = Math.round((next - now) / 86400000);
  const whenTxt = days <= 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
  return `Next nudge: ${whenTxt} (${formatDate(next)})`;
}

function StepCard({
  n,
  title,
  done,
  active,
  children,
}: {
  n: number;
  title: string;
  done: boolean;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`glass rounded-xl p-5 transition-opacity duration-300 ${active || done ? "opacity-100" : "opacity-60"}`}
      id={`step-${n}`}
      data-testid={`recovery-step-${n}`}
    >
      <div className="flex items-center gap-3">
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-full text-xs"
          style={{
            background: done ? "#5B8CFF" : active ? "#C8A96B" : "transparent",
            border: done || active ? "none" : "1px solid var(--border)",
            color: done || active ? "#08090A" : "inherit",
          }}
        >
          {done ? "✓" : n}
        </span>
        <h3 className="font-heading text-sm">{title}</h3>
      </div>
      <div className="mt-4 pl-10">{children}</div>
    </div>
  );
}

export default function RecoveryCasePage() {
  const { caseId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: me } = useMe();
  const canDelete = useCan("delete");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [proofKind, setProofKind] = useState<ProofKind>("INVOICE");
  const [routeAck, setRouteAck] = useState(false);
  const [statementEmail, setStatementEmail] = useState("");
  const [pauseDate, setPauseDate] = useState("");

  const kase = useQuery<RecoveryCase>({
    queryKey: ["recovery-case", caseId],
    queryFn: () => apiGet<RecoveryCase>(`/recovery/cases/${caseId}`),
  });
  const proofs = useQuery<RecoveryProof[]>({
    queryKey: ["recovery-proofs", caseId],
    queryFn: () => apiGet<RecoveryProof[]>(`/recovery/cases/${caseId}/proofs`),
  });
  const statementPreview = useQuery<{ summary: string; next_date: string | null }>({
    queryKey: ["statement-preview", caseId],
    queryFn: () =>
      apiGet<{ summary: string; next_date: string | null }>(
        `/recovery/cases/${caseId}/statement-preview`,
      ),
  });

  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: ["recovery-case", caseId] });
    await qc.invalidateQueries({ queryKey: ["recovery-proofs", caseId] });
    await qc.invalidateQueries({ queryKey: ["recovery-readiness", caseId] });
    await qc.invalidateQueries({ queryKey: ["notice-workflow", caseId] });
    await qc.invalidateQueries({ queryKey: ["notice-versions", caseId] });
    await qc.invalidateQueries({ queryKey: ["notice-delivery", caseId] });
    await qc.invalidateQueries({ queryKey: ["notice-translations", caseId] });
    await qc.invalidateQueries({ queryKey: ["statement-preview", caseId] });
    await qc.invalidateQueries({ queryKey: ["recovery-cases"] });
  };

  const upload = useMutation({
    mutationFn: (file: File) =>
      apiUpload<RecoveryProof>(`/recovery/cases/${caseId}/proofs`, file, { kind: proofKind }),
    onSuccess: async (p) => {
      await invalidate();
      if (p.processing_status === "READY") toast.success("Proof added");
      else toast.warning(p.failure_reason ?? "We could not read that file");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const extract = useMutation({
    mutationFn: () => apiPost<RecoveryCase>(`/recovery/cases/${caseId}/extract`),
    onSuccess: async () => {
      await invalidate();
      toast.success("We read your case");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const notice = useMutation({
    mutationFn: () => apiPost<RecoveryCase>(`/recovery/cases/${caseId}/notice`, { acknowledge_route: routeAck }),
    onSuccess: async () => {
      await invalidate();
      toast.success("Your demand notice is ready");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const handoff = useMutation({
    mutationFn: () => apiPost<{ id: string }>(`/recovery/cases/${caseId}/handoff`),
    onSuccess: async (m) => {
      await invalidate();
      toast.success("Sent to Matters for a lawyer to review");
      navigate(`/matters/${m.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  const retryCc = useMutation({
    mutationFn: (logId: string) =>
      apiPost<{ ok: boolean; cc_sent: string[]; cc_failed: string[] }>(
        `/recovery/cases/${caseId}/statement-retry-cc`,
        { log_id: logId },
      ),
    onSuccess: async (r) => {
      await invalidate();
      if (r.cc_sent?.length) toast.success(`Resent to ${r.cc_sent.join(", ")}`);
      if (r.cc_failed?.length) toast.warning(`Still could not reach ${r.cc_failed.join(", ")}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  useEffect(() => {
    if (me?.email && !statementEmail) setStatementEmail(me.email);
  }, [me?.email, statementEmail]);

  const emailStatement = useMutation({
    mutationFn: () =>
      apiPost<{ ok: boolean; sent_to: string; cc_sent: string[]; cc_failed: string[] }>(
        `/recovery/cases/${caseId}/statement-email`,
        { email: statementEmail },
      ),
    onSuccess: async (r) => {
      await invalidate();
      toast.success(`Statement emailed to ${r.sent_to}`);
      if (r.cc_failed?.length)
        toast.warning(`Could not reach: ${r.cc_failed.join(", ")} — check those addresses`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  const scheduleMut = useMutation({
    mutationFn: (payload: {
      schedule?: string;
      day?: number;
      pause_until?: string;
      resume?: boolean;
    }) => apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/statement-schedule`, payload),
    onSuccess: async () => {
      await invalidate();
      toast.success("Statement settings updated");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const reminders = useMutation({
    mutationFn: (payload: { enabled?: boolean; snooze_days?: number; cadence_days?: number }) =>
      apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/reminders`, payload),
    onSuccess: async () => {
      await invalidate();
      toast.success("Reminder settings updated");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const resolve = useMutation({
    mutationFn: () => apiPost<RecoveryCase>(`/recovery/cases/${caseId}/resolve`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Marked as paid / resolved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const deleteCase = useMutation({
    mutationFn: () => apiDelete(`/recovery/cases/${caseId}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["recovery-cases"] });
      toast.success("Recovery deleted");
      navigate("/recovery", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const reopen = useMutation({
    mutationFn: () => apiPost<RecoveryCase>(`/recovery/cases/${caseId}/reopen`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Recovery reopened");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const [payAmount, setPayAmount] = useState("");
  const recordPayment = useMutation({
    mutationFn: () =>
      apiPost<RecoveryCase>(`/recovery/cases/${caseId}/payment`, { amount: Number(payAmount) || 0 }),
    onSuccess: async () => {
      await invalidate();
      setPayAmount("");
      toast.success("Payment recorded");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const deletePayment = useMutation({
    mutationFn: (pid: string) => apiDelete<RecoveryCase>(`/recovery/cases/${caseId}/payment/${pid}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Payment removed");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const preview = useMutation({
    mutationFn: () =>
      apiGet<{ subject: string; body: string }>(`/recovery/cases/${caseId}/nudge-preview`),
    onError: (e) => toast.error(describe(e)),
  });

  const nudgeSend = useMutation({
    mutationFn: () =>
      apiPost<{ ok: boolean; sent_to: string }>(`/recovery/cases/${caseId}/nudge-send`),
    onSuccess: (r) => toast.success(`Reminder sent to ${r.sent_to}`),
    onError: (e) => toast.error(describe(e)),
  });

  const [editId, setEditId] = useState<string | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");
  const editPayment = useMutation({
    mutationFn: (pid: string) =>
      apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/payment/${pid}`, {
        amount: Number(editAmount) || 0,
        date: editDate || undefined,
      }),
    onSuccess: async () => {
      await invalidate();
      setEditId(null);
      setEditAmount("");
      setEditDate("");
      toast.success("Payment updated");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const c = kase.data;
  const step = c ? STEP_INDEX[c.status] : 0;
  const busy = extract.isPending || notice.isPending || handoff.isPending || upload.isPending;
  const readyProofs = proofs.data ?? [];
  const readiness = useReadiness(caseId, !!c);
  const relabel = useMutation({
    mutationFn: (v: { id: string; kind: ProofKind }) =>
      apiPatch<RecoveryProof>(`/recovery/cases/${caseId}/proofs/${v.id}`, { kind: v.kind }),
    onSuccess: invalidate,
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AppShell
      title={c ? `${c.creditor_name} → ${c.debtor_name}` : "Recovery"}
      back="/recovery"
      intensity={busy ? "active" : "ambient"}
    >
      <div className="mx-auto max-w-2xl">
        <VerifyEmailBanner />
        <h2 className="text-2xl" data-testid="recovery-case-title">
          {c ? `${c.creditor_name} → ${c.debtor_name}` : "Loading…"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {c ? money(c.amount || c.detected_amount || 0, c.currency) : ""} · step {Math.min(step + 1, 5)} of 5
        </p>
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-border" data-testid="recovery-progress">
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${(step / 5) * 100}%`, background: "#C8A96B" }}
          />
        </div>
        {c && (
          <NextStepCard
            c={c}
            readiness={readiness.data}
            proofCount={readyProofs.length}
            workflowState={c.workflow?.state ?? "DRAFT"}
            reading={extract.isPending}
            writing={notice.isPending}
            onAddPaper={() => fileRef.current?.click()}
            onRead={() => extract.mutate()}
            onWrite={() => notice.mutate()}
            goTo={(id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
          />
        )}
        {c && (
          <details className="mt-4 rounded-2xl border border-border p-4">
            <summary className="cursor-pointer text-sm text-muted-foreground">More options: reminders, mark as paid, delete</summary>
          <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="recovery-controls">
            <Button
              size="xs"
              variant="outline"
              onClick={() => reminders.mutate({ enabled: !c.reminders_enabled })}
              disabled={reminders.isPending}
              data-testid="toggle-reminders"
            >
              {c.reminders_enabled ? "Reminders: on" : "Reminders: off"}
            </Button>
            <div className="flex overflow-hidden rounded-md border border-border" data-testid="cadence-group">
              {[
                { d: 1, label: "Daily" },
                { d: 3, label: "Every 3d" },
                { d: 7, label: "Weekly" },
              ].map((o) => (
                <button
                  key={o.d}
                  onClick={() => reminders.mutate({ cadence_days: o.d })}
                  disabled={reminders.isPending}
                  data-testid={`cadence-${o.d}`}
                  className={`px-2 py-1 text-xs transition-colors duration-200 ${
                    c.reminder_cadence_days === o.d
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <Button
              size="xs"
              variant="outline"
              onClick={() => reminders.mutate({ snooze_days: 7 })}
              disabled={reminders.isPending}
              data-testid="snooze-reminders"
            >
              Snooze 7 days
            </Button>
            <Button
              size="xs"
              variant="outline"
              onClick={() => preview.mutate()}
              disabled={preview.isPending}
              data-testid="preview-nudge"
            >
              Preview reminder
            </Button>
            {c.status === "RESOLVED" ? (
              <Button
                size="xs"
                variant="outline"
                onClick={() => reopen.mutate()}
                disabled={reopen.isPending}
                data-testid="reopen-case"
              >
                Reopen
              </Button>
            ) : (
              <Button
                size="xs"
                variant="outline"
                onClick={() => resolve.mutate()}
                disabled={resolve.isPending}
                data-testid="resolve-case"
              >
                Mark paid / resolved
              </Button>
            )}
            {c.status === "RESOLVED" && (
              <Badge variant="outline" style={{ color: "#5B8CFF" }} data-testid="resolved-badge">
                Paid / Resolved
              </Badge>
            )}
            {canDelete && (
              <Button size="xs" variant="ghost" onClick={() => setDeleteOpen(true)} data-testid="delete-case">
                Delete…
              </Button>
            )}
            <ConfirmDeleteDialog
              open={deleteOpen}
              onOpenChange={setDeleteOpen}
              title="Delete this recovery?"
              description={
                "The proof you uploaded, the notice, payments and the record of emails sent are deleted for good." +
                (c?.linked_matter_id ? " The matter opened for a lawyer in Matters is a separate copy and is NOT deleted: delete it there if you want it gone." : "")
              }
              confirmWord="DELETE"
              pending={deleteCase.isPending}
              onConfirm={() => deleteCase.mutate()}
            />
          </div>
          </details>
        )}
        {c && nextNudge(c) && (
          <p className="mt-2 text-xs text-muted-foreground" data-testid="next-nudge-hint">
            {nextNudge(c)}
          </p>
        )}
        {preview.data && (
          <div data-testid="nudge-preview-block">
            <pre
              className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/40 p-3 text-xs"
              data-testid="nudge-preview"
            >
              {`Subject: ${preview.data.subject}\n\n${preview.data.body}`}
            </pre>
            <Button
              size="xs"
              variant="outline"
              className="mt-2"
              onClick={() => nudgeSend.mutate()}
              disabled={nudgeSend.isPending}
              data-testid="nudge-send-now"
            >
              {nudgeSend.isPending ? "Sending…" : "Send this reminder to me now"}
            </Button>
          </div>
        )}

        <div className="mt-6 space-y-4">
          <StepCard n={1} title="Your case" done={step >= 1} active={step === 0}>
            <p className="text-sm text-muted-foreground">
              {c?.description || "No description yet."}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              You said {c ? money(c.amount ?? 0, c.currency) : "—"} is owed. Add your proof below and
              we&apos;ll check the details for you.
            </p>
            {c && (
              <details className="mt-3 rounded-md border border-border p-3" open={!c.intake?.invoice_number}>
                <summary className="cursor-pointer text-sm">Invoice and customer details</summary>
                <div className="mt-3">
                  <IntakeCard c={c} caseId={caseId} onChanged={invalidate} />
                </div>
              </details>
            )}
          </StepCard>

          <StepCard n={2} title="Add your proof" done={step >= 2} active={step <= 1}>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
              className="hidden"
              data-testid="recovery-proof-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <label htmlFor="proof-kind">This file is a</label>
              <select
                id="proof-kind"
                className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground"
                value={proofKind}
                onChange={(e) => setProofKind(e.target.value as ProofKind)}
                data-testid="proof-kind-select"
              >
                {KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <Button
              variant="outline"
              onClick={() => fileRef.current?.click()}
              disabled={upload.isPending}
              data-testid="recovery-upload-button"
            >
              {upload.isPending ? "Reading…" : "Upload proof — invoice, agreement, or a chat screenshot"}
            </Button>
            <div className="mt-3 space-y-1.5">
              {readyProofs.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-xs"
                  data-testid="recovery-proof-row"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {p.has_file ? (
                      <a className="underline" {...fileLinkProps(`/api/recovery/cases/${caseId}/proofs/${p.id}/file`)}>
                        {p.filename}
                      </a>
                    ) : (
                      p.filename
                    )}
                    {p.processing_status !== "READY" && (
                      <span className="block text-xs" style={{ color: "#F0A63A" }}>
                        Kept, but we could not read its text. {p.failure_reason ?? ""}
                      </span>
                    )}
                  </span>
                  <select
                    className="mx-2 h-7 rounded-md border border-border bg-background px-1 text-xs"
                    value={p.kind}
                    onChange={(e) => relabel.mutate({ id: p.id, kind: e.target.value as ProofKind })}
                    aria-label={`What ${p.filename} is`}
                  >
                    {KIND_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <Badge variant="secondary">{p.page_count} pages</Badge>
                </div>
              ))}
              {readyProofs.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No proof yet. Even one invoice or chat export helps a lot.
                </p>
              )}
            </div>
          </StepCard>

          <StepCard n={3} title="What we found" done={step >= 2} active={step === 1 || step === 2}>
            <Button
              onClick={() => extract.mutate()}
              disabled={extract.isPending}
              data-testid="recovery-extract-button"
            >
              {extract.isPending ? "Reading your case…" : "Understand my case"}
            </Button>
            {c?.summary && (
              <div className="mt-4" data-testid="recovery-summary">
                <p className="text-sm">{c.summary}</p>
                {c.detected_amount != null && (
                  <p className="mt-2 text-sm" style={{ color: "#5B8CFF" }}>
                    Amount we found in your proof: {money(c.detected_amount, c.currency)}
                  </p>
                )}
                {c.timeline.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {c.timeline.map((t, i) => (
                      <li key={i} className="border-l-2 pl-3 text-sm" style={{ borderColor: "#C8A96B" }}>
                        <span className="text-xs" style={{ color: "#C8A96B" }}>
                          {formatDateText(t.date) || "date unknown"}
                        </span>
                        <p>
                          {t.description}
                          {t.amount != null ? ` — ${money(t.amount, c.currency)}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </StepCard>

          <StepCard n={4} title="Your demand notice" done={step >= 3} active={step === 2 || step === 3}>
            {c && <CaseDetailsCard c={c} caseId={caseId} onChanged={invalidate} />}
            {readiness.data && (
              <div className="mt-4">
                <ReadinessPanel r={readiness.data} ack={routeAck} onAck={setRouteAck} />
              </div>
            )}
            {readiness.data && readiness.data.draft_blockers.length > 0 && (
              <p className="mt-3 text-xs" style={{ color: "#F0A63A" }} data-testid="draft-blockers">
                Before you can draft: {readiness.data.draft_blockers.join(" ")}
              </p>
            )}
            <Button
              className="mt-4"
              onClick={() => notice.mutate()}
              disabled={
                notice.isPending ||
                !(c?.creditor_address ?? "").trim() ||
                !(c?.debtor_address ?? "").trim() ||
                (readiness.data ? !readiness.data.can_draft : false) ||
                (readiness.data?.route_acknowledgement_needed === true && !routeAck)
              }
              data-testid="recovery-notice-button"
            >
              {notice.isPending ? "Drafting…" : c?.notice_body ? "Re-draft notice" : "Create demand notice"}
            </Button>
            {c?.notice_body && <NoticeBlock c={c} caseId={caseId} onChanged={invalidate} />}
            {c?.notice_body && <NoticeWorkflowCard caseId={caseId} onChanged={invalidate} />}
            {c?.notice_body && <TranslationCard caseId={caseId} />}
            {c?.notice_body && <DeliveryCard caseId={caseId} workflowState={c.workflow?.state ?? "DRAFT"} onChanged={invalidate} />}
          </StepCard>

          <StepCard n={5} title="Get a lawyer to review" done={step >= 4} active={step >= 3}>
            <p className="text-sm text-muted-foreground">
              Want a professional to take it further? We&apos;ll open this as a matter in VIDHI Legal
              Intelligence, carrying your notice and timeline across.
            </p>
            <Button
              className="mt-3"
              onClick={() => handoff.mutate()}
              disabled={handoff.isPending}
              data-testid="recovery-handoff-button"
            >
              {handoff.isPending
                ? "Handing over…"
                : c?.linked_matter_id
                  ? "Open the lawyer's matter"
                  : "Send for lawyer review"}
            </Button>
          </StepCard>

          {c && (
            <div className="glass rounded-xl p-5" data-testid="recovery-interest-card">
              <h3 className="font-heading text-sm">Interest and time limits</h3>
              <div className="mt-3">
                <InterestLimitationCard c={c} caseId={caseId} />
              </div>
            </div>
          )}

          {c && (
            <div className="glass rounded-xl p-5" data-testid="recovery-payments">
              <h3 className="font-heading text-sm">Payments received</h3>
              {(() => {
                const rb = readiness.data?.balance;
                const total = rb ? rb.invoice_amount + rb.charges_total - rb.credits_total : c.amount || c.detected_amount || 0;
                const received = c.paid_amount ?? 0;
                const remaining = Math.max(0, total - received);
                const pct = total > 0 ? Math.min(100, (received / total) * 100) : 0;
                return (
                  <div className="mt-3">
                    <div className="flex flex-wrap gap-4 text-sm">
                      <span>Owed: {money(total, c.currency)}</span>
                      <span style={{ color: "#5B8CFF" }}>Received: {money(received, c.currency)}</span>
                      <span
                        style={{ color: remaining === 0 && received > 0 ? "#5B8CFF" : "#C8A96B" }}
                        data-testid="recovery-remaining"
                      >
                        Remaining: {money(remaining, c.currency)}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full rounded-full transition-[width] duration-500"
                        style={{ width: `${pct}%`, background: "#5B8CFF" }}
                      />
                    </div>
                    {received > total && total > 0 && (
                      <p className="mt-2 text-xs" style={{ color: "#F0A63A" }} data-testid="overpayment-note">
                        Recorded payments exceed the amount owed by{" "}
                        {money(received - total, c.currency)} — check your entries.
                      </p>
                    )}
                    <form
                      className="mt-3 flex flex-wrap items-center gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        recordPayment.mutate();
                      }}
                    >
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={payAmount}
                        onChange={(e) => setPayAmount(e.target.value)}
                        placeholder="Amount received"
                        className="w-40"
                        data-testid="recovery-payment-input"
                      />
                      <Button
                        type="submit"
                        size="sm"
                        variant="outline"
                        disabled={recordPayment.isPending}
                        data-testid="recovery-payment-button"
                      >
                        {recordPayment.isPending ? "Saving…" : "Record payment"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          openApiFile(`/api/recovery/cases/${caseId}/statement.pdf`)
                        }
                        data-testid="recovery-statement-button"
                      >
                        Download statement (PDF)
                      </Button>
                    </form>
                    <form
                      className="mt-2 flex flex-wrap items-center gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        emailStatement.mutate();
                      }}
                    >
                      <select
                        value={statementEmail}
                        onChange={(e) => setStatementEmail(e.target.value)}
                        aria-label="Send the statement to"
                        className="h-8 w-64 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                        data-testid="statement-email-input"
                      >
                        {[me?.email, ...(c.accountant_emails ?? [])]
                          .filter((e): e is string => !!e)
                          .map((e) => (
                            <option key={e} value={e} className="bg-popover">
                              {e === me?.email ? `${e} (you)` : e}
                            </option>
                          ))}
                      </select>
                      <Button
                        type="submit"
                        size="sm"
                        variant="outline"
                        disabled={emailStatement.isPending}
                        data-testid="statement-email-button"
                      >
                        {emailStatement.isPending ? "Sending…" : "Email statement"}
                      </Button>
                    </form>
                    <div
                      className="mt-3 border-t border-border/50 pt-3"
                      data-testid="statement-schedule"
                    >
                      <p className="text-xs text-muted-foreground">Automatic statements</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <div
                          className="flex overflow-hidden rounded-md border border-border"
                          data-testid="statement-schedule-group"
                        >
                          {[
                            { v: "OFF", label: "Off" },
                            { v: "MONTHLY", label: "Monthly" },
                            { v: "FORTNIGHTLY", label: "Fortnightly" },
                          ].map((o) => (
                            <button
                              key={o.v}
                              onClick={() => scheduleMut.mutate({ schedule: o.v })}
                              disabled={scheduleMut.isPending}
                              data-testid={`statement-schedule-${o.v.toLowerCase()}`}
                              className={`px-2 py-1 text-xs transition-colors duration-200 ${
                                c.statement_schedule === o.v
                                  ? "bg-accent text-foreground"
                                  : "text-muted-foreground hover:text-foreground"
                              }`}
                            >
                              {o.label}
                            </button>
                          ))}
                        </div>
                        {c.statement_schedule === "MONTHLY" && (
                          <label className="flex items-center gap-1 text-xs text-muted-foreground">
                            on day
                            <Input
                              key={c.statement_day}
                              type="number"
                              min="1"
                              max="28"
                              defaultValue={c.statement_day}
                              className="h-7 w-16"
                              data-testid="statement-day-input"
                              onBlur={(e) => {
                                const d = Number(e.target.value);
                                if (d >= 1 && d <= 28 && d !== c.statement_day)
                                  scheduleMut.mutate({ day: d });
                              }}
                            />
                          </label>
                        )}
                      </div>
                      <p
                        className="mt-1 text-xs text-muted-foreground"
                        data-testid="statement-schedule-hint"
                      >
                        {c.statement_schedule === "OFF"
                          ? "No automatic statements will be sent."
                          : c.statement_schedule === "MONTHLY"
                            ? `A statement is emailed to you on day ${c.statement_day} of each month while a balance remains.`
                            : "A statement is emailed to you every 14 days while a balance remains."}
                      </p>
                      {statementPreview.data?.summary && (
                        <p
                          className="mt-1 text-xs"
                          style={{ color: "#5B8CFF" }}
                          data-testid="statement-next-preview"
                        >
                          {statementPreview.data.summary}
                        </p>
                      )}
                      {(() => {
                        const paused =
                          c.statement_paused_until &&
                          (toDate(c.statement_paused_until) ?? new Date(0)) > new Date();
                        return (
                          <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="statement-pause">
                            {paused ? (
                              <>
                                <span className="text-xs" style={{ color: "#F0A63A" }} data-testid="statement-paused-label">
                                  Paused until {formatDate(c.statement_paused_until)}
                                </span>
                                <Button
                                  size="xs"
                                  variant="outline"
                                  onClick={() => scheduleMut.mutate({ resume: true })}
                                  disabled={scheduleMut.isPending}
                                  data-testid="statement-resume"
                                >
                                  Resume now
                                </Button>
                              </>
                            ) : (
                              <>
                                <span className="text-xs text-muted-foreground">Pause until</span>
                                <Input
                                  type="date"
                                  value={pauseDate}
                                  onChange={(e) => setPauseDate(e.target.value)}
                                  className="h-7 w-36"
                                  data-testid="statement-pause-input"
                                />
                                <Button
                                  size="xs"
                                  variant="outline"
                                  onClick={() => pauseDate && scheduleMut.mutate({ pause_until: pauseDate })}
                                  disabled={scheduleMut.isPending || !pauseDate}
                                  data-testid="statement-pause-button"
                                >
                                  Pause
                                </Button>
                              </>
                            )}
                          </div>
                        );
                      })()}
                      <AccountantsCard
                        c={c}
                        caseId={caseId}
                        onChanged={invalidate}
                        verified={!!me?.email_verified}
                      />
                    </div>
                    {(c.statement_log?.length ?? 0) > 0 && (
                      <div className="mt-3" data-testid="statement-log">
                        <p className="text-xs text-muted-foreground">Statements sent</p>
                        <ul className="mt-1 space-y-1">
                          {c.statement_log
                            .slice()
                            .reverse()
                            .map((s) => (
                              <li
                                key={s.id}
                                className="flex items-center justify-between border-b border-border/50 py-1 text-xs text-muted-foreground"
                                data-testid="statement-log-row"
                                title={`Balance stated in this email: ${money(s.balance, c.currency)} (owed ${money(s.owed, c.currency)}, received ${money(s.received, c.currency)})${(s.cc?.length ?? 0) > 0 ? ` · CC: ${s.cc.join(", ")}` : ""}${(s.cc_failed?.length ?? 0) > 0 ? ` · Bounced: ${s.cc_failed.join(", ")}` : ""}`}
                              >
                                <span className="truncate">
                                  {formatDate(s.date)} · {s.email}
                                </span>
                                <span className="flex items-center gap-2">
                                  {(s.cc_failed?.length ?? 0) > 0 && (
                                    <button
                                      onClick={() => retryCc.mutate(s.id)}
                                      disabled={retryCc.isPending}
                                      data-testid="retry-cc"
                                      className="rounded border px-1.5 py-0.5 transition-colors duration-200 hover:text-foreground"
                                      style={{ color: "#F0A63A", borderColor: "#F0A63A55" }}
                                    >
                                      Retry CC
                                    </button>
                                  )}
                                  <span style={{ color: "#C8A96B" }}>
                                    {money(s.balance, c.currency)}
                                  </span>
                                  <Badge variant="secondary">
                                    {s.via === "scheduled" ? "Auto" : "Manual"}
                                  </Badge>
                                </span>
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}
                    {(c.payments?.length ?? 0) > 0 && (
                      <ul className="mt-3 space-y-1" data-testid="payment-log">
                        {c.payments.map((p, i) => (
                          <li
                            key={p.id ?? i}
                            className="flex items-center justify-between border-b border-border/50 py-1 text-xs text-muted-foreground"
                            data-testid="payment-log-row"
                          >
                            {editId === p.id ? (
                              <form
                                className="flex w-full flex-wrap items-center gap-2"
                                onSubmit={(e) => {
                                  e.preventDefault();
                                  editPayment.mutate(p.id);
                                }}
                              >
                                <Input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={editAmount}
                                  onChange={(e) => setEditAmount(e.target.value)}
                                  className="h-7 w-28"
                                  data-testid="edit-payment-input"
                                />
                                <Input
                                  type="date"
                                  value={editDate}
                                  onChange={(e) => setEditDate(e.target.value)}
                                  className="h-7 w-36"
                                  data-testid="edit-payment-date"
                                />
                                <Button type="submit" size="xs" data-testid="edit-payment-save">
                                  Save
                                </Button>
                                <button
                                  type="button"
                                  onClick={() => setEditId(null)}
                                  className="text-muted-foreground"
                                >
                                  cancel
                                </button>
                              </form>
                            ) : (
                              <>
                                <span>{formatDate(p.date)}</span>
                                <span className="flex items-center gap-2">
                                  <span style={{ color: "#5B8CFF" }}>+{money(p.amount, c.currency)}</span>
                                  {p.id && (
                                    <button
                                      onClick={() => {
                                        setEditId(p.id);
                                        setEditAmount(String(p.amount));
                                        setEditDate(
                                          toDate(p.date)?.toISOString().slice(0, 10) ?? "",
                                        );
                                      }}
                                      aria-label="Edit payment"
                                      data-testid="edit-payment"
                                      className="text-muted-foreground transition-colors duration-200 hover:text-foreground"
                                    >
                                      ✎
                                    </button>
                                  )}
                                  {p.id && (
                                    <button
                                      onClick={() => deletePayment.mutate(p.id)}
                                      disabled={deletePayment.isPending}
                                      aria-label="Remove payment"
                                      data-testid="delete-payment"
                                      className="text-muted-foreground transition-colors duration-200 hover:text-[#F0A63A]"
                                    >
                                      ✕
                                    </button>
                                  )}
                                </span>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {remaining === 0 && received > 0 && c.status !== "RESOLVED" && (
                      <div
                        className="mt-3 rounded-md border p-3"
                        style={{ borderColor: "#5B8CFF55", background: "rgba(91,140,255,0.06)" }}
                        data-testid="auto-resolve-prompt"
                      >
                        <p className="text-sm">Fully paid — nice work. Close this recovery?</p>
                        <Button
                          size="sm"
                          className="mt-2"
                          onClick={() => resolve.mutate()}
                          disabled={resolve.isPending}
                          data-testid="auto-resolve-button"
                        >
                          Mark as resolved
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
