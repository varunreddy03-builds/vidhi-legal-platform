import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiDelete, apiGet, apiPost, apiUpload } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { DocumentAnalysis, DocumentOut, Matter } from "@/lib/types";

type Preset = { id: string; label: string; question: string };
type Column = { id?: string; label?: string; question?: string };
type Cell = { id: string; status: "FOUND" | "UNCONFIRMED" | "NONE_REPORTED"; answer: string; quote: string; page: number | null; note: string };
type Row = { id: string; document_id: string; filename: string; cells: Cell[]; read_in_full: boolean; coverage_note: string };
type Rows = { rows: Row[]; columns: { id: string; label: string; question: string }[]; documents_total: number; documents_with_text: number; note: string };
type SummaryItem = { document_id: string; filename: string; doc_class: string; has_text: boolean; analysis: DocumentAnalysis | null };
type Summaries = { items: SummaryItem[]; documents_total: number; summarised: number; waiting: number };

const STATUS_TEXT: Record<Cell["status"], string> = { FOUND: "Quote found", UNCONFIRMED: "Unconfirmed", NONE_REPORTED: "Nothing reported" };
const STATUS_STYLE: Record<Cell["status"], "default" | "secondary" | "outline"> = { FOUND: "default", UNCONFIRMED: "secondary", NONE_REPORTED: "outline" };

