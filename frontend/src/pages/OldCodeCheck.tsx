import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import FileDrop from "@/components/FileDrop";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import { openApiFile } from "@/lib/files";
import { describe } from "@/lib/interaction";

type Reviewed = { relationship: string; equivalence: string; new: string[]; authorities: string[]; reviewed_by: string | null };
type Draft = { relationship: string; equivalence: string; new: string[]; authorities: string[] };
type Mapping = { status: "reviewed" | "none"; reviewed: Reviewed[]; unreviewed_count: number; unreviewed?: Draft[]; message?: string };
type Item = { n: number; kind: string; label: string; act: string; act_name: string; section: string; raw: string; sentence: string; note: string; page: number | null; where: string; part: number; mapping: Mapping | null };
type Counts = { total: number; by_act: Record<string, number>; sections: number; with_reviewed_mapping: number };
type Check = { id: string; title: string; created_at: string; expires_at?: string; source_file: string | null; page_kind: "pdf" | "no_pages" | "unknown"; notice: string; caveat: string; counts: Counts; items: Item[] };
type Summary = Omit<Check, "items">;

const PAGE_NOTES: Record<string, string> = {
  pdf: "Page numbers are the pages of the PDF file.",
  no_pages: "This file type (Word or text) has no fixed pages, so no page numbers are given. “Part” shows where in the file the place sits; a part is not a page.",
  unknown: "This check was made from pasted text, which has no pages.",
};

const NOTICE =
  "This lists where the draft names the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act, and the section numbers written there. A newer section is shown only if a named reviewer has marked a mapping as reviewed. Where none is recorded, that does not mean none exists. It does not say which code applies to a matter: that depends on dates and transitional rules, and a lawyer decides.";

/** Old-code to new-code checker: paste or upload a draft, see every place it names the older criminal codes, and the reviewed newer section where one is recorded. */
export default function OldCodeCheckPage() {
  const { id } = useParams();
  return (
    <AppShell title="Old-code to new-code checker">
      <div className={`mx-auto ${id ? "max-w-5xl" : "max-w-3xl"}`}>
        <Link to="/katalyst" className="inline-block py-2 text-xs text-muted-foreground" data-testid="oldcode-back">
          ← Legal Katalyst
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl" data-testid="oldcode-title">
          Old-code to new-code checker
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="oldcode-notice">
          {NOTICE}
        </p>
        {id ? <CheckView id={id} /> : <Start />}
      </div>
    </AppShell>
  );
}

