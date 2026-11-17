import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import DeadlineData from "@/components/admin/DeadlineData";
import JudgmentLinks from "@/components/admin/JudgmentLinks";
import LegalReview from "@/components/admin/LegalReview";
import PilotInvites from "@/components/admin/PilotInvites";
import PilotFeedbackList from "@/components/admin/PilotFeedbackList";
import ProductNumbers from "@/components/admin/ProductNumbers";
import WeeklyView from "@/components/admin/WeeklyView";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";
import { useMe } from "@/lib/useMe";

type Tab = "overview" | "weekly" | "product" | "deadlines" | "people" | "payments" | "legal" | "review" | "judgments" | "pilot" | "ai" | "support" | "data" | "signals";
const TABS: [Tab, string][] = [["overview", "Overview"], ["weekly", "This week"], ["product", "Product"], ["deadlines", "Deadline data"], ["people", "People"], ["payments", "Payments"], ["legal", "Legal sources"], ["review", "Review law"], ["judgments", "Judgment links"], ["pilot", "Pilot invites"], ["ai", "AI spend"], ["support", "Support"], ["data", "Data requests"], ["signals", "Signals"]];

const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="glass rounded-lg p-4">
    <h2 className="font-heading text-xs uppercase tracking-wider text-muted-foreground">{title}</h2>
    <div className="mt-2 text-sm">{children}</div>
  </section>
);

/** The operator's console. The server checks the operator's identity on every call; this screen only hides itself from everyone else. */
export default function Admin() {
  const { data: me, isLoading } = useMe();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  useEffect(() => {
    if (!isLoading && me && !me.platform_admin) navigate("/start", { replace: true });
  }, [isLoading, me, navigate]);
  if (!me?.platform_admin) return null;
  return (
    <AppShell title="Admin console">
      <div className="mx-auto max-w-5xl space-y-4" data-testid="admin-console">
        {!me.two_factor && <p className="rounded-md border border-border p-3 text-sm" style={{ color: "#F0A63A" }}>Turn on two-step sign-in in Settings to use the admin console.</p>}
        <div className="flex flex-wrap gap-2" role="tablist">
          {TABS.map(([id, label]) => (
            <Button key={id} variant={tab === id ? "default" : "outline"} size="sm" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} data-testid={`admin-tab-${id}`}>{label}</Button>
          ))}
        </div>
        {tab === "overview" && <Overview />}
        {tab === "weekly" && <WeeklyView />}
        {tab === "product" && <ProductNumbers />}
        {tab === "deadlines" && <DeadlineData />}
        {tab === "people" && <People />}
        {tab === "payments" && <Payments />}
        {tab === "legal" && <LegalSources />}
        {tab === "review" && <LegalReview />}
        {tab === "judgments" && <JudgmentLinks />}
        {tab === "pilot" && (
          <>
            <PilotInvites />
            <PilotFeedbackList />
          </>
        )}
        {tab === "ai" && <AiSpend />}
        {tab === "support" && <Support />}
        {tab === "data" && <DataRequests />}
        {tab === "signals" && <Signals />}
      </div>
    </AppShell>
  );
}

