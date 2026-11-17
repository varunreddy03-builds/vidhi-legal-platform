import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import ConfirmDeleteDialog from "@/components/ConfirmDeleteDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useCan } from "@/lib/useMe";

interface ClientRow {
  id: string;
  name: string;
  kind: "INDIVIDUAL" | "COMPANY" | "OTHER";
  email: string;
  phone: string;
  address: string;
  notes: string;
  matter_count?: number;
}
interface ClientDetail extends ClientRow {
  matters: { id: string; title: string; status: string }[];
}

const KIND: Record<string, string> = { INDIVIDUAL: "Person", COMPANY: "Company or firm", OTHER: "Other" };
const EMPTY = { name: "", kind: "INDIVIDUAL" as ClientRow["kind"], email: "", phone: "", address: "", notes: "" };
const SELECT = "h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring dark:bg-input/30";

function Form({ initial, submitLabel, busy, onSubmit, onCancel }: { initial: typeof EMPTY; submitLabel: string; busy: boolean; onSubmit: (v: typeof EMPTY) => void; onCancel?: () => void }) {
  const [v, setV] = useState(initial);
  const set = <K extends keyof typeof EMPTY>(k: K, val: (typeof EMPTY)[K]) => setV((p) => ({ ...p, [k]: val }));
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(v);
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="cl-name">Name</Label>
          <Input id="cl-name" value={v.name} onChange={(e) => set("name", e.target.value)} required maxLength={200} data-testid="client-name" />
        </div>
        <div>
          <Label htmlFor="cl-kind">Kind</Label>
          <select id="cl-kind" value={v.kind} onChange={(e) => set("kind", e.target.value as ClientRow["kind"])} className={SELECT} data-testid="client-kind">
            {Object.entries(KIND).map(([k, label]) => (
              <option key={k} value={k} className="bg-popover">
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="cl-email">Email</Label>
          <Input id="cl-email" type="email" value={v.email} onChange={(e) => set("email", e.target.value)} maxLength={200} data-testid="client-email" />
        </div>
        <div>
          <Label htmlFor="cl-phone">Phone</Label>
          <Input id="cl-phone" value={v.phone} onChange={(e) => set("phone", e.target.value)} maxLength={40} data-testid="client-phone" />
        </div>
      </div>
      <div>
        <Label htmlFor="cl-address">Address</Label>
        <Textarea id="cl-address" rows={2} value={v.address} onChange={(e) => set("address", e.target.value)} maxLength={1000} />
      </div>
      <div>
        <Label htmlFor="cl-notes">Private notes</Label>
        <Textarea id="cl-notes" rows={3} value={v.notes} onChange={(e) => set("notes", e.target.value)} maxLength={5000} data-testid="client-notes" />
        <p className="mt-1 text-xs text-muted-foreground">Only people in your firm see this. It is not shared with the client and is not sent to any AI.</p>
      </div>
      <div className="flex gap-2">
        <Button type="submit" loading={busy} data-testid="client-save">
          {submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

function Detail({ id, onGone }: { id: string; onGone: () => void }) {
  const qc = useQueryClient();
  const canWrite = useCan("write");
  const canDelete = useCan("delete");
  const detail = useQuery({ queryKey: ["client", id], queryFn: () => apiGet<ClientDetail>(`/clients/${id}`) });
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["client", id] }), qc.invalidateQueries({ queryKey: ["clients"] })]);
  const save = useMutation({
    mutationFn: (v: typeof EMPTY) => apiPatch<ClientRow>(`/clients/${id}`, v),
    onSuccess: async () => {
      await refresh();
      setEditing(false);
      toast.success("Client saved");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const remove = useMutation({
    mutationFn: () => apiDelete(`/clients/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["clients"] });
      toast.success("Client deleted");
      onGone();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const c = detail.data;
  if (!c) return <p className="text-sm text-muted-foreground">{detail.isError ? "This client could not be loaded." : "Loading…"}</p>;
  if (editing) return <Form initial={{ name: c.name, kind: c.kind, email: c.email, phone: c.phone, address: c.address, notes: c.notes }} submitLabel="Save changes" busy={save.isPending} onSubmit={(v) => save.mutate(v)} onCancel={() => setEditing(false)} />;
  return (
    <div className="space-y-3" data-testid="client-detail">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg">{c.name}</h3>
          <p className="text-xs text-muted-foreground">{KIND[c.kind]}</p>
        </div>
        <div className="flex gap-2">
          {canWrite && (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)} data-testid="client-edit">
              Edit
            </Button>
          )}
          {canDelete && (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)} data-testid="client-delete">
              Delete
            </Button>
          )}
        </div>
      </div>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="text-xs text-muted-foreground">Email</dt><dd>{c.email || "-"}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Phone</dt><dd>{c.phone || "-"}</dd></div>
        <div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Address</dt><dd className="whitespace-pre-wrap">{c.address || "-"}</dd></div>
        <div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Private notes</dt><dd className="whitespace-pre-wrap">{c.notes || "-"}</dd></div>
      </dl>
      <ConfirmDeleteDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete this client?"
        description={c.matters.length ? "Matters are still linked to this client. Open each matter and choose another client first." : "The client record is removed. Matters and documents are not affected. Type the client's name to confirm."}
        confirmWord={c.name}
        pending={remove.isPending}
        canConfirm={c.matters.length === 0}
        onConfirm={() => remove.mutate()}
        testId="client-delete-dialog"
      />
      <div>
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Matters</h4>
        {c.matters.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">No matters yet. Open a matter and choose this client under its details.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {c.matters.map((m) => (
              <li key={m.id}>
                <Link className="underline" to={`/matters/${m.id}`}>
                  {m.title}
                </Link>{" "}
                <span className="text-xs text-muted-foreground">({m.status.toLowerCase().replace("_", " ")})</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function Clients() {
  const qc = useQueryClient();
  const canWrite = useCan("write");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const list = useQuery({ queryKey: ["clients", q], queryFn: () => apiGet<ClientRow[]>(`/clients?q=${encodeURIComponent(q)}`) });
  const create = useMutation({
    mutationFn: (v: typeof EMPTY) => apiPost<ClientRow>("/clients", v),
    onSuccess: async (c) => {
      await qc.invalidateQueries({ queryKey: ["clients"] });
      setAdding(false);
      setOpen(c.id);
      toast.success("Client added");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const rows = list.data ?? [];
  return (
    <AppShell title="Clients">
      <div className="mx-auto max-w-5xl space-y-6" data-testid="clients-page">
        <div>
          <h2 className="text-2xl">Clients</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Who your firm acts for, with contact details and private notes, and which matters are theirs. Kept inside your firm.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, email or phone" aria-label="Search clients" className="max-w-xs" data-testid="client-search" />
          {canWrite && (
            <Button onClick={() => { setAdding(true); setOpen(null); }} data-testid="client-add">
              Add a client
            </Button>
          )}
        </div>
        <div className="grid gap-6 md:grid-cols-[18rem_1fr]">
          <ul className="space-y-1" aria-label="Clients">
            {rows.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => { setOpen(c.id); setAdding(false); }}
                  aria-current={open === c.id}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${open === c.id ? "border-ring bg-muted/50" : ""}`}
                  data-testid="client-row"
                >
                  <span className="block font-medium">{c.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {KIND[c.kind]} · {c.matter_count ?? 0} matter{c.matter_count === 1 ? "" : "s"}
                  </span>
                </button>
              </li>
            ))}
            {!list.isLoading && rows.length === 0 && <li className="text-sm text-muted-foreground">{q ? "No client matches that search." : "No clients yet."}</li>}
          </ul>
          <div className="glass rounded-lg p-4">
            {adding ? (
              <Form initial={EMPTY} submitLabel="Add client" busy={create.isPending} onSubmit={(v) => create.mutate(v)} onCancel={() => setAdding(false)} />
            ) : open ? (
              <Detail key={open} id={open} onGone={() => setOpen(null)} />
            ) : (
              <p className="text-sm text-muted-foreground">Choose a client, or add one.</p>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
