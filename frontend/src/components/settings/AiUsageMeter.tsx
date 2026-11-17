import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export interface AiLimit {
  name: "window" | "day" | "week" | "month";
  label: string;
  percent: number;
  resets_at: string | null;
}
export interface AiUsage {
  plan: "free" | "pro";
  limits: AiLimit[];
}

const TITLES: Record<AiLimit["name"], string> = { window: "Every 5 hours", day: "Today", week: "This week", month: "This month" };

function renews(l: AiLimit): string {
  if (!l.resets_at) return "starts again with your next question";
  const at = new Date(l.resets_at);
  const when = l.name === "window" ? at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : at.toLocaleDateString([], { day: "numeric", month: "short" });
  return `renews ${l.name === "window" ? "at" : "on"} ${when}`;
}

/** How much of each AI limit this person has used, like a usage meter: a share and a renewal time, never money. The server decides every limit; this only shows them. */
export default function AiUsageMeter() {
  const q = useQuery<AiUsage>({ queryKey: ["ai-usage"], queryFn: () => apiGet("/auth/ai-usage"), refetchInterval: 60_000 });
  if (!q.data || q.data.limits.length === 0) return null;
  return (
    <section className="glass rounded-lg p-5" data-testid="ai-usage" aria-labelledby="ai-usage-title">
      <h2 id="ai-usage-title" className="text-sm font-medium">
        Your AI use
      </h2>
      <p className="mt-1 text-xs text-muted-foreground">
        {q.data.plan === "pro"
          ? "Your AI allowance is shared out over time so the month lasts: a limit every 5 hours, a daily share, a weekly limit and a monthly allowance. Each one renews on its own."
          : "The free plan has a small AI allowance each day. It renews after midnight."}
      </p>
      <ul className="mt-3 space-y-3">
        {q.data.limits.map((l) => {
          const full = l.percent >= 100;
          const pct = Math.min(100, Math.max(0, Math.round(l.percent)));
          return (
            <li key={l.name} data-testid={`ai-usage-${l.name}`}>
              <div className="flex items-baseline justify-between gap-3 text-xs">
                <span id={`ai-usage-${l.name}-label`}>{TITLES[l.name]}</span>
                <span className="text-muted-foreground" style={full ? { color: "#F0A63A" } : undefined}>
                  {full ? "Limit reached" : `${pct}% used`} · {renews(l)}
                </span>
              </div>
              <div
                role="progressbar"
                aria-labelledby={`ai-usage-${l.name}-label`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                aria-valuetext={`${pct}% used`}
                className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted"
              >
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: full ? "#F0A63A" : "#5B8CFF" }} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
