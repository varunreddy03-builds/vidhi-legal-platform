import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { JudgmentCard } from "@/components/Judgments";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet } from "@/lib/api";
import { useT } from "@/lib/i18n/I18nProvider";
import type { JudgmentEntry } from "@/lib/types";

const PAGE = 20;

/** High Court judgments from the public dataset (25 High Courts). All of it is "not reviewed" and nothing here verifies an answer. */
export default function Judgments() {
  const t = useT();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [court, setCourt] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [page, setPage] = useState(0);
  const years = `&year_from=${/^\d{4}$/.test(yearFrom) ? yearFrom : 0}&year_to=${/^\d{4}$/.test(yearTo) ? yearTo : 0}`;  // only a full four-digit year counts; anything else means "no limit"
  const courts = useQuery<{ courts: { court_code: string; court_name: string; count: number }[]; attribution: string; note: string }>({ queryKey: ["hc-courts"], queryFn: () => apiGet("/judgments/courts"), staleTime: 300_000 });
  const list = useQuery<{ items: JudgmentEntry[]; total: number; total_is_at_least?: boolean; too_broad?: boolean; unranked?: boolean; note: string; attribution: string }>({
    queryKey: ["judgments", term, court, years, page],
    queryFn: () => apiGet(`/judgments?q=${encodeURIComponent(term)}&court=${encodeURIComponent(court)}${years}&skip=${page * PAGE}&limit=${PAGE}`),
  });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  return (
    <AppShell title={t("nav.judgments")}>
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl md:text-3xl" data-testid="judgments-title">
          {t("nav.judgments")}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="judgments-note">
          Judgments from the public Supreme Court and High Court datasets, for looking things up. No lawyer has compared them with the court&apos;s own copy, and they may have been appealed or set aside. The list covers the Supreme Court from 1971 and the 25 High Courts from 1999, with a smaller number of earlier High Court cases (mostly 1995 to 1998). The text of a judgment is fetched from the public archive when you open it; some court files are missing or are scans.
        </p>
        <form
          className="mt-4 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(0);
            setTerm(q.trim());
          }}
        >
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search judgments, for example: bail or cheque dishonour" aria-label="Search judgments" className="min-w-0 flex-1" data-testid="judgments-search" />
          <select
            value={court}
            onChange={(e) => {
              setCourt(e.target.value);
              setPage(0);
            }}
            aria-label="Court"
            className="h-10 max-w-full rounded-md border border-border bg-background px-2 text-sm"
            data-testid="judgments-court"
          >
            <option value="">All courts</option>
            {(courts.data?.courts ?? []).map((c) => (
              <option key={c.court_code} value={c.court_code}>
                {c.court_name} ({c.count})
              </option>
            ))}
          </select>
          <Input value={yearFrom} onChange={(e) => { setYearFrom(e.target.value); setPage(0); }} inputMode="numeric" maxLength={4} placeholder="From year" aria-label="From year" className="w-24" data-testid="judgments-year-from" />
          <Input value={yearTo} onChange={(e) => { setYearTo(e.target.value); setPage(0); }} inputMode="numeric" maxLength={4} placeholder="To year" aria-label="To year" className="w-24" data-testid="judgments-year-to" />
          <Button type="submit" data-testid="judgments-go">
            Search
          </Button>
        </form>
        {list.isLoading && <p className="mt-4 text-sm text-muted-foreground">Loading…</p>}
        {!list.isLoading && items.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground" data-testid="judgments-empty">
            {list.data?.too_broad ? list.data.note : "Nothing found. Try other words."}
          </p>
        )}
        {list.data?.unranked && (
          <p className="mt-4 text-xs text-muted-foreground" data-testid="judgments-unranked">
            Too many judgments match to rank them by relevance. These are the first matches; add words, a court or a year range to narrow them.
          </p>
        )}
        <ul className="mt-4 space-y-2" data-testid="judgments-list">
          {items.map((j) => (
            <JudgmentCard key={j.id} j={j} />
          ))}
        </ul>
        <div className="mt-4 flex items-center gap-3 text-sm text-muted-foreground">
          <Button type="button" variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span>
            Page {page + 1} ({list.data?.total_is_at_least ? "at least " : ""}{total.toLocaleString()} judgments)
          </span>
          <Button type="button" variant="outline" size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
        <p className="mt-6 text-xs text-muted-foreground">{courts.data?.attribution ?? list.data?.attribution}</p>
      </div>
    </AppShell>
  );
}
