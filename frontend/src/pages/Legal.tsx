import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet } from "@/lib/api";
import { describe } from "@/lib/interaction";

interface Component { kind: string; label: string; text: string }
interface Provision {
  id: string;
  number: string;
  heading: string;
  kind: string;
  unit?: string;
  instrument: string;
  instrument_id?: string;
  path: string[];
  page_start: number | null;
  components: Component[];
  limits: Component[];
  version: { label: string; note: string };
  review: { status: "unreviewed" | "reviewed"; statement: string };
  reading: { machine_read: boolean; warning: string | null };
  source: { name: string | null; document: string | null; url: string | null; sha256: string | null; retrieved_on: string | null };
}
interface Entry { instrument: string; version_note: string | null; provisions: Provision[] }
interface Result { query: string; exact: Entry[]; text: Provision[]; review_notice: string }
interface Mapping {
  id: string;
  relationship: string;
  verified: boolean;
  legacy: { citation: string }[];
  new: { citation: string }[];
  differences_in_effect: string;
  commencement: { date: string | null; evidence: string };
  transitional_and_saving: { note: string }[];
  reviewed_by: string | null;
  verified_on: string | null;
}
interface MappingResult { mappings: Mapping[]; verified_mappings: Mapping[]; caveat: string; message?: string; offence_date_note?: string }
interface HistoryEntry { version_id: string; label: string; effective_from: string | null; effective_to: string | null; evidence: string; change: string; review_status: string }
interface HistoryItem { instrument_id: string; timeline: HistoryEntry[]; warnings: string[] }
interface HistoryResult { results: HistoryItem[]; note: string }
interface RefEdge { id: string; kind: string; to_number: string; sub: string; hint: string | null; resolved: boolean; structural: boolean; from_number: string }
interface RefResult { refers_to: RefEdge[]; referred_to_by: RefEdge[]; note: string }
interface Coverage { provisions: number; provisions_reviewed: number; instruments: number; meaning: string }
interface Resources { resources: { id: string; name: string; gives: string; note: string }[]; note: string }

const KIND_LABEL: Record<string, string> = { rule: "Rule", subsection: "Subsection", clause: "Clause", proviso: "Proviso", explanation: "Explanation", illustration: "Illustration", exception: "Exception" };
const LIMIT_KINDS = new Set(["proviso", "exception"]);

