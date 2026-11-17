import { useState } from "react";
import { openApiFile } from "@/lib/files";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiPatch } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { NoticeCheck, RecoveryCase } from "@/lib/types";
import SendNoticeDialog from "./SendNoticeDialog";

/**
 * The drafted notice. It can be edited, and it cannot be downloaded or emailed while it still has blanks
 * ([ ]) or legal references - the software cannot verify those, so a person must fix or remove them.
 */
export default function NoticeBlock({
  c,
  caseId,
  onChanged,
}: {
  c: RecoveryCase;
  caseId: string;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [sendOpen, setSendOpen] = useState(false);

  const check = (c.notice_check ?? {}) as Partial<NoticeCheck>;
  const blocked = !!check.blocked;
  const placeholders = check.placeholders ?? [];
  const refs = check.legal_references ?? [];
  const risky = check.risky_language ?? [];
  const strayAmounts = check.amount_mismatches ?? [];
  const serviceClaims = check.service_claims ?? [];

  const saveEdit = useMutation({
    mutationFn: () => apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/notice`, { notice_body: draft }),
    onSuccess: async () => {
      await onChanged();
      setEditing(false);
      toast.success("Notice saved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const wfState = c.workflow?.state ?? "DRAFT";
  const canSend =
    wfState === "APPROVED" || (wfState === "SENT" && ["BOUNCED", "FAILED"].includes(c.debtor_email_status ?? ""));
  const status = c.debtor_email_status;
  const statusText: Record<string, string> = {
    ACCEPTED: "Sent — accepted for delivery (not yet confirmed as delivered)",
    DELIVERED: "Delivered",
    BOUNCED: "Bounced — that address could not receive it. Send it another way.",
    COMPLAINED: "The recipient marked it as spam. Do not email them again.",
    FAILED: "Could not be sent",
  };

  return (
    <div className="mt-4" data-testid="recovery-notice">
      {blocked && (
        <div
          className="mb-3 rounded-md border p-3 text-xs"
          style={{ borderColor: "#F0A63A66", background: "#F0A63A14" }}
          role="alert"
          data-testid="notice-blockers"
        >
          <p style={{ color: "#F0A63A" }}>This notice is not ready to send.</p>
          {placeholders.length > 0 && (
            <p className="mt-1">
              Fill in the blanks: <span className="text-muted-foreground">{placeholders.join("  ")}</span>
            </p>
          )}
          {refs.length > 0 && (
            <p className="mt-1">
              Remove these legal references, or have a lawyer check them first (this tool cannot verify law):{" "}
              <span className="text-muted-foreground">{refs.join("  ·  ")}</span>
            </p>
          )}
          {risky.length > 0 && (
            <p className="mt-1">
              Remove words that threaten or accuse the customer (a payment reminder should not):{" "}
              <span className="text-muted-foreground">{risky.join("  ·  ")}</span>
            </p>
          )}
          {strayAmounts.length > 0 && (
            <p className="mt-1">
              These amounts in the wording do not match the statement of account VIDHI calculated. Remove them or correct them:{" "}
              <span className="text-muted-foreground">{strayAmounts.join("  ·  ")}</span>
            </p>
          )}
          {serviceClaims.length > 0 && (
            <p className="mt-1">
              Take out wording that says the notice has been served or received (only a delivery record can show that):{" "}
              <span className="text-muted-foreground">{serviceClaims.join("  ·  ")}</span>
            </p>
          )}
          {check.statement_changed && (
            <p className="mt-1">The statement of account has been changed. It must stay exactly as VIDHI wrote it: draft the notice again to get a fresh one.</p>
          )}
          {check.figures_changed && (
            <p className="mt-1">The figures on this case have changed since the notice was drafted (a payment, credit or charge). Draft it again so it demands the right sum.</p>
          )}
          <Button
            size="xs"
            variant="outline"
            className="mt-2"
            onClick={() => {
              setDraft(c.notice_body);
              setEditing(true);
            }}
            data-testid="fix-notice-button"
          >
            Edit the notice
          </Button>
        </div>
      )}

      {editing ? (
        <div>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={16}
            maxLength={12000}
            className="font-mono text-xs"
            data-testid="notice-editor"
          />
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => saveEdit.mutate()} disabled={saveEdit.isPending || draft.trim().length < 20} data-testid="save-notice-button">
              {saveEdit.isPending ? "Saving…" : "Save notice"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saveEdit.isPending}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/40 p-4 text-xs">
          {c.notice_body}
        </pre>
      )}

      {!editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setDraft(c.notice_body);
              setEditing(true);
            }}
            data-testid="edit-notice-button"
          >
            Edit
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              navigator.clipboard?.writeText(c.notice_body);
              toast.success("Notice copied");
            }}
            data-testid="recovery-copy-notice"
          >
            Copy notice
          </Button>
          <Button
            size="sm"
            onClick={() => openApiFile(`/api/recovery/cases/${caseId}/notice.pdf`)}
            disabled={blocked}
            data-testid="recovery-download-pdf"
          >
            Download PDF
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setSendOpen(true)}
            disabled={blocked || !canSend}
            data-testid="open-send-dialog"
          >
            Email to debtor…
          </Button>
        </div>
      )}

      {status && (
        <p
          className="mt-2 text-xs"
          style={{ color: status === "BOUNCED" || status === "COMPLAINED" || status === "FAILED" ? "#E0604D" : "#5B8CFF" }}
          data-testid="debtor-email-status"
        >
          Email to {c.debtor_email}: {statusText[status] ?? status}
        </p>
      )}
      {!canSend && !blocked && wfState !== "CLOSED" && (
        <p className="mt-2 text-xs text-muted-foreground" data-testid="send-needs-approval">
          {wfState === "SENT"
            ? "This notice was already sent. Edit it to create a new version if you need to send another."
            : "You can email it once the current version is approved (see Approval and review below)."}
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        This is a draft. Have a lawyer review it before you send it.
      </p>

      <SendNoticeDialog
        open={sendOpen}
        onOpenChange={setSendOpen}
        caseId={caseId}
        defaultEmail={c.debtor_email ?? ""}
        confirmedAccountants={c.accountant_emails ?? []}
        onSent={onChanged}
      />
    </div>
  );
}
