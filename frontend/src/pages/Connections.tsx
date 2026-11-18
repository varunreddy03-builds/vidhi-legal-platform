import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { Matter } from "@/lib/types";

type Conn = { id: string; name: string; state: "available" | "connected" | "not_connected" | "not_configured" | "not_available"; does: string; setup: string[]; account?: string | null; page?: string };
type FileItem = { id: string; name: string; size: number; folder: boolean; modified: string };
type Mail = { id: string; subject: string; from: string; received: string; preview: string };

const STATE_TEXT: Record<Conn["state"], string> = { available: "Available", connected: "Connected", not_connected: "Not connected", not_configured: "Not set up on this site", not_available: "Not available" };
const MESSAGE: Record<string, string> = { connected: "Connected to Microsoft 365.", cancelled: "The Microsoft sign-in was cancelled. Nothing was connected.", failed: "Microsoft sign-in did not complete. Please try again." };

function Microsoft({ conn }: { conn: Conn }) {
  const qc = useQueryClient();
  const [folder, setFolder] = useState<string | undefined>();
  const [matter, setMatter] = useState("");
  const on = conn.state === "connected";
  const matters = useQuery<Matter[]>({ queryKey: ["matters"], queryFn: () => apiGet<Matter[]>("/matters"), enabled: on });
  const files = useQuery<{ items: FileItem[] }>({ queryKey: ["ms-files", folder], queryFn: () => apiGet(`/connectors/microsoft/files${folder ? `?folder=${encodeURIComponent(folder)}` : ""}`), enabled: on, retry: false });
  const mail = useQuery<{ items: Mail[] }>({ queryKey: ["ms-mail"], queryFn: () => apiGet("/connectors/microsoft/mail"), enabled: on, retry: false });
  const disconnect = useMutation({ mutationFn: () => apiDelete("/connectors/microsoft"), onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }), onError: (e) => toast.error(describe(e)) });
  const imp = useMutation({
    mutationFn: (v: { kind: "file" | "mail"; id: string }) => apiPost(`/matters/${matter}/connectors/microsoft/import`, v),
    onSuccess: () => toast.success("Copied into the matter"),
    onError: (e) => toast.error(describe(e)),
  });
  const select = "h-9 w-full max-w-sm rounded-lg border border-input bg-background px-2 text-sm";
  return (
    <>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!on && conn.state === "not_connected" && <a href="/api/connectors/microsoft/start" className="inline-flex h-9 items-center rounded-lg bg-primary px-3 text-sm text-primary-foreground" data-testid="ms-connect">Connect Microsoft 365</a>}
        {on && <Button type="button" variant="outline" onClick={() => disconnect.mutate()} data-testid="ms-disconnect">Disconnect</Button>}
        {on && conn.account && <span className="text-sm text-muted-foreground" data-testid="ms-account">{conn.account}</span>}
      </div>
      {conn.state === "not_configured" && <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground" data-testid="ms-setup">{conn.setup.map((s) => <li key={s}>{s}</li>)}</ul>}
      {on && (
        <div className="mt-4 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="ms-matter">Copy into this matter</Label>
            <select id="ms-matter" className={select} value={matter} onChange={(e) => setMatter(e.target.value)} data-testid="ms-matter">
              <option value="">Choose a matter…</option>
              {(matters.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.kind === "VAULT" ? `Vault: ${m.title}` : m.title}</option>)}
            </select>
          </div>
          <section aria-labelledby="ms-files-h">
            <h4 id="ms-files-h" className="font-medium">Files{folder ? <button type="button" className="ml-3 text-sm font-normal underline" onClick={() => setFolder(undefined)}>Back to the top</button> : null}</h4>
            {files.isError && <p className="text-sm text-muted-foreground">{describe(files.error)}</p>}
            <ul className="mt-1 space-y-1 text-sm" data-testid="ms-files">
              {(files.data?.items ?? []).map((f) => (
                <li key={f.id} className="flex flex-wrap items-center gap-2">
                  {f.folder ? <button type="button" className="underline" onClick={() => setFolder(f.id)}>{f.name}/</button> : <span className="break-all">{f.name}</span>}
                  {!f.folder && <Button type="button" size="sm" variant="outline" disabled={!matter || imp.isPending} onClick={() => imp.mutate({ kind: "file", id: f.id })} data-testid="ms-import-file">Copy in</Button>}
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="ms-mail-h">
            <h4 id="ms-mail-h" className="font-medium">Recent mail</h4>
            {mail.isError && <p className="text-sm text-muted-foreground">{describe(mail.error)}</p>}
            <ul className="mt-1 space-y-2 text-sm" data-testid="ms-mail">
              {(mail.data?.items ?? []).map((m) => (
                <li key={m.id} className="flex flex-wrap items-start justify-between gap-2">
                  <span><span className="font-medium">{m.subject}</span><span className="block text-muted-foreground">{m.from}: {m.preview}</span></span>
                  <Button type="button" size="sm" variant="outline" disabled={!matter || imp.isPending} onClick={() => imp.mutate({ kind: "mail", id: m.id })} data-testid="ms-import-mail">Copy in</Button>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-muted-foreground">A mail is copied as text (who, when, subject and body). Attachments are not copied.</p>
          </section>
        </div>
      )}
    </>
  );
}

export default function Connections() {
  const [params] = useSearchParams();
  const flag = params.get("microsoft");
  const q = useQuery<{ connections: Conn[]; note: string }>({ queryKey: ["connections"], queryFn: () => apiGet("/connectors") });
  return (
    <AppShell title="Connections">
      <div className="mx-auto max-w-4xl vidhi-rise">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Settings</p>
        <h2 className="mt-1 text-3xl tracking-tight">Connections</h2>
        <p className="mt-2 text-sm text-muted-foreground">{q.data?.note ?? "Every connection is read-only and uses your own account."}</p>
        {flag && MESSAGE[flag] && <p className="glass mt-4 rounded-xl p-3 text-sm" role="status" data-testid="ms-flash">{MESSAGE[flag]}</p>}
        <div className="mt-6 space-y-4">
          {(q.data?.connections ?? []).map((c) => (
            <section key={c.id} className="glass rounded-xl p-5" data-testid={`conn-${c.id}`} aria-labelledby={`conn-h-${c.id}`}>
              <div className="flex flex-wrap items-center gap-2">
                <h3 id={`conn-h-${c.id}`} className="text-lg font-medium">{c.name}</h3>
                <Badge variant={c.state === "connected" || c.state === "available" ? "default" : "outline"} data-testid={`conn-state-${c.id}`}>{STATE_TEXT[c.state]}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{c.does}</p>
              {c.id === "microsoft" ? <Microsoft conn={c} /> : (
                <>
                  {c.setup.length > 0 && <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">{c.setup.map((s) => <li key={s}>{s}</li>)}</ul>}
                  {c.page && <Link to={c.page} className="mt-2 inline-block text-sm underline underline-offset-4">Open</Link>}
                </>
              )}
            </section>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