function Start() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const list = useQuery({ queryKey: ["oldcodechecks"], queryFn: () => apiGet<Summary[]>("/oldcodechecks"), retry: false });
  const run = useMutation({
    mutationFn: () => apiPost<Check>("/oldcodechecks", { title: title.trim() || "Untitled draft", text }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["oldcodechecks"] });
      navigate(`/katalyst/oldcode/${r.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (list.error instanceof ApiError && list.error.status === 404) {
    return (
      <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="oldcode-off">
        The old-code checker is not switched on for this server.
      </p>
    );
  }
  return (
    <>
      <div className="glass mt-6 space-y-2 rounded-2xl p-5" data-testid="oldcode-file-card">
        <h3 className="text-sm font-medium">Check a file</h3>
        <p className="text-xs text-muted-foreground">PDF, Word or text. The file is read and then dropped: only the findings are kept. Only a PDF has real page numbers.</p>
        <div>
          <Label htmlFor="oc-title">Name of the draft</Label>
          <Input id="oc-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="oldcode-title-input" />
        </div>
        <FileDrop<Check>
          path="/oldcodechecks/file"
          accept=".pdf,.docx,.txt,.md"
          fields={{ title: title.trim() }}
          idleLabel="Choose a draft"
          testId="oldcode-file"
          onDone={async (r) => {
            await qc.invalidateQueries({ queryKey: ["oldcodechecks"] });
            navigate(`/katalyst/oldcode/${r.id}`);
          }}
        />
      </div>
      <form
        className="glass mt-4 space-y-3 rounded-2xl p-5"
        data-testid="oldcode-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) run.mutate();
        }}
      >
        <h3 className="text-sm font-medium">Or paste the draft</h3>
        <div>
          <Label htmlFor="oc-text">Text</Label>
          <textarea
            id="oc-text"
            value={text}
            rows={8}
            maxLength={300000}
            onChange={(e) => setText(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
            data-testid="oldcode-text-input"
          />
          <p className="mt-1 text-xs text-muted-foreground">Pasted text has no pages.</p>
        </div>
        <Button type="submit" disabled={run.isPending || !text.trim()} data-testid="oldcode-run">
          {run.isPending ? "Checking…" : "Check this draft"}
        </Button>
      </form>
      <h3 className="mt-8 text-sm uppercase tracking-wider text-muted-foreground">Earlier checks</h3>
      <ul className="mt-3 space-y-2" data-testid="oldcode-list">
        {(list.data ?? []).map((r) => (
          <li key={r.id}>
            <Link to={`/katalyst/oldcode/${r.id}`} className="glass flex items-center justify-between gap-3 rounded-lg p-4" data-testid="oldcode-row">
              <span className="min-w-0">
                <span className="block truncate text-sm">{r.title}</span>
                <span className="block text-xs text-muted-foreground">{r.counts.total} references</span>
              </span>
            </Link>
          </li>
        ))}
        {list.data && list.data.length === 0 && <li className="text-sm text-muted-foreground">No checks yet.</li>}
      </ul>
    </>
  );
}

function MappingView({ m }: { m: Mapping }) {
  if (m.status !== "reviewed") {
    return (
      <div className="mt-1 space-y-1 text-xs" data-testid="oldcode-item-mapping">
        <p>
          {m.message}
          {m.unreviewed_count > 0 ? ` ${m.unreviewed_count} unreviewed ${m.unreviewed_count === 1 ? "entry exists and is" : "entries exist and are"} not counted as an answer.` : ""}
        </p>
        {(m.unreviewed ?? []).map((d, k) => (
          <p key={k} className="rounded border border-dashed border-amber-500/60 px-2 py-1" data-testid="oldcode-item-unreviewed">
            <span className="font-medium">Unreviewed, not verified</span> ({d.relationship}; {d.equivalence}): {d.new.join(", ") || "no newer provision"}. Source: {d.authorities.join("; ")}. No reviewer has compared it with its source.
          </p>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-1 space-y-1 text-xs" data-testid="oldcode-item-mapping">
      {m.reviewed.map((r, k) => (
        <p key={k}>
          Reviewed mapping ({r.relationship}; {r.equivalence}): {r.new.join(", ") || "no newer provision"}. Source: {r.authorities.join("; ")}. Reviewed by {r.reviewed_by}.
        </p>
      ))}
    </div>
  );
}

function CheckView({ id }: { id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["oldcodechecks", id], queryFn: () => apiGet<Check>(`/oldcodechecks/${id}`), retry: false });
  const remove = useMutation({
    mutationFn: () => apiDelete(`/oldcodechecks/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["oldcodechecks"] });
      navigate("/katalyst/oldcode");
    },
    onError: (e) => toast.error(describe(e)),
  });
  if (q.isLoading) return <p className="mt-6 text-sm text-muted-foreground">Loading…</p>;
  if (!q.data) return <p className="mt-6 text-sm">This check could not be opened.</p>;
  const r = q.data;
  return (
    <div className="mt-6" data-testid="oldcode-report">
      <h3 className="text-lg">{r.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground" data-testid="oldcode-summary">
        {r.counts.total === 0
          ? "No reference to the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act was found. That is not a finding that the draft has none."
          : `${r.counts.total} references · ${r.counts.sections} with a section number · ${r.counts.with_reviewed_mapping} with a reviewed mapping`}
        {r.source_file ? ` · ${r.source_file}` : ""}
      </p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="oldcode-page-note">
        {PAGE_NOTES[r.page_kind] ?? PAGE_NOTES.unknown}
      </p>
      {r.expires_at && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="oldcode-kept">
          Kept until {r.expires_at.slice(0, 10)}, then deleted automatically. Download the Word or PDF copy to keep it.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/oldcodechecks/${r.id}/export?format=docx`, "old-code-check.docx")} data-testid="oldcode-export-docx">
          Download Word
        </Button>
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/oldcodechecks/${r.id}/export?format=pdf`, "old-code-check.pdf")} data-testid="oldcode-export-pdf">
          Download PDF
        </Button>
        <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()} data-testid="oldcode-delete">
          Delete this check
        </Button>
      </div>
      <ol className="mt-5 space-y-2" data-testid="oldcode-items">
        {r.items.map((i) => (
          <li key={i.n} className="glass rounded-xl p-4" data-testid="oldcode-item">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px]" data-testid="oldcode-item-label">
                {i.act_name}
                {i.section ? ` · section ${i.section}` : " · named"}
              </span>
              <span className="break-all text-sm font-medium" data-testid="oldcode-item-raw">
                {i.raw}
              </span>
              <span className="ml-auto text-xs text-muted-foreground" data-testid="oldcode-item-where">
                {i.where}
              </span>
            </div>
            {i.sentence && <p className="mt-1 break-words text-xs italic text-muted-foreground">“{i.sentence}”</p>}
            {i.mapping ? (
              <MappingView m={i.mapping} />
            ) : (
              <p className="mt-1 text-xs" data-testid="oldcode-item-note">
                {i.note}
              </p>
            )}
          </li>
        ))}
      </ol>
      <p className="mt-5 text-xs text-muted-foreground" data-testid="oldcode-caveat">
        {r.caveat}
      </p>
    </div>
  );
}
