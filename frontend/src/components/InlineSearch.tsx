import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText, Folder, HandCoins, Search, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { apiGet } from "@/lib/api";
import { useT } from "@/lib/i18n/I18nProvider";
import type { SearchResponse } from "@/lib/types";

const ICON: Record<string, typeof Folder> = {
  "Money recoveries": HandCoins,
  "Papers in recoveries": FileText,
  Matters: Folder,
  Documents: FileText,
  Research: Sparkles,
  Drafts: FileText,
};
const PLAIN_GROUP: Record<string, string> = { Matters: "Cases", Research: "Past questions", Drafts: "Drafts" };

/** A search box that works as you type, with simple filter chips, so nobody has to know where something is kept. */
export default function InlineSearch({ autoFocus = false }: { autoFocus?: boolean }) {
  const t = useT();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [only, setOnly] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 220);
    return () => clearTimeout(t);
  }, [q]);

  const { data, isFetching } = useQuery<SearchResponse>({
    queryKey: ["inline-search", debounced],
    queryFn: () => apiGet<SearchResponse>(`/search?q=${encodeURIComponent(debounced)}`),
    enabled: debounced.length >= 2,
  });
  const groups = data?.groups ?? [];
  const shown = only ? groups.filter((g) => g.type === only) : groups;
  const label = (t: string) => PLAIN_GROUP[t] ?? t;

  return (
    <div data-testid="inline-search">
      <div className="relative">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOnly(null);
          }}
          autoFocus={autoFocus}
          placeholder={t("start.search")}
          className="h-14 rounded-2xl pl-12 text-base md:text-lg"
          aria-label={t("search.label")}
          data-testid="inline-search-input"
        />
      </div>
      {debounced.length >= 2 && (
        <div className="mt-3" aria-live="polite">
          {groups.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {[null, ...groups.map((g) => g.type)].map((t) => (
                <button
                  key={t ?? "all"}
                  onClick={() => setOnly(t)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    only === t ? "border-primary bg-primary/15 text-primary" : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t ? label(t) : "Everything"}
                </button>
              ))}
            </div>
          )}
          <div className="space-y-4">
            {shown.map((g) => {
              const Icon = ICON[g.type] ?? Folder;
              return (
                <div key={g.type}>
                  <p className="mb-1 text-xs uppercase tracking-[0.2em] text-muted-foreground">{label(g.type)}</p>
                  <div className="space-y-1.5">
                    {g.items.map((it) => (
                      <Link
                        key={it.id}
                        to={it.href}
                        className="glass flex items-center gap-3 rounded-xl px-4 py-3 text-sm transition-colors hover:border-primary/50"
                        data-testid="inline-search-result"
                      >
                        <Icon className="size-4 shrink-0 text-primary" />
                        <span className="truncate">{it.label}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              );
            })}
            {!isFetching && groups.length === 0 && (
              <div className="glass rounded-xl p-5 text-center text-sm text-muted-foreground" data-testid="inline-search-empty">
                Nothing found for “{debounced}”. Try a different word, or open <Link to="/research" className="text-primary underline underline-offset-4">Research</Link>.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
