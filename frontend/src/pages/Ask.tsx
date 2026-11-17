import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, FileUp, Paperclip, RotateCcw, Sparkles, X } from "lucide-react";
import AppShell from "@/components/AppShell";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { Button, buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import AnswerFeedback from "@/components/AnswerFeedback";
import CitationPanel from "@/components/CitationPanel";
import { ListenButton, VoiceInput } from "@/components/Voice";
import { ApiError, apiGet, apiPost, apiUpload } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { PLAIN_CLAIM_KIND, PLAIN_CLAIM_STATUS, TONE_COLOR } from "@/lib/plain";
import type { Claim, DocumentOut, Matter, ResearchResult } from "@/lib/types";
import { useEntitlement } from "@/lib/useMe";

const QUICK_CASE = "My documents (quick questions)";

/**
 * "Ask a question": the simplest way in. One box, one button. The answer says plainly how much of it could be backed up
 * by a real source, and never hides the parts that could not. (Professionals use the full Research page instead.)
 */
export default function Ask() {
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const { t, lang } = useI18n();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [attached, setAttached] = useState<{ name: string; matterId: string } | null>(null);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [limitMessage, setLimitMessage] = useState<string | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const [kind, setKind] = useState<{ route: string } | null>(null);
  useEffect(() => {
    // Instant, free sorting in code (no AI): does this look like money owed, or something to take to a lawyer soon?
    if (question.trim().length < 12) {
      setKind(null);
      return;
    }
    const id = window.setTimeout(() => {
      apiPost<{ route: string }>("/decide/question", { text: question }).then(setKind).catch(() => setKind(null));
    }, 600);
    return () => window.clearTimeout(id);
  }, [question]);
  const { data: ent, refetch: refetchEnt } = useEntitlement();

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const matters = await apiGet<Matter[]>("/matters");
      let id = matters.find((m) => m.title === QUICK_CASE)?.id;
      if (!id) id = (await apiPost<Matter>("/matters", { title: QUICK_CASE, parties: "", description: "Papers you asked about." })).id;
      const doc = await apiUpload<DocumentOut>(`/matters/${id}/documents`, file);
      return { id, doc };
    },
    onSuccess: ({ id, doc }) => {
      setAttached({ name: doc.filename, matterId: id });
      if (doc.processing_status !== "READY") toast.warning(doc.failure_reason ?? "We could not read the words in that file. Try a clearer copy.");
      else toast.success("Paper added. Now ask your question about it.");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const ask = useMutation({
    mutationFn: () => apiPost<ResearchResult>("/research", { question, mode: "STANDARD", matter_id: attached?.matterId ?? null, language: lang }),
    onSuccess: async (r) => {
      setLimitMessage(null);
      setResult(r);
      await qc.invalidateQueries({ queryKey: ["research"] });
      await refetchEnt();
    },
    onMutate: () => setAskError(null),
    onError: (e) => {
      if (e instanceof ApiError && e.status === 402) setLimitMessage(describe(e));
      else {
        setAskError(describe(e)); // stays on the screen (a toast disappears); the question stays in the box
        toast.error(describe(e));
      }
    },
  });

  const left = ent?.ai_limit_today != null ? Math.max(0, ent.ai_limit_today - ent.ai_used_today) : null;
  const busy = ask.isPending || upload.isPending;

  return (
    <AppShell title={t("ask.title")} intensity={busy ? "active" : "ambient"}>
      <div className="mx-auto max-w-3xl">
        <div className="text-center">
          <h2 className="text-3xl md:text-4xl">{t("ask.title")}</h2>
          <p className="mx-auto mt-2 max-w-xl text-base text-muted-foreground">{t("ask.sub")}</p>
        </div>

        {!result && (
          <form
            className="glass mt-8 rounded-2xl p-5 md:p-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim().length >= 3) ask.mutate();
            }}
          >
            <label htmlFor="ask-q" className="text-sm text-muted-foreground">
              {t("ask.label")}
            </label>
            <Textarea
              id="ask-q"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={4}
              className="mt-2 text-base md:text-lg"
              placeholder={t("ask.placeholder")}
              data-testid="ask-input"
            />
            {recoveryOn && kind?.route === "recovery" && (
              <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#C8A96B55] bg-[#C8A96B0F] p-3 text-sm" data-testid="ask-hint-recovery">
                <span className="flex-1">{t("decide.recovery")}</span>
                <Link to="/recovery" className={buttonVariants({ size: "sm" })}>
                  {t("decide.recovery.btn")}
                </Link>
              </div>
            )}
            {kind?.route === "lawyer" && (
              <div className="mt-3 rounded-xl border border-[#F5B35C66] bg-[#F5B35C0F] p-3 text-sm" role="note" data-testid="ask-hint-lawyer">
                {t("decide.urgent")}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload.mutate(f);
                  e.target.value = "";
                }}
                data-testid="ask-file-input"
              />
              {attached ? (
                <span className="inline-flex items-center gap-2 rounded-full border border-primary/40 bg-primary/10 px-3 py-1.5 text-sm" data-testid="ask-attached">
                  <Paperclip className="size-4 text-primary" /> {attached.name}
                  <button type="button" aria-label="Remove this paper" onClick={() => setAttached(null)}>
                    <X className="size-4 text-muted-foreground hover:text-foreground" />
                  </button>
                </span>
              ) : (
                <Button type="button" variant="outline" size="sm" loading={upload.isPending} onClick={() => fileRef.current?.click()}>
                  <FileUp /> {t("ask.paper")}
                </Button>
              )}
              <VoiceInput onText={(w) => setQuestion((q) => (q.trim() ? `${q.trim()} ${w}` : w))} />
              <div className="ml-auto flex items-center gap-3">
                {left !== null && (
                  <span className="text-xs text-muted-foreground" data-testid="ask-left">
                    {t("ask.left", { n: left })}
                  </span>
                )}
                <Button type="submit" size="lg" loading={ask.isPending} disabled={question.trim().length < 3} data-testid="ask-submit">
                  <Sparkles /> {ask.isPending ? t("ask.working") : t("ask.submit")}
                </Button>
              </div>
            </div>
            <div className="mt-5">
              <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t("ask.tryOne")}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(["ask.ex1", "ask.ex2", "ask.ex3"] as const).map((k) => t(k)).map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => setQuestion(q)}
                    className="rounded-full border border-border px-3.5 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </form>
        )}

        {askError && (
          <div className="glass mt-5 rounded-2xl border-primary/40 p-5" role="alert" data-testid="ask-error">
            <p className="text-base">{askError}</p>
            <p className="mt-1 text-sm text-muted-foreground">Your question is still in the box. Press the button to try again.</p>
          </div>
        )}

        {limitMessage && (
          <div className="glass mt-5 rounded-2xl border-primary/40 p-5" role="alert" data-testid="ask-limit">
            <p className="text-base">{limitMessage}</p>
            <Link to="/settings" className={buttonVariants({ className: "mt-3" })}>
              {t("ask.upgrade")}
            </Link>
          </div>
        )}

        {result && <Answer r={result} onAgain={() => { setResult(null); setQuestion(""); }} />}

        <p className="mt-8 text-center text-sm text-muted-foreground">
          {t("ask.disclaimer")}{" "}
          <Link to={result ? `/research?q=${encodeURIComponent(result.question)}` : "/research"} className="underline underline-offset-4" data-testid="ask-go-deeper">
            {t("ask.pro")}
          </Link>
        </p>
      </div>
    </AppShell>
  );
}

