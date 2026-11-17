import { useEffect } from "react";
import { formatDate } from "@/lib/format";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { guideStrings } from "@/lib/recovery/guideStrings";
import { useRecoveryMode } from "@/lib/recovery/useRecoveryMode";
import type { RecoveryCase } from "@/lib/types";

const STEP_LABEL: Record<string, string> = {
  DRAFT: "Just started",
  PROOF_ADDED: "Proof added",
  TIMELINE_READY: "We understood it",
  NOTICE_READY: "Notice ready",
  SENT_FOR_REVIEW: "With a lawyer",
  RESOLVED: "Resolved",
};

const STEP_INDEX: Record<string, number> = {
  DRAFT: 0,
  PROOF_ADDED: 1,
  TIMELINE_READY: 2,
  NOTICE_READY: 3,
  SENT_FOR_REVIEW: 4,
  RESOLVED: 5,
};

/** Legal Recovery's front page. Every new recovery starts in the guide (free government portal first, legal notice next); there is no one-step "send a notice" button. */
export default function RecoveryDashboard() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const g = guideStrings(lang);
  const [params] = useSearchParams();
  const { full } = useRecoveryMode(); // off: one plain list of claims, each opening the guide
  useEffect(() => {
    if (params.get("new") === "1") navigate("/recovery/guide", { replace: true }); // the old address that opened the one-step form now opens the guide
  }, [params, navigate]);

  const cases = useQuery<RecoveryCase[]>({
    queryKey: ["recovery-cases"],
    queryFn: () => apiGet<RecoveryCase[]>("/recovery/cases"),
  });
  const previews = useQuery<{ case_id: string; summary: string; next_date: string | null }[]>({
    queryKey: ["statement-previews"],
    enabled: full,
    queryFn: () =>
      apiGet<{ case_id: string; summary: string; next_date: string | null }[]>(
        "/recovery/statement-previews",
      ),
  });
  const previewMap = new Map((previews.data ?? []).map((p) => [p.case_id, p]));
  const recoveryCases = cases.isError ? [] : cases.data ?? [];
  const listed = recoveryCases.filter((c) => !full || c.status !== "RESOLVED");
  const stageLabel = (c: RecoveryCase) => {
    const s = c.guide?.stage;
    return s && s !== "NOT_STARTED" ? g.status[s] : STEP_LABEL[c.status];
  };

  return (
    <AppShell title="Legal Recovery">
      <div className="mx-auto max-w-4xl">
        <div className="glass rounded-2xl p-6 md:p-8" data-testid="recovery-hero">
          <span
            className="rounded-full border px-2 py-0.5 text-xs uppercase tracking-wider"
            style={{ color: "#C8A96B", borderColor: "#C8A96B55" }}
          >
            Free · No lawyer needed to start
          </span>
          <h2 className="mt-4 text-2xl md:text-3xl">Recover money you&apos;re owed</h2>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">{g.sub}</p>
          <p className="mt-2 text-sm font-medium" data-testid="recovery-tagline">
            {g.tagline}
          </p>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            {full ? "A few simple questions first, then the free government route if it fits, then a legal notice, then a lawyer if you still need one. Plain language. No jargon." : g.smallIntro}
          </p>
          <Button className="mt-5" size="lg" onClick={() => navigate("/recovery/guide")} data-testid="start-recovery-button">
            {g.newGuide}
          </Button>
          <p className="mt-3 text-xs text-muted-foreground">{g.disclaimer}</p>
        </div>

        <h3 className="mt-10 font-heading text-sm uppercase tracking-wider text-muted-foreground">
          {full ? "Active recoveries" : g.claims}
        </h3>
        {cases.isError && (
          <div
            className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber/30 bg-amber/10 p-4 text-sm"
            role="alert"
            data-testid="recovery-load-error"
          >
            <span>Could not load your recoveries. Your saved cases have not changed.</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => cases.refetch()}
              disabled={cases.isFetching}
              data-testid="retry-recoveries-button"
            >
              {cases.isFetching ? "Retrying…" : "Retry"}
            </Button>
          </div>
        )}
        <div className="mt-3 space-y-2">
          {cases.isLoading && <div className="glass h-16 rounded-lg vidhi-sweep" />}
          {listed.map((c) => (
            <Link
              key={c.id}
              to={!full || c.guide?.stage ? `/recovery/guide/${c.id}` : `/recovery/cases/${c.id}`}
              className="glass flex items-center justify-between gap-3 rounded-lg p-4 transition-transform duration-200 hover:translate-x-1"
              data-testid="recovery-case-row"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {c.creditor_name} → {c.debtor_name}
                </p>
                <p className="text-xs text-muted-foreground">
                  ₹{(c.amount || c.detected_amount || 0).toLocaleString("en-IN")}
                  {full && <> · step {Math.min(STEP_INDEX[c.status] + 1, 5)} of 5</>}
                </p>
                {!full && c.guide?.tracker?.next_date && (
                  <p className="mt-0.5 text-xs text-muted-foreground" data-testid="case-next-date">
                    {g.nextDate}: {formatDate(c.guide.tracker.next_date)}
                  </p>
                )}
                {full && previewMap.get(c.id)?.next_date && (
                  <p
                    className="mt-0.5 text-xs"
                    style={{ color: "#5B8CFF" }}
                    data-testid="case-next-statement"
                  >
                    Next statement:{" "}
                    {formatDate(previewMap.get(c.id)!.next_date!)}
                  </p>
                )}
                {full && (
                  <div className="mt-2 h-1 w-40 max-w-full overflow-hidden rounded-full bg-border">
                    <div className="h-full rounded-full" style={{ width: `${(STEP_INDEX[c.status] / 5) * 100}%`, background: "#C8A96B" }} />
                  </div>
                )}
              </div>
              <Badge variant="outline" style={{ color: "#C8A96B" }} data-testid="recovery-case-stage">
                {stageLabel(c)}
              </Badge>
            </Link>
          ))}
          {!cases.isLoading &&
            !cases.isError &&
            listed.length === 0 && (
              <div className="glass rounded-lg p-10 text-center">
                <p className="text-sm text-muted-foreground">
                  {full ? "No active recoveries. Starting one takes under a minute." : g.noClaims}
                </p>
              </div>
            )}
        </div>

        {full && recoveryCases.some((c) => c.status === "RESOLVED") && (
          <>
            <h3 className="mt-8 font-heading text-sm uppercase tracking-wider text-muted-foreground">
              Resolved
            </h3>
            <div className="mt-3 space-y-2">
              {recoveryCases
                .filter((c) => c.status === "RESOLVED")
                .map((c) => (
                  <Link
                    key={c.id}
                    to={`/recovery/cases/${c.id}`}
                    className="glass flex items-center justify-between gap-3 rounded-lg p-4 opacity-70"
                    data-testid="recovery-resolved-row"
                  >
                    <p className="truncate text-sm">
                      {c.creditor_name} → {c.debtor_name}
                    </p>
                    <Badge variant="outline" style={{ color: "#5B8CFF" }}>
                      Paid / Resolved
                    </Badge>
                  </Link>
                ))}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
