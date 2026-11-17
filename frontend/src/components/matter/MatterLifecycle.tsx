import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import ConfirmDeleteDialog from "@/components/ConfirmDeleteDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDelete, apiPatch } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { Matter } from "@/lib/types";
import { useCan } from "@/lib/useMe";

/** Close / reopen, legal hold (admins) and permanent deletion (roles that may delete). */
export default function MatterLifecycle({ matter }: { matter: Matter }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const canDelete = useCan("delete");
  const canHold = useCan("admin");
  const [open, setOpen] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["matter", matter.id] });

  const setStatus = useMutation({
    mutationFn: (status: Matter["status"]) => apiPatch(`/matters/${matter.id}`, { status }),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });
  const hold = useMutation({
    mutationFn: (on: boolean) => apiPatch(`/matters/${matter.id}/legal-hold`, { on }),
    onSuccess: async (_d, on) => {
      await refresh();
      toast.success(on ? "Legal hold on: this matter cannot be deleted" : "Legal hold removed");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const del = useMutation({
    mutationFn: () => apiDelete(`/matters/${matter.id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["matters"] });
      toast.success("Matter deleted");
      navigate("/matters", { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  const closed = matter.status === "CLOSED";
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="matter-lifecycle">
      {closed ? (
        <Button size="xs" variant="outline" disabled={setStatus.isPending} onClick={() => setStatus.mutate("OPEN")} data-testid="matter-reopen">
          Reopen matter
        </Button>
      ) : (
        <Button size="xs" variant="outline" disabled={setStatus.isPending} onClick={() => setStatus.mutate("CLOSED")} data-testid="matter-close">
          Close matter
        </Button>
      )}
      {matter.legal_hold && (
        <Badge variant="outline" style={{ color: "#F0A63A" }} data-testid="legal-hold-badge">
          Legal hold
        </Badge>
      )}
      {canHold && (
        <Button size="xs" variant="ghost" disabled={hold.isPending} onClick={() => hold.mutate(!matter.legal_hold)} data-testid="legal-hold-toggle">
          {matter.legal_hold ? "Remove legal hold" : "Place on legal hold"}
        </Button>
      )}
      {canDelete && (
        <Button size="xs" variant="ghost" onClick={() => setOpen(true)} disabled={matter.legal_hold} data-testid="matter-delete">
          Delete…
        </Button>
      )}
      {matter.deletion_notice_at && (
        <p className="w-full text-xs text-muted-foreground" data-testid="deletion-notice">
          Scheduled for automatic deletion (notice sent {formatDate(matter.deletion_notice_at)}). Reopen it or place it on legal hold to keep it.
        </p>
      )}
      <ConfirmDeleteDialog
        open={open}
        onOpenChange={setOpen}
        title="Delete this matter?"
        description="Its documents, facts, timeline, evidence, research and drafts are deleted for good. The activity log keeps a line saying it happened."
        confirmWord={matter.title}
        pending={del.isPending}
        onConfirm={() => del.mutate()}
      />
    </div>
  );
}
