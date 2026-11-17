import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { Readiness } from "@/lib/types";

export function useReadiness(caseId: string, enabled = true) {
  return useQuery<Readiness>({
    queryKey: ["recovery-readiness", caseId],
    queryFn: () => apiGet<Readiness>(`/recovery/cases/${caseId}/readiness`),
    enabled,
  });
}

const LEVEL_COLOR = { INFO: "#5B8CFF", WARN: "#F0A63A", STOP: "#E5646E" } as const;
const SOURCE_LABEL: Record<string, string> = {
  YOU_ENTERED: "You entered",
  CALCULATED: "Calculated by VIDHI",
  READ_FROM_DOCUMENTS: "Read from your documents by AI",
  AI_SUGGESTION: "AI suggestion",
};

function money(n: number, currency: string) {
  return currency === "INR" ? `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : `${n.toLocaleString()} ${currency}`;
}

/** "Check before you draft": the balance working, missing evidence, and warnings, all computed by code. */
export default function ReadinessPanel({
  r,
  ack,
  onAck,
}: {
  r: Readiness;
  ack: boolean;
  onAck: (v: boolean) => void;
}) {
  const b = r.balance;
  return (
    <div className="space-y-4" data-testid="readiness-panel">
      <div className="rounded-md border border-border p-4" data-testid="balance-card">
        <p className="text-sm">How much is owed</p>
        <table className="mt-2 w-full text-sm">
          <tbody>
            {b.lines.map((l, i) => (
              <tr key={i} className="border-b border-border/50 last:border-0">
                <td className="py-1 pr-2 text-muted-foreground">{l.sign > 0 ? "+" : "−"}</td>
                <td className="py-1">
                  {l.label}
                  {l.date ? <span className="text-xs text-muted-foreground"> · {l.date}</span> : null}
                  {l.basis ? <span className="block text-xs text-muted-foreground">Agreed in: {l.basis}</span> : null}
                  {l.reason ? <span className="block text-xs text-muted-foreground">{l.reason}</span> : null}
                </td>
                <td className="py-1 text-right tabular-nums">{money(l.amount, b.currency)}</td>
              </tr>
            ))}
            <tr>
              <td />
              <td className="pt-2 font-medium">Balance due</td>
              <td className="pt-2 text-right font-medium tabular-nums" style={{ color: "#C8A96B" }} data-testid="balance-due">
                {money(b.balance, b.currency)}
              </td>
            </tr>
          </tbody>
        </table>
        {b.ignored_charges.map((x, i) => (
          <p key={i} className="mt-1 text-xs" style={{ color: "#F0A63A" }}>
            Not counted: {x.label} ({money(x.amount, b.currency)}) — {x.reason}.
          </p>
        ))}
        {b.warnings.map((w, i) => (
          <p key={i} className="mt-1 text-xs" style={{ color: "#F0A63A" }}>
            {w}
          </p>
        ))}
        <p className="mt-2 text-xs text-muted-foreground">{b.formula}</p>
      </div>

      <div className="rounded-md border border-border p-4" data-testid="evidence-checklist">
        <p className="text-sm">Your evidence</p>
        <ul className="mt-2 space-y-1.5">
          {r.evidence.items.map((i) => (
            <li key={i.key} className="text-sm">
              <span style={{ color: i.status === "PRESENT" ? "#5B8CFF" : i.need === "required" ? "#E5646E" : "#F0A63A" }}>
                {i.status === "PRESENT" ? "✓" : "✗"}
              </span>{" "}
              {i.label}
              {i.status === "MISSING" && (
                <span className="block pl-5 text-xs text-muted-foreground">
                  {i.need === "required" ? "Needed. " : "Helpful. "}
                  {i.why}
                </span>
              )}
              {i.files.length > 0 && <span className="block pl-5 text-xs text-muted-foreground">{i.files.join(", ")}</span>}
            </li>
          ))}
        </ul>
        {r.evidence.facts_missing.length > 0 && (
          <p className="mt-2 text-xs" style={{ color: "#F0A63A" }} data-testid="facts-missing">
            Still to fill in: {r.evidence.facts_missing.map((f) => f.label.toLowerCase()).join(", ")}.
          </p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">{r.evidence.note}</p>
      </div>

      <div className="space-y-2" data-testid="route-warnings">
        {r.routes.flags.map((f) => (
          <div key={f.key} className="rounded-md border p-3" style={{ borderColor: LEVEL_COLOR[f.level] }}>
            <p className="text-sm" style={{ color: LEVEL_COLOR[f.level] }}>
              {f.level === "STOP" ? "Please read: " : ""}
              {f.title}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{f.text}</p>
            {f.questions && (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                {f.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {r.route_acknowledgement_needed && (
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className="mt-0.5" checked={ack} onChange={(e) => onAck(e.target.checked)} data-testid="route-ack" />
            <span>I have read the warnings above and I still want to draft an ordinary demand letter.</span>
          </label>
        )}
        {r.routes.advocate_recommended && (
          <p className="text-xs text-muted-foreground">
            Because of the above, having an advocate look at this before you send anything is a good idea (step 5).
          </p>
        )}
        <p className="text-xs text-muted-foreground">{r.routes.disclaimer}</p>
      </div>

      <details className="rounded-md border border-border p-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">Where each fact in the notice comes from</summary>
        <table className="mt-2 w-full text-xs">
          <tbody>
            {r.provenance.map((p, i) => (
              <tr key={i} className="border-b border-border/50 last:border-0">
                <td className="py-1 pr-2 text-muted-foreground">{p.label}</td>
                <td className="py-1 pr-2">{p.value}</td>
                <td className="py-1 text-right text-xs text-muted-foreground">{SOURCE_LABEL[p.source]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