function Mappings({ p }: { p: Provision }) {
  const [offence, setOffence] = useState("");
  const q = useMutation({
    mutationFn: () => apiGet<MappingResult>(`/legal/mappings?number=${encodeURIComponent(p.number)}&instrument=${encodeURIComponent(p.instrument)}${offence ? `&offence_date=${offence}` : ""}`),
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor={`off-${p.id}`} className="text-xs">Date of the conduct (optional)</Label>
          <Input id={`off-${p.id}`} type="date" value={offence} onChange={(e) => setOffence(e.target.value)} className="h-8" />
        </div>
        <Button size="sm" variant="outline" loading={q.isPending} onClick={() => q.mutate()} data-testid="mappings-check">Check recorded cross-references</Button>
      </div>
      {q.data && (
        <div className="mt-3 space-y-2 text-sm" data-testid="mappings-result">
          {q.data.message && <p>{q.data.message}</p>}
          {q.data.mappings.map((m) => (
            <div key={m.id} className="rounded-md border border-border p-3">
              <p className="font-medium">
                {m.verified ? "Reviewed cross-reference" : "Unreviewed (not verified)"} · {m.relationship}
              </p>
              <p>{m.legacy.map((x) => x.citation).join("; ")} → {m.new.length ? m.new.map((x) => x.citation).join("; ") : "no corresponding provision recorded"}</p>
              <p className="mt-1 text-muted-foreground">Differences: {m.differences_in_effect}</p>
              {m.commencement.date && <p className="text-muted-foreground">Recorded commencement: {m.commencement.date} ({m.commencement.evidence})</p>}
              {m.transitional_and_saving.map((t, i) => <p key={i} className="text-muted-foreground">Transitional note: {t.note}</p>)}
              {m.verified && <p className="text-xs text-muted-foreground">Reviewed by {m.reviewed_by} on {m.verified_on}</p>}
            </div>
          ))}
          {q.data.offence_date_note && <p className="text-muted-foreground">{q.data.offence_date_note}</p>}
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2" role="note">{q.data.caveat}</p>
        </div>
      )}
    </div>
  );
}

function Connections({ p }: { p: Provision }) {
  const [open, setOpen] = useState(false);
  const history = useQuery({
    queryKey: ["legal-history", p.instrument_id ?? p.id, p.number],
    queryFn: () => apiGet<HistoryResult>(`/legal/history?number=${encodeURIComponent(p.number)}&instrument=${encodeURIComponent(p.instrument)}`),
    enabled: open,
  });
  const refs = useQuery({ queryKey: ["legal-refs", p.id], queryFn: () => apiGet<RefResult>(`/legal/provisions/${p.id}/references`), enabled: open });
  const item = history.data?.results.find((r) => r.instrument_id === p.instrument_id) ?? history.data?.results[0];
  const edge = (e: RefEdge) => `${e.kind} ${e.to_number}${e.sub}${e.hint ? ` of ${e.hint}` : ""}${e.resolved ? "" : e.structural ? "" : " (not loaded)"}`;
  return (
    <div className="mt-3 border-t border-border pt-3">
      <Button size="sm" variant="outline" onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="connections-toggle">
        {open ? "Hide history and cross-references" : "Show history and cross-references"}
      </Button>
      {open && (
        <div className="mt-3 space-y-3 text-sm" data-testid="connections">
          <div>
            <p className="font-medium">Versions loaded</p>
            {history.isLoading && <p className="text-muted-foreground">Loading…</p>}
            {item && (
              <ul className="mt-1 space-y-1">
                {item.timeline.map((t) => (
                  <li key={t.version_id}>
                    {t.label}: {t.effective_from ? `from ${t.effective_from}` : "effective date not recorded"}
                    {t.effective_to ? ` to ${t.effective_to}` : ""} · {t.change.replace("_", " ")} · {t.review_status}
                  </li>
                ))}
              </ul>
            )}
            {item?.warnings.map((w) => <p key={w} className="text-muted-foreground">{w}</p>)}
            {history.data && <p className="mt-1 text-xs text-muted-foreground">{history.data.note}</p>}
          </div>
          <div>
            <p className="font-medium">Mentions</p>
            {refs.data && refs.data.refers_to.length === 0 && <p className="text-muted-foreground">Nothing else is mentioned in this text.</p>}
            {refs.data && refs.data.refers_to.length > 0 && <p className="text-muted-foreground">{refs.data.refers_to.map(edge).join("; ")}</p>}
            {refs.data && refs.data.referred_to_by.length > 0 && <p className="mt-1 text-muted-foreground">Mentioned by: {refs.data.referred_to_by.map((e) => e.from_number).join(", ")}</p>}
            {refs.data && <p className="mt-1 text-xs text-muted-foreground">{refs.data.note}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function ProvisionCard({ p }: { p: Provision }) {
  const reviewed = p.review.status === "reviewed";
  return (
    <article className="glass rounded-lg p-4" data-testid="provision-card" aria-label={`${p.unit ?? "Section"} ${p.number} of ${p.instrument}`}>
      <h3 className="text-lg">
        {p.kind === "section" ? `${p.unit ?? "Section"} ` : ""}
        {p.number}
        {p.heading ? `: ${p.heading}` : ""}
      </h3>
      <p className="text-sm text-muted-foreground">
        {p.instrument} · {p.version.label} ({p.version.note}){p.page_start ? ` · page ${p.page_start}` : ""}
        {p.path.length > 0 ? ` · ${p.path.join(" > ")}` : ""}
      </p>
      <p className={`mt-2 rounded-md border p-2 text-sm ${reviewed ? "border-emerald-500/40 bg-emerald-500/10" : "border-amber-500/40 bg-amber-500/10"}`} role="note" data-testid="review-statement">
        {reviewed ? "Reviewed. " : "Not verified. "}
        {p.review.statement}
      </p>
      {p.reading.warning && <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm" role="note">{p.reading.warning}</p>}
      {p.limits.length > 0 && <p className="mt-2 text-sm">This provision has {p.limits.length} proviso(s) or exception(s). All are shown below, in order.</p>}
      <div className="mt-3 space-y-2">
        {p.components.map((c, i) => (
          <div key={i} className={`rounded-md p-2 text-sm ${LIMIT_KINDS.has(c.kind) ? "border border-border bg-muted/40" : ""}`} data-testid={`component-${c.kind}`}>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">{KIND_LABEL[c.kind] ?? c.kind}{c.label && c.kind !== "rule" && !c.label.toLowerCase().startsWith(c.kind) ? ` ${c.label}` : ""}</p>
            <p className="whitespace-pre-wrap">{c.text}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Source: {p.source.name ?? "unknown"}{p.source.document ? `, ${p.source.document}` : ""}
        {p.source.retrieved_on ? `, retrieved ${p.source.retrieved_on}` : ""}
        {p.source.sha256 ? `, file fingerprint ${p.source.sha256.slice(0, 12)}` : ""}
        {p.source.url ? (
          <>
            {" "}
            <a href={p.source.url} target="_blank" rel="noreferrer" className="underline">official source</a>
          </>
        ) : null}
      </p>
      <Connections p={p} />
      {p.kind === "section" && <Mappings p={p} />}
    </article>
  );
}

/** Looks up a provision of an Act that has been loaded from an official source. Everything is labelled with its review status; nothing here is legal advice. */
export default function Legal() {
  const [q, setQ] = useState("");
  const [on, setOn] = useState("");
  const coverage = useQuery({ queryKey: ["legal-coverage"], queryFn: () => apiGet<Coverage>("/legal/coverage") });
  const help = useQuery({ queryKey: ["legal-resources"], queryFn: () => apiGet<Resources>("/legal/resources") });
  const search = useMutation({
    mutationFn: () => apiGet<Result>(`/legal/search?q=${encodeURIComponent(q)}${on ? `&on=${on}` : ""}`),
    onError: (e) => toast.error(describe(e)),
  });
  const r = search.data;
  const empty = coverage.isSuccess && coverage.data.provisions === 0;

  return (
    <AppShell title="Legal lookup">
      <div className="mx-auto max-w-4xl space-y-6" data-testid="legal-page">
        <div>
          <h2 className="text-2xl">Legal lookup</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Look up a section of an Act that has been loaded from an official source, for example &ldquo;Section 3 of the Example Act&rdquo; or words from the text. This is a research aid, not legal advice.
          </p>
        </div>
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note">
          Text shown here is <strong>not verified as law</strong> unless it says it was reviewed, and even then a lawyer must check it for your facts.
          {coverage.data && (
            <>
              {" "}Currently loaded: {coverage.data.provisions} provision(s) from {coverage.data.instruments} instrument(s); {coverage.data.provisions_reviewed} reviewed. {coverage.data.meaning}
            </>
          )}
        </div>
        {empty && (
          <p className="text-sm text-muted-foreground" data-testid="legal-empty">
            No legal text has been loaded yet, so there is nothing to look up. Legal text is added by the operator from official sources and reviewed by a lawyer before it is relied on.
          </p>
        )}
        <form
          className="glass space-y-3 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault();
            search.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="legal-q">Section and Act, or words from the text</Label>
            <Input id="legal-q" value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} required data-testid="legal-query" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="legal-on">Date the text should apply on (optional)</Label>
            <Input id="legal-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} className="max-w-48" />
            <p className="text-xs text-muted-foreground">A version is chosen by date only when its effective dates are recorded. Otherwise every loaded version is shown.</p>
          </div>
          <Button type="submit" loading={search.isPending} data-testid="legal-search">Look up</Button>
        </form>

        {r && (
          <div className="space-y-5" data-testid="legal-results">
            {r.exact.map((e) => (
              <section key={e.instrument} className="space-y-3">
                <h3 className="text-xl">{e.instrument}</h3>
                {e.version_note && <p className="text-sm text-muted-foreground">{e.version_note}</p>}
                {e.provisions.map((p) => <ProvisionCard key={p.id} p={p} />)}
              </section>
            ))}
            {r.text.length > 0 && (
              <section className="space-y-3">
                <h3 className="text-xl">Other matches in the text</h3>
                {r.text.map((p) => <ProvisionCard key={p.id} p={p} />)}
              </section>
            )}
            {r.exact.length === 0 && r.text.length === 0 && <p className="text-sm text-muted-foreground" data-testid="legal-none">Nothing matched in the legal text that has been loaded. That does not mean no such provision exists.</p>}
          </div>
        )}
        {help.data && help.data.resources.length > 0 && (
          <section className="glass rounded-lg p-4" aria-labelledby="free-help" data-testid="free-help">
            <h3 id="free-help" className="text-lg">Free legal help</h3>
            <p className="mt-1 text-sm text-muted-foreground">{help.data.note}</p>
            <ul className="mt-3 space-y-2 text-sm">
              {help.data.resources.map((r) => (
                <li key={r.id}>
                  <span className="font-medium">{r.name}</span>: {r.gives}
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="text-xs text-muted-foreground">
          Questions about your own documents belong in <Link to="/research" className="underline">Research</Link>; the verified law library is what lets an answer cite law as verified.
        </p>
      </div>
    </AppShell>
  );
}
