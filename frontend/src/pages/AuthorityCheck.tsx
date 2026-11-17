import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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

type Review = { state: "open" | "fix" | "accept_as_is" | "reviewed"; note?: string; by?: string; at?: string };
type Flag = { problem: string; note?: string; at?: string };
const PROBLEMS: [string, string][] = [
  ["says_not_found_but_it_exists", "It says not found or could not check, but the reference is real"],
  ["says_found_but_it_is_wrong", "It says found or confirmed, but the reference is wrong"],
  ["unclear_or_confusing", "I cannot tell why it got this label"],
  ["other", "Something else"],
];
type QuoteResult = { quote: string; result: "QUOTE_FOUND" | "QUOTE_NOT_FOUND" | "QUOTE_NOT_CHECKED"; paragraph: number | null; reason: string };
type Proposition = { state: "may_not_support" | "no_flag" | "not_checked"; note: string; paragraph?: number | null };
type Item = {
  n: number;
  kind: "case" | "statute";
  raw: string;
  page: number;
  sentence: string;
  label: string;
  reason: string;
  differences: string[];
  source_url: string;
  old_code_note: string;
  current_status: string;
  review: Review;
  flagged?: Flag;
  matched_title?: string;
  confirmed?: Record<string, boolean | null | undefined>;
  quotes?: QuoteResult[];
  proposition?: Proposition | null;
};
type Counts = { total: number; cases: number; statutes: number; by_label: Record<string, number>; open: number; old_code_notes: number };
type Report = { id: string; title: string; created_at: string; expires_at?: string; counts: Counts; current_status: string; source: string; source_attribution?: { text: string } | null; items: Item[] };
type Summary = Omit<Report, "items">;

const LABELS: Record<string, string> = {
  FOUND_MATCHES: "Found, details agree",
  DETAILS_DIFFER: "Found, details differ",
  COULD_NOT_CHECK: "Could not check",
  NOT_FOUND_FULL_SEARCH: "Not found after a full search",
  QUOTE_NOT_FOUND: "Case found, quoted words not found",
  MAY_NOT_SUPPORT: "Case found, may not support the point",
  FOUND_REVIEWED: "In reviewed library",
  FOUND_NOT_REVIEWED: "In library, not yet reviewed",
  NOT_IN_REVIEWED_LIBRARY: "Not in reviewed library",
};
const QUOTE_LABELS: Record<string, string> = { QUOTE_FOUND: "Quote found", QUOTE_NOT_FOUND: "Quote not found", QUOTE_NOT_CHECKED: "Quote not checked" };
const STATES: Record<string, string> = { open: "Open", fix: "Marked to fix", accept_as_is: "Accepted as is", reviewed: "Marked reviewed" };

/** What each label means, in plain words (the same meanings the checker uses; none of them says a reference is wrong or that the law is settled). */
const LABEL_HELP: [string, string][] = [
  ["FOUND_MATCHES", "A case was found in the public source and the names, year and court in your draft agree with it. Whether it is still good law is not checked."],
  ["DETAILS_DIFFER", "A case was found but something your draft says differs from the source. The differences are listed. Look at them; they may be a typing slip or a different case."],
  ["COULD_NOT_CHECK", "The check could not be completed with confidence: the source was unavailable, there was more than one possible case, or the citation gave too little to search. This is not a finding that the reference is wrong."],
  ["NOT_FOUND_FULL_SEARCH", "Every search that could be made reached the source and found nothing. Look at the reference yourself before you decide."],
  ["FOUND_REVIEWED", "A section with that number is in VIDHI's library and a lawyer has compared it with the official text. It does not say your draft uses it correctly."],
  ["FOUND_NOT_REVIEWED", "A section with that number is in VIDHI's library but no lawyer has compared it with the official text yet."],
  ["NOT_IN_REVIEWED_LIBRARY", "VIDHI does not hold that provision. That is about VIDHI's library, not about the law: it is not a finding that the citation is wrong."],
  ["QUOTE_NOT_FOUND", "The case was found, but the words you put in quotation marks were not found in its text."],
  ["MAY_NOT_SUPPORT", "The case was found, and the AI suggests you read it again because it may not support the point. Only a caution; you decide."],
];

