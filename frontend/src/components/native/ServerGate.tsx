import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DEFAULT_SERVER, cleanServerUrl, isNative, serverBase, serverReachable, setServerBase } from "@/lib/native";

/** The Android app's address screen: asks where the VIDHI server is, checks it answers, remembers it. */
export function ServerForm({ onSaved, onCancel }: { onSaved: () => void; onCancel?: () => void }) {
  const [value, setValue] = useState(serverBase() || DEFAULT_SERVER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const url = cleanServerUrl(value);
    if (!url) return setError("Enter the address of your VIDHI server.");
    setBusy(true);
    setError("");
    const ok = await serverReachable(url);
    setBusy(false);
    if (!ok) return setError(`Cannot reach ${url}. Check the address, that the server is running, and your internet connection.`);
    setServerBase(url);
    onSaved();
  }

  return (
    <form onSubmit={connect} className="w-full max-w-sm space-y-3 text-left" data-testid="server-form">
      <p className="text-sm text-muted-foreground">Enter the address of your VIDHI server, for example https://your-server.example.com</p>
      <Input value={value} onChange={(e) => setValue(e.target.value)} inputMode="url" autoCapitalize="off" autoCorrect="off" spellCheck={false} placeholder="https://…" aria-label="Server address" data-testid="server-url" />
      {error && <p className="text-sm text-destructive" role="alert" data-testid="server-error">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" loading={busy} className="flex-1" data-testid="server-connect">Connect</Button>
        {onCancel && <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}

/** In a browser this renders its children untouched. In the Android app it shows the address screen until a server is saved. */
export default function ServerGate({ children }: { children: ReactNode }) {
  const [, bump] = useState(0);
  if (!isNative() || serverBase()) return <>{children}</>;
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background px-6 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] text-foreground">
      <h1 className="font-heading text-3xl tracking-widest">VIDHI</h1>
      <ServerForm onSaved={() => bump((n) => n + 1)} />
    </main>
  );
}
