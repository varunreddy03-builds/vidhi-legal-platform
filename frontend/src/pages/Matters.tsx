import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { apiGet, apiPost } from "@/lib/api";
import type { Matter } from "@/lib/types";
import { describe } from "@/lib/interaction";

export default function Matters() {
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [parties, setParties] = useState("");
  const qc = useQueryClient();

  const matters = useQuery<Matter[]>({
    queryKey: ["matters"],
    queryFn: () => apiGet<Matter[]>("/matters"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiPost<Matter>("/matters", { title, description, parties, jurisdiction_id: "IN" }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["matters"] });
      await qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success("Matter created");
      setTitle("");
      setDescription("");
      setParties("");
      setOpen(false);
      params.delete("new");
      setParams(params, { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AppShell title="Matters">
      <div className="mx-auto max-w-5xl">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl">Matters</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Every matter is scoped to your organization.{" "}
              <Link to="/conflicts" className="underline underline-offset-4" data-testid="matters-conflicts-link">Check a name for conflicts</Link>{" · "}
              <Link to="/legal" className="underline underline-offset-4" data-testid="matters-legal-link">Look up a provision</Link>
            </p>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger
              render={<Button data-testid="new-matter-button">New matter</Button>}
            />
            <DialogContent data-testid="new-matter-dialog">
              <DialogHeader>
                <DialogTitle>New matter</DialogTitle>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  create.mutate();
                }}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="title">Title</Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                    data-testid="matter-title-input"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="parties">Parties</Label>
                  <Input
                    id="parties"
                    value={parties}
                    onChange={(e) => setParties(e.target.value)}
                    placeholder="Petitioner v. Respondent"
                    data-testid="matter-parties-input"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="desc">Description</Label>
                  <Textarea
                    id="desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    data-testid="matter-description-input"
                  />
                </div>
                <Button
                  type="submit"
                  disabled={create.isPending}
                  className="w-full"
                  data-testid="matter-submit-button"
                >
                  {create.isPending ? "Creating…" : "Create matter"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>

        <div className="mt-8 space-y-2">
          {matters.isLoading && <div className="glass h-16 rounded-lg vidhi-sweep" />}
          {matters.isError && (
            <p className="text-sm" style={{ color: "#F0A63A" }}>
              Could not load matters. Reload to retry.
            </p>
          )}
          {(matters.data ?? []).map((m) => (
            <Link
              key={m.id}
              to={`/matters/${m.id}`}
              data-testid="matter-row"
              className="glass flex items-center justify-between rounded-lg p-4 transition-transform duration-200 hover:translate-x-1"
            >
              <div className="min-w-0">
                <p className="truncate text-sm">{m.title}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {m.parties || "No parties recorded"}
                </p>
                {m.description?.trim() && (
                  <p className="line-clamp-2 break-words text-xs text-muted-foreground" data-testid="matter-row-description">
                    {m.description}
                  </p>
                )}
              </div>
              <Badge variant="outline">{m.status}</Badge>
            </Link>
          ))}
          {!matters.isLoading && !matters.isError && (matters.data ?? []).length === 0 && (
            <div className="glass rounded-lg p-10 text-center">
              <p className="text-sm text-muted-foreground">
                No matters yet — create one to start a workflow.
              </p>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
