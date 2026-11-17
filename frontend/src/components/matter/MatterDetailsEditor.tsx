import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPatch } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { Matter } from "@/lib/types";
import { useCan } from "@/lib/useMe";

/** The matter's description, shown in full, with a way to change the title, parties and description after the matter was created. */
export default function MatterDetailsEditor({ matter }: { matter: Matter }) {
  const qc = useQueryClient();
  const canWrite = useCan("write");
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(matter.title);
  const [parties, setParties] = useState(matter.parties);
  const [description, setDescription] = useState(matter.description);
  const [clientId, setClientId] = useState(matter.client_id ?? "");
  const clients = useQuery({ queryKey: ["clients", ""], queryFn: () => apiGet<{ id: string; name: string }[]>("/clients"), enabled: canWrite });

  const save = useMutation({
    mutationFn: () => apiPatch<Matter>(`/matters/${matter.id}`, { title: title.trim(), parties, description, client_id: clientId }),
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ["matter", matter.id] }), qc.invalidateQueries({ queryKey: ["matters"] })]);
      setEditing(false);
      toast.success("Matter details saved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const start = () => {
    setTitle(matter.title);
    setParties(matter.parties);
    setDescription(matter.description);
    setClientId(matter.client_id ?? "");
    setEditing(true);
  };

  if (!editing) {
    return (
      <div className="mt-4 border-t border-border pt-4" data-testid="matter-details">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Description</h4>
          {canWrite && (
            <Button size="xs" variant="outline" onClick={start} data-testid="matter-edit-details">
              Edit details
            </Button>
          )}
        </div>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm" data-testid="matter-description">
          {matter.description?.trim() || "No description recorded."}
        </p>
      </div>
    );
  }

  return (
    <form
      className="mt-4 space-y-3 border-t border-border pt-4"
      data-testid="matter-details-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) save.mutate();
      }}
    >
      <div>
        <Label htmlFor="md-title">Title</Label>
        <Input id="md-title" value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} data-testid="matter-edit-title" />
      </div>
      <div>
        <Label htmlFor="md-parties">Parties</Label>
        <Input id="md-parties" value={parties} maxLength={5000} onChange={(e) => setParties(e.target.value)} data-testid="matter-edit-parties" />
      </div>
      <div>
        <Label htmlFor="md-client">Client</Label>
        <select
          id="md-client"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className="mt-1 h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring dark:bg-input/30"
          data-testid="matter-edit-client"
        >
          <option value="" className="bg-popover">
            No client chosen
          </option>
          {(clients.data ?? []).map((c) => (
            <option key={c.id} value={c.id} className="bg-popover">
              {c.name}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-muted-foreground">Client records are kept under More, Clients.</p>
      </div>
      <div>
        <Label htmlFor="md-desc">Description</Label>
        <textarea
          id="md-desc"
          value={description}
          maxLength={20000}
          rows={6}
          onChange={(e) => setDescription(e.target.value)}
          className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
          data-testid="matter-edit-description"
        />
        <p className="mt-1 text-xs text-muted-foreground">{description.length} / 20000 characters</p>
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={save.isPending || !title.trim()} data-testid="matter-edit-save">
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={save.isPending} onClick={() => setEditing(false)} data-testid="matter-edit-cancel">
          Cancel
        </Button>
      </div>
    </form>
  );
}
