import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";

interface State {
  clients: { id: string; email: string; name: string; since: string; pending: boolean }[];
  updates: { id: string; text: string; by: string; at: string }[];
  shared_document_ids: string[];
  notice: string;
}

/** The firm's side of the client portal for one matter: who can see it, what was written for them, which documents are shared. */
export default function ClientPortalPanel({ matterId, docs }: { matterId: string; docs: { id: string; filename: string }[] }) {
  const qc = useQueryClient();
  const key = ["portal", matterId];
  const state = useQuery({ queryKey: key, queryFn: () => apiGet<State>(`/matters/${matterId}/portal`) });
  const [email, setEmail] = useState("");
  const [text, setText] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const fail = (e: unknown) => toast.error(describe(e));

  const invite = useMutation({
    mutationFn: () => apiPost<{ pending: boolean }>(`/matters/${matterId}/portal/clients`, { email }),
    onSuccess: (r) => {
      setEmail("");
      toast.success(r.pending ? "Invitation sent." : "Access added.");
      void refresh();
    },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => apiDelete(`/matters/${matterId}/portal/clients/${id}`), onSuccess: () => void refresh(), onError: fail });
  const post = useMutation({
    mutationFn: () => apiPost(`/matters/${matterId}/portal/updates`, { text }),
    onSuccess: () => {
      setText("");
      toast.success("Update posted. Clients were told by email that something is new (the email does not contain it).");
      void refresh();
    },
    onError: fail,
  });
  const drop = useMutation({ mutationFn: (id: string) => apiDelete(`/matters/${matterId}/portal/updates/${id}`), onSuccess: () => void refresh(), onError: fail });
  const share = useMutation({
    mutationFn: (v: { id: string; on: boolean }) => (v.on ? apiPost(`/matters/${matterId}/portal/documents`, { document_id: v.id }) : apiDelete(`/matters/${matterId}/portal/documents/${v.id}`)),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const shared = new Set(state.data?.shared_document_ids ?? []);

  return (
    <div className="space-y-6" data-testid="client-portal-panel">
      <p className="text-sm text-muted-foreground">{state.data?.notice ?? "Clients see only the updates and documents you share here, read-only."}</p>

      <section className="glass space-y-3 rounded-lg p-4">
        <h3 className="text-lg">Clients with access to this matter</h3>
        {(state.data?.clients ?? []).map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-2 text-sm" data-testid="portal-client-row">
            <span>{c.email} <span className="text-xs text-muted-foreground">{c.pending ? "invited, not accepted yet" : "has access"}</span></span>
            <Button size="xs" variant="destructive" onClick={() => remove.mutate(c.id)}>{c.pending ? "Withdraw" : "Remove access"}</Button>
          </div>
        ))}
        {state.isSuccess && state.data.clients.length === 0 && <p className="text-sm text-muted-foreground">No client has access yet.</p>}
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <div className="min-w-60 flex-1 space-y-1.5">
            <Label htmlFor="portal-email">Invite a client by email</Label>
            <Input id="portal-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="portal-invite-email" />
          </div>
          <Button type="submit" loading={invite.isPending} data-testid="portal-invite-send">Send invitation</Button>
        </form>
        <p className="text-xs text-muted-foreground">The invitation does not mention the matter. A person who already has a VIDHI account with another firm cannot be invited.</p>
      </section>

      <section className="glass space-y-3 rounded-lg p-4">
        <h3 className="text-lg">Updates for clients</h3>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); post.mutate(); }}>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000} required placeholder="Write in plain words. Every client with access can read it." data-testid="portal-update-text" />
          <Button type="submit" loading={post.isPending} data-testid="portal-update-post">Post update</Button>
        </form>
        {(state.data?.updates ?? []).map((u) => (
          <div key={u.id} className="border-t border-border pt-2 text-sm">
            <p className="whitespace-pre-wrap">{u.text}</p>
            <p className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
              <span>{u.by} · {formatDateTime(u.at)}</span>
              <button className="underline" onClick={() => drop.mutate(u.id)}>Delete</button>
            </p>
          </div>
        ))}
      </section>

      <section className="glass space-y-2 rounded-lg p-4">
        <h3 className="text-lg">Documents shared with clients</h3>
        <p className="text-xs text-muted-foreground">Nothing is shared unless you switch it on. A client can download what you share.</p>
        {docs.map((d) => (
          <label key={d.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={shared.has(d.id)} onChange={(e) => share.mutate({ id: d.id, on: e.target.checked })} />
            {d.filename}
          </label>
        ))}
        {docs.length === 0 && <p className="text-sm text-muted-foreground">Upload documents on the Documents tab first.</p>}
      </section>
    </div>
  );
}