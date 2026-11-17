import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

interface Match {
  strength: "strong" | "possible" | "weak";
  reason: string;
  source: string;
  matched_text: string;
  matter_title: string | null;
  matter_status: string | null;
  case_label: string | null;
  href: string | null;
}
interface Result {
  results: { name: string; matches: Match[]; total_matches: number }[];
  notice: string;
  searched: { matters: number; people_in_matters: number; recovery_cases: number };
  truncated: boolean;
}

const BADGE: Record<string, string> = { strong: "bg-red-500/15 text-red-700 dark:text-red-400", possible: "bg-amber-500/15 text-amber-700 dark:text-amber-400", weak: "bg-muted text-muted-foreground" };

export default function Conflicts() {
  const [names, setNames] = useState("");
  const check = useMutation({
    mutationFn: () => apiPost<Result>("/conflicts/check", { names: names.split("\n").map((n) => n.trim()).filter(Boolean) }),
    onError: (e) => toast.error(describe(e)),
  });
  const r = check.data;

  return (
    <AppShell title="Conflict check">
      <div className="mx-auto max-w-4xl space-y-6" data-testid="conflicts-page">
        <div>
          <h2 className="text-2xl">Conflict check</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Type the prospective client and the other parties, one name per line. VIDHI compares them with the names already in your matters, the people found in documents and your recovery cases. It cannot see anything outside VIDHI.
          </p>
        </div>
        <form className="glass space-y-3 rounded-lg p-4" onSubmit={(e) => { e.preventDefault(); check.mutate(); }}>
          <Label htmlFor="c-names">Names (up to 10)</Label>
          <Textarea id="c-names" rows={4} value={names} onChange={(e) => setNames(e.target.value)} required placeholder={"Ramesh Kumar\nAcme Traders Pvt Ltd"} data-testid="conflict-names" />
          <Button type="submit" loading={check.isPending} data-testid="conflict-run">Check</Button>
        </form>

        {r && (
          <div className="space-y-4" data-testid="conflict-results">
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note">{r.notice}</div>
            <p className="text-xs text-muted-foreground">
              Searched {r.searched.matters} matter(s), {r.searched.people_in_matters} people in documents and {r.searched.recovery_cases} recovery case(s).{r.truncated ? " Your records are large; only the first part was searched." : ""}
            </p>
            {r.results.map((x) => (
              <section key={x.name} className="glass space-y-2 rounded-lg p-4">
                <h3 className="text-lg">{x.name}</h3>
                {x.matches.length === 0 && <p className="text-sm text-muted-foreground" data-testid="conflict-none">No similar name found in your VIDHI records. That is not a clearance.</p>}
                {x.matches.map((m, i) => (
                  <div key={i} className="flex flex-wrap items-start justify-between gap-2 border-t border-border pt-2 text-sm" data-testid="conflict-match">
                    <div>
                      <span className={`mr-2 rounded-full px-2 py-0.5 text-xs ${BADGE[m.strength]}`}>{m.strength}</span>
                      <strong>{m.matched_text}</strong> <span className="text-muted-foreground">· {m.source}</span>
                      <p className="text-xs text-muted-foreground">{m.reason}{m.matter_title ? ` · matter: ${m.matter_title}${m.matter_status ? ` (${m.matter_status.toLowerCase()})` : ""}` : ""}{m.case_label ? ` · recovery: ${m.case_label}` : ""}</p>
                    </div>
                    {m.href && <Link to={m.href} className="text-sm underline underline-offset-4">Open</Link>}
                  </div>
                ))}
              </section>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}