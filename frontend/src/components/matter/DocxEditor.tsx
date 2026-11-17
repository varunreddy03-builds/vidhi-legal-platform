import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiGet, apiPost } from "@/lib/api";

type Paragraphs = { filename: string; paragraphs: string[]; truncated: boolean };

/** Edits the text of a matter's Word file. The edited text is saved as a NEW document in the same matter; the original is never changed.
 * Tables, headers and pictures are not shown and are carried over untouched. */
export default function DocxEditor({ docId, matterId, title, open, onClose }: { docId: string; matterId: string; title: string; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["docx-paragraphs", docId], queryFn: () => apiGet<Paragraphs>(`/documents/${docId}/paragraphs`), enabled: open, retry: false });
  const [text, setText] = useState<string[]>([]);
  useEffect(() => {
    if (q.data) setText(q.data.paragraphs);
  }, [q.data]);
  const changed = q.data ? text.map((t, i) => ({ index: i, text: t })).filter((e) => e.text !== q.data!.paragraphs[e.index]) : [];
  const save = useMutation({
    mutationFn: () => apiPost<{ filename: string; changed: number }>(`/documents/${docId}/edit-copy`, { edits: changed }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["documents", matterId] });
      toast.success(`Saved as a new document: ${r.filename}`);
      onClose();
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not save the edited copy"),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] w-[min(96vw,50rem)] max-w-none overflow-hidden sm:max-w-none" data-testid="docx-editor">
        <DialogHeader>
          <DialogTitle className="truncate">Edit: {title}</DialogTitle>
          <DialogDescription>Your changes are saved as a new document in this matter. The original file is unchanged. Tables, headers and pictures are kept as they are.</DialogDescription>
        </DialogHeader>
        {q.isError && <p role="alert" className="text-sm text-destructive">This Word file could not be opened for editing.</p>}
        {q.isLoading && <p className="text-sm text-muted-foreground">Opening…</p>}
        {q.data && (
          <>
            {q.data.truncated && <p className="text-xs text-muted-foreground">Only the first paragraphs are shown. Edit the rest in Word.</p>}
            <div className="max-h-[60vh] space-y-2 overflow-auto pr-1" role="region" tabIndex={0} aria-label="Paragraphs of the document">
              {text.map((t, i) => (
                <Textarea key={i} value={t} rows={Math.min(8, Math.max(1, Math.ceil(t.length / 90)))} maxLength={20000} aria-label={`Paragraph ${i + 1}`} className="text-sm" data-testid="docx-paragraph" onChange={(e) => setText((all) => all.map((x, j) => (j === i ? e.target.value : x)))} />
              ))}
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={!changed.length || save.isPending} onClick={() => save.mutate()} data-testid="docx-save">
                {save.isPending ? "Saving…" : "Save as new document"}
              </Button>
              <span className="text-xs text-muted-foreground" aria-live="polite">{changed.length ? `${changed.length} paragraph${changed.length === 1 ? "" : "s"} changed` : "No changes yet"}</span>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
