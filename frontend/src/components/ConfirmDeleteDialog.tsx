import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/**
 * Permanent deletions need a deliberate act: the person types the name of what they are deleting.
 * `extra` renders more fields (e.g. a password) and `canConfirm` lets the caller add its own conditions.
 */
export default function ConfirmDeleteDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmWord,
  confirmLabel = "Delete permanently",
  pending,
  canConfirm = true,
  extra,
  onConfirm,
  testId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmWord: string;
  confirmLabel?: string;
  pending: boolean;
  canConfirm?: boolean;
  extra?: React.ReactNode;
  onConfirm: () => void;
  testId?: string;
}) {
  const [typed, setTyped] = useState("");
  const inputId = useId();
  const ok = typed.trim() === confirmWord && canConfirm;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setTyped("");
        onOpenChange(o);
      }}
    >
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor={inputId} className="text-xs text-muted-foreground">
              Type <span className="font-semibold text-foreground">{confirmWord}</span> to confirm
            </label>
            <Input id={inputId} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" data-testid="confirm-delete-input" />
          </div>
          {extra}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={!ok || pending} onClick={onConfirm} data-testid="confirm-delete-button">
            {pending ? "Deleting…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
