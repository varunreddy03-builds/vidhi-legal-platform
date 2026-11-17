import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Review = { requested_by_name?: string; requested_at?: string; decided_by_name?: string; decided_at?: string; decision?: string; reason?: string; reset_from?: string };
type State = { id: string; status: "DRAFT" | "WITH_REVIEWER" | "APPROVED" | "CHANGES_REQUESTED"; review: Review | null; may_review: boolean };
type Comment = { id: string; author_name: string; text: string; created_at: string; resolved_at: string | null; resolved_by_name: string | null };

const LABEL: Record<State["status"], string> = { DRAFT: "Draft", WITH_REVIEWER: "With a reviewer", APPROVED: "Approved", CHANGES_REQUESTED: "Changes requested" };
const day = (iso?: string) => (iso ? iso.slice(0, 10) : "");

/** Send a draft for review, approve it or ask for changes, and write comments on it. The status says who did what and when; it blocks nothing. */
export function DraftReview({ draftId, dirty, refreshKey }: { draftId: string; dirty: boolean; refreshKey?: string }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  const [text, setText] = useState("");
  const review = useQuery({ queryKey: ["draft-review", draftId, refreshKey], queryFn: () => apiGet<State>(`/drafts/${draftId}/review`) });
  const comments = useQuery({ queryKey: ["draft-comments", draftId], queryFn: () => apiGet<Comment[]>(`/drafts/${draftId}/comments`) });
  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["draft-review", draftId] });
    await qc.invalidateQueries({ queryKey: ["draft", draftId] });
  };
  const send = useMutation({ mutationFn: () => apiPost(`/drafts/${draftId}/send-for-review`), onSuccess: refresh, onError: (e) => toast.error(describe(e)) });
  const decide = useMutation({
    mutationFn: (decision: "approve" | "changes") => apiPost(`/drafts/${draftId}/review`, { decision, reason }),
    onSuccess: async () => {
      setReason("");
      setAsking(false);
      await refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const add = useMutation({
    mutationFn: () => apiPost(`/drafts/${draftId}/comments`, { text }),
    onSuccess: async () => {
      setText("");
      await qc.invalidateQueries({ queryKey: ["draft-comments", draftId] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const resolve = useMutation({
    mutationFn: (id: string) => apiPost(`/drafts/${draftId}/comments/${id}/resolve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["draft-comments", draftId] }),
    onError: (e) => toast.error(describe(e)),
  });

  const s = review.data;
  const r = s?.review;
  const line = !s
    ? ""
    : s.status === "APPROVED"
      ? `Approved by ${r?.decided_by_name ?? "a reviewer"} on ${day(r?.decided_at)}.`
      : s.status === "CHANGES_REQUESTED"
        ? `${r?.decided_by_name ?? "A reviewer"} asked for changes on ${day(r?.decided_at)}: ${r?.reason ?? ""}`
        : s.status === "WITH_REVIEWER"
          ? `Sent for review by ${r?.requested_by_name ?? "the author"} on ${day(r?.requested_at)}.`
          : r?.reset_from
            ? `Changed after it was ${r.reset_from === "APPROVED" ? "approved" : "sent for review"}, so it needs to be sent again.`
            : "Not yet sent for review.";

  return (
    <section className="mt-6 rounded-lg border border-border p-3" aria-label="Review and comments" data-testid="draft-review">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full border border-border px-2 py-0.5 text-xs font-medium" data-testid="review-status">
          {s ? LABEL[s.status] : "…"}
        </span>
        <span className="text-sm text-muted-foreground" data-testid="review-line">
          {line}
        </span>
      </div>
      {s && (s.status === "DRAFT" || s.status === "CHANGES_REQUESTED") && (
        <div className="mt-3">
          <Button size="sm" variant="outline" onClick={() => send.mutate()} disabled={send.isPending || dirty} data-testid="review-send">
            Send for review
          </Button>
          {dirty && <span className="ml-2 text-xs text-muted-foreground">Save your changes first.</span>}
        </div>
      )}
      {s?.may_review && (
        <div className="mt-3 space-y-2" data-testid="review-decide">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => decide.mutate("approve")} disabled={decide.isPending} data-testid="review-approve">
              Approve
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAsking(true)} disabled={decide.isPending} data-testid="review-ask-changes">
              Ask for changes
            </Button>
          </div>
          {asking && (
            <div className="space-y-2">
              <label htmlFor="review-reason" className="text-sm">
                What needs to change? (one line)
              </label>
              <input
                id="review-reason"
                value={reason}
                maxLength={300}
                onChange={(e) => setReason(e.target.value)}
                className="h-10 w-full rounded-md border border-border bg-background px-2 text-base md:text-sm"
                data-testid="review-reason"
              />
              <Button size="sm" onClick={() => decide.mutate("changes")} disabled={decide.isPending || !reason.trim()} data-testid="review-send-changes">
                Send to the author
              </Button>
            </div>
          )}
        </div>
      )}

      <h3 className="mt-5 text-sm font-medium">Comments</h3>
      <ul className="mt-2 space-y-2" data-testid="comment-list">
        {(comments.data ?? []).map((c) => (
          <li key={c.id} className={`rounded-md border border-border p-2 text-sm ${c.resolved_at ? "opacity-60" : ""}`} data-testid="comment">
            <p className="text-xs text-muted-foreground">
              {c.author_name} · {day(c.created_at)}
              {c.resolved_at ? ` · resolved by ${c.resolved_by_name ?? "someone"}` : ""}
            </p>
            <p className="mt-1 whitespace-pre-wrap">{c.text}</p>
            {!c.resolved_at && (
              <Button size="sm" variant="ghost" className="mt-1" onClick={() => resolve.mutate(c.id)} disabled={resolve.isPending} data-testid="comment-resolve">
                Mark resolved
              </Button>
            )}
          </li>
        ))}
        {comments.data?.length === 0 && <li className="text-sm text-muted-foreground">No comments yet.</li>}
      </ul>
      <form
        className="mt-3 space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) add.mutate();
        }}
      >
        <label htmlFor="comment-text" className="text-sm">
          Write a comment
        </label>
        <textarea
          id="comment-text"
          value={text}
          rows={2}
          maxLength={1000}
          onChange={(e) => setText(e.target.value)}
          className="w-full rounded-md border border-border bg-background p-2 text-base md:text-sm"
          data-testid="comment-input"
        />
        <p className="text-xs text-muted-foreground">Comments are kept with the draft and cannot be edited or deleted. They are never sent to the AI.</p>
        <Button type="submit" size="sm" disabled={add.isPending || !text.trim()} data-testid="comment-add">
          Add comment
        </Button>
      </form>
    </section>
  );
}
