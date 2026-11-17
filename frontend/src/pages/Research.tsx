import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiGet, apiPost } from "@/lib/api";
import { formatDate } from "@/lib/format";
import AnswerFeedback from "@/components/AnswerFeedback";
import DraftLaw from "@/components/DraftLaw";
import Judgments from "@/components/Judgments";
import type { Claim, LibraryStatus, Matter, ResearchResult, VerifyResult } from "@/lib/types";
import { describe } from "@/lib/interaction";

const MODES: Record<string, string> = {
  QUICK: "Quick",
  STANDARD: "Standard",
  MATTER: "Matter",
  DEEP: "Deep research",
};

const STATUS_COLOR: Record<string, string> = {
  VERIFIED: "#5B8CFF",
  PARTIALLY_VERIFIED: "#C8A96B",
  UNSUPPORTED: "#F0A63A",
  UNVERIFIED: "#F0A63A",
  UNAVAILABLE: "#E0604D",
};

const KIND_LABEL: Record<string, string> = {
  LEGAL: "Law",
  FACTUAL: "Fact in the file",
  PROCEDURAL: "Suggested step",
  ABSENCE: "Not in the file",
};

export default function Research() {
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [mode, setMode] = useState(params.get("mode") === "DEEP" ? "DEEP" : "STANDARD");
  const [matterId, setMatterId] = useState(params.get("matter") ?? "none");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [selected, setSelected] = useState<Claim | null>(null);
  const [citation, setCitation] = useState("");
  const [verify, setVerify] = useState<VerifyResult | null>(null);

  const matters = useQuery<Matter[]>({
    queryKey: ["matters"],
    queryFn: () => apiGet<Matter[]>("/matters"),
  });
  const history = useQuery<ResearchResult[]>({
    queryKey: ["research"],
    queryFn: () => apiGet<ResearchResult[]>("/research"),
  });
  const library = useQuery<LibraryStatus>({
    queryKey: ["library"],
    queryFn: () => apiGet<LibraryStatus>("/library"),
    staleTime: 60_000,
  });

  const ask = useMutation({
    mutationFn: () =>
      apiPost<ResearchResult>("/research", {
        question,
        mode,
        matter_id: matterId === "none" ? null : matterId,
      }),
    onSuccess: async (r) => {
      setResult(r);
      setSelected(r.claims[0] ?? null);
      await qc.invalidateQueries({ queryKey: ["research"] });
      await qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e) => toast.error(describe(e)),
  });

  const verifyMutation = useMutation({
    mutationFn: () => apiPost<VerifyResult>("/verify-citation", { citation, jurisdiction_id: "IN" }),
    onSuccess: (v) => setVerify(v),
    onError: (e) => toast.error(describe(e)),
  });

  const busy = ask.isPending || verifyMutation.isPending;
  const cov = result?.coverage;

  return (
    <AppShell title="Research" intensity={busy ? "active" : "ambient"}>
      <div className="mx-auto max-w-6xl">
        <form
          className="glass rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault();
            ask.mutate();
          }}
          data-testid="research-form"
        >
          <Label htmlFor="q">Research question (English or हिंदी)</Label>
          <Textarea
            id="q"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            rows={3}
            className="mt-1.5"
            placeholder="Type your research question"
            aria-describedby="q-hint"
            data-testid="research-question-input"
          />
          <p id="q-hint" className="mt-1.5 text-xs text-muted-foreground">
            Example: Is there a WhatsApp chat in the matter file, and who is the person named in it?
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div className="w-44 space-y-1.5">
              <Label>Mode</Label>
              <Select value={mode} onValueChange={(v: string) => setMode(v)}>
                <SelectTrigger data-testid="research-mode-select" aria-label="Mode">
                  <SelectValue>{(v) => MODES[v as string] ?? "Standard"}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.keys(MODES).map((m) => (
                    <SelectItem key={m} value={m}>
                      {MODES[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-60 space-y-1.5">
              <Label>Matter context</Label>
              <Select value={matterId} onValueChange={(v: string) => setMatterId(v)}>
                <SelectTrigger data-testid="research-matter-select" aria-label="Matter context">
                  <SelectValue>
                    {(v) =>
                      v === "none"
                        ? "No matter"
                        : ((matters.data ?? []).find((m) => m.id === v)?.title ?? "No matter")
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No matter</SelectItem>
                  {(matters.data ?? []).map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={ask.isPending} data-testid="research-submit-button">
              {ask.isPending ? "Researching…" : "Run research"}
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground" data-testid="library-status">
            {library.data
              ? library.data.count > 0
                ? `Verified law library: ${library.data.count} source${library.data.count === 1 ? "" : "s"}. Only these can make a legal claim verified.`
                : library.data.note
              : ""}
          </p>
        </form>

        {/* two columns on a laptop (answer and sources); the memory list joins as a third only on a wide screen, where there is room for all three */}
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[200px_minmax(0,1fr)_300px]">
          <aside aria-label="Research memory" className="order-last space-y-2 lg:col-span-2 2xl:order-none 2xl:col-span-1">
            <h2 className="text-xs uppercase tracking-wider text-muted-foreground">
              Research memory
            </h2>
            {(history.data ?? []).slice(0, 12).map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  setResult(r);
                  setSelected(r.claims[0] ?? null);
                }}
                className="glass w-full truncate rounded-md p-2 text-left text-xs transition-colors hover:bg-accent"
                data-testid="research-history-item"
              >
                {r.question}
              </button>
            ))}
            {(history.data ?? []).length === 0 && (
              <p className="text-xs text-muted-foreground">No prior questions in this matter.</p>
            )}
          </aside>

          <section className="glass min-h-[220px] min-w-0 rounded-lg p-5" data-testid="research-answer">
            {ask.isPending && <div className="h-24 rounded vidhi-sweep" />}
            {!ask.isPending && !result && (
              <p className="text-sm text-muted-foreground">
                Ask a question to get a source-grounded answer. Every claim is checked against the exact
                words of your documents or the verified law library; anything that cannot be checked is
                marked UNSUPPORTED — never presented as authority.
              </p>
            )}
            {result && !ask.isPending && (
              <div className="space-y-4">
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">
                    Direct answer · {result.mode} · {result.capabilities_used.join(" + ")}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap font-serif text-[15px] leading-relaxed" data-testid="research-answer-text">{result.answer}</p>
              <div className="mt-3">
                <AnswerFeedback answerId={result.id} />
              </div>
                </div>

                {cov?.summary && (
                  <p
                    className="rounded-md border px-3 py-2 text-xs"
                    style={{
                      borderColor: cov.complete ? "#5B8CFF55" : "#F0A63A66",
                      color: cov.complete ? "#5B8CFF" : "#F0A63A",
                    }}
                    data-testid="coverage-line"
                  >
                    {cov.complete ? "Whole matter read. " : "Not everything was read. "}
                    {cov.summary}
                  </p>
                )}

                {result.missing_information.length > 0 && (
                  <div data-testid="missing-information">
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">
                      Information that would help
                    </p>
                    <ul className="mt-1.5 list-disc pl-5 text-sm">
                      {result.missing_information.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.unresolved_evidence.length > 0 && (
                  <div data-testid="unresolved-evidence">
                    <p className="text-xs uppercase tracking-wider" style={{ color: "#F0A63A" }}>
                      Evidence not yet matched to anyone
                    </p>
                    <ul className="mt-1.5 list-disc pl-5 text-sm">
                      {result.unresolved_evidence.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.unverified_references.length > 0 && (
                  <p className="text-xs" style={{ color: "#F0A63A" }} data-testid="unverified-references">
                    The wording mentions {result.unverified_references.join("; ")} — not in the verified law
                    library, so not verified. Check it in the official source.
                  </p>
                )}

                <DraftLaw items={result.draft_law ?? []} />
                <Judgments items={result.judgments ?? []} />

                {result.claims.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-wider text-muted-foreground">Claims</p>
                    <div className="mt-2 space-y-2">
                      {result.claims.map((c, n) => (
                        <button
                          key={c.id}
                          onClick={() => setSelected(c)}
                          className="w-full rounded-md border border-border p-3 text-left transition-colors hover:bg-accent"
                          data-testid="research-claim"
                        >
                          <p className="text-sm">
                            <span className="mr-1.5 text-muted-foreground" data-testid="claim-number">{n + 1}.</span>
                            {c.text}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="text-muted-foreground">
                              {KIND_LABEL[c.claim_kind] ?? c.claim_kind}
                            </Badge>
                            <Badge
                              variant="outline"
                              style={{ color: STATUS_COLOR[c.verification_status] }}
                            >
                              {c.verification_status}
                            </Badge>
                            {c.human_review_required && (
                              <span className="text-xs" style={{ color: "#F0A63A" }}>
                                HUMAN REVIEW REQUIRED
                              </span>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {result.contrary_authority.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-wider" style={{ color: "#F0A63A" }}>
                      Contrary authority
                    </p>
                    <ul className="mt-1.5 list-disc pl-5 text-sm">
                      {result.contrary_authority.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.uncertainty && (
                  <p className="text-xs text-muted-foreground">
                    Uncertainty: {result.uncertainty}
                  </p>
                )}
                {result.neutral_adjusted && (
                  <p className="text-xs text-muted-foreground">
                    Some wording that judged a person&apos;s honesty was removed. VIDHI flags differences
                    between sources; it does not decide who is truthful — lawyers do.
                  </p>
                )}
                <p className="text-xs text-muted-foreground">{result.disclaimer}</p>
              </div>
            )}
          </section>

          <aside aria-label="Sources and verification" className="space-y-4">
            <div className="glass rounded-lg p-4" data-testid="source-panel">
              <h2 className="text-xs uppercase tracking-wider text-muted-foreground">
                Sources &amp; verification
              </h2>
              {!selected && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Select a claim to inspect its sources.
                </p>
              )}
              {selected && (
                <p className="mt-2 text-xs" style={{ color: STATUS_COLOR[selected.verification_status] }} data-testid="claim-note">
                  {selected.note}
                </p>
              )}
              {selected?.citations.length === 0 && (
                <p className="mt-2 text-xs" style={{ color: "#F0A63A" }}>
                  No source cited — this claim needs human verification.
                </p>
              )}
              {selected?.citations.map((c, i) => (
                <div key={i} className="mt-3 rounded border border-border p-3" data-testid="source-card">
                  <p className="text-sm">{c.citation || "(untitled source)"}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {c.library_id ? "Verified law library" : (c.doc_label ?? c.authority_level)}
                    {c.page ? ` · page ${c.page}` : ""}
                  </p>
                  <p className="mt-1 text-xs" style={{ color: c.quote_verified ? "#5B8CFF" : "#F0A63A" }}>
                    {c.quote_verified ? "Quote found exactly in the source" : "Quote NOT found in the source"}
                  </p>
                  {c.passage && (
                    <p className="mt-2 text-xs text-muted-foreground">“{c.passage}”</p>
                  )}
                </div>
              ))}
              {selected && selected.conflicts.length > 0 && (
                <div className="mt-3 rounded border p-3" style={{ borderColor: "#F0A63A66" }} data-testid="claim-conflicts">
                  <p className="text-xs" style={{ color: "#F0A63A" }}>
                    Another document says something different
                  </p>
                  {selected.conflicts.map((k, i) => (
                    <p key={i} className="mt-1 text-xs text-muted-foreground">
                      {k.doc_label} {k.filename}, page {k.page}: “{k.quote}”
                    </p>
                  ))}
                </div>
              )}
            </div>

            <div className="glass rounded-lg p-4">
              <h2 className="text-xs uppercase tracking-wider text-muted-foreground">
                Verify citation
              </h2>
              <form
                className="mt-2 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  verifyMutation.mutate();
                }}
              >
                <Input
                  value={citation}
                  onChange={(e) => setCitation(e.target.value)}
                  required
                  placeholder="Type a citation"
                  aria-label="Citation to check"
                  aria-describedby="cite-hint"
                  data-testid="verify-citation-input"
                />
                <p id="cite-hint" className="text-xs text-muted-foreground">
                  Example: Section 138, Negotiable Instruments Act
                </p>
                <Button
                  type="submit"
                  size="sm"
                  className="w-full"
                  disabled={verifyMutation.isPending}
                  data-testid="verify-citation-button"
                >
                  {verifyMutation.isPending ? "Checking…" : "Check the library"}
                </Button>
              </form>
              {verify && (
                <div className="mt-3 space-y-1" data-testid="verify-result">
                  <p className="text-xs" style={{ color: STATUS_COLOR[verify.verification_status] }}>
                    {verify.verification_status === "VERIFIED"
                      ? "FOUND IN THE VERIFIED LIBRARY"
                      : "NOT VERIFIED — not in the library"}
                  </p>
                  {verify.checks.map((c) => (
                    <p key={c.label} className="text-xs text-muted-foreground">
                      {c.status === "PASS" ? "✓" : c.status === "FAIL" ? "✕" : "–"} {c.label}
                      {c.status === "UNKNOWN" ? " — not assessed" : ""}
                    </p>
                  ))}
                  {verify.source_text && (
                    <div className="mt-2 rounded border border-border p-2" data-testid="verify-source-text">
                      <p className="text-xs">{verify.normalized_citation}</p>
                      <p className="mt-1 text-xs text-muted-foreground">“{verify.source_text}”</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {verify.source_name} · {verify.version} · verified by {verify.verified_by} on{" "}
                        {formatDate(verify.verified_on)}
                      </p>
                    </div>
                  )}
                  {verify.suggestions.length > 0 && (
                    <div className="text-xs text-muted-foreground">
                      Did you mean:
                      <ul className="list-disc pl-4">
                        {verify.suggestions.map((s) => (
                          <li key={s.id}>
                            <button className="underline" onClick={() => setCitation(s.citation)} type="button">
                              {s.citation}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {verify.notes && (
                    <p className="pt-1 text-xs text-muted-foreground" data-testid="verify-notes">
                      {verify.notes}
                    </p>
                  )}
                  <p className="pt-1 text-xs" style={{ color: "#F0A63A" }}>
                    HUMAN REVIEW REQUIRED
                  </p>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
