import { useState } from "react";
import { formatDateTime } from "@/lib/format";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet, apiPost } from "@/lib/api";
import type { Draft } from "@/lib/types";
import { describe } from "@/lib/interaction";

export default function Drafts() {
  const [params] = useSearchParams();
  const [title, setTitle] = useState(params.get("new") === "1" ? "Untitled draft" : "");
  const qc = useQueryClient();

  const drafts = useQuery<Draft[]>({
    queryKey: ["drafts"],
    queryFn: () => apiGet<Draft[]>("/drafts"),
  });

  const create = useMutation({
    mutationFn: () => apiPost<Draft>("/drafts", { title, body: "" }),
    onSuccess: async () => {
      setTitle("");
      await qc.invalidateQueries({ queryKey: ["drafts"] });
      await qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success("Draft created");
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AppShell title="Drafts">
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl">Drafting</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Drafts stay editable by you. AI-assisted text is never authoritative legal advice.
        </p>
        <p className="mt-3 text-sm">
          <Link to="/templates" className="underline underline-offset-4" data-testid="drafts-templates-link">
            Start from a template
          </Link>{" "}
          <span className="text-muted-foreground">(rent agreement, loan agreement, NDA, cheque-return notice, employment letter)</span>
        </p>
        <form
          className="glass mt-6 flex gap-3 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="Draft title"
            data-testid="draft-title-input"
          />
          <Button type="submit" disabled={create.isPending} data-testid="create-draft-button">
            {create.isPending ? "Creating…" : "New draft"}
          </Button>
        </form>

        <div className="mt-6 space-y-2">
          {(drafts.data ?? []).map((d) => (
            <Link
              key={d.id}
              to={`/drafts/${d.id}`}
              className="glass block rounded-lg p-4 transition-transform duration-200 hover:translate-x-1"
              data-testid="draft-row"
            >
              <p className="text-sm">{d.title}</p>
              <p className="text-xs text-muted-foreground">
                v{d.version} · updated {formatDateTime(d.updated_at)}
              </p>
            </Link>
          ))}
          {!drafts.isLoading && (drafts.data ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">No drafts yet.</p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
