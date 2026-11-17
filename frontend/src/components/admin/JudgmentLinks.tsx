import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { JudgmentRelation } from "@/components/JudgmentHistory";

type Item = JudgmentRelation & { case_title: string | null; court_name: string | null; decision_date: string | null; judgment_url: string | null };

/** A named reviewer compares each relation (appeal, followed, distinguished, overruled) with the judgment it was read from, then approves or rejects it. Nothing counts as reviewed until they do. */
export default function JudgmentLinks() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("UNVERIFIED");
  const [reviewer, setReviewer] = useState("");
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));
  const list = useQuery({ queryKey: ["judgment-relations", status], queryFn: () => apiGet<{ items: Item[]; total: number }>(`/admin/judgments/relations?status=${status}&limit=25`) });
  const done = (msg: string) => () => {
    toast.success(msg);
    void qc.invalidateQueries({ queryKey: ["judgment-relations"] });
  };
  const approve = useMutation({ mutationFn: (id: string) => apiPost(`/admin/judgments/relations/${id}/approve`, { reviewed_by: reviewer, on }), onSuccess: done("Approved under your name."), onError: (e) => toast.error(describe(e)) });
  const reject = useMutation({ mutationFn: (v: { id: string; reason: string }) => apiPost(`/admin/judgments/relations/${v.id}/reject`, { reviewed_by: reviewer, on, reason: v.reason }), onSuccess: done("Rejected."), onError: (e) => toast.error(describe(e)) });
  const nameOk = reviewer.trim().length >= 5;
  return (
    <div className="space-y-4" data-testid="judgment-links">
      <p className="text-sm text-muted-foreground">
        These links were read by fixed rules from the text of judgments, or entered by a person. Open the judgment, find the quoted sentence, and approve it only if it really says that. A rejected link is hidden and never shown as a fact.
      </p>
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <Label htmlFor="jl-status">Show</Label>
          <select id="jl-status" className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="judgment-links-status">
            <option value="UNVERIFIED">Waiting for review</option>
            <option value="REVIEWED">Reviewed</option>
            <option value="REJECTED">Rejected</option>
          </select>
        </div>
        <div className="md:col-span-2">
          <Label htmlFor="jl-name">Your full name</Label>
          <Input id="jl-name" value={reviewer} maxLength={120} onChange={(e) => setReviewer(e.target.value)} data-testid="judgment-links-name" />
        </div>
        <div>
          <Label htmlFor="jl-date">Date of review</Label>
          <Input id="jl-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </div>
      </div>
      {!nameOk && <p className="text-xs text-muted-foreground">Enter your full name above to approve or reject.</p>}
      <p className="text-xs text-muted-foreground">{list.data ? `${list.data.total} link(s) in this list` : "Loading…"}</p>
      <ul className="space-y-3">
        {(list.data?.items ?? []).map((r) => (
          <Row key={r.id} r={r} nameOk={nameOk} busy={approve.isPending || reject.isPending} onApprove={() => approve.mutate(r.id)} onReject={(reason) => reject.mutate({ id: r.id, reason })} />
        ))}
      </ul>
      {list.data && list.data.items.length === 0 && <p className="text-sm text-muted-foreground">Nothing in this list.</p>}
    </div>
  );
}

function Row({ r, nameOk, busy, onApprove, onReject }: { r: Item; nameOk: boolean; busy: boolean; onApprove: () => void; onReject: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <li className="glass rounded-lg p-4 text-sm" data-testid="judgment-links-item">
      <p className="font-medium">
        {r.case_title ?? r.from_id} <span className="font-normal text-muted-foreground">· {r.court_name}{r.decision_date ? ` · decided ${r.decision_date}` : ""}</span>
      </p>
      <p className="mt-1">
        {r.label}: <strong>{r.target_ref || "(case not named in the sentence)"}</strong>
      </p>
      <p className="mt-1 whitespace-pre-line text-xs italic">“{r.quote}”</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Source: {r.source}. {r.verified ? `Reviewed by ${r.reviewed_by} on ${r.reviewed_on}.` : r.status}
        {r.judgment_url && (
          <>
            {" "}
            <a href={r.judgment_url} target="_blank" rel="noreferrer" className="underline">
              Court PDF
            </a>
          </>
        )}
      </p>
      {r.status.startsWith("UNVERIFIED") && (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button size="xs" disabled={!nameOk || busy} onClick={onApprove} data-testid="judgment-links-approve">
            Approve
          </Button>
          <Input value={reason} maxLength={1000} placeholder="What is wrong with this link?" onChange={(e) => setReason(e.target.value)} aria-label="Reason for rejecting" className="sm:max-w-sm" />
          <Button size="xs" variant="outline" disabled={!nameOk || busy || reason.trim().length < 10} onClick={() => onReject(reason)} data-testid="judgment-links-reject">
            Reject
          </Button>
        </div>
      )}
    </li>
  );
}
