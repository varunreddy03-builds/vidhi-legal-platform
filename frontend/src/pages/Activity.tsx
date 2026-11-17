import { useQuery } from "@tanstack/react-query";
import { formatDateTime } from "@/lib/format";
import AppShell from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import type { AuditEvent } from "@/lib/types";

export default function Activity() {
  const audit = useQuery<AuditEvent[]>({
    queryKey: ["audit", null],
    queryFn: () => apiGet<AuditEvent[]>("/audit"),
  });

  return (
    <AppShell title="Activity">
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl">Audit &amp; AI activity</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Every significant operation is recorded. Hidden model reasoning is never exposed.
        </p>
        <div className="glass mt-6 space-y-2 rounded-lg p-4">
          {(audit.data ?? []).map((a) => (
            <div key={a.id} className="border-b border-border pb-2 text-xs last:border-0" data-testid="audit-row">
              <span style={{ color: "#5B8CFF" }}>{a.operation}</span> · {a.result} · {a.user_email}
              {a.detail ? ` · ${a.detail}` : ""}
              <span className="text-muted-foreground"> · {formatDateTime(a.created_at)}</span>
            </div>
          ))}
          {!audit.isLoading && (audit.data ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
