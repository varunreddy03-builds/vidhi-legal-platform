import DocCompare from "@/components/matter/DocCompare";
import { useState } from "react";
import { formatDateText, formatDateTime } from "@/lib/format";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import FileDrop from "@/components/FileDrop";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import type {
  AuditEvent,
  DocumentAnalysis,
  DocumentOut,
  Fact,
  GraphOut,
  Matter,
  TimelineEvent,
  EvidenceItem,
  Inconsistency,
} from "@/lib/types";
import { describe } from "@/lib/interaction";
import DocumentCard from "@/components/matter/DocumentCard";
import EvidenceTab from "@/components/matter/EvidenceTab";
import MatterLifecycle from "@/components/matter/MatterLifecycle";
import MatterDetailsEditor from "@/components/matter/MatterDetailsEditor";
import ClientPortalPanel from "@/components/matter/ClientPortalPanel";
import { useCan } from "@/lib/useMe";

const FACT_STATUSES = [
  "LAWYER_PROVIDED",
  "DOCUMENT_SUPPORTED",
  "DIRECT",
  "INFERRED",
  "CONTESTED",
  "CONTRADICTED",
  "MISSING",
];

export default function MatterDetail() {
  const { matterId = "" } = useParams();
  const canShare = useCan("send_mail"); // sharing with a client is sharing outside the firm: the same people who may email third parties
  const qc = useQueryClient();
    const [analyses, setAnalyses] = useState<Record<string, DocumentAnalysis>>({});
  const [factDoc, setFactDoc] = useState("");
  const [graphView, setGraphView] = useState<"structured" | "visual">("structured");
  const [factValue, setFactValue] = useState("");
  const [factStatus, setFactStatus] = useState("LAWYER_PROVIDED");
  const [evDate, setEvDate] = useState("");
  const [evDesc, setEvDesc] = useState("");

  const matter = useQuery<Matter>({
    queryKey: ["matter", matterId],
    queryFn: () => apiGet<Matter>(`/matters/${matterId}`),
  });
  const docs = useQuery<DocumentOut[]>({
    queryKey: ["documents", matterId],
    queryFn: () => apiGet<DocumentOut[]>(`/matters/${matterId}/documents`),
  });
  const facts = useQuery<Fact[]>({
    queryKey: ["facts", matterId],
    queryFn: () => apiGet<Fact[]>(`/matters/${matterId}/facts`),
  });
  const timeline = useQuery<TimelineEvent[]>({
    queryKey: ["timeline", matterId],
    queryFn: () => apiGet<TimelineEvent[]>(`/matters/${matterId}/timeline`),
  });
  const evidence = useQuery<EvidenceItem[]>({
    queryKey: ["evidence", matterId],
    queryFn: () => apiGet<EvidenceItem[]>(`/matters/${matterId}/evidence`),
  });
  const differences = useQuery<Inconsistency[]>({
    queryKey: ["inconsistencies", matterId],
    queryFn: () => apiGet<Inconsistency[]>(`/matters/${matterId}/inconsistencies`),
  });
  const graph = useQuery<GraphOut>({
    queryKey: ["graph", matterId],
    queryFn: () => apiGet<GraphOut>(`/matters/${matterId}/graph`),
  });
  const audit = useQuery<AuditEvent[]>({
    queryKey: ["audit", matterId],
    queryFn: () => apiGet<AuditEvent[]>(`/audit?matter_id=${matterId}`),
  });

  const analyze = useMutation({
    mutationFn: (id: string) => apiPost<DocumentAnalysis>(`/documents/${id}/analyze`),
    onSuccess: async (a) => {
      setAnalyses((prev) => ({ ...prev, [a.document_id]: a }));
      for (const k of ["evidence", "inconsistencies", "entities", "graph"]) await qc.invalidateQueries({ queryKey: [k, matterId] });
      toast.success("Analysis ready");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const addFact = useMutation({
    mutationFn: () =>
      apiPost<Fact>(`/matters/${matterId}/facts`, {
        value: factValue,
        status: factStatus,
        document_id: factDoc || null,
      }),
    onSuccess: async () => {
      setFactValue("");
      await qc.invalidateQueries({ queryKey: ["facts", matterId] });
      await qc.invalidateQueries({ queryKey: ["graph", matterId] });
      toast.success("Fact recorded");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const addEvent = useMutation({
    mutationFn: () =>
      apiPost<TimelineEvent>(`/matters/${matterId}/timeline`, {
        event_date: evDate,
        description: evDesc,
      }),
    onSuccess: async () => {
      setEvDate("");
      setEvDesc("");
      await qc.invalidateQueries({ queryKey: ["timeline", matterId] });
      await qc.invalidateQueries({ queryKey: ["graph", matterId] });
      toast.success("Timeline event added");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const removeFact = useMutation({
    mutationFn: (id: string) => apiDelete(`/matters/${matterId}/facts/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["facts", matterId] });
      toast.success("Fact deleted");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const busy = analyze.isPending;
  // "Disputed" and "missing" count everything the matter holds: facts marked that way, differences found between documents, and evidence nobody has been matched to.
  const disputedFacts = (facts.data ?? []).filter((f) => f.status === "CONTESTED" || f.status === "CONTRADICTED").length;
  const missingFacts = (facts.data ?? []).filter((f) => f.status === "MISSING").length;
  const disputed = disputedFacts + (differences.data?.length ?? 0);
  const unidentified = (evidence.data ?? []).filter((e) => e.status === "UNIDENTIFIED" || e.status === "UNMATCHED").length;
  const missing = missingFacts + unidentified;

  return (
    <AppShell
      title={matter.data?.title ?? "Matter"}
      back="/matters"
      intensity={busy ? "active" : "ambient"}
    >
      <div className="mx-auto max-w-5xl">
        <h2 className="text-2xl" data-testid="matter-title">
          {matter.data?.title ?? "Loading…"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {matter.data?.parties || "No parties recorded"} · {matter.data?.jurisdiction_id ?? "IN"} ·{" "}
          {matter.data?.status}
        </p>

        {matter.data && <MatterLifecycle matter={matter.data} />}

        <Tabs defaultValue="overview" className="mt-6">
          <TabsList variant="line" className="flex-wrap">
            {["overview", "documents", "evidence", "facts", "timeline", "graph", ...(canShare ? ["client"] : []), "activity"].map((t) => (
              <TabsTrigger key={t} value={t} data-testid={`tab-${t}`} className="capitalize">
                {t}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview" className="mt-6 space-y-4">
            <div className="glass rounded-lg p-5">
              <h3 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
                Smart matter summary
              </h3>
              <ul className="mt-3 space-y-1.5 text-sm">
                <li data-testid="count-facts">What we know: {facts.data?.length ?? 0} recorded facts</li>
                <li data-testid="count-documents">Documents on file: {docs.data?.length ?? 0}</li>
                <li data-testid="count-evidence">Evidence items: {evidence.data?.length ?? 0}</li>
                <li data-testid="count-disputed">Disputed (differences between documents or contested facts): {disputed}</li>
                <li data-testid="count-missing">Missing or not yet matched to a person: {missing}</li>
                <li data-testid="count-timeline">Timeline events: {timeline.data?.length ?? 0}</li>
              </ul>
              {matter.data && <MatterDetailsEditor key={matter.data.updated_at} matter={matter.data} />}
              <Link
                to={`/research?matter=${matterId}`}
                className="mt-4 inline-block text-sm"
                style={{ color: "#5B8CFF" }}
                data-testid="matter-research-link"
              >
                Research this matter →
              </Link>
            </div>
          </TabsContent>

          <TabsContent value="documents" className="mt-6 space-y-3">
            <FileDrop<DocumentOut>
              path={`/matters/${matterId}/documents`}
              accept=".pdf,.docx,.xlsx,.pptx,.eml,.txt,.md,.png,.jpg,.jpeg,.webp,.mp4,.mov,.webm,.mp3,.wav,.m4a"
              idleLabel="Upload document or evidence"
              testId="document-upload"
              onDone={async (d) => {
                await qc.invalidateQueries({ queryKey: ["documents", matterId] });
                await qc.invalidateQueries({ queryKey: ["graph", matterId] });
                if (d.processing_status === "READY") toast.success(`${d.filename} processed`);
                else toast.warning(d.failure_reason ?? "Document could not be processed");
              }}
            />
            <FileDrop<{ added: number; skipped: number; results: { filename: string; status: string; reason?: string }[] }>
              path={`/matters/${matterId}/documents/zip`}
              accept=".zip"
              idleLabel="Upload many files at once (a .zip, up to 50 files)"
              hint="Each file is checked and read like a single upload. Files that cannot be added are listed with the reason."
              testId="document-zip-upload"
              onDone={async (r) => {
                await qc.invalidateQueries({ queryKey: ["documents", matterId] });
                await qc.invalidateQueries({ queryKey: ["graph", matterId] });
                const skipped = r.results.filter((x) => x.status !== "added").map((x) => `${x.filename}: ${x.reason ?? "skipped"}`);
                if (r.skipped === 0) toast.success(`${r.added} files added`);
                else toast.warning(`${r.added} added, ${r.skipped} not added. ${skipped.slice(0, 3).join(" | ")}${skipped.length > 3 ? " …" : ""}`);
              }}
            />
            <DocCompare docs={docs.data ?? []} />
            {(docs.data ?? []).map((d) => (
              <DocumentCard
                key={d.id}
                d={d}
                analysis={analyses[d.id]}
                analyzing={analyze.isPending && analyze.variables === d.id}
                onAnalyze={() => analyze.mutate(d.id)}
                onChanged={async () => {
                  await qc.invalidateQueries({ queryKey: ["documents", matterId] });
                  await qc.invalidateQueries({ queryKey: ["graph", matterId] });
                }}
              />
            ))}
            {!docs.isLoading && (docs.data ?? []).length === 0 && (
              <p className="text-sm text-muted-foreground">
                No documents yet — upload a case file to begin.
              </p>
            )}
          </TabsContent>

          <TabsContent value="evidence" className="mt-6">
            <EvidenceTab matterId={matterId} docs={docs.data ?? []} />
          </TabsContent>

          <TabsContent value="facts" className="mt-6 space-y-3">
            <form
              className="glass flex flex-wrap items-end gap-3 rounded-lg p-4"
              onSubmit={(e) => {
                e.preventDefault();
                addFact.mutate();
              }}
            >
              <div className="min-w-[220px] flex-1 space-y-1.5">
                <Label htmlFor="fact">Fact</Label>
                <Input
                  id="fact"
                  value={factValue}
                  onChange={(e) => setFactValue(e.target.value)}
                  required
                  data-testid="fact-value-input"
                />
              </div>
              <div className="w-48 space-y-1.5">
                <Label>Status</Label>
                <Select value={factStatus} onValueChange={(v: string) => setFactStatus(v)}>
                  <SelectTrigger data-testid="fact-status-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FACT_STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-48 space-y-1.5">
                <Label htmlFor="fact-doc">From document (optional)</Label>
                <select
                  id="fact-doc"
                  value={factDoc}
                  onChange={(e) => setFactDoc(e.target.value)}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring dark:bg-input/30"
                  data-testid="fact-doc-select"
                >
                  <option value="" className="bg-popover">— none —</option>
                  {(docs.data ?? []).map((d) => (
                    <option key={d.id} value={d.id} className="bg-popover">{d.filename}</option>
                  ))}
                </select>
              </div>
              <Button type="submit" disabled={addFact.isPending} data-testid="add-fact-button">
                Add fact
              </Button>
            </form>
            {(facts.data ?? []).map((f) => (
              <div
                key={f.id}
                className="glass flex items-center justify-between gap-3 rounded-lg p-4"
                data-testid="fact-row"
              >
                <p className="min-w-0 truncate text-sm">{f.value}</p>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant="outline">{f.status}</Badge>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => removeFact.mutate(f.id)}
                    data-testid="delete-fact-button"
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
            {!facts.isLoading && (facts.data ?? []).length === 0 && (
              <p className="text-sm text-muted-foreground">
                No facts recorded. Evidence gaps appear here once facts exist.
              </p>
            )}
          </TabsContent>

          <TabsContent value="timeline" className="mt-6 space-y-3">
            <form
              className="glass flex flex-wrap items-end gap-3 rounded-lg p-4"
              onSubmit={(e) => {
                e.preventDefault();
                addEvent.mutate();
              }}
            >
              <div className="w-44 space-y-1.5">
                <Label htmlFor="evdate">Date</Label>
                <Input
                  id="evdate"
                  type="date"
                  value={evDate}
                  onChange={(e) => setEvDate(e.target.value)}
                  required
                  data-testid="event-date-input"
                />
              </div>
              <div className="min-w-[220px] flex-1 space-y-1.5">
                <Label htmlFor="evdesc">Event</Label>
                <Input
                  id="evdesc"
                  value={evDesc}
                  onChange={(e) => setEvDesc(e.target.value)}
                  required
                  data-testid="event-description-input"
                />
              </div>
              <Button type="submit" disabled={addEvent.isPending} data-testid="add-event-button">
                Add event
              </Button>
            </form>
            {(timeline.data ?? []).map((e) => (
              <div key={e.id} className="glass rounded-lg p-4" data-testid="timeline-row">
                <p className="text-xs" style={{ color: "#C8A96B" }}>
                  {formatDateText(e.event_date)}
                </p>
                <p className="text-sm">{e.description}</p>
                <p className="text-xs text-muted-foreground">{e.status}</p>
              </div>
            ))}
            {!timeline.isLoading && (timeline.data ?? []).length === 0 && (
              <p className="text-sm text-muted-foreground">No timeline events yet.</p>
            )}
          </TabsContent>

          <TabsContent value="graph" className="mt-6">
            <div className="mb-3 flex items-center gap-2">
              <Button
                size="xs"
                variant={graphView === "structured" ? "default" : "outline"}
                onClick={() => setGraphView("structured")}
                data-testid="graph-structured-toggle"
              >
                Structured view
              </Button>
              <Button
                size="xs"
                variant={graphView === "visual" ? "default" : "outline"}
                onClick={() => setGraphView("visual")}
                data-testid="graph-visual-toggle"
              >
                Visual graph
              </Button>
              <span className="text-xs text-muted-foreground">
                Structured view is the accessible default
              </span>
            </div>
            <div className="glass rounded-lg p-4" data-testid="matter-graph">
              {graphView === "structured" ? (
                <ul className="space-y-1.5 text-sm">
                  {(graph.data?.edges ?? []).map((e, i) => {
                    const src = graph.data?.nodes.find((n) => n.id === e.source);
                    const tgt = graph.data?.nodes.find((n) => n.id === e.target);
                    return (
                      <li key={i} className="truncate" data-testid="graph-edge-row">
                        <span className="text-muted-foreground">[{src?.node_type}]</span>{" "}
                        {src?.label}
                        {src?.sublabel ? <span className="text-muted-foreground"> ({src.sublabel})</span> : null}{" "}
                        <span style={{ color: "#5B8CFF" }}>—{e.relation}→</span>{" "}
                        <span className="text-muted-foreground">[{tgt?.node_type}]</span>{" "}
                        {tgt?.label}
                        {tgt?.sublabel ? <span className="text-muted-foreground"> ({tgt.sublabel})</span> : null}
                      </li>
                    );
                  })}
                  {(graph.data?.edges ?? []).length === 0 && (
                    <li className="text-muted-foreground">
                      No relationships yet — the graph uses real matter data only.
                    </li>
                  )}
                </ul>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {(graph.data?.nodes ?? []).map((n) => (
                    <span
                      key={n.id}
                      className="rounded-full border border-border px-3 py-1 text-xs"
                      style={{ borderColor: "#5B8CFF55" }}
                      data-testid="graph-node-chip"
                    >
                      {n.node_type}: {n.label}
                      {n.sublabel ? ` (${n.sublabel})` : ""}
                    </span>
                  ))}
                  {(graph.data?.nodes ?? []).length === 0 && (
                    <p className="text-sm text-muted-foreground">Nothing to plot yet.</p>
                  )}
                </div>
              )}
            </div>
          </TabsContent>

          {canShare && (
            <TabsContent value="client" className="mt-6">
              <ClientPortalPanel matterId={matterId} docs={(docs.data ?? []).map((d) => ({ id: d.id, filename: d.filename }))} />
            </TabsContent>
          )}

          <TabsContent value="activity" className="mt-6">
            <div className="glass space-y-2 rounded-lg p-4">
              {(audit.data ?? []).map((a) => (
                <div key={a.id} className="text-xs" data-testid="matter-audit-row">
                  <span style={{ color: "#5B8CFF" }}>{a.operation}</span> · {a.result} ·{" "}
                  {a.user_email} · {formatDateTime(a.created_at)}
                  {a.detail ? ` · ${a.detail}` : ""}
                </div>
              ))}
              {(audit.data ?? []).length === 0 && (
                <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
