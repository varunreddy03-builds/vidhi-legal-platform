import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { endSession } from "@/lib/session";

export default function SecuritySection() {
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const mismatch = again.length > 0 && again !== next;

  const change = useMutation({
    mutationFn: () => apiPost("/auth/change-password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setAgain("");
      toast.success("Password changed. Your other devices were signed out.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const everywhere = useMutation({
    mutationFn: () => apiPost<{ sessions_ended: number }>("/auth/logout-all"),
    onSuccess: async () => {
      await endSession().catch(() => undefined);
      toast.success("Signed out on every device");
      navigate("/login", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-security">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Security</h2>
      <form
        className="mt-3 grid gap-3 md:max-w-sm"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) change.mutate();
        }}
      >
        <div>
          <label className="text-xs text-muted-foreground">Current password</label>
          <Input type="password" aria-label="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className="mt-1" required data-testid="pw-current" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">New password (at least 8 characters)</label>
          <Input type="password" aria-label="New password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} className="mt-1" required data-testid="pw-new" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">New password again</label>
          <Input type="password" aria-label="Repeat the new password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} className="mt-1" required />
          {mismatch && <p className="mt-1 text-xs text-destructive">The two passwords do not match.</p>}
        </div>
        <div>
          <Button type="submit" size="sm" variant="outline" disabled={change.isPending || mismatch} data-testid="pw-save">
            {change.isPending ? "Saving…" : "Change password"}
          </Button>
        </div>
      </form>
      <div className="mt-5 border-t border-border pt-4">
        <p className="text-xs text-muted-foreground">
          Lost a device or shared a computer? This signs you out everywhere, including here.
        </p>
        <Button size="sm" variant="outline" className="mt-2" onClick={() => everywhere.mutate()} disabled={everywhere.isPending} data-testid="logout-all">
          Sign out on every device
        </Button>
      </div>
    </section>
  );
}