function Answer({ r, onAgain }: { r: ResearchResult; onAgain: () => void }) {
  const { t } = useI18n();
  const verified = r.claims.filter((c) => c.verification_status === "VERIFIED").length;
  const total = r.claims.length;
  return (
    <div className="mt-8 space-y-5" data-testid="ask-answer">
      <div className="glass rounded-2xl p-5 md:p-7">
        <p className="text-xs uppercase tracking-[0.25em] text-[#C8A96B]">{t("ask.youAsked")}</p>
        <p className="mt-1 text-lg">{r.question}</p>
        <div className="my-5 h-px bg-border" />
        <p className="text-xs uppercase tracking-[0.25em] text-[#C8A96B]">{t("ask.answer")}</p>
        <p className="mt-2 whitespace-pre-wrap font-serif text-base leading-relaxed md:text-lg" data-testid="ask-answer-text">{r.answer}</p>
      </div>

      <div
        className="rounded-2xl border p-4 text-sm md:text-base"
        style={{ borderColor: verified > 0 ? "#7FE3B055" : "#F5B35C66", background: verified > 0 ? "#7FE3B00F" : "#F5B35C0F" }}
        data-testid="ask-honesty"
      >
        {total === 0
          ? t("ask.honest.general")
          : verified === total
            ? t("ask.honest.all")
            : verified > 0
              ? t("ask.honest.some", { v: verified, t: total })
              : t("ask.honest.none")}
      </div>

      {r.missing_information.length > 0 && (
        <div className="glass rounded-2xl p-5">
          <p className="text-sm font-medium">{t("ask.more")}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground md:text-base">
            {r.missing_information.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {r.contrary_authority.length > 0 && (
        <div className="glass rounded-2xl p-5">
          <p className="text-sm font-medium" style={{ color: "#F5B35C" }}>
            {t("ask.contrary")}
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground md:text-base">
            {r.contrary_authority.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {total > 0 && <CitationPanel claims={r.claims} />}

      {total > 0 && (
        <details className="glass rounded-2xl p-5" data-testid="ask-sources">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
            {t("ask.sources")}
            <ChevronDown className="size-4 text-muted-foreground" />
          </summary>
          <div className="mt-4 space-y-3">
            {r.claims.map((c, n) => (
              <ClaimRow key={c.id} c={c} n={n + 1} />
            ))}
          </div>
        </details>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <ListenButton text={r.answer} />
        <AnswerFeedback answerId={r.id} />
        <Button variant="outline" onClick={onAgain}>
          <RotateCcw /> {t("ask.again")}
        </Button>
        <p className="max-w-md text-xs text-muted-foreground">{r.disclaimer}</p>
      </div>
    </div>
  );
}

function ClaimRow({ c, n }: { c: Claim; n: number }) {
  const s = PLAIN_CLAIM_STATUS[c.verification_status] ?? PLAIN_CLAIM_STATUS.UNSUPPORTED;
  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-sm md:text-base">
        <span className="mr-1.5 text-muted-foreground">{n}.</span>
        {c.text}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full border border-border px-2.5 py-0.5 text-muted-foreground">{PLAIN_CLAIM_KIND[c.claim_kind] ?? c.claim_kind}</span>
        <span className="rounded-full border px-2.5 py-0.5" style={{ color: TONE_COLOR[s.tone], borderColor: `${TONE_COLOR[s.tone]}66` }}>
          {s.label}
        </span>
      </div>
      {c.citations.map((ci, i) => (
        <p key={i} className="mt-2 text-xs text-muted-foreground">
          {ci.doc_label ? `${ci.doc_label}${ci.page ? `, page ${ci.page}` : ""}` : ci.citation}
          {ci.passage ? `: “${ci.passage}”` : ""}
          {ci.passage ? (
            <span className="ml-1.5" style={{ color: ci.quote_verified ? "#5B8CFF" : "#F0A63A" }} data-testid="ask-quote-check">
              {ci.quote_verified ? "(quote found exactly in the source)" : "(quote not found in the source)"}
            </span>
          ) : null}
        </p>
      ))}
      {c.conflicts.map((k, i) => (
        <p key={i} className="mt-2 text-xs" style={{ color: "#F5B35C" }}>
          Another paper says something different ({k.filename}, page {k.page}): “{k.quote}”
        </p>
      ))}
    </div>
  );
}