/** A made-up draft for a first try. Every name, case and Act in it is invented, except the one section named last, so the result shows how the labels look without anyone's real matter. */
const SAMPLE_TITLE = "SAMPLE: reply to a demand notice (fictional)";
const SAMPLE_DRAFT = `SAMPLE DRAFT - FICTIONAL. Every name, case and Act below is invented for practice, except Section 138 of the Negotiable Instruments Act, 1881, which is named only to show how a statute reference is listed.

1. The complaint is not maintainable. In Sunil Rao v. Kulkarni Traders Pvt Ltd, (2019) 4 SCC 111, it was held that a notice sent before the cheque was returned is of no effect.
2. The respondent also relies on Section 12 of the Fictional Sale of Goods Act, 1930, which does not apply to a cheque given as a gift.
3. In Meera Textiles v. Union of Sampleland, 2021 SCC OnLine SC 9001, the Court said "the burden of proof never shifts in a sample case".
4. The complaint under Section 138 of the Negotiable Instruments Act, 1881 is therefore liable to be dismissed.
`;

const NOTICE =
  "This checks what your draft cites. It is not legal advice. “Could not check” and “Not in reviewed library” are not findings that a reference is wrong. Whether a case is still good law is not checked. A lawyer decides.";

/** Authority Check: paste a draft, see every case and section it cites with what could and could not be checked, and record your decision on each. */
export default function AuthorityCheck() {
  const { id } = useParams();
  return (
    <AppShell title="Authority Check">
      <div className={`mx-auto ${id ? "max-w-6xl" : "max-w-3xl"}`}>
        <Link to="/katalyst" className="inline-block py-2 text-xs text-muted-foreground" data-testid="authority-back">
          ← Legal Katalyst
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl" data-testid="authority-title">
          Authority Check
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="authority-notice">
          {NOTICE}
        </p>
        {id ? <ReportView id={id} /> : <Start />}
      </div>
    </AppShell>
  );
}

