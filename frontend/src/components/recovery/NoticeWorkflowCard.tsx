import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { NoticeVersion, NoticeWorkflow } from "@/lib/types";

const STATE_COLOR: Record<string, string> = {
  DRAFT: "#C8A96B",
  ADVOCATE_REVIEW_REQUESTED: "#5B8CFF",
  CHANGES_REQUESTED: "#F0A63A",
  APPROVED: "#5B8CFF",
  SENT: "#5B8CFF",
  RESPONSE_RECEIVED: "#5B8CFF",
  CLOSED: "#8A8F98",
  ESCALATED: "#F0A63A",
};

const ORIGIN: Record<string, string> = { AI_DRAFT: "AI draft", TEMPLATE: "From the template", EDIT: "Edited", LEGACY: "Earlier draft" };

/** Where the notice stands: versions, who approved which version, advocate review, and what happened after sending. */
export default function NoticeWorkflowCard({ caseId, onChanged }: { caseId: string; onChanged: () => Promise<void> }) {
  const wf = useQuery<NoticeWorkflow>({
    queryKey: ["notice-workflow", caseId],
    queryFn: () => apiGet<NoticeWorkflow>(`/recovery/cases/${caseId}/notice/workflow`),
  });
  const [showVersions, setShowVersions] = useState(false);
  const versions = useQuery<NoticeVersion[]>({
    queryKey: ["notice-versions", caseId],
    queryFn: () => apiGet<NoticeVersion[]>(`/recovery/cases/${caseId}/notice/versions`),
    enabled: showVersions,
  });
  const [openVersion, setOpenVersion] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const [note, setNote] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [decision, setDecision] = useState<"APPROVE" | "REQUEST_CHANGES">("APPROVE");
  const [comments, setComments] = useState("");
  const [enrol, setEnrol] = useState("");
  const [decl, setDecl] = useState(false);
  const [markNote, setMarkNote] = useState("");

  const refresh = async () => {
    await onChanged();
    await wf.refetch();
    if (showVersions) await versions.refetch();
  };
  const done = (msg: string) => async () => {
    setAck(false);
    setNote("");
    setComments("");
    setDecl(false);
    setReviewOpen(false);
    setMarkNote("");
    await refresh();
    toast.success(msg);
  };
  const post = (path: string, body: unknown, msg: string) => ({
    mutationFn: () => apiPost(`/recovery/cases/${caseId}/notice/${path}`, body),
    onSuccess: done(msg),
    onError: (e: unknown) => toast.error(describe(e)),
  });

  const w = wf.data;
  const approve = useMutation(post("approve", { acknowledged: ack, version_id: w?.current_version?.id }, "Approved. You can now email it."));
  const request = useMutation(post("request-review", { note }, "Review requested"));
  const review = useMutation(
    post("review", { decision, comments, declaration: decl, enrolment_no: enrol, version_id: w?.current_version?.id }, "Your review was recorded"),
  );
  const mark = (state: string, msg: string) =>
    useMutation(post("mark", { state, note: markNote }, msg)); // eslint-disable-line react-hooks/rules-of-hooks
  const markResponse = mark("RESPONSE_RECEIVED", "Recorded");
  const markClosed = mark("CLOSED", "Closed");
  const markEscalated = mark("ESCALATED", "Marked as escalated");

  if (!w) return null;
  const can = (a: string) => w.allowed.includes(a);

  return (
    <div className="mt-4 rounded-md border border-border p-4" data-testid="notice-workflow">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm">Approval and review</p>
        <Badge variant="outline" style={{ color: STATE_COLOR[w.state] }} data-testid="notice-state">
          {w.label}
        </Badge>
        {w.current_version && <span className="text-xs text-muted-foreground">Version {w.current_version.number}</span>}
      </div>

      {w.approved && (
        <p className="mt-2 text-xs" data-testid="notice-approval-record">
          {w.approved.kind === "ADVOCATE" ? (
            <>
              Approved after review by {w.approved.name || w.approved.email} on {formatDateTime(w.approved.at)}. This is the
              reviewer&apos;s own declaration that they are an advocate and read the notice
              {w.approved.enrolment_no_stated_by_reviewer
                ? `; enrolment number stated by the reviewer (not verified by VIDHI): ${w.approved.enrolment_no_stated_by_reviewer}`
                : ""}
              .{w.approved.comments ? ` Comment: “${w.approved.comments}”` : ""}
            </>
          ) : (
            <>
              Approved by {w.approved.name || w.approved.email} (the owner, not an advocate) on {formatDateTime(w.approved.at)}.
            </>
          )}
        </p>
      )}
      {w.last_review && w.state === "CHANGES_REQUESTED" && (
        <p className="mt-2 text-xs" style={{ color: "#F0A63A" }}>
          {w.last_review.name || w.last_review.email} asked for changes: “{w.last_review.comments}”. Edit the notice, then approve or request review
          again.
        </p>
      )}
      {w.review_request && w.state === "ADVOCATE_REVIEW_REQUESTED" && (
        <p className="mt-2 text-xs text-muted-foreground">
          Review requested by {w.review_request.name || w.review_request.email}
          {w.review_request.note ? `: “${w.review_request.note}”` : ""}. Nobody has been notified automatically; invite your advocate
          under Settings &gt; Team and tell them.
        </p>
      )}
      {w.needs_advocate_reason && (
        <p className="mt-2 text-xs" style={{ color: "#E5646E" }} data-testid="needs-advocate">
          {w.needs_advocate_reason}
        </p>
      )}
      {w.sent && (
        <p className="mt-2 text-xs text-muted-foreground">
          Emailed to {w.sent.to} on {formatDateTime(w.sent.at)} (version {w.sent.version}). “Sent” means the email provider accepted it.
          It does not prove the customer received it or that the notice was legally served.
        </p>
      )}

      <div className="mt-3 space-y-3">
        {can("approve") && (
          <div>
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className="mt-0.5" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="approve-ack" />
              <span>I have read this exact version. Its facts are correct and I want it to be sent.</span>
            </label>
            <Button size="sm" className="mt-2" disabled={!ack || approve.isPending} onClick={() => approve.mutate()} data-testid="approve-notice">
              {approve.isPending ? "Approving…" : `Approve version ${w.current_version?.number ?? ""}`}
            </Button>
          </div>
        )}
        {can("request_review") && (
          <div>
            <Input placeholder="Anything the advocate should know? (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
            <Button size="sm" variant="outline" className="mt-2" disabled={request.isPending} onClick={() => request.mutate()} data-testid="request-review">
              Ask an advocate to review
            </Button>
          </div>
        )}
        {can("review") && (
          <div>
            <Button size="xs" variant="ghost" onClick={() => setReviewOpen(!reviewOpen)} data-testid="open-review">
              {reviewOpen ? "Hide" : "I am reviewing this as an advocate…"}
            </Button>
            {reviewOpen && (
              <div className="mt-2 space-y-2 rounded-md border border-border p-3">
                <div className="flex gap-4 text-sm">
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={decision === "APPROVE"} onChange={() => setDecision("APPROVE")} /> Approve
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={decision === "REQUEST_CHANGES"} onChange={() => setDecision("REQUEST_CHANGES")} /> Ask for changes
                  </label>
                </div>
                <Textarea rows={3} placeholder={decision === "REQUEST_CHANGES" ? "What should change? (required)" : "Comments (optional)"} value={comments} onChange={(e) => setComments(e.target.value)} maxLength={2000} />
                <Input placeholder="Your enrolment number (optional; shown as stated by you, not verified)" value={enrol} onChange={(e) => setEnrol(e.target.value)} maxLength={60} />
                <label className="flex items-start gap-2 text-xs">
                  <input type="checkbox" className="mt-0.5" checked={decl} onChange={(e) => setDecl(e.target.checked)} data-testid="review-declaration" />
                  <span>{w.advocate_declaration}</span>
                </label>
                <Button size="sm" disabled={!decl || review.isPending || (decision === "REQUEST_CHANGES" && !comments.trim())} onClick={() => review.mutate()} data-testid="submit-review">
                  Record my review
                </Button>
              </div>
            )}
          </div>
        )}
        {(can("mark_response") || can("mark_closed") || can("escalate")) && (
          <div>
            <Input placeholder="A short note for the record (optional)" value={markNote} onChange={(e) => setMarkNote(e.target.value)} maxLength={1000} />
            <div className="mt-2 flex flex-wrap gap-2">
              {can("mark_response") && (
                <Button size="xs" variant="outline" onClick={() => markResponse.mutate()} data-testid="mark-response">
                  The customer replied
                </Button>
              )}
              {can("mark_closed") && (
                <Button size="xs" variant="outline" onClick={() => markClosed.mutate()} data-testid="mark-closed">
                  Close this notice
                </Button>
              )}
              {can("escalate") && (
                <Button size="xs" variant="outline" onClick={() => markEscalated.mutate()} data-testid="mark-escalated">
                  Escalate (taking further advice or action)
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="mt-3">
        <Button size="xs" variant="ghost" onClick={() => setShowVersions(!showVersions)} data-testid="toggle-versions">
          {showVersions ? "Hide versions" : "Show every version and the history"}
        </Button>
        {showVersions && (
          <div className="mt-2 space-y-2" data-testid="notice-versions">
            {(versions.data ?? []).map((v) => (
              <div key={v.id} className="rounded-md border border-border p-2 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    Version {v.number} · {ORIGIN[v.origin] ?? v.origin} · {formatDateTime(v.created_at)}
                    {v.created_by?.name ? ` · ${v.created_by.name}` : ""}
                    {v.is_current ? " · current" : ""}
                  </span>
                  <Button size="xs" variant="ghost" onClick={() => setOpenVersion(openVersion === v.id ? null : v.id)}>
                    {openVersion === v.id ? "Hide text" : "View text"}
                  </Button>
                </div>
                {v.approvals.map((a, i) => (
                  <p key={i} className="mt-1 text-muted-foreground">
                    {a.kind === "OWNER" ? "Approved by owner" : a.kind === "ADVOCATE" ? "Approved after advocate review (declared by reviewer)" : "Advocate asked for changes (declared by reviewer)"}:{" "}
                    {a.name || a.email}, {formatDateTime(a.at)}
                  </p>
                ))}
                {openVersion === v.id && <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded border border-border bg-background/40 p-2">{v.body}</pre>}
              </div>
            ))}
            <ul className="space-y-1 border-l-2 pl-3 text-xs" style={{ borderColor: "#C8A96B" }}>
              {w.history.map((h, i) => (
                <li key={i}>
                  <span className="text-muted-foreground">{formatDateTime(h.at)}</span> · {h.event}
                  {h.by?.name ? ` · ${h.by.name}` : ""}
                  {h.note ? ` — “${h.note}”` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
        {w.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
