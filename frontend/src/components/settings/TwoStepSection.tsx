import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useMe } from "@/lib/useMe";

/** Two-step sign-in with an authenticator app: set up, show recovery codes once, turn off. */
export default function TwoStepSection() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [turningOff, setTurningOff] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["me"] });

  const start = useMutation({
    mutationFn: () => apiPost<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup", {}),
    onSuccess: (r) => {
      setSetup(r);
      setCode("");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const enable = useMutation({
    mutationFn: () => apiPost<{ recovery_codes: string[] }>("/auth/2fa/enable", { code }),
    onSuccess: async (r) => {
      setRecovery(r.recovery_codes);
      setSetup(null);
      setCode("");
      await refresh();
      toast.success("Two-step sign-in is on.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const disable = useMutation({
    mutationFn: () => apiPost("/auth/2fa/disable", { password, code }),
    onSuccess: async () => {
      setTurningOff(false);
      setPassword("");
      setCode("");
      await refresh();
      toast.success("Two-step sign-in is off.");
    },
    onError: (e) => toast.error(describe(e)),
  });

  if (!me) return null;
  const on = me.two_factor;

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-two-step">
      <h2 className="flex items-center gap-2 font-heading text-sm uppercase tracking-wider text-muted-foreground">
        <ShieldCheck className="size-4" /> Two-step sign-in
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Adds a 6-digit code from an app on your phone (Google Authenticator, Microsoft Authenticator, Authy or similar) after your password. If someone learns
        your password, they still cannot sign in.
      </p>

      {recovery && (
        <div className="mt-4 rounded-md border border-border p-4" data-testid="recovery-codes">
          <p className="text-sm font-medium">Save these recovery codes now</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Each works once if you lose your phone. They are shown only this one time. Keep them somewhere safe, such as a printout.
          </p>
          <ul className="mt-3 grid grid-cols-2 gap-2 font-mono text-sm">
            {recovery.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <Button size="sm" variant="outline" className="mt-3" onClick={() => setRecovery(null)}>
            I have saved them
          </Button>
        </div>
      )}

      {!on && !setup && !recovery && (
        <Button className="mt-4" size="sm" loading={start.isPending} onClick={() => start.mutate()} data-testid="two-step-start">
          Turn on two-step sign-in
        </Button>
      )}

      {!on && setup && (
        <div className="mt-4 space-y-3" data-testid="two-step-setup">
          <p className="text-sm">1. In your authenticator app, add an account and enter this key (or tap the link on your phone):</p>
          <p className="break-all rounded-md border border-border px-3 py-2 font-mono text-sm" data-testid="two-step-secret">
            {setup.secret}
          </p>
          <a href={setup.otpauth_uri} className="text-sm underline underline-offset-4">
            Open in my authenticator app
          </a>
          <p className="text-sm">2. Type the 6-digit code the app shows:</p>
          <div className="flex gap-2">
            <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="max-w-40" data-testid="two-step-code" />
            <Button size="sm" loading={enable.isPending} disabled={code.trim().length < 6} onClick={() => enable.mutate()} data-testid="two-step-confirm">
              Confirm
            </Button>
          </div>
        </div>
      )}

      {on && !turningOff && (
        <div className="mt-4 flex items-center gap-3">
          <span className="rounded-full border px-2.5 py-0.5 text-xs" style={{ color: "#7FE3B0", borderColor: "#7FE3B055" }} data-testid="two-step-on">
            On
          </span>
          <Button size="sm" variant="outline" onClick={() => setTurningOff(true)} data-testid="two-step-off">
            Turn off
          </Button>
        </div>
      )}

      {on && turningOff && (
        <div className="mt-4 space-y-3">
          <p className="text-sm">To turn it off, enter your password and a current code (or a recovery code).</p>
          <div className="flex flex-wrap gap-2">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" className="max-w-56" />
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Code" className="max-w-40" />
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" loading={disable.isPending} disabled={!password || code.trim().length < 6} onClick={() => disable.mutate()}>
              Turn off
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setTurningOff(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