function Start() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const withSample = params.get("sample") === "1";
  const [title, setTitle] = useState(withSample ? SAMPLE_TITLE : "");
  const [text, setText] = useState(withSample ? SAMPLE_DRAFT : "");
  const [proposition, setProposition] = useState(false);
  const list = useQuery({ queryKey: ["authority"], queryFn: () => apiGet<Summary[]>("/authority/checks"), retry: false });
  const run = useMutation({
    mutationFn: () => apiPost<Report>("/authority/checks", { title: title.trim() || "Untitled draft", text, proposition_check: proposition }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["authority"] });
      navigate(`/katalyst/authority/${r.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (list.error instanceof ApiError && list.error.status === 404) {
    return (
      <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="authority-off">
        Authority Check is not switched on for this server.
      </p>
    );
  }
  return (
    <>
      <form
        className="glass mt-6 space-y-3 rounded-2xl p-5"
        data-testid="authority-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) run.mutate();
        }}
      >
        <div>
          <Label htmlFor="ac-title">Name of the draft</Label>
          <Input id="ac-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} data-testid="authority-title-input" />
        </div>
        <div>
          <Label htmlFor="ac-text">Paste the draft</Label>
          <textarea
            id="ac-text"
            value={text}
            rows={9}
            maxLength={300000}
            onChange={(e) => setText(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
            data-testid="authority-text-input"
          />
          <p className="mt-1 text-xs text-muted-foreground">Up to 40 references in one check. Text only for now: paste the draft here.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => {
              setTitle(SAMPLE_TITLE);
              setText(SAMPLE_DRAFT);
            }}
            data-testid="authority-use-sample"
          >
            No draft handy? Use a made-up sample
          </Button>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={proposition} onChange={(e) => setProposition(e.target.checked)} className="mt-1" data-testid="authority-proposition" />
          <span>
            Also ask the AI to look for points a case may not support. It can only add a “may not support, please read” caution. It never confirms that a case supports a point, and it uses one of your AI requests.
          </span>
        </label>
        <Button type="submit" disabled={run.isPending || !text.trim()} data-testid="authority-run">
          {run.isPending ? "Checking…" : "Check this draft"}
        </Button>
      </form>
      <div className="glass mt-4 space-y-2 rounded-2xl p-5" data-testid="authority-file-card">
        <h3 className="text-sm font-medium">Or check a file</h3>
        <p className="text-xs text-muted-foreground">PDF, Word or text. The file is read and then dropped: only the report is kept. Uses the name and the AI option above.</p>
        <FileDrop<Report>
          path="/authority/checks/file"
          accept=".pdf,.docx,.txt,.md"
          fields={{ title: title.trim(), proposition_check: proposition ? "true" : "false" }}
          idleLabel="Choose a draft to check"
          testId="authority-file"
          onDone={async (r) => {
            await qc.invalidateQueries({ queryKey: ["authority"] });
            navigate(`/katalyst/authority/${r.id}`);
          }}
        />
      </div>
      <h3 className="mt-8 text-sm uppercase tracking-wider text-muted-foreground">Earlier checks</h3>
      <ul className="mt-3 space-y-2" data-testid="authority-list">
        {(list.data ?? []).map((r) => (
          <li key={r.id}>
            <Link to={`/katalyst/authority/${r.id}`} className="glass flex items-center justify-between gap-3 rounded-lg p-4" data-testid="authority-row">
              <span className="min-w-0">
                <span className="block truncate text-sm">{r.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {r.counts.total} references · {r.counts.open} open
                </span>
              </span>
            </Link>
          </li>
        ))}
        {list.data && list.data.length === 0 && <li className="text-sm text-muted-foreground">No checks yet.</li>}
      </ul>
    </>
  );
}

const CONFIRMED_LINES: [string, string][] = [
  ["names", "Parties"],
  ["year", "Year"],
  ["court", "Court"],
  ["neutral", "Neutral citation"],
  ["report", "Report citation (SCC, AIR …)"],
];

function ReportView({ id }: { id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["authority", id], queryFn: () => apiGet<Report>(`/authority/checks/${id}`), retry: false });
  const remove = useMutation({
    mutationFn: () => apiDelete(`/authority/checks/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["authority"] });
      navigate("/katalyst/authority");
    },
    onError: (e) => toast.error(describe(e)),
  });
  // On a laptop both panes show, with the first reference open. On a phone one pane shows: the list, or the open reference with a Back button.
  const [open, setOpen] = useState<number | null>(null);
  const detail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open !== null) detail.current?.focus();
  }, [open]);
  if (q.isLoading) return <p className="mt-6 text-sm text-muted-foreground">Loading…</p>;
  if (!q.data) return <p className="mt-6 text-sm">This report could not be opened.</p>;
  const r = q.data;
  const shown = r.items.find((i) => i.n === open) ?? r.items[0];
  return (
    <div className="mt-6" data-testid="authority-report">
      <h3 className="text-lg">{r.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground" data-testid="authority-summary">
        {r.counts.total} references ({r.counts.cases} cases, {r.counts.statutes} statutes) · {r.counts.open} still open
        {Object.entries(r.counts.by_label).map(([k, v]) => ` · ${LABELS[k] ?? k}: ${v}`)}
      </p>
      <p className="mt-1 text-xs text-muted-foreground" data-testid="authority-current-status">
        For every case, {r.current_status}.
      </p>
      <details className="mt-2 text-sm" data-testid="authority-legend">
        <summary className="cursor-pointer py-2 underline underline-offset-4">What do these labels mean?</summary>
        <dl className="mt-1 space-y-2">
          {LABEL_HELP.map(([k, text]) => (
            <div key={k}>
              <dt className="font-medium">{LABELS[k]}</dt>
              <dd className="text-muted-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      </details>
      {r.expires_at && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="authority-kept">
          Kept until {r.expires_at.slice(0, 10)}, then deleted automatically. Download the Word or PDF copy to keep it.
        </p>
      )}
      {r.source_attribution?.text && (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="authority-source">
          {r.source_attribution.text}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/authority/checks/${r.id}/export?format=docx`, "authority-check.docx")} data-testid="authority-export-docx">
          Download Word
        </Button>
        <Button size="sm" variant="outline" onClick={() => openApiFile(`/authority/checks/${r.id}/export?format=pdf`, "authority-check.pdf")} data-testid="authority-export-pdf">
          Download PDF
        </Button>
        <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()} data-testid="authority-delete">
          Delete this check
        </Button>
      </div>
      {r.items.length === 0 && <p className="mt-6 text-sm text-muted-foreground">No cases or sections were found in this draft.</p>}
      {shown && (
        <div className="mt-5 md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] md:gap-6">
          <section aria-label="Your draft" className={open !== null ? "hidden md:block" : ""}>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">Your draft</h4>
            <ul className="space-y-2" data-testid="authority-list-pane">
              {r.items.map((i) => (
                <li key={i.n}>
                  <button
                    type="button"
                    onClick={() => setOpen(i.n)}
                    aria-current={shown.n === i.n ? "true" : undefined}
                    className={`glass w-full rounded-lg p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring ${shown.n === i.n ? "border border-foreground/60" : "border border-transparent"}`}
                    data-testid="authority-ref"
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-border px-2 py-0.5 text-[11px]" data-testid="authority-ref-label">
                        {LABELS[i.label] ?? i.label}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {i.kind === "case" ? "Case" : "Statute"} · page {i.page}
                      </span>
                      <span className="ml-auto text-xs text-muted-foreground" data-testid="authority-ref-state">
                        {STATES[i.review.state]}
                      </span>
                    </span>
                    <span className="mt-1 block break-words text-sm font-medium">{i.raw}</span>
                    {i.sentence && <span className="mt-1 line-clamp-3 block break-words text-xs italic text-muted-foreground">“{i.sentence}”</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section aria-label="What the source shows" className={open === null ? "hidden md:block" : ""}>
            <div ref={detail} tabIndex={-1} className="outline-none" data-testid="authority-detail">
              <Button size="sm" variant="ghost" className="mb-2 md:hidden" onClick={() => setOpen(null)} data-testid="authority-back-to-list">
                ← All references
              </Button>
              <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">What the source shows</h4>
              <ItemCard key={`${r.id}-${shown.n}`} reportId={r.id} item={shown} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function ItemCard({ reportId, item }: { reportId: string; item: Item }) {
  const qc = useQueryClient();
  const [fixing, setFixing] = useState(false);
  const [note, setNote] = useState("");
  const review = useMutation({
    mutationFn: (b: { action: string; note?: string }) => apiPost<Report>(`/authority/checks/${reportId}/items/${item.n}/review`, b),
    onSuccess: (r) => {
      qc.setQueryData(["authority", reportId], r);
      setFixing(false);
    },
    onError: (e) => toast.error(describe(e)),
  });
  const [flagging, setFlagging] = useState(false);
  const [problem, setProblem] = useState(item.flagged?.problem ?? "");
  const [flagNote, setFlagNote] = useState(item.flagged?.note ?? "");
  const flag = useMutation({
    mutationFn: () => apiPost<Report>(`/authority/checks/${reportId}/items/${item.n}/flag`, { problem, note: flagNote }),
    onSuccess: (r) => {
      qc.setQueryData(["authority", reportId], r);
      setFlagging(false);
      toast.success("Thank you: this result was marked for the people building the tool.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const st = item.review.state;
  return (
    <li className="glass rounded-xl p-4" data-testid="authority-item" aria-label="Reference details">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-border px-2 py-0.5 text-[11px]" data-testid="authority-item-label">
          {LABELS[item.label] ?? item.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {item.kind === "case" ? "Case" : "Statute"} · page {item.page}
        </span>
        <span className="ml-auto text-xs text-muted-foreground" data-testid="authority-item-state">
          {STATES[st]}
          {item.review.by ? ` by ${item.review.by}` : ""}
        </span>
      </div>
      <div className="md:hidden">
        <p className="mt-2 break-words text-sm font-medium">{item.raw}</p>
        {item.sentence && <p className="mt-1 break-words text-xs italic text-muted-foreground">“{item.sentence}”</p>}
      </div>
      <p className="mt-2 text-sm text-muted-foreground" data-testid="authority-item-reason">
        {item.reason}
      </p>
      {item.matched_title && (
        <div className="mt-2 text-sm" data-testid="authority-source-facts">
          <p>
            <span className="text-muted-foreground">Case found at the source:</span> {item.matched_title}
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
            {CONFIRMED_LINES.map(([k, name]) => {
              const v = item.confirmed?.[k];
              if (v === undefined) return null;
              return (
                <li key={k}>
                  {name}: {v === true ? "agrees with the draft" : v === false ? "differs from the draft" : "the source does not show this"}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {item.differences.map((d) => (
        <p key={d} className="mt-1 text-sm">
          Difference: {d}
        </p>
      ))}
      {(item.quotes ?? []).map((q, k) => (
        <p key={k} className="mt-1 break-words text-sm" data-testid="authority-quote">
          <span className="font-medium">{QUOTE_LABELS[q.result]}:</span> “{q.quote.length > 140 ? `${q.quote.slice(0, 140)}…` : q.quote}”. {q.reason}
        </p>
      ))}
      {item.proposition && item.proposition.state !== "not_checked" && (
        <p className="mt-1 text-sm text-muted-foreground" data-testid="authority-proposition-note">
          {item.proposition.note}
        </p>
      )}
      {item.old_code_note && <p className="mt-1 text-sm text-muted-foreground">{item.old_code_note}</p>}
      {item.source_url && (
        <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-sm underline" data-testid="authority-source-link">
          Open the source
        </a>
      )}
      {item.review.note && <p className="mt-1 text-xs">Note: {item.review.note}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="xs" variant="outline" disabled={review.isPending} onClick={() => setFixing((v) => !v)} data-testid="authority-fix">
          Fix
        </Button>
        <Button size="xs" variant="outline" disabled={review.isPending} onClick={() => review.mutate({ action: "accept_as_is" })} data-testid="authority-accept">
          Accept as is
        </Button>
        <Button size="xs" variant="outline" disabled={review.isPending} onClick={() => review.mutate({ action: "reviewed" })} data-testid="authority-reviewed">
          Mark reviewed
        </Button>
      </div>
      <div className="mt-3 border-t border-border pt-3" data-testid="authority-flag-block">
        {item.flagged && !flagging && (
          <p className="text-xs text-muted-foreground" data-testid="authority-flagged">
            You marked this result as wrong or unclear: {PROBLEMS.find(([v]) => v === item.flagged?.problem)?.[1] ?? item.flagged.problem}
            {item.flagged.note ? ` (${item.flagged.note})` : ""}
          </p>
        )}
        <Button size="xs" variant="ghost" onClick={() => setFlagging((v) => !v)} data-testid="authority-flag">
          {item.flagged ? "Change my mark" : "This result is wrong or unclear"}
        </Button>
        {flagging && (
          <form
            className="mt-2 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (problem) flag.mutate();
            }}
          >
            <fieldset className="space-y-1">
              <legend className="sr-only">What is wrong</legend>
              {PROBLEMS.map(([v, label]) => (
                <label key={v} className="flex min-h-9 items-start gap-2 text-sm">
                  <input type="radio" name={`flag-${item.n}`} className="mt-1 size-4" checked={problem === v} onChange={() => setProblem(v)} data-testid={`authority-flag-${v}`} />
                  {label}
                </label>
              ))}
            </fieldset>
            <Input value={flagNote} maxLength={500} placeholder="A short note (optional): what should it say?" onChange={(e) => setFlagNote(e.target.value)} data-testid="authority-flag-note" />
            <Button type="submit" size="sm" disabled={!problem || flag.isPending} data-testid="authority-flag-save">
              Send
            </Button>
          </form>
        )}
      </div>
      {fixing && (
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) review.mutate({ action: "fix", note });
          }}
        >
          <Input value={note} maxLength={500} placeholder="What must be fixed, or the corrected reference" onChange={(e) => setNote(e.target.value)} data-testid="authority-fix-note" />
          <Button type="submit" size="sm" disabled={review.isPending || !note.trim()} data-testid="authority-fix-save">
            Save
          </Button>
        </form>
      )}
    </li>
  );
}
