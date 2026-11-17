import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiPost } from "@/lib/api";
import { openApiFile } from "@/lib/files";
import { describe } from "@/lib/interaction";

type Version = { version_id: string; act: string; label: string; effective_from: string | null; effective_to: string | null; sections: number; reviewed: number; rejected: number };
type Diff = { loaded: string; second: string; before: string };
type Prov = {
  id: string;
  number: string;
  heading: string;
  text: string;
  status: "DRAFT" | "REVIEWED" | "REJECTED";
  reviewed_by: string | null;
  reviewed_on: string | null;
  rejected_reason: string | null;
  hash: string;
  machine_read: boolean;
  second_source: { status: string; differences: Diff[]; checked_on: string } | null;
  library_entry_id: string | null;
};
type Detail = { document_id: string; act: string; version_label: string; effective: string; source_url: string; retrieved_on: string | null; document: string; document_sha256: string; provisions: Prov[] };

const CHIP: Record<string, string> = { DRAFT: "Draft: not compared yet", REVIEWED: "Reviewed", REJECTED: "Rejected" };

/** The advocate's screen: pick a loaded Act version, read each section next to the link to the official text, then approve or reject it under your name and date.
 * Nothing counts as reviewed until a named person does this. */
export default function LegalReview() {
  const qc = useQueryClient();
  const [versionId, setVersionId] = useState("");
  const [status, setStatus] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));
  const versions = useQuery({ queryKey: ["legal-versions"], queryFn: () => apiGet<Version[]>("/admin/legal/versions") });
  const detail = useQuery({
    queryKey: ["legal-version", versionId, status],
    queryFn: () => apiGet<Detail>(`/admin/legal/versions/${versionId}/provisions${status ? `?status=${status}` : ""}`),
    enabled: !!versionId,
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["legal-version"] });
    void qc.invalidateQueries({ queryKey: ["legal-versions"] });
  };
  const approve = useMutation({
    mutationFn: (v: { id: string; machine: boolean; second: boolean }) =>
      apiPost(`/admin/legal/provisions/${v.id}/approve`, { reviewed_by: reviewer, on, acknowledge_machine_read: v.machine, acknowledge_second_source_difference: v.second }),
    onSuccess: () => {
      toast.success("Approved under your name and added to the verified library.");
      refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const withdraw = useMutation({
    mutationFn: (v: { id: string; reason: string }) => apiPost(`/admin/legal/provisions/${v.id}/withdraw`, { reviewed_by: reviewer, on, reason: v.reason }),
    onSuccess: () => {
      toast.success("Taken out of the verified library.");
      refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const setUrl = useMutation({
    mutationFn: (v: { document: string; url: string }) => apiPost(`/admin/legal/documents/${v.document}/source-url`, { url: v.url }),
    onSuccess: () => {
      toast.success("Source address saved.");
      refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const reject = useMutation({
    mutationFn: (v: { id: string; reason: string }) => apiPost(`/admin/legal/provisions/${v.id}/reject`, { reviewed_by: reviewer, on, reason: v.reason }),
    onSuccess: () => {
      toast.success("Marked rejected.");
      refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const nameOk = reviewer.trim().length >= 5;

  return (
    <div className="space-y-4" data-testid="legal-review">
      <p className="text-sm text-muted-foreground">
        Law loaded here is a <strong>draft</strong> until you compare each section with the official text (open the source link) and approve it under your name and date. A rejected section stays unreviewed and is never
        used as verified law.
      </p>
      <div className="grid gap-3 md:grid-cols-4">
        <div className="md:col-span-2">
          <Label htmlFor="lr-version">Act and version</Label>
          <select id="lr-version" className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm" value={versionId} onChange={(e) => setVersionId(e.target.value)} data-testid="legal-review-version">
            <option value="">Choose…</option>
            {(versions.data ?? []).map((v) => (
              <option key={v.version_id} value={v.version_id}>
                {v.act} · {v.label} · {v.reviewed}/{v.sections} reviewed
              </option>
            ))}
          </select>
          {versions.data && versions.data.length === 0 && <p className="mt-1 text-xs text-muted-foreground">No Act has been loaded yet.</p>}
        </div>
        <div>
          <Label htmlFor="lr-name">Your full name</Label>
          <Input id="lr-name" value={reviewer} maxLength={120} onChange={(e) => setReviewer(e.target.value)} data-testid="legal-review-name" />
        </div>
        <div>
          <Label htmlFor="lr-date">Date of review</Label>
          <Input id="lr-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} data-testid="legal-review-date" />
        </div>
      </div>
      {versionId && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Show" className="rounded-md border border-border bg-background p-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="legal-review-filter">
            <option value="">All sections</option>
            <option value="DRAFT">Draft only</option>
            <option value="REVIEWED">Reviewed only</option>
            <option value="REJECTED">Rejected only</option>
          </select>
          <Button size="sm" variant="outline" onClick={() => openApiFile(`/admin/legal/review-pack/${versionId}?format=docx${status ? `&status=${status}` : ""}`, "review-pack.docx")} data-testid="legal-review-docx">
            Download Word pack
          </Button>
          <Button size="sm" variant="outline" onClick={() => openApiFile(`/admin/legal/review-pack/${versionId}?format=csv${status ? `&status=${status}` : ""}`, "review-pack.csv")} data-testid="legal-review-csv">
            Download CSV
          </Button>
        </div>
      )}
      {!nameOk && versionId && <p className="text-xs text-muted-foreground">Enter your full name above to approve or reject.</p>}
      {detail.data && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {detail.data.act} · {detail.data.version_label} · effective {detail.data.effective} · file {detail.data.document} (SHA-256 {detail.data.document_sha256.slice(0, 12)}) · retrieved {detail.data.retrieved_on ?? "date not recorded"}
          </p>
          {detail.data.provisions.map((p) => (
            <Section key={p.id} p={p} sourceUrl={detail.data.source_url} nameOk={nameOk} busy={approve.isPending || reject.isPending || withdraw.isPending || setUrl.isPending} onWithdraw={(reason) => withdraw.mutate({ id: p.id, reason })} onSetUrl={(url) => setUrl.mutate({ document: detail.data.document_id, url })} onApprove={(machine, second) => approve.mutate({ id: p.id, machine, second })} onReject={(reason) => reject.mutate({ id: p.id, reason })} />
          ))}
          {detail.data.provisions.length === 0 && <p className="text-sm text-muted-foreground">No sections match this filter.</p>}
        </div>
      )}
    </div>
  );
}

function Section({ p, sourceUrl, nameOk, busy, onApprove, onReject, onWithdraw, onSetUrl }: { p: Prov; sourceUrl: string; nameOk: boolean; busy: boolean; onApprove: (machine: boolean, second: boolean) => void; onReject: (reason: string) => void; onWithdraw: (reason: string) => void; onSetUrl: (url: string) => void }) {
  const [reason, setReason] = useState("");
  const [why, setWhy] = useState("");
  const [url, setUrl] = useState("");
  const [ack, setAck] = useState(false);
  const differs = p.second_source?.status === "DIFFERENT";
  const needsAck = p.machine_read || differs;
  return (
    <article className="glass rounded-lg p-4 md:grid md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:gap-4" data-testid="legal-review-section" aria-label={`Section ${p.number}`}>
      <div>
        <h4 className="text-sm font-medium">
          Section {p.number}
          {p.heading ? `: ${p.heading}` : ""}
        </h4>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-border p-2 font-sans text-sm" data-testid="legal-review-text">
          {p.text}
        </pre>
      </div>
      <div className="mt-3 space-y-2 text-sm md:mt-0">
        <p>
          <span className="rounded-full border border-border px-2 py-0.5 text-[11px]" data-testid="legal-review-status">
            {CHIP[p.status]}
          </span>
          {p.reviewed_by && (
            <span className="ml-2 text-xs text-muted-foreground">
              by {p.reviewed_by} on {p.reviewed_on}
            </span>
          )}
        </p>
        {p.rejected_reason && <p className="text-xs">Reason: {p.rejected_reason}</p>}
        {p.library_entry_id && (
          <div className="space-y-2" data-testid="legal-review-inlibrary">
            <p className="text-xs">
              <span className="rounded-full border px-2 py-0.5 text-[11px]" style={{ color: "#4CAF7A", borderColor: "#4CAF7A" }}>
                In the verified library
              </span>{" "}
              Entry <code className="text-[11px]">{p.library_entry_id}</code>
            </p>
            <Button size="xs" variant="outline" onClick={() => openApiFile(`/admin/legal/library-entries/${encodeURIComponent(p.library_entry_id!)}/export`, "library-entry.json")} data-testid="legal-review-export">
              Download as a library file
            </Button>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={why} maxLength={1000} placeholder="Why is it being withdrawn?" onChange={(e) => setWhy(e.target.value)} aria-label="Reason for withdrawing" data-testid="legal-review-why" />
              <Button size="xs" variant="outline" disabled={!nameOk || busy || why.trim().length < 10} onClick={() => onWithdraw(why)} data-testid="legal-review-withdraw">
                Withdraw
              </Button>
            </div>
          </div>
        )}
        <p className="text-xs text-muted-foreground">Hash {p.hash}</p>
        {sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noreferrer" className="underline" data-testid="legal-review-source">
            Open the official source to compare
          </a>
        ) : (
          <div className="space-y-1" data-testid="legal-review-nourl">
            <p className="text-xs">No source address is recorded, so this cannot be approved. Add the web address of the official source:</p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={url} maxLength={500} placeholder="https://" onChange={(e) => setUrl(e.target.value)} aria-label="Official source address" data-testid="legal-review-url" />
              <Button size="xs" variant="outline" disabled={busy || url.trim().length < 10} onClick={() => onSetUrl(url.trim())} data-testid="legal-review-url-save">
                Save address
              </Button>
            </div>
          </div>
        )}
        {p.machine_read && <p className="text-xs">Read from a scan by a machine: compare it word by word.</p>}
        {p.second_source && (
          <p className="text-xs" data-testid="legal-review-second">
            Second official source: {p.second_source.status === "SAME" ? "agrees" : p.second_source.status === "DIFFERENT" ? "words this differently" : p.second_source.status === "ONLY_IN_LOADED" ? "has no such section" : p.second_source.status}
          </p>
        )}
        {differs && (
          <ul className="space-y-1 text-xs">
            {p.second_source!.differences.map((d, i) => (
              <li key={i}>
                …{d.before} <span className="underline">this text: “{d.loaded || "—"}”</span> / <span className="underline">second source: “{d.second || "—"}”</span>
              </li>
            ))}
          </ul>
        )}
        {needsAck && p.status !== "REVIEWED" && (
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" data-testid="legal-review-ack" />
            <span>I have read the points above and compared this section word by word.</span>
          </label>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="xs" disabled={!nameOk || busy || !sourceUrl || !!p.library_entry_id || p.status === "REJECTED" || (needsAck && !ack)} onClick={() => onApprove(p.machine_read && ack, differs && ack)} data-testid="legal-review-approve">
            Approve and add to the verified library
          </Button>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input value={reason} maxLength={1000} placeholder="What does not match the official text?" onChange={(e) => setReason(e.target.value)} aria-label="Reason for rejecting" data-testid="legal-review-reason" />
          <Button size="xs" variant="outline" disabled={!nameOk || busy || reason.trim().length < 10} onClick={() => onReject(reason)} data-testid="legal-review-reject">
            Reject
          </Button>
        </div>
      </div>
    </article>
  );
}
