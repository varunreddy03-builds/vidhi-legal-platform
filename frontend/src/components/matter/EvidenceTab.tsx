import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useEntitlement } from "@/lib/useMe";
import type {
  DocumentOut,
  Entity,
  EvidenceItem,
  EvidenceKind,
  EvidenceStatus,
  Inconsistency,
  SynthesisResult,
} from "@/lib/types";

const KINDS: Record<EvidenceKind, string> = {
  FINGERPRINT: "Fingerprint",
  FOOTPRINT: "Footprint",
  DNA: "DNA",
  CCTV_SIGHTING: "CCTV sighting",
  WITNESS_STATEMENT: "Witness statement",
  DEVICE_RECORD: "Device record",
  DOCUMENT: "Document",
  OTHER: "Other",
};
const STATUS: Record<EvidenceStatus, { label: string; color: string }> = {
  MATCHED: { label: "Matched to a person", color: "#5B8CFF" },
  UNMATCHED: { label: "Compared — no match", color: "#F0A63A" },
  UNIDENTIFIED: { label: "Not yet identified", color: "#F0A63A" },
  UNKNOWN: { label: "Status unknown", color: "#9aa0aa" },
};
const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring dark:bg-input/30";

export default function EvidenceTab({ matterId, docs }: { matterId: string; docs: DocumentOut[] }) {
  const { data: ent } = useEntitlement();
  const isFree = ent?.plan === "FREE";
  const qc = useQueryClient();
  const evidence = useQuery<EvidenceItem[]>({
    queryKey: ["evidence", matterId],
    queryFn: () => apiGet<EvidenceItem[]>(`/matters/${matterId}/evidence`),
  });
  const entities = useQuery<Entity[]>({
    queryKey: ["entities", matterId],
    queryFn: () => apiGet<Entity[]>(`/matters/${matterId}/entities`),
  });
  const diffs = useQuery<Inconsistency[]>({
    queryKey: ["inconsistencies", matterId],
    queryFn: () => apiGet<Inconsistency[]>(`/matters/${matterId}/inconsistencies`),
  });
  const [synth, setSynth] = useState<SynthesisResult | null>(null);
  const refresh = async () => {
    for (const k of ["evidence", "entities", "inconsistencies", "graph"]) {
      await qc.invalidateQueries({ queryKey: [k, matterId] });
    }
  };

  const synthesize = useMutation({
    mutationFn: () => apiPost<SynthesisResult>(`/matters/${matterId}/synthesize`),
    onSuccess: async (r) => {
      setSynth(r);
      await refresh();
      toast.success("All documents read together");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const [kind, setKind] = useState<EvidenceKind>("OTHER");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState<EvidenceStatus>("UNKNOWN");
  const [who, setWho] = useState("");
  const [docId, setDocId] = useState("");
  const [quote, setQuote] = useState("");
  const add = useMutation({
    mutationFn: () =>
      apiPost<EvidenceItem>(`/matters/${matterId}/evidence`, {
        kind,
        label,
        status,
        identified_as: who || null,
        document_id: docId || null,
        quote,
      }),
    onSuccess: async () => {
      setLabel("");
      setWho("");
      setQuote("");
      await refresh();
      toast.success("Evidence item added");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const update = useMutation({
    mutationFn: (v: { id: string; status?: EvidenceStatus; identified_as?: string }) =>
      apiPatch<EvidenceItem>(`/matters/${matterId}/evidence/${v.id}`, { status: v.status, identified_as: v.identified_as }),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/matters/${matterId}/evidence/${id}`),
    onSuccess: async () => {
      await refresh();
      toast.success("Evidence item removed");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const docName = (id: string | null) => docs.find((d) => d.id === id)?.filename;
  const open = (evidence.data ?? []).filter((e) => e.status === "UNMATCHED" || e.status === "UNIDENTIFIED");
  const textDocs = docs.filter((d) => d.text_available).length;

  return (
    <div className="space-y-6" data-testid="evidence-tab">
      <section className="glass rounded-lg p-5" data-testid="people-section">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
              People &amp; differences across all documents
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Reads every document together to work out who is who and where sources differ. Each item is backed by a
              quote that is checked against the document; anything that cannot be found is dropped.
            </p>
          </div>
          <Button size="sm" onClick={() => synthesize.mutate()} disabled={synthesize.isPending || textDocs === 0} data-testid="synthesize-button">
            {synthesize.isPending ? "Reading everything…" : isFree ? "Read all documents together · Pro" : "Read all documents together"}
          </Button>
        </div>
        {textDocs === 0 && <p className="mt-2 text-xs text-muted-foreground">Add a document with readable text first.</p>}
        {synth && (
          <p className="mt-3 text-xs" style={{ color: synth.coverage.complete ? "#5B8CFF" : "#F0A63A" }} data-testid="synthesis-coverage">
            {synth.coverage.summary}
            {synth.dropped_unverified > 0 && ` ${synth.dropped_unverified} item(s) were dropped because their quote could not be found.`}
          </p>
        )}
        {(entities.data ?? []).length > 0 && (
          <div className="mt-4" data-testid="entity-list">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">People</p>
            <ul className="mt-2 space-y-2">
              {(entities.data ?? []).map((p) => (
                <li key={p.id} className="rounded border border-border p-3 text-sm" data-testid="entity-row">
                  <p>
                    {p.name} <span className="text-muted-foreground">— {p.role}</span>
                    {p.aliases.length > 0 && <span className="text-xs text-muted-foreground"> (also: {p.aliases.join(", ")})</span>}
                  </p>
                  {p.appearances.map((a, i) => (
                    <p key={i} className="mt-1 text-xs text-muted-foreground">
                      {a.doc_label}
                      {a.page ? `, page ${a.page}` : ""}: “{a.quote}”
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        )}
        {(diffs.data ?? []).length > 0 && (
          <div className="mt-4" data-testid="inconsistency-list">
            <p className="text-xs uppercase tracking-wider" style={{ color: "#F0A63A" }}>
              Where sources differ (for a lawyer to weigh)
            </p>
            <ul className="mt-2 space-y-2">
              {(diffs.data ?? []).map((i) => (
                <li key={i.id} className="rounded border p-3 text-sm" style={{ borderColor: "#F0A63A44" }}>
                  <p>{i.description}</p>
                  {[i.a, i.b].map((s, n) => (
                    <p key={n} className="mt-1 text-xs text-muted-foreground">
                      {s.doc_label}
                      {s.page ? `, page ${s.page}` : ""}: “{s.quote}”
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section data-testid="evidence-section">
        <h3 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Evidence items</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Prints, sightings, records and statements, each with whether it has been matched to anyone. Research answers
          must account for every item that is unmatched or unidentified.
        </p>
        {open.length > 0 && (
          <p className="mt-2 text-xs" style={{ color: "#F0A63A" }} data-testid="open-evidence-note">
            {open.length} item{open.length === 1 ? " is" : "s are"} not matched to anyone.
          </p>
        )}
        <form
          className="glass mt-3 flex flex-wrap items-end gap-3 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <div className="min-w-[200px] flex-1 space-y-1.5">
            <Label htmlFor="ev-label">What is it?</Label>
            <Input id="ev-label" value={label} onChange={(e) => setLabel(e.target.value)} required minLength={2} data-testid="evidence-label-input" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ev-kind">Kind</Label>
            <select id="ev-kind" className={selectClass} value={kind} onChange={(e) => setKind(e.target.value as EvidenceKind)} data-testid="evidence-kind-select">
              {Object.entries(KINDS).map(([k, v]) => (
                <option key={k} value={k} className="bg-popover">{v}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ev-status">Status</Label>
            <select id="ev-status" className={selectClass} value={status} onChange={(e) => setStatus(e.target.value as EvidenceStatus)} data-testid="evidence-status-select">
              {Object.entries(STATUS).map(([k, v]) => (
                <option key={k} value={k} className="bg-popover">{v.label}</option>
              ))}
            </select>
          </div>
          <div className="w-44 space-y-1.5">
            <Label htmlFor="ev-who">Matched to (if any)</Label>
            <Input id="ev-who" value={who} onChange={(e) => setWho(e.target.value)} data-testid="evidence-who-input" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ev-doc">From document</Label>
            <select id="ev-doc" className={`${selectClass} max-w-[180px]`} value={docId} onChange={(e) => setDocId(e.target.value)} data-testid="evidence-doc-select">
              <option value="" className="bg-popover">— none —</option>
              {docs.map((d) => (
                <option key={d.id} value={d.id} className="bg-popover">{d.filename}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[200px] flex-1 space-y-1.5">
            <Label htmlFor="ev-quote">Exact words from the document (optional)</Label>
            <Input id="ev-quote" value={quote} onChange={(e) => setQuote(e.target.value)} data-testid="evidence-quote-input" />
          </div>
          <Button type="submit" disabled={add.isPending} data-testid="add-evidence-button">
            Add item
          </Button>
        </form>

        <div className="mt-3 space-y-2">
          {(evidence.data ?? []).map((e) => (
            <div key={e.id} className="glass rounded-lg p-4" data-testid="evidence-row">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm">{e.label}</p>
                  <p className="text-xs text-muted-foreground">
                    {KINDS[e.kind]}
                    {e.location ? ` · ${e.location}` : ""}
                    {docName(e.document_id) ? ` · ${docName(e.document_id)}${e.page ? `, page ${e.page}` : ""}` : ""}
                    {" · "}
                    {e.source === "AI_EXTRACTED" ? "read from the document by AI" : "added by you"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    className={selectClass}
                    value={e.status}
                    onChange={(ev) => update.mutate({ id: e.id, status: ev.target.value as EvidenceStatus })}
                    aria-label="Status"
                    style={{ color: STATUS[e.status].color }}
                    data-testid="evidence-row-status"
                  >
                    {Object.entries(STATUS).map(([k, v]) => (
                      <option key={k} value={k} className="bg-popover">{v.label}</option>
                    ))}
                  </select>
                  <Button size="xs" variant="ghost" onClick={() => remove.mutate(e.id)} data-testid="delete-evidence-button">
                    Delete
                  </Button>
                </div>
              </div>
              {e.identified_as && <p className="mt-1 text-xs">Matched to: {e.identified_as}</p>}
              {e.quote && (
                <p className="mt-1 text-xs text-muted-foreground">
                  “{e.quote}”{" "}
                  <Badge variant="outline" style={{ color: e.quote_verified ? "#5B8CFF" : "#F0A63A" }}>
                    {e.quote_verified ? "quote verified" : "quote not checked"}
                  </Badge>
                </p>
              )}
            </div>
          ))}
          {!evidence.isLoading && (evidence.data ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">
              No evidence items yet. Analyse a forensic report, police record or CCTV log to pull them out, or add one above.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
