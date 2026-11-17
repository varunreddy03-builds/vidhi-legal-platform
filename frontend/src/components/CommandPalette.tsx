import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface Command {
  label: string;
  href: string;
}

const COMMANDS: Command[] = [
  { label: "New Matter", href: "/matters?new=1" },
  { label: "Deep Research", href: "/research?mode=DEEP" },
  { label: "Search Legal Sources", href: "/research" },
  { label: "Verify Citation", href: "/research?tab=verify" },
  { label: "Create Draft", href: "/drafts?new=1" },
  { label: "Open Tasks", href: "/dashboard" },
  { label: "Open Matters", href: "/matters" },
  { label: "Open Settings", href: "/settings" },
];

export default function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  const { data: results } = useQuery<SearchResponse>({
    queryKey: ["search", q],
    queryFn: () => apiGet<SearchResponse>(`/search?q=${encodeURIComponent(q)}`),
    enabled: open && q.trim().length >= 2,
  });

  const filtered = COMMANDS.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()));

  function go(href: string) {
    onOpenChange(false);
    navigate(href);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl p-0" data-testid="command-palette">
        <DialogTitle className="sr-only">Command center</DialogTitle>
        <div className="border-b border-border p-3">
          <Input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search matters, documents, drafts — or run a command"
            data-testid="command-palette-input"
          />
          <p className="mt-2 text-xs text-muted-foreground">
            Scope: your organization only — matters, documents, research, drafts
          </p>
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-2">
          {filtered.length > 0 && (
            <div className="mb-2">
              <p className="px-2 py-1 text-[11px] uppercase tracking-wider text-muted-foreground">
                Commands
              </p>
              {filtered.map((c) => (
                <button
                  key={c.label}
                  onClick={() => go(c.href)}
                  className="w-full rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent"
                  data-testid={`command-${c.label.toLowerCase().replace(/\s+/g, "-")}`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}
          {(results?.groups ?? []).map((g) => (
            <div key={g.type} className="mb-2">
              <p className="px-2 py-1 text-[11px] uppercase tracking-wider text-muted-foreground">
                {g.type}
              </p>
              {g.items.map((it) => (
                <button
                  key={it.id}
                  onClick={() => go(it.href)}
                  className="w-full truncate rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent"
                  data-testid="command-search-result"
                >
                  {it.label}
                </button>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (results?.groups ?? []).length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              {q.trim().length < 2 ? "Type at least 2 characters" : "No matches"}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
