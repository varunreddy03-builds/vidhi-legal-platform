import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Laptop } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";
import { endSession } from "@/lib/session";

type Row = { id: string; current: boolean; device: string; network: string | null; signed_in_at: string; last_active: string };

/** Where you are signed in. End any you do not recognise; ending this one signs you out here. */
export default function SessionsSection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sessions"], queryFn: () => apiGet<Row[]>("/auth/sessions") });
  const end = useMutation({
    mutationFn: (id: string) => apiDelete<{ was_current: boolean }>(`/auth/sessions/${id}`),
    onSuccess: async (r) => {
      if (r.was_current) {
        await endSession();
        window.location.href = "/login";
      } else {
        await qc.invalidateQueries({ queryKey: ["sessions"] });
        toast.success("That device was signed out.");
      }
    },
    onError: (e) => toast.error(describe(e)),
  });
  const all = useMutation({
    mutationFn: () => apiPost("/auth/logout-all"),
    onSuccess: async () => {
      await endSession();
      window.location.href = "/login";
    },
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <section className="glass rounded-lg p-5" data-testid="settings-sessions">
      <h2 className="flex items-center gap-2 font-heading text-sm uppercase tracking-wider text-muted-foreground">
        <Laptop className="size-4" /> Where you are signed in
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">We email you when someone signs in from a device we have not seen before. If you do not recognise a device below, sign it out and change your password.</p>
      <ul className="mt-3 space-y-2">
        {q.data?.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm" data-testid="session-row">
            <span>
              {s.device} {s.current && <span className="ml-1 rounded-full border px-2 py-0.5 text-[10px]" style={{ color: "#7FE3B0", borderColor: "#7FE3B055" }}>this device</span>}
              <br />
              <span className="text-xs text-muted-foreground">
                {s.network ? `Network ${s.network} · ` : ""}last active {formatDateTime(s.last_active)}
              </span>
            </span>
            <Button size="xs" variant="outline" loading={end.isPending && end.variables === s.id} onClick={() => end.mutate(s.id)} data-testid={s.current ? "end-this-session" : "end-session"}>
              {s.current ? "Sign out here" : "Sign out this device"}
            </Button>
          </li>
        ))}
      </ul>
      {(q.data?.length ?? 0) > 1 && (
        <Button className="mt-3" size="sm" variant="outline" loading={all.isPending} onClick={() => all.mutate()} data-testid="sign-out-everywhere">
          Sign out of every device
        </Button>
      )}
    </section>
  );
}