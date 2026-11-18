import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLawDrafts } from "@/lib/useLawDrafts";
import AppShell from "@/components/AppShell";
import { DraftLawCard } from "@/components/DraftLaw";
import ReviewedBy from "@/components/ReviewedBy";
import UnifiedSearchResults from "@/components/UnifiedSearchResults";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet } from "@/lib/api";
import { useT } from "@/lib/i18n/I18nProvider";
import type { DraftLawEntry } from "@/lib/types";

const PAGE = 20;

/** Law library: the official Acts and Rules, cut into provisions. All of it is "not reviewed" until a lawyer approves it, and nothing here verifies an answer. */
export default function Law() {
  const t = useT();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [act, setAct] = useState("");
  const [page, setPage] = useState(0);
  const [onDate, setOnDate] = useState("");
  const acts = useLawDrafts();
  // A typed search across every Act is answered by the one search over the verified library, the law library and the draft text; choosing one Act keeps the browse list for that Act.
  const unified = term.length > 0 && act === "";
  const list = useQuery<{ items: DraftLawEntry[]; total: number | null; note: string }>({
    queryKey: ["drafts", term, act, page],
    queryFn: () => apiGet(`/library/drafts?q=${encodeURIComponent(term)}&act=${encodeURIComponent(act)}&skip=${page * PAGE}&limit=${PAGE}`),
    enabled: !unified,
  });
  const total = list.data?.total;
  const items = list.data?.items ?? [];
  const hasNext = total != null ? (page + 1) * PAGE < total : items.length === PAGE;
  if (acts.data?.enabled === false) {
    return (
      <AppShell title={t("nav.law")}>
        <div className="mx-auto max-w-4xl">
          <h2 className="text-2xl md:text-3xl" data-testid="law-title">
            {t("nav.law")}
          </h2>
          <p className="mt-3 text-sm text-muted-foreground" data-testid="law-off">
            {acts.data.switched_off_note}
          </p>
        </div>
      </AppShell>
    );
  }
  return (
    <AppShell title={t("nav.law")}>
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl md:text-3xl" data-testid="law-title">
          {t("nav.law")}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="law-note">
          {acts.data?.note ?? "Official texts cut into provisions."} Reviewed law is what can make an answer verified; this list is for looking things up.
        </p>
        <ReviewedBy />
        <form
          className="mt-4 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(0);
            setTerm(q.trim());
          }}
        >
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the law, for example: cheating or limitation for a suit" aria-label="Search the law" className="min-w-0 flex-1" data-testid="law-search" />
          <select
            value={act}
            onChange={(e) => {
              setAct(e.target.value);
              setPage(0);
            }}
            aria-label="Act or Rule"
            className="h-10 max-w-full rounded-md border border-border bg-background px-2 text-sm"
            data-testid="law-act"
          >
            <option value="">All Acts and Rules</option>
            {(acts.data?.acts ?? []).map((a) => (
              <option key={a.act_id} value={a.act_id}>
                {a.title} ({a.count}){a.historical ? " - repealed" : ""}
              </option>
            ))}
          </select>
          <Input type="date" value={onDate} onChange={(e) => setOnDate(e.target.value)} aria-label="Check on this date (optional)" title="Check on this date (optional)" className="w-auto" data-testid="law-date" />
          <Button type="submit" data-testid="law-go">
            Search
          </Button>
        </form>
        {unified ? (
          <UnifiedSearchResults term={term} onDate={onDate} />
        ) : (
          <>
            {list.isLoading && <p className="mt-4 text-sm text-muted-foreground">Loading…</p>}
            {!list.isLoading && items.length === 0 && <p className="mt-4 text-sm text-muted-foreground" data-testid="law-empty">Nothing found. Try other words.</p>}
            <ul className="mt-4 space-y-2" data-testid="law-list">
              {items.map((d) => (
                <DraftLawCard key={d.id} d={d} />
              ))}
            </ul>
            <div className="mt-4 flex items-center gap-3 text-sm text-muted-foreground">
              <Button type="button" variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <span>
                Page {page + 1}
                {total != null ? ` of ${Math.max(1, Math.ceil(total / PAGE))} (${total} provisions)` : ""}
              </span>
              <Button type="button" variant="outline" size="sm" disabled={!hasNext} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