/** What legal text has been loaded, from which sources, how much of it a person has reviewed, and the background jobs reading scans. Counts come from the database; "loaded" never means "complete". */
function LegalSources() {
  const qc = useQueryClient();
  const cov = useQuery({ queryKey: ["admin-legal-coverage"], queryFn: () => apiGet<any>("/legal/coverage") });
  const sources = useQuery({ queryKey: ["admin-legal-sources"], queryFn: () => apiGet<any[]>("/admin/legal/sources") });
  const jobs = useQuery({ queryKey: ["admin-legal-jobs"], queryFn: () => apiGet<any[]>("/admin/legal/jobs") });
  const run = useMutation({
    mutationFn: () => apiPost<{ done: number; failed: number }>("/admin/legal/jobs/run?limit=5"),
    onSuccess: (r) => {
      toast.success(`Ran jobs: ${r.done} done, ${r.failed} failed.`);
      void qc.invalidateQueries({ queryKey: ["admin-legal-jobs"] });
      void qc.invalidateQueries({ queryKey: ["admin-legal-coverage"] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const c = cov.data;
  return (
    <div className="space-y-4" data-testid="admin-legal">
      <Card title="Coverage (counted from the database)">
        {c ? (
          <>
            <p>{c.sources} source(s) registered ({c.sources_terms_not_read} with terms not yet read) · {c.documents} document(s) · {c.instruments} instrument(s) · {c.provisions} provision(s), {c.provisions_reviewed} reviewed · {c.mappings} mapping(s), {c.mappings_reviewed} reviewed.</p>
            <p className="mt-1 text-muted-foreground">{c.meaning}</p>
            {c.per_instrument.length > 0 && (
              <table className="mt-3 w-full text-left text-xs">
                <caption className="sr-only">Provisions loaded per instrument</caption>
                <thead><tr><th scope="col">Instrument</th><th scope="col">Versions</th><th scope="col">Provisions</th><th scope="col">Reviewed</th><th scope="col">Parser warnings</th><th scope="col">No effective date</th></tr></thead>
                <tbody>
                  {c.per_instrument.map((i: any) => (
                    <tr key={i.instrument}><td>{i.instrument}</td><td>{i.versions}</td><td>{i.provisions}</td><td>{i.reviewed}</td><td>{i.versions_with_parser_warnings}</td><td>{i.versions_without_effective_date}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : <p>Loading…</p>}
      </Card>
      <Card title="Sources">
        {(sources.data ?? []).map((s: any) => (
          <p key={s.id} className="border-b border-border py-1 last:border-0">{s.name} · {s.publisher} · {s.access_method} · <strong>{s.status === "terms-recorded" ? `terms read ${s.terms_checked_on}` : "terms NOT read yet"}</strong></p>
        ))}
        {sources.isSuccess && sources.data.length === 0 && <p className="text-muted-foreground">No sources registered. See docs/VIDHI_LEGAL_SOURCES.md for what has been checked.</p>}
      </Card>
      <Card title="Background jobs">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}>Run due jobs now</Button>
        {(jobs.data ?? []).map((j: any) => (
          <p key={j.id} className="border-b border-border py-1 last:border-0">{j.kind} · {j.state} · attempts {j.attempts}/{j.max_attempts}{j.last_error ? ` · ${j.last_error}` : ""} · {formatDateTime(j.created_at)}</p>
        ))}
        {jobs.isSuccess && jobs.data.length === 0 && <p className="mt-2 text-muted-foreground">No jobs.</p>}
      </Card>
    </div>
  );
}

/** Payments and refund records. VIDHI does not move money: refund in the provider's dashboard first, then record it here. */
function Payments() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [returned, setReturned] = useState(false);
  const [endPro, setEndPro] = useState(false);
  const list = useQuery({ queryKey: ["admin-payments", q], queryFn: () => apiGet<any[]>(`/admin/payments?q=${encodeURIComponent(q)}`) });
  const rec = useMutation({
    mutationFn: (sid: string) => apiPost<any>(`/admin/payments/${sid}/refund`, { ...(amount ? { amount: Number(amount) } : {}), reason, returned_through_provider: returned, end_pro_now: endPro }),
    onSuccess: (r) => {
      toast.success(`Refund recorded. ${r.reminder}`);
      setOpen(null); setAmount(""); setReason(""); setReturned(false); setEndPro(false);
      void qc.invalidateQueries({ queryKey: ["admin-payments"] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <div className="space-y-3" data-testid="admin-payments">
      <Card title="How refunds work">VIDHI does not move money. Refund the payment in Stripe, Razorpay or PayPal first, then record it here so the history, the customer and the audit log agree. Cancel the subscription in the provider&apos;s dashboard too.</Card>
      <Input placeholder="Search by customer email or payment reference" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search payments" />
      {(list.data ?? []).map((p: any) => (
        <div key={p.session_id} className="glass rounded-lg p-3 text-sm" data-testid="admin-payment-row">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{p.email ?? "unknown"} · {p.provider} · {p.package_id}{p.renewal ? " (renewal)" : ""} · {p.currency?.toUpperCase()} {p.amount} · {p.payment_status}{p.refunded_amount ? ` · refunded ${p.refunded_amount}` : ""} · {formatDateTime(p.created_at)}</span>
            {p.payment_status === "paid" && p.status === "completed" && <Button size="xs" variant="outline" onClick={() => setOpen(open === p.session_id ? null : p.session_id)}>Record a refund</Button>}
          </div>
          {open === p.session_id && (
            <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); rec.mutate(p.session_id); }}>
              <Input placeholder="Amount (empty = everything not yet refunded)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <Input placeholder="Reason (kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} maxLength={300} />
              <label className="flex items-center gap-2"><input type="checkbox" checked={returned} onChange={(e) => setReturned(e.target.checked)} />I have already returned this money in the provider&apos;s dashboard</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={endPro} onChange={(e) => setEndPro(e.target.checked)} />Also move the organisation to the Free plan now</label>
              <Button type="submit" size="sm" loading={rec.isPending} disabled={!returned}>Record refund</Button>
            </form>
          )}
        </div>
      ))}
      {list.isSuccess && list.data.length === 0 && <p className="text-sm text-muted-foreground">No payments found.</p>}
    </div>
  );
}

function Overview() {
  const q = useQuery({ queryKey: ["admin-overview"], queryFn: () => apiGet<any>("/admin/overview") });
  const o = q.data;
  if (!o) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="admin-overview">
      <Card title="Health">
        <p>Database: <strong>{o.database}</strong></p>
        <ul className="mt-2 grid grid-cols-2 gap-1 text-xs">
          {Object.entries(o.services as Record<string, boolean>).map(([k, v]) => (
            <li key={k} style={{ color: v ? "#7FE3B0" : "#F0A63A" }}>{v ? "✓" : "○"} {k.replaceAll("_", " ")}</li>
          ))}
        </ul>
      </Card>
      <Card title="People">
        <p>{o.users.total} accounts in {o.users.organisations} organisations ({o.users.new_7_days} new this week)</p>
        <p className="text-muted-foreground">Owners on Pro: {o.users.pro_owners} · Free: {o.users.free_owners} · Blocked: {o.users.blocked}</p>
      </Card>
      <Card title="AI spending this month">
        <p>Rs {o.ai_budget.used_inr.toLocaleString("en-IN")} of Rs {o.ai_budget.cap_inr.toLocaleString("en-IN")} ({o.ai_budget.percent}%)</p>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border"><div className="h-full rounded-full" style={{ width: `${Math.min(100, o.ai_budget.percent)}%`, background: o.ai_budget.percent >= 80 ? "#F0A63A" : "#5B8CFF" }} /></div>
        {o.ai_budget.exhausted && <p className="mt-2" style={{ color: "#E5646E" }}>AI features are paused until next month.</p>}
      </Card>
      <Card title="Waiting for you">
        <p>Open support messages: {o.work.open_support}</p>
        <p>Open data requests: {o.work.open_data_requests}</p>
        <p>Law-library drafts awaiting a lawyer: {o.work.pending_lawyer_review_entries}</p>
      </Card>
      <div className="md:col-span-2">
        <Card title="Still to set up">
          {o.todo.length ? <ul className="list-disc space-y-1 pl-5" data-testid="admin-todo">{o.todo.map((t: string) => <li key={t}>{t}</li>)}</ul> : <p>Nothing outstanding.</p>}
        </Card>
      </div>
    </div>
  );
}

function People() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const list = useQuery({ queryKey: ["admin-users", q], queryFn: () => apiGet<any>(`/admin/users?q=${encodeURIComponent(q)}`) });
  const act = useMutation({
    mutationFn: ({ id, block }: { id: string; block: boolean }) => {
      if (!block) return apiPost(`/admin/users/${id}/unblock`);
      const reason = window.prompt("Why is this account being blocked? (the person is signed out at once)");
      if (!reason || reason.trim().length < 3) throw new Error("A reason is required.");
      return apiPost(`/admin/users/${id}/block`, { reason });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <div className="space-y-3" data-testid="admin-people">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by email, name or organisation" className="max-w-sm" />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted-foreground"><tr><th className="py-1 pr-3">Person</th><th className="pr-3">Organisation</th><th className="pr-3">Plan</th><th className="pr-3">Work</th><th className="pr-3">Joined</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {list.data?.users.map((u: any) => (
              <tr key={u.id} className="border-t border-border align-top">
                <td className="py-1.5 pr-3">{u.name}<br /><span className="text-muted-foreground">{u.email}{u.email_verified ? "" : " (unconfirmed)"}</span></td>
                <td className="pr-3">{u.organization}<br /><span className="text-muted-foreground">{u.role}</span></td>
                <td className="pr-3">{u.plan}</td>
                <td className="pr-3">{u.matters} matters<br />{u.recovery_cases} cases</td>
                <td className="pr-3">{formatDate(u.created_at)}</td>
                <td>
                  {u.is_platform_admin ? <span className="text-muted-foreground">admin</span> : u.blocked ? (
                    <Button size="xs" variant="outline" onClick={() => act.mutate({ id: u.id, block: false })} title={u.blocked.reason}>Unblock</Button>
                  ) : (
                    <Button size="xs" variant="destructive" onClick={() => act.mutate({ id: u.id, block: true })}>Block</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AiSpend() {
  const q = useQuery({ queryKey: ["admin-ai"], queryFn: () => apiGet<any>("/admin/ai-spend") });
  if (!q.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const b = q.data.budget;
  return (
    <div className="space-y-4" data-testid="admin-ai">
      <Card title={`Month ${b.month}`}>
        <p>Used Rs {b.used_inr.toLocaleString("en-IN")} of Rs {b.cap_inr.toLocaleString("en-IN")} · {b.calls} calls · alert at 80% {b.alert80_sent ? "was sent" : "not reached"}</p>
        {!b.alert_email_configured && <p style={{ color: "#F0A63A" }}>No alert email is set (OWNER_ALERT_EMAIL), so the 80% alert would only be logged.</p>}
        <p className="mt-2 text-xs text-muted-foreground">By provider: {Object.entries(b.by_provider).map(([k, v]) => `${k} Rs ${v}`).join(" · ") || "none yet"}</p>
        <p className="text-xs text-muted-foreground">By task: {Object.entries(b.by_task).map(([k, v]) => `${k} Rs ${v}`).join(" · ") || "none yet"}</p>
        <p className="mt-2 text-xs text-muted-foreground">Costs use the price settings in AI_PRICES_JSON (placeholders until you set the real prices). Also set a spending limit inside each provider&apos;s own console.</p>
      </Card>
      <Card title="Latest calls (cost only, never content)">
        <ul className="space-y-0.5 text-xs">{q.data.recent_calls.map((c: any, i: number) => <li key={i}>{formatDateTime(c.created_at)} · {c.provider} · {c.task} · Rs {c.cost_inr}{c.estimated ? " (estimate)" : ""}</li>)}</ul>
      </Card>
    </div>
  );
}

function Support() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-support"], queryFn: () => apiGet<any>("/admin/support") });
  const set = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => apiPatch(`/admin/support/${id}`, { status }), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-support"] }), onError: (e) => toast.error(describe(e)) });
  return (
    <div className="space-y-3" data-testid="admin-support">
      {q.data?.tickets.length === 0 && <p className="text-sm text-muted-foreground">No open messages.</p>}
      {q.data?.tickets.map((t: any) => (
        <Card key={t.id} title={`${t.reference} · ${t.category} · ${formatDateTime(t.created_at)}`}>
          <p className="whitespace-pre-wrap">{t.message}</p>
          <p className="mt-2 text-xs text-muted-foreground">{t.name} · {t.email}{t.user_id ? " · signed in" : ""}</p>
          <div className="mt-2 flex gap-2">
            <Button size="xs" variant="outline" onClick={() => set.mutate({ id: t.id, status: "IN_PROGRESS" })}>In progress</Button>
            <Button size="xs" onClick={() => set.mutate({ id: t.id, status: "CLOSED" })}>Close</Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

function DataRequests() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-data"], queryFn: () => apiGet<any>("/admin/data-requests") });
  const act = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => {
      const outcome = status === "IN_PROGRESS" ? "" : window.prompt("What was done, or why was it refused? (the person is told)") ?? "";
      return apiPatch(`/admin/data-requests/${id}`, { status, outcome });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <div className="space-y-3" data-testid="admin-data">
      {q.data?.requests.length === 0 && <p className="text-sm text-muted-foreground">No open requests.</p>}
      {q.data?.requests.map((r: any) => (
        <Card key={r.id} title={`${r.kind} · ${r.id.slice(0, 8)} · reply target ${formatDate(r.due_by)}`}>
          <p className="text-xs text-muted-foreground">{r.email} · {r.status.replace("_", " ").toLowerCase()}</p>
          {r.details && <p className="mt-1 whitespace-pre-wrap">{r.details}</p>}
          <div className="mt-2 flex gap-2">
            <Button size="xs" variant="outline" onClick={() => act.mutate({ id: r.id, status: "IN_PROGRESS" })}>In progress</Button>
            <Button size="xs" onClick={() => act.mutate({ id: r.id, status: "COMPLETED" })}>Done</Button>
            <Button size="xs" variant="destructive" onClick={() => act.mutate({ id: r.id, status: "REJECTED" })}>Refuse</Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

function Signals() {
  const q = useQuery({ queryKey: ["admin-signals"], queryFn: () => apiGet<any>("/admin/signals?hours=24") });
  const sig = Object.entries((q.data?.signals ?? {}) as Record<string, { total: number; top: { user: string; count: number }[] }>);
  return (
    <div className="space-y-3" data-testid="admin-signals">
      <p className="text-xs text-muted-foreground">Last 24 hours. Who and how often, never what they wrote.</p>
      {sig.length === 0 && <p className="text-sm">Nothing unusual.</p>}
      {sig.map(([op, d]) => (
        <Card key={op} title={`${op.replaceAll("_", " ").toLowerCase()} · ${d.total}`}>
          <ul className="text-xs">{d.top.map((t) => <li key={t.user}>{t.user}: {t.count}</li>)}</ul>
        </Card>
      ))}
    </div>
  );
}