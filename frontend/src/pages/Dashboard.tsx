import { Link } from "react-router-dom";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { Card, CardContent } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import type { DashboardStats, Matter, AuditEvent } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import IllustrationCard from "@/components/IllustrationCard";

export default function Dashboard() {
  const { data: me } = useMe();
  const stats = useQuery<DashboardStats>({
    queryKey: ["stats"],
    queryFn: () => apiGet<DashboardStats>("/dashboard/stats"),
  });
  const matters = useQuery<Matter[]>({
    queryKey: ["matters"],
    queryFn: () => apiGet<Matter[]>("/matters"),
  });
  const audit = useQuery<AuditEvent[]>({
    queryKey: ["audit", null],
    queryFn: () => apiGet<AuditEvent[]>("/audit"),
  });

  const tiles = [
    ["Matters", stats.data?.matters],
    ["Documents", stats.data?.documents],
    ["Research sessions", stats.data?.research_sessions],
    ["Drafts", stats.data?.drafts],
    ["Unsupported claims", stats.data?.unverified_claims],
  ] as const;

  return (
    <AppShell title="Dashboard">
      <div className="mx-auto max-w-5xl">
        <h2 className="text-2xl">Good to see you, {me?.full_name ?? "counsel"}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {me?.organization_name} · jurisdiction India (IN) · plugin v1.0.0
        </p>

        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {tiles.map(([label, value]) => (
            <Card key={label} className="glass" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
              <CardContent className="p-4">
                <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
                <p className="mt-2 font-heading text-2xl">
                  {stats.isLoading ? "—" : (value ?? 0)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="flex items-center justify-between">
              <h3 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
                Recent matters
              </h3>
              <Link to="/matters" className={buttonVariants({ variant: "outline", size: "xs" })}>
                All matters
              </Link>
            </div>
            <div className="mt-3 space-y-2">
              {(matters.data ?? []).slice(0, 5).map((m) => (
                <Link
                  key={m.id}
                  to={`/matters/${m.id}`}
                  data-testid="dashboard-matter-row"
                  className="glass block rounded-lg p-4 transition-transform duration-200 hover:translate-x-1"
                >
                  <p className="text-sm">{m.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {m.status} · {m.jurisdiction_id}
                  </p>
                </Link>
              ))}
              {!matters.isLoading && (matters.data ?? []).length === 0 && (
                <div className="glass rounded-lg p-8 text-center">
                  <p className="text-sm text-muted-foreground">No matters yet.</p>
                  <Link
                    to="/matters?new=1"
                    className={buttonVariants({ size: "sm", className: "mt-3" })}
                    data-testid="dashboard-create-matter"
                  >
                    Create your first matter
                  </Link>
                </div>
              )}
              {matters.isError && (
                <p className="text-sm" style={{ color: "#F0A63A" }}>
                  Could not load matters. Reload the page to retry.
                </p>
              )}
            </div>
          </section>

          <section>
            <h3 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
              AI &amp; audit activity
            </h3>
            <div className="glass mt-3 space-y-2 rounded-lg p-4">
              {(audit.data ?? []).slice(0, 8).map((a) => (
                <div key={a.id} className="text-xs" data-testid="dashboard-audit-row">
                  <span style={{ color: "#5B8CFF" }}>{a.operation}</span>
                  <span className="text-muted-foreground"> · {formatDateTime(a.created_at)}</span>
                </div>
              ))}
              {(audit.data ?? []).length === 0 && (
                <p className="text-xs text-muted-foreground">No recorded activity yet.</p>
              )}
            </div>
          </section>
        </div>
        <IllustrationCard />
      </div>
    </AppShell>
  );
}
