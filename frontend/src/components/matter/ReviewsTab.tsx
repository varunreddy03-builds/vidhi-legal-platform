import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useMe } from "@/lib/useMe";

type Review = { id: string; kind: string; ref_id: string; reviewer_id: string; reviewer_name: string; requested_by_name: string; note: string; status: "REQUESTED" | "APPROVED" | "CHANGES_REQUESTED"; decision_comment: string; created_at: string; decided_at: string | null };
type Choice = { id: string; name: string; role: string };
type Item = { id: string; label: string };

const KIND_LABEL: Record<string, string> = { research: "Research answer", draft: "Draft", document: "Document", analysis: "Document analysis" };
const STATUS_TEXT: Record<Review["status"], string> = { REQUESTED: "Waiting", APPROVED: "Approved", CHANGES_REQUESTED: "Changes requested" };

// Ask a colleague to look at a piece of work in this matter, and see their answer. It is a hand-off between people: the program decides nothing about the item.
export default function ReviewsTab({ matterId }: { matterId: string }) {
  const qc = useQueryClient();
  const me = useMe();
  const [kind, setKind] = useState("document");
  const [ref, setRef] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [comment, setComment] = useState<Record<string, string>>({});

  const reviews = useQuery<{ reviews: Review[] }>({ queryKey: ["reviews", matterId], queryFn: () => apiGet(`/matters/${matterId}/reviews`) });
  const choices = useQuery<{ reviewers: Choice[] }>({ queryKey: ["reviewers", matterId], queryFn: () => apiGet(`/matters/${matterId}/reviews/reviewers`) });
  const items = useQuery<Item[]>({
    queryKey: ["review-items", matterId, kind],
    queryFn: async () => {
      if (kind === "research") return (await apiGet<{ id: string; question: string }[]>(`/research?matter_id=${matterId}`)).map((r) => ({ id: r.id, label: r.question.slice(0, 90) }));
      if (kind === "draft") return (await apiGet<{ id: string; title: string }[]>(`/drafts?matter_id=${matterId}`)).map((d) => ({ id: d.id, label: d.title }));
      return (await apiGet<{ id: string; filename: string }[]>(`/matters/${matterId}/documents`)).map((d) => ({ id: d.id, label: d.filename }));
    },
  });
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["reviews", matterId] }), qc.invalidateQueries({ queryKey: ["my-reviews"] })]);

  const send = useMutation({
    mutationFn: () => apiPost(`/matters/${matterId}/reviews`, { kind, ref_id: ref, reviewer_id: reviewer, note }),
    onSuccess: async () => {
      toast.success("Review requested");
      setRef("");
      setNote("");
      await refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; decision: "APPROVED" | "CHANGES_REQUESTED" }) => apiPost(`/reviews/${v.id}/decision`, { decision: v.decision, comment: comment[v.id] ?? "" }),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });

  const select = "h-9 w-full rounded-lg border border-input bg-background px-2 text-sm";
  const label = (r: Review) => items.data?.find((i) => i.id === r.ref_id)?.label;
  const canAsk = (choices.data?.reviewers.length ?? 0) > 0;

  return (
    <div className="space-y-6" data-testid="reviews-tab">
      <section className="glass rounded-xl p-4">
        <h3 className="text-lg font-medium">Ask for a review</h3>
        {!canAsk && <p className="mt-1 text-sm text-muted-foreground">No colleague who can review is in your firm yet. Add a lawyer under Settings, then ask here.</p>}
        {canAsk && (
          <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (ref && reviewer) send.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="rv-kind">What</Label>
              <select id="rv-kind" className={select} value={kind} onChange={(e) => { setKind(e.target.value); setRef(""); }} data-testid="review-kind">
                {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rv-item">Which one</Label>
              <select id="rv-item" className={select} value={ref} onChange={(e) => setRef(e.target.value)} data-testid="review-item">
                <option value="">Choose…</option>
                {(items.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rv-who">Reviewer</Label>
              <select id="rv-who" className={select} value={reviewer} onChange={(e) => setReviewer(e.target.value)} data-testid="review-reviewer">
                <option value="">Choose…</option>
                {(choices.data?.reviewers ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.role.toLowerCase()})</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rv-note">What to look at (optional)</Label>
              <Input id="rv-note" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} data-testid="review-note" />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={!ref || !reviewer || send.isPending} data-testid="review-send">{send.isPending ? "Sending…" : "Request review"}</Button>
            </div>
          </form>
        )}
      </section>

      <section aria-labelledby="rv-list-h">
        <h3 id="rv-list-h" className="text-lg font-medium">Reviews in this matter</h3>
        {reviews.data && reviews.data.reviews.length === 0 && <p className="mt-1 text-sm text-muted-foreground" data-testid="review-empty">None yet.</p>}
        <ul className="mt-2 space-y-2">
          {(reviews.data?.reviews ?? []).map((r) => {
            const mine = r.status === "REQUESTED" && r.reviewer_id === me.data?.id;
            return (
              <li key={r.id} className="glass rounded-xl p-4 text-sm" data-testid="review-item-row">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{KIND_LABEL[r.kind] ?? r.kind}{label(r) ? `: ${label(r)}` : ""}</span>
                  <Badge variant={r.status === "APPROVED" ? "default" : r.status === "REQUESTED" ? "outline" : "secondary"}>{STATUS_TEXT[r.status]}</Badge>
                </div>
                <p className="mt-1 text-muted-foreground">Asked by {r.requested_by_name || "a colleague"}, for {r.reviewer_name || "a colleague"} to review{r.note ? `: ${r.note}` : ""}</p>
                {r.decision_comment && <p className="mt-1">“{r.decision_comment}”</p>}
                {mine && (
                  <div className="mt-3 space-y-2">
                    <Label htmlFor={`rv-c-${r.id}`}>Your comment</Label>
                    <Input id={`rv-c-${r.id}`} value={comment[r.id] ?? ""} maxLength={2000} onChange={(e) => setComment((c) => ({ ...c, [r.id]: e.target.value }))} data-testid="review-comment" />
                    <div className="flex gap-2">
                      <Button type="button" onClick={() => decide.mutate({ id: r.id, decision: "APPROVED" })} disabled={decide.isPending} data-testid="review-approve">Approve</Button>
                      <Button type="button" variant="outline" onClick={() => decide.mutate({ id: r.id, decision: "CHANGES_REQUESTED" })} disabled={decide.isPending} data-testid="review-changes">Ask for changes</Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
