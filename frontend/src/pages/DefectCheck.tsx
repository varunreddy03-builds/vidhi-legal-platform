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

type Item = { n: number; kind: string; label: string; raw: string; sentence: string; note: string; page: number | null; where: string; part: number };
type Counts = { total: number; by_kind: Record<string, number> };
type Check = { id: string; title: string; created_at: string; expires_at?: string; source_file: string | null; page_kind: "pdf" | "no_pages" | "unknown"; notice: string; counts: Counts; items: Item[] };
type Summary = Omit<Check, "items">;

const PAGE_NOTES: Record<string, string> = {
  pdf: "Page numbers are the pages of the PDF file.",
  no_pages: "This file type (Word or text) has no fixed pages, so no page numbers are given. “Part” shows where in the file the place sits; a part is not a page.",
  unknown: "This check was made from pasted text, which has no pages.",
};

const NOTICE =
  "This points to drafting slips that may need a look before filing: blanks, numbering, annexure labels, paragraph references and doubled words. It does not know any court’s rules, so it cannot say a filing will be accepted or rejected, and it does not say a draft is defective. Each note says why it may not be a slip. A lawyer decides.";

/** Pre-filing defect check: paste or upload a draft, see the drafting slips it points to with the sentence and where each is, and download the list. */
export default function DefectCheckPage() {
  const { id } = useParams();
  return (
    <AppShell title="Pre-filing defect check">
      <div className={`mx-auto ${id ? "max-w-5xl" : "max-w-3xl"}`}>
        <Link to="/katalyst" className="inline-block py-2 text-xs text-muted-foreground" data-testid="defect-back">
          ← Legal Katalyst
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl" data-testid="defect-title">
          Pre-filing defect check
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="defect-notice">
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
  const list = useQuery({ queryKey: ["defectchecks"], queryFn: () => apiGet<Summary[]>("/defectchecks"), retry: false });
  const run = useMutation({
    mutationFn: () => apiPost<Check>("/defectchecks", { title: title.trim() || "Untitled draft", text }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["defectchecks"] });
      navigate(`/katalyst/defects/${r.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (list.error instanceof ApiError && list.error.status === 404) {
    return (
      <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="defect-off">
        The pre-filing defect check is not switched on for this server.
      </p>
    );
  }
  return (
    <>
      <div className="glass mt-6 space-y-2 rounded-2xl p-5" data-testid="defect-file-card">
        <h3 className="text-sm font-medium">Check a file</h3>
        <p className="text-xs text-muted-foreground">PDF, Word or text. The file is read and then dropped: only the findings are kept. Only a PDF has real page numbers.</p>
        <div>
          <Label htmlFor="df-title">Name of the draft</Label>
          <Input id="df-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="defect-title-input" />
        </div>
        <FileDrop<Check>
          path="/defectchecks/file"
          accept=".pdf,.docx,.txt,.md"
          fields={{ title: title.trim() }}
          idleLabel="Choose a draft"
          testId="defect-file"
          onDone={async (r) => {
            await qc.invalidateQueries({ queryKey: ["defectchecks"] });
            navigate(`/katalyst/defects/${r.id}`);
          }}
        />
      </div>
      <form
        className="glass mt-4 space-y-3 rounded-2xl p-5"
        data-testid="defect-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) run.mutate();
        }}
      >
        <h3 className="text-sm font-medium">Or paste the draft</h3>
        <div>
          <Label htmlFor="df-text">Text</Label>
          <textarea
            id="df-text"
            value={text}
            rows={8}
            maxLength={300000}
            onChange={(e) => setText(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
            data-testid="defect-text-input"
          />
          <p className="mt-1 text-xs text-muted-foreground">Pasted text has no pages. Put each numbered paragraph on its own line.</p>
        </div>
        <Button type="submit" disabled={run.isPending || !text.trim()} data-testid="defect-run">
          {run.isPending ? "Checking…" : "Check this draft"}
        </Button>
      </form>
      <h3 className="mt-8 text-sm uppercase tracking-wider text-muted-foreground">Earlier checks</h3>
      <ul className="mt-3 space-y-2" data-testid="defect-list">
        {(list.data ?? []).map((r) => (
          <li key={r.id}>
            <Link to={`/katalyst/defects/${r.id}`} className="glass flex items-center justify-between gap-3 rounded-lg p-4" data-testid="defect-row">
              <span className="min-w-0">
                <span className="block truncate text-sm">{r.title}</span>
                <span className="block text-xs text-muted-foreground">{r.counts.total} places to look at</span>
              </span>
            </Link>
          </li>
        ))}
        {list.data && list.data.length === 0 && <li className="text-sm text-muted-foreground">No checks yet.</li>}
      </ul>
    </>
  );
}

function CheckView({ id }: { id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["defectchecks", id], queryFn: () => apiGet<Check>(`/defectchecks/${id}`), retry: false });
  const remove = useMutation({
    mutationFn: () => apiDelete(`/defectchecks/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["defectchecks"] });
      navigate("/katalyst/defects");
    },
    onError: (e) => toast.error(describe(e)),
  });
  if (q.isLoading) return <p className="mt-6 text-sm text-muted-foreground">Loading…</p>;
  if (!q.data) return <p className="mt-6 text-sm">This check could not be opened.</p>;
  const r = q.data;
  return (
    <div className="mt-6" data-testid="defect-report">
      <h3 className="text-lg">{r.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground" data-testid="defect-summary">
        {r.counts.total === 0
          ? "Nothing was pointed out. That is not a finding that the draft is ready to file."
          : `${r.counts.total} places to look at · ${Object.entries(r.counts.by_kind)
              .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)
              .join(" · ")}`}
        {r.source_file ? ` · ${r.source_file}` : ""}
      </p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="defect-page-note">
        {PAGE_NOTES[r.page_kind] ?? PAGE_NOTES.unknown}
      </p>
      {r.expires_at && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="defect-kept">
          Kept until {r.expires_at.slice(0, 10)}, then deleted automatically. Download the Word or PDF copy to keep it.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/defectchecks/${r.id}/export?format=docx`, "defect-check.docx")} data-testid="defect-export-docx">
          Download Word
        </Button>
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/defectchecks/${r.id}/export?format=pdf`, "defect-check.pdf")} data-testid="defect-export-pdf">
          Download PDF
        </Button>
        <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()} data-testid="defect-delete">
          Delete this check
        </Button>
      </div>
      <ol className="mt-5 space-y-2" data-testid="defect-items">
        {r.items.map((i) => (
          <li key={i.n} className="glass rounded-xl p-4" data-testid="defect-item">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px]" data-testid="defect-item-label">
                {i.label}
              </span>
              <span className="break-all text-sm font-medium" data-testid="defect-item-raw">
                {i.raw}
              </span>
              <span className="ml-auto text-xs text-muted-foreground" data-testid="defect-item-where">
                {i.where}
              </span>
            </div>
            {i.sentence && <p className="mt-1 break-words text-xs italic text-muted-foreground">“{i.sentence}”</p>}
            <p className="mt-1 text-xs" data-testid="defect-item-note">
              {i.note}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}
