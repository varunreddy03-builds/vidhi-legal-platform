import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import AddToDates from "@/components/AddToDates";
import FileDrop from "@/components/FileDrop";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import { openApiFile } from "@/lib/files";
import { describe } from "@/lib/interaction";

type Item = { n: number; raw: string; date: string | null; kind: string; flags: string[]; sentence: string; page: number | null; where: string; part: number };
type Counts = { total: number; dated: number; not_read_cleanly: number; no_exact_day: number };
type DateList = { id: string; title: string; created_at: string; expires_at?: string; source_file: string | null; page_kind: "pdf" | "no_pages" | "unknown"; notice: string; counts: Counts; items: Item[] };
type Summary = Omit<DateList, "items">;

const PAGE_NOTES: Record<string, string> = {
  pdf: "Page numbers are the pages of the PDF file.",
  no_pages: "This file type (Word or text) has no fixed pages, so no page numbers are given. “Part” shows where in the file the date sits; a part is not a page.",
  unknown: "This list was made from pasted text, which has no pages.",
};

const NOTICE =
  "This lists the dates written in your document, in date order, with the sentence and where each one is. It does not say what an event means or which dates matter. Dates it cannot read cleanly are marked, never corrected. A lawyer decides.";

/** List of dates with page references: upload or paste a document, see every date it contains with the sentence and the page, and download the list. */
export default function DateListPage() {
  const { id } = useParams();
  return (
    <AppShell title="List of dates">
      <div className={`mx-auto ${id ? "max-w-5xl" : "max-w-3xl"}`}>
        <Link to="/katalyst" className="inline-block py-2 text-xs text-muted-foreground" data-testid="datelist-back">
          ← Legal Katalyst
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl" data-testid="datelist-title">
          List of dates with page references
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="datelist-notice">
          {NOTICE}
        </p>
        {id ? <ListView id={id} /> : <Start />}
      </div>
    </AppShell>
  );
}