function VaultList() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const vaults = useQuery<Matter[]>({ queryKey: ["vaults"], queryFn: async () => (await apiGet<Matter[]>("/matters")).filter((m) => m.kind === "VAULT") });
  const create = useMutation({
    mutationFn: () => apiPost<Matter>("/matters", { title: title.trim(), description: "", parties: "", jurisdiction_id: "IN", kind: "VAULT" }),
    onSuccess: async (m) => {
      await qc.invalidateQueries({ queryKey: ["vaults"] });
      await qc.invalidateQueries({ queryKey: ["matters"] });
      navigate(`/vault/${m.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <AppShell title="Vault">
      <div className="mx-auto max-w-4xl vidhi-rise">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Legal Intelligence</p>
        <h2 className="mt-1 text-3xl tracking-tight">Vault</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          A Vault holds many documents together. Add them, get a summary of each, and fill one table that asks the same questions of every document, with the exact quote and page for each answer. Everything stays in your own
          organisation. Check the document before relying on any answer.
        </p>
        <form
          className="mt-6 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) create.mutate();
          }}
        >
          <div className="min-w-56 flex-1 space-y-1.5">
            <Label htmlFor="vault-title">New Vault name</Label>
            <Input id="vault-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} data-testid="vault-title-input" />
          </div>
          <Button type="submit" disabled={create.isPending || !title.trim()} data-testid="vault-create-button">
            {create.isPending ? "Creating…" : "Create Vault"}
          </Button>
        </form>
        <div className="mt-8 space-y-2">
          {vaults.isLoading && <div className="glass h-16 rounded-lg vidhi-sweep" />}
          {vaults.isError && <p className="text-sm">Could not load your Vaults. Reload to retry.</p>}
          {vaults.data && vaults.data.length === 0 && <p className="text-sm text-muted-foreground" data-testid="vault-empty">No Vaults yet. Create one above.</p>}
          {(vaults.data ?? []).map((m) => (
            <Link key={m.id} to={`/vault/${m.id}`} className="glass glass-lift block rounded-xl p-4" data-testid="vault-item">
              <span className="font-medium">{m.title}</span>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function Summary({ item }: { item: SummaryItem }) {
  const a = item.analysis;
  return (
    <li className="rounded-xl border bg-background/40 p-4" data-testid="vault-summary-item">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium break-all">{item.filename}</span>
        <Badge variant="outline">{item.doc_class}</Badge>
      </div>
      {!item.has_text && <p className="mt-1 text-sm text-muted-foreground">This file has no readable text, so it cannot be summarised.</p>}
      {item.has_text && !a && <p className="mt-1 text-sm text-muted-foreground">Not summarised yet.</p>}
      {a && (
        <>
          <p className="mt-2 text-sm whitespace-pre-wrap">{a.summary}</p>
          {a.flags?.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {a.flags.map((f, i) => (
                <li key={i}>
                  <span className="font-medium">{f.clause}</span> ({f.risk.toLowerCase()}): {f.why}
                  {f.quote && (
                    <span className="block text-muted-foreground">
                      “{f.quote}”{f.page ? `, page ${f.page}` : ""} {f.quote_verified ? "· quote found by the program" : "· quote not confirmed"}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {a.coverage_note && <p className="mt-1 text-xs text-muted-foreground">{a.coverage_note}</p>}
        </>
      )}
    </li>
  );
}

function VaultDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const stop = useRef(false);
  const [presets, setPresets] = useState<string[]>(["parties", "date", "termination"]);
  const [custom, setCustom] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"" | "upload" | "summarise" | "table">("");
  const [progress, setProgress] = useState("");

  const matter = useQuery<Matter>({ queryKey: ["matter", id], queryFn: () => apiGet<Matter>(`/matters/${id}`) });
  const columnsInfo = useQuery<{ presets: Preset[]; max_columns: number }>({ queryKey: ["vault-columns"], queryFn: () => apiGet("/vault/columns") });
  const docs = useQuery<DocumentOut[]>({ queryKey: ["vault-docs", id], queryFn: () => apiGet<DocumentOut[]>(`/matters/${id}/documents`), refetchInterval: (q) => (q.state.data?.some((d) => d.processing_status === "PROCESSING") ? 2000 : false) });
  const summaries = useQuery<Summaries>({ queryKey: ["vault-summaries", id], queryFn: () => apiGet<Summaries>(`/matters/${id}/vault/summaries`) });
  const rows = useQuery<Rows>({ queryKey: ["vault-rows", id], queryFn: () => apiGet<Rows>(`/matters/${id}/vault/rows`) });

  const refresh = async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: ["vault-docs", id] }), qc.invalidateQueries({ queryKey: ["vault-summaries", id] }), qc.invalidateQueries({ queryKey: ["vault-rows", id] })]);
  };

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy("upload");
    let ok = 0;
    for (const f of Array.from(files)) {
      setProgress(`Adding ${f.name}…`);
      try {
        await apiUpload(`/matters/${id}/documents`, f);
        ok += 1;
      } catch (e) {
        toast.error(`${f.name}: ${describe(e)}`);
      }
    }
    if (fileInput.current) fileInput.current.value = "";
    setBusy("");
    setProgress("");
    if (ok) toast.success(`${ok} file${ok === 1 ? "" : "s"} added`);
    await refresh();
  }

  async function summariseAll() {
    const todo = (summaries.data?.items ?? []).filter((i) => i.has_text && !i.analysis);
    if (!todo.length) return;
    stop.current = false;
    setBusy("summarise");
    let done = 0;
    for (const item of todo) {
      if (stop.current) break;
      setProgress(`Summarising ${done + 1} of ${todo.length}: ${item.filename}`);
      try {
        await apiPost(`/documents/${item.document_id}/analyze`, {});
      } catch (e) {
        toast.error(`${item.filename}: ${describe(e)}`);
        if (/limit|cap|plan/i.test(describe(e))) break;
      }
      done += 1;
      await qc.invalidateQueries({ queryKey: ["vault-summaries", id] });
    }
    setBusy("");
    setProgress("");
    await refresh();
  }

  const columns: Column[] = [...presets.map((p) => ({ id: p })), ...custom.map((q) => ({ question: q }))];

  async function fillTable() {
    const list = (docs.data ?? []).filter((d) => d.processing_status === "READY");
    if (!list.length || !columns.length) return;
    stop.current = false;
    setBusy("table");
    let done = 0;
    for (const d of list) {
      if (stop.current) break;
      setProgress(`Reading ${done + 1} of ${list.length}: ${d.filename}`);
      try {
        await apiPost(`/matters/${id}/vault/rows`, { document_id: d.id, columns });
      } catch (e) {
        toast.error(`${d.filename}: ${describe(e)}`);
        if (/limit|cap|plan/i.test(describe(e))) break;
      }
      done += 1;
      await qc.invalidateQueries({ queryKey: ["vault-rows", id] });
    }
    setBusy("");
    setProgress("");
  }

  const clear = useMutation({
    mutationFn: () => apiDelete(`/matters/${id}/vault/rows`),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });

  const max = columnsInfo.data?.max_columns ?? 12;
  const toggle = (pid: string) => setPresets((cur) => (cur.includes(pid) ? cur.filter((x) => x !== pid) : cur.length + custom.length < max ? [...cur, pid] : cur));
  const addCustom = () => {
    const q = draft.trim().replace(/\s+/g, " ");
    if (q.length < 5 || q.length > 300 || presets.length + custom.length >= max) return;
    setCustom((c) => [...c, q]);
    setDraft("");
  };
  const t = rows.data;
  const sum = summaries.data;

  return (
    <AppShell title="Vault">
      <div className="mx-auto max-w-6xl vidhi-rise">
        <Link to="/vault" className="text-sm underline underline-offset-4">All Vaults</Link>
        <h2 className="mt-2 text-3xl tracking-tight" data-testid="vault-name">{matter.data?.title ?? "Vault"}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Ask a question across all of these documents in <Link to={`/research?matter=${id}`} className="underline underline-offset-4">Research</Link>, or open the files in{" "}
          <Link to={`/matters/${id}`} className="underline underline-offset-4">the matter view</Link>.
        </p>

        <section className="glass vidhi-rise mt-6 rounded-xl p-5 sm:p-6" aria-labelledby="vault-docs-h">
          <h3 id="vault-docs-h" className="text-lg font-medium">1. Documents</h3>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <input ref={fileInput} type="file" multiple className="sr-only" id="vault-files" aria-label="Choose files to add to this Vault" data-testid="vault-file-input" onChange={(e) => void upload(e.target.files)} disabled={busy !== ""} />
            <Button type="button" onClick={() => fileInput.current?.click()} disabled={busy !== ""} data-testid="vault-add-files">Add files</Button>
            <span className="text-sm text-muted-foreground" data-testid="vault-doc-count">{docs.data?.length ?? 0} document{(docs.data?.length ?? 0) === 1 ? "" : "s"}</span>
          </div>
          {docs.data?.some((d) => d.processing_status === "FAILED" || d.processing_status === "UNSUPPORTED") && (
            <p className="mt-1 text-sm text-muted-foreground">Some files could not be read; they are left out of the table.</p>
          )}
        </section>

        <section className="glass vidhi-rise mt-6 rounded-xl p-5 sm:p-6" aria-labelledby="vault-sum-h">
          <h3 id="vault-sum-h" className="text-lg font-medium">2. Summaries</h3>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={() => void summariseAll()} disabled={busy !== "" || !sum?.waiting} data-testid="vault-summarise">
              {sum?.waiting ? `Summarise ${sum.waiting} waiting` : "Nothing waiting"}
            </Button>
            <span className="text-sm text-muted-foreground">{sum ? `${sum.summarised} of ${sum.documents_total} summarised` : ""}</span>
          </div>
          <ul className="mt-3 space-y-2">{(sum?.items ?? []).map((i) => <Summary key={i.document_id} item={i} />)}</ul>
        </section>

        <section className="glass vidhi-rise mt-6 rounded-xl p-5 sm:p-6" aria-labelledby="vault-table-h">
          <h3 id="vault-table-h" className="text-lg font-medium">3. Review table</h3>
          <p className="mt-1 text-sm text-muted-foreground">Choose the columns (up to {max}). Each document is read once for all of them.</p>
          <fieldset className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
            <legend className="sr-only">Columns</legend>
            {(columnsInfo.data?.presets ?? []).map((p) => (
              <label key={p.id} className="flex min-h-10 items-center gap-2 text-sm">
                <input type="checkbox" checked={presets.includes(p.id)} onChange={() => toggle(p.id)} data-testid={`vault-col-${p.id}`} />
                {p.label}
              </label>
            ))}
          </fieldset>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <div className="min-w-56 flex-1 space-y-1.5">
              <Label htmlFor="vault-custom">Your own question</Label>
              <Input id="vault-custom" value={draft} maxLength={300} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }} data-testid="vault-custom-input" />
            </div>
            <Button type="button" variant="outline" onClick={addCustom} disabled={draft.trim().length < 5} data-testid="vault-custom-add">Add question</Button>
          </div>
          {custom.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm">
              {custom.map((q, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span>{q}</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setCustom((c) => c.filter((_, j) => j !== i))} aria-label={`Remove question: ${q}`}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={() => void fillTable()} disabled={busy !== "" || !columns.length || !(docs.data ?? []).some((d) => d.processing_status === "READY")} data-testid="vault-run">
              Fill the table
            </Button>
            {busy !== "" && busy !== "upload" && <Button type="button" variant="outline" onClick={() => { stop.current = true; }} data-testid="vault-stop">Stop</Button>}
            {t && t.rows.length > 0 && (
              <>
                <a className="text-sm underline underline-offset-4" href={`/api/matters/${id}/vault/table.csv`} download data-testid="vault-csv">Download CSV</a>
                <Button type="button" variant="ghost" size="sm" disabled={busy !== "" || clear.isPending} onClick={() => clear.mutate()} data-testid="vault-clear">Clear table</Button>
              </>
            )}
          </div>
          <p className="mt-2 min-h-5 text-sm text-muted-foreground" role="status" aria-live="polite" data-testid="vault-progress">{progress}</p>

          {t && t.rows.length > 0 && (
            <div className="mt-2 overflow-x-auto rounded-lg border" data-testid="vault-table-wrap">
              <table className="w-full min-w-[40rem] text-left text-sm" data-testid="vault-table">
                <caption className="sr-only">Answers from each document, with the quote and page for each</caption>
                <thead>
                  <tr>
                    <th scope="col" className="p-2">Document</th>
                    {t.columns.map((c) => <th scope="col" key={c.id} className="p-2">{c.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r) => {
                    const by = Object.fromEntries(r.cells.map((c) => [c.id, c]));
                    return (
                      <tr key={r.id} className="border-t align-top" data-testid="vault-row">
                        <th scope="row" className="p-2 font-medium break-all">
                          {r.filename}
                          {!r.read_in_full && <span className="block text-xs font-normal text-muted-foreground">{r.coverage_note || "Not read in full."}</span>}
                        </th>
                        {t.columns.map((c) => {
                          const cell = by[c.id];
                          if (!cell) return <td key={c.id} className="p-2" />;
                          return (
                            <td key={c.id} className="p-2" data-testid={`vault-cell-${cell.status}`}>
                              {cell.answer && <p>{cell.answer}</p>}
                              <Badge variant={STATUS_STYLE[cell.status]} title={cell.note}>{STATUS_TEXT[cell.status]}</Badge>
                              {cell.quote && <p className="mt-1 text-xs text-muted-foreground">“{cell.quote}”{cell.page ? `, page ${cell.page}` : ""}</p>}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {t && <p className="mt-2 text-xs text-muted-foreground">{t.note}</p>}
        </section>
      </div>
    </AppShell>
  );
}

export default function Vault() {
  const { id } = useParams();
  return id ? <VaultDetail id={id} /> : <VaultList />;
}
