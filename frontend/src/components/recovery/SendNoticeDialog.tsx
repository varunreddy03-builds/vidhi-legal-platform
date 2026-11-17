import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { NoticePreview, TranslationList } from "@/lib/types";

interface SendResult {
  ok: boolean;
  sent_to: string;
  cc_sent: string[];
  cc_failed: string[];
}

/**
 * Two steps, so nothing is emailed by accident:
 *  1. type the recipient and preview exactly what will be sent and to whom (nothing is sent yet)
 *  2. tick the confirmation and send - the server sends only to what was previewed
 */
export default function SendNoticeDialog({
  open,
  onOpenChange,
  caseId,
  defaultEmail,
  confirmedAccountants,
  onSent,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  caseId: string;
  defaultEmail: string;
  confirmedAccountants: string[];
  onSent: () => Promise<void>;
}) {
  const [email, setEmail] = useState(defaultEmail);
  const [cc, setCc] = useState(false);
  const [preview, setPreview] = useState<NoticePreview | null>(null);
  const [ack, setAck] = useState(false);
  const [translationId, setTranslationId] = useState("");
  const [subject, setSubject] = useState("");
  const [cover, setCover] = useState("");
  const translations = useQuery<TranslationList>({
    queryKey: ["notice-translations", caseId],
    queryFn: () => apiGet<TranslationList>(`/recovery/cases/${caseId}/notice/translations`),
    enabled: open,
  });
  const usable = (translations.data?.translations ?? []).filter((t) => t.usable);

  const reset = () => {
    setPreview(null);
    setAck(false);
  };

  const prepare = useMutation({
    mutationFn: () =>
      apiPost<NoticePreview>(`/recovery/cases/${caseId}/email/prepare`, {
        debtor_email: email,
        cc_accountants: cc,
        translation_id: translationId || null,
        subject: subject.trim() || null,
        cover_message: cover.trim() || null,
      }),
    onSuccess: (p) => {
      setPreview(p);
      setAck(false);
    },
    onError: (e) => toast.error(describe(e)),
  });

  const send = useMutation({
    mutationFn: () =>
      apiPost<SendResult>(`/recovery/cases/${caseId}/email`, {
        confirmation_id: preview?.confirmation_id,
        acknowledged: ack,
      }),
    onSuccess: async (r) => {
      await onSent();
      toast.success(`Notice sent to ${r.sent_to}. It is accepted for delivery — we will show if it bounces.`);
      if (r.cc_failed?.length) toast.warning(`Could not copy: ${r.cc_failed.join(", ")}`);
      reset();
      onOpenChange(false);
    },
    onError: (e) => {
      toast.error(describe(e));
      reset(); // a stale/used confirmation must be re-reviewed, never retried silently
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl" data-testid="send-notice-dialog">
        <DialogHeader>
          <DialogTitle>{preview ? "Check before you send" : "Email the notice"}</DialogTitle>
        </DialogHeader>

        {!preview && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              prepare.mutate();
            }}
          >
            <p className="text-xs text-muted-foreground">
              Enter the email address of the person who owes you the money. You will see exactly what is sent before
              anything leaves.
            </p>
            <Input
              type="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Their email address"
              data-testid="recovery-email-input"
            />
            {confirmedAccountants.length > 0 && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="notice-cc-accountants-label">
                <input
                  type="checkbox"
                  checked={cc}
                  onChange={(e) => setCc(e.target.checked)}
                  data-testid="notice-cc-accountants"
                />
                Also copy my confirmed accountant{confirmedAccountants.length === 1 ? "" : "s"} (
                {confirmedAccountants.join(", ")})
              </label>
            )}
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={150} placeholder="Subject (optional: we write a standard one if you leave this empty)" aria-label="Email subject" data-testid="send-subject" />
            <Textarea value={cover} onChange={(e) => setCover(e.target.value)} maxLength={600} rows={2} placeholder="A short note above the notice (optional). Keep to the facts: no threats, no legal sections." aria-label="Short cover message" data-testid="send-cover" />
            {usable.length > 0 && (
              <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                Also include a translation under the English notice:
                <select className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground" value={translationId} onChange={(e) => setTranslationId(e.target.value)} data-testid="send-translation-select">
                  <option value="">English only</option>
                  {usable.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.language_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Button type="submit" disabled={prepare.isPending} data-testid="recovery-email-button">
              {prepare.isPending ? "Preparing…" : "Preview"}
            </Button>
          </form>
        )}

        {preview && (
          <div className="space-y-3" data-testid="send-preview">
            <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">To</dt>
              <dd data-testid="preview-to" className="break-all">
                {preview.to}
              </dd>
              <dt className="text-muted-foreground">Also copied</dt>
              <dd data-testid="preview-cc" className="break-all">
                {preview.cc.length ? preview.cc.join(", ") : "No one else"}
              </dd>
              <dt className="text-muted-foreground">Your copy</dt>
              <dd className="break-all">{preview.sender_copy_to}</dd>
              <dt className="text-muted-foreground">Subject</dt>
              <dd>{preview.subject}</dd>
              {preview.cover_message ? (
                <>
                  <dt className="text-muted-foreground">Your note</dt>
                  <dd data-testid="preview-cover">{preview.cover_message}</dd>
                </>
              ) : null}
              <dt className="text-muted-foreground">Attached</dt>
              <dd>{preview.attachment_name} (the notice as a PDF)</dd>
            </dl>
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/40 p-3 text-xs">
              {preview.notice_text}
            </pre>
            {preview.translation && (
              <div data-testid="preview-translation">
                <p className="text-xs text-muted-foreground">Translation ({preview.translation.language_name}) that will appear under the English notice:</p>
                <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background/40 p-3 text-xs">
                  {preview.translation.text}
                </pre>
              </div>
            )}
            <label className="flex items-start gap-2 text-xs" data-testid="confirm-send-label">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
                data-testid="confirm-send-checkbox"
              />
              <span>
                I have read this notice, and I confirm that <strong>{preview.to}</strong> is the right person to send it
                to.
              </span>
            </label>
            <p className="text-xs text-muted-foreground">
              This is a draft made by software. Have a lawyer review it before you send it. Once sent it cannot be
              recalled. This confirmation expires in {preview.expires_in_minutes} minutes.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => send.mutate()} disabled={!ack || send.isPending} data-testid="confirm-send-button">
                {send.isPending ? "Sending…" : "Send now"}
              </Button>
              <Button variant="outline" onClick={reset} disabled={send.isPending} data-testid="back-to-edit-button">
                Back
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
