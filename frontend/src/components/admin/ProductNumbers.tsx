import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

type Tool = {
  tool: string;
  label: string;
  runs: number;
  failed: number;
  refused: number;
  avg_ms: number | null;
  buckets: Record<string, number>;
  share_under_3s_pct: number | null;
  failed_pct: number | null;
  wrong_result_reports: number | null;
  wrong_result_rate_pct: number | null;
};
interface Product {
  days: number;
  from_day: string;
  tools: Tool[];
  note: string;
}

const dash = "–";
const secs = (ms: number | null) => (ms == null ? dash : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);
const pct = (n: number | null) => (n == null ? dash : `${n}%`);

/** The operator's product numbers: how often each tool ran, how long it took, how often it failed, and the wrong-result rate where there is a report button. Counters only. */
export default function ProductNumbers() {
  const [days, setDays] = useState(28);
  const q = useQuery({ queryKey: ["admin-product", days], queryFn: () => apiGet<Product>(`/admin/product?days=${days}`) });
  if (q.isPending) return <p className="text-sm text-muted-foreground" role="status">Loading the product numbers…</p>;
  if (q.isError || !q.data) return <p className="text-sm" role="alert" style={{ color: "#F0A63A" }}>The product numbers could not be loaded. Reload the page.</p>;
  const p = q.data;
  return (
    <section className="glass rounded-lg p-4" data-testid="admin-product" aria-labelledby="product-h">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="product-h" className="font-heading text-xs uppercase tracking-wider text-muted-foreground">Product numbers</h2>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Period</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-9 rounded-md border border-border bg-background px-2" data-testid="product-days">
            {[7, 28, 90, 365].map((d) => (
              <option key={d} value={d}>{d} days</option>
            ))}
          </select>
        </label>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">Since {p.from_day} (Indian days). {p.note}</p>
      <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Product numbers by tool">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-3 font-medium">Tool</th>
              <th className="px-2 font-medium">Runs</th>
              <th className="px-2 font-medium">Refused</th>
              <th className="px-2 font-medium">Failed</th>
              <th className="px-2 font-medium">Average time</th>
              <th className="px-2 font-medium">Under 3 s</th>
              <th className="px-2 font-medium">Wrong-result rate</th>
            </tr>
          </thead>
          <tbody>
            {p.tools.map((t) => (
              <tr key={t.tool} className="border-t border-border" data-testid="product-row" data-tool={t.tool}>
                <th scope="row" className="py-2 pr-3 font-normal">{t.label}</th>
                <td className="px-2" data-testid="product-runs">{t.runs}</td>
                <td className="px-2">{t.refused}</td>
                <td className="px-2">{t.failed}{t.failed_pct != null && t.failed > 0 ? ` (${t.failed_pct}%)` : ""}</td>
                <td className="px-2">{secs(t.avg_ms)}</td>
                <td className="px-2">{pct(t.share_under_3s_pct)}</td>
                <td className="px-2">{t.wrong_result_reports == null ? dash : `${t.wrong_result_reports} reported · ${pct(t.wrong_result_rate_pct)}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