function Start() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const list = useQuery({ queryKey: ["datelists"], queryFn: () => apiGet<Summary[]>("/datelists"), retry: false });
  const run = useMutation({
    mutationFn: () => apiPost<DateList>("/datelists", { title: title.trim() || "Untitled list", text }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["datelists"] });
      navigate(`/katalyst/dates/${r.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (list.error instanceof ApiError && list.error.status === 404) {
    return (
      <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="datelist-off">
        The list of dates is not switched on for this server.
      </p>
    );
  }
  return (
    <>
      <div className="glass mt-6 space-y-2 rounded-2xl p-5" data-testid="datelist-file-card">
        <h3 className="text-sm font-medium">List the dates in a file</h3>
        <p className="text-xs text-muted-foreground">PDF, Word or text. The file is read and then dropped: only the list is kept. Only a PDF has real page numbers.</p>
        <div>
          <Label htmlFor="dl-title">Name of the list</Label>
          <Input id="dl-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="datelist-title-input" />
        </div>
        <FileDrop<DateList>
          path="/datelists/file"
          accept=".pdf,.docx,.txt,.md"
          fields={{ title: title.trim() }}
          idleLabel="Choose a document"
          testId="datelist-file"
          onDone={async (r) => {
            await qc.invalidateQueries({ queryKey: ["datelists"] });
            navigate(`/katalyst/dates/${r.id}`);
          }}
        />
      </div>
      <form
        className="glass mt-4 space-y-3 rounded-2xl p-5"
        data-testid="datelist-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) run.mutate();
        }}
      >
        <h3 className="text-sm font-medium">Or paste the text</h3>
        <div>
          <Label htmlFor="dl-text">Text</Label>
          <textarea
            id="dl-text"
            value={text}
            rows={8}
            maxLength={300000}
            onChange={(e) => setText(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
            data-testid="datelist-text-input"
          />
          <p className="mt-1 text-xs text-muted-foreground">Pasted text has no pages. Up to 3,000 dates in one list.</p>
        </div>
        <Button type="submit" disabled={run.isPending || !text.trim()} data-testid="datelist-run">
          {run.isPending ? "Listing…" : "List the dates"}
        </Button>
      </form>
      <h3 className="mt-8 text-sm uppercase tracking-wider text-muted-foreground">Earlier lists</h3>
      <ul className="mt-3 space-y-2" data-testid="datelist-list">
        {(list.data ?? []).map((r) => (
          <li key={r.id}>
            <Link to={`/katalyst/dates/${r.id}`} className="glass flex items-center justify-between gap-3 rounded-lg p-4" data-testid="datelist-row">
              <span className="min-w-0">
                <span className="block truncate text-sm">{r.title}</span>
                <span className="block text-xs text-muted-foreground">{r.counts.total} dates</span>
              </span>
            </Link>
          </li>
        ))}
        {list.data && list.data.length === 0 && <li className="text-sm text-muted-foreground">No lists yet.</li>}
      </ul>
    </>
  );
}

function ListView({ id }: { id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["datelists", id], queryFn: () => apiGet<DateList>(`/datelists/${id}`), retry: false });
  const remove = useMutation({
    mutationFn: () => apiDelete(`/datelists/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["datelists"] });
      navigate("/katalyst/dates");
    },
    onError: (e) => toast.error(describe(e)),
  });
  if (q.isLoading) return <p className="mt-6 text-sm text-muted-foreground">Loading…</p>;
  if (!q.data) return <p className="mt-6 text-sm">This list could not be opened.</p>;
  const r = q.data;
  return (
    <div className="mt-6" data-testid="datelist-report">
      <h3 className="text-lg">{r.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground" data-testid="datelist-summary">
        {r.counts.total} dates · {r.counts.dated} read as one real day · {r.counts.no_exact_day} not read as one day · {r.counts.not_read_cleanly} with a note
        {r.source_file ? ` · ${r.source_file}` : ""}
      </p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="datelist-page-note">
        {PAGE_NOTES[r.page_kind] ?? PAGE_NOTES.unknown}
      </p>
      {r.expires_at && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="datelist-kept">
          Kept until {r.expires_at.slice(0, 10)}, then deleted automatically. Download the Word or PDF copy to keep it.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/datelists/${r.id}/export?format=docx`, "list-of-dates.docx")} data-testid="datelist-export-docx">
          Download Word
        </Button>
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/datelists/${r.id}/export?format=pdf`, "list-of-dates.pdf")} data-testid="datelist-export-pdf">
          Download PDF
        </Button>
        <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()} data-testid="datelist-delete">
          Delete this list
        </Button>
      </div>
      {r.items.length === 0 && (
        <p className="mt-6 text-sm text-muted-foreground" data-testid="datelist-empty">
          No dates were found in this document.
        </p>
      )}
      <ol className="mt-5 space-y-2" data-testid="datelist-items">
        {r.items.map((i) => (
          <li key={i.n} className="glass rounded-xl p-4" data-testid="datelist-item">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-sm font-medium" data-testid="datelist-item-raw">
                {i.raw}
              </span>
              <span className="text-xs text-muted-foreground" data-testid="datelist-item-read">
                {i.date ? `read as ${i.date}` : "not read as one day"}
              </span>
              <span className="ml-auto text-xs text-muted-foreground" data-testid="datelist-item-where">
                {i.where}
              </span>
            </div>
            {i.sentence && <p className="mt-1 break-words text-xs italic text-muted-foreground">“{i.sentence}”</p>}
            {i.flags.map((f) => (
              <p key={f} className="mt-1 text-xs" data-testid="datelist-item-flag">
                Note: {f}
              </p>
            ))}
            {i.date && <AddToDates title={i.sentence || i.raw} date={i.date} note={`Copied from a list of dates (${i.where}). Check the date in the document.`} hint="Check the date against the document before you add it. Reminders use your usual settings." testPrefix="datelist" />}
          </li>
        ))}
      </ol>
    </div>
  );
}
