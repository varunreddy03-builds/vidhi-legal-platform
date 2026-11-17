import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiGet, apiPost, apiUpload } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Cal = { id: string; year: number | null; review_status: string; reviewed_by: string | null; verified_on: string | null; enabled: boolean; holidays: number; source_url: string | null; source_checked_on: string | null; batch_id: string | null };
type Court = { court: string; calendars: Cal[]; live: boolean };
type Coverage = { courts_total: number; courts_live: number; summary: string; courts: Court[]; unmatched_calendars: { id: string; court: string; year: number }[] };
type Loaded = { ok: boolean; dry_run?: boolean; batch_id: string | null; kind: string; created: { id?: string; title: string }[]; warnings: string[]; note: string };

/** Court holiday calendars and deadline rules from files: check a file, load it (unreviewed), have a named reviewer mark it reviewed, switch the court's calendar on, or roll a load back.
 *  Nothing here writes a rule or a date; the files come from the owner and cite their official source. */
export default function DeadlineData() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Loaded | null>(null);
  const [problem, setProblem] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));
  const cov = useQuery({ queryKey: ["deadline-coverage"], queryFn: () => apiGet<Coverage>("/admin/legal/deadline-data/coverage") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["deadline-coverage"] });
  const send = useMutation({
    mutationFn: (mode: "preview" | "load") => apiUpload<Loaded>(`/admin/legal/deadline-data/${mode}`, file as File),
    onSuccess: async (r) => {
      setResult(r);
      setProblem("");
      await refresh();
    },
    onError: (e) => {
      setResult(null);
      setProblem(e instanceof ApiError ? describe(e) : "The file could not be sent.");
    },
  });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: Record<string, string> }) => apiPost(`/admin/legal/${path}`, body),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <div className="space-y-4" data-testid="admin-deadlines">
      <section className="glass rounded-lg p-4">
        <h2 className="font-heading text-xs uppercase tracking-wider text-muted-foreground">Load a file</h2>
        <p className="mt-1 text-xs text-muted-foreground">A court holiday calendar or a deadline-rules file (JSON, up to 1 MB) that names its official source and the day it was checked. A file with any problem is refused as a whole. Loaded records are UNREVIEWED and unusable until reviewed.</p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="min-w-0 max-w-full space-y-1">
            <Label htmlFor="dd-file">File</Label>
            <input id="dd-file" type="file" className="block w-full max-w-[16rem] text-sm" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="deadline-file" />
          </div>
          <Button size="sm" variant="outline" disabled={!file || send.isPending} onClick={() => send.mutate("preview")} data-testid="deadline-preview">Check the file</Button>
          <Button size="sm" disabled={!file || send.isPending} onClick={() => send.mutate("load")} data-testid="deadline-load">Load it</Button>
        </div>
        {problem && <p role="alert" className="mt-2 text-sm" style={{ color: "#F0A63A" }} data-testid="deadline-problem">{problem}</p>}
        {result && (
          <div role="status" className="mt-2 text-sm" data-testid="deadline-result">
            <p>{result.dry_run ? "Checked, nothing stored: " : "Loaded: "}{result.created.length} {result.kind === "court_calendar" ? "calendar" : "rule(s)"}. {result.note}</p>
            {result.warnings.map((w) => <p key={w} style={{ color: "#F0A63A" }}>{w}</p>)}
            {result.batch_id && <p className="text-xs text-muted-foreground">Batch {result.batch_id}</p>}
          </div>
        )}
      </section>

      <section className="glass rounded-lg p-4" aria-labelledby="dd-cov">
        <h2 id="dd-cov" className="font-heading text-xs uppercase tracking-wider text-muted-foreground">Courts</h2>
        <p className="mt-1 text-sm font-medium" data-testid="deadline-summary">{cov.data?.summary ?? "…"}</p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="min-w-0 max-w-full space-y-1">
            <Label htmlFor="dd-reviewer">Reviewing advocate (full name)</Label>
            <Input id="dd-reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} className="max-w-full" data-testid="deadline-reviewer" />
          </div>
          <div className="min-w-0 max-w-full space-y-1">
            <Label htmlFor="dd-on">Date compared with the source</Label>
            <Input id="dd-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} className="w-44 max-w-full" data-testid="deadline-on" />
          </div>
        </div>
        <ul className="mt-3 space-y-3">
          {(cov.data?.courts ?? []).map((c) => (
            <li key={c.court} className="rounded-md border border-border p-3" data-testid="deadline-court">
              <p className="text-sm font-medium">{c.court} <span className="text-xs text-muted-foreground">{c.live ? "· on" : "· not on"}</span></p>
              {c.calendars.length === 0 && <p className="text-xs text-muted-foreground">No calendar loaded.</p>}
              {c.calendars.map((k) => (
                <div key={k.id} className="mt-2 text-sm" data-testid="deadline-calendar">
                  <p>
                    {k.year} · {k.holidays} holidays · {k.review_status === "reviewed" ? `reviewed by ${k.reviewed_by} on ${k.verified_on}` : "not reviewed"} · {k.enabled ? "switched on" : "switched off"}
                  </p>
                  <p className="text-xs text-muted-foreground">Source: {k.source_url} (checked {k.source_checked_on})</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {k.review_status !== "reviewed" && (
                      <Button size="sm" variant="outline" disabled={act.isPending || reviewer.trim().length < 5} onClick={() => act.mutate({ path: `deadline-calendars/${k.id}/review`, body: { reviewed_by: reviewer, on } })} data-testid="deadline-review">
                        Mark reviewed
                      </Button>
                    )}
                    {k.review_status === "reviewed" && !k.enabled && (
                      <Button size="sm" onClick={() => act.mutate({ path: `deadline-calendars/${k.id}/enable` })} disabled={act.isPending} data-testid="deadline-enable">Switch on</Button>
                    )}
                    {k.enabled && (
                      <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `deadline-calendars/${k.id}/disable` })} disabled={act.isPending} data-testid="deadline-disable">Switch off</Button>
                    )}
                    {k.batch_id && (
                      <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => act.mutate({ path: `deadline-data/batches/${k.batch_id}/rollback`, body: { reason: "Rolled back from the operator console." } })} data-testid="deadline-rollback">
                        Roll back this load
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </li>
          ))}
          {cov.data && cov.data.courts.length === 0 && <li className="text-sm text-muted-foreground">VIDHI lists no courts yet (no judgment list is loaded), so no calendar can be matched to a court.</li>}
        </ul>
        {(cov.data?.unmatched_calendars.length ?? 0) > 0 && (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="deadline-unmatched">
            {cov.data?.unmatched_calendars.length} loaded calendar(s) name a court VIDHI does not list: {cov.data?.unmatched_calendars.map((u) => `${u.court} ${u.year}`).join("; ")}. They do not count.
          </p>
        )}
      </section>
    </div>
  );
}
