import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiDelete, apiGet, apiPatch, NetworkError } from "@/lib/api";
import { AUTOSAVE_AFTER_MS, clearLocal, differsFromSaved, readLocal, statusText, writeLocal, type LocalCopy, type SaveState } from "@/lib/autosave";
import type { Draft } from "@/lib/types";
import { describe } from "@/lib/interaction";
import { DraftChecks, type DraftFlag } from "@/components/DraftChecks";
import { DraftReview } from "@/components/DraftReview";

/** Items a template left open: [LAWYER TO CONFIRM: ...] and [... - to be filled]. */
const openItems = (text: string) => (text.match(/\[(?:LAWYER[^\]\n]{0,200}|[^\]\n]{3,120} - to be filled)\]/g) ?? []).length;

export default function DraftEditor() {
  const { draftId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);
  const [guardOpen, setGuardOpen] = useState(false);
  const [state, setState] = useState<SaveState>("saved");
  const [offered, setOffered] = useState<LocalCopy | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const latest = useRef({ title: "", body: "" });
  latest.current = { title, body };

  const draft = useQuery<Draft>({
    queryKey: ["draft", draftId],
    queryFn: () => apiGet<Draft>(`/drafts/${draftId}`),
  });

  useEffect(() => {
    if (draft.data && !dirty) {
      setTitle(draft.data.title);
      setBody(draft.data.body);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.data]);

  // Text typed on this device that never reached the server (the line dropped, the tab was closed): offered back once, when the saved draft has loaded.
  const offerChecked = useRef(false);
  useEffect(() => {
    if (!draft.data || offerChecked.current) return;
    offerChecked.current = true;
    const local = readLocal(draftId);
    if (differsFromSaved(local, draft.data)) setOffered(local);
    else clearLocal(draftId);
  }, [draft.data, draftId]);

  // While there are unsaved changes, a copy is kept on the device a moment after each keystroke.
  useEffect(() => {
    if (!dirty) return;
    const id = window.setTimeout(() => writeLocal(draftId, title, body), 400);
    return () => window.clearTimeout(id);
  }, [dirty, title, body, draftId]);

  const autosave = useMutation({
    mutationFn: (sent: { title: string; body: string }) => apiPatch<Draft>(`/drafts/${draftId}`, { ...sent, autosave: true }).then(() => sent),
    onMutate: () => setState("saving"),
    onSuccess: (sent) => {
      // only "saved" if nothing more was typed while the request was out
      if (sent.title === latest.current.title && sent.body === latest.current.body) {
        setDirty(false);
        setState("saved");
        clearLocal(draftId);
      } else setState("dirty");
    },
    onError: (e) => setState(e instanceof NetworkError || navigator.onLine === false ? "offline" : "failed"),
  });

  // A few seconds after the last keystroke the text goes to the server by itself; when the connection returns, anything waiting goes at once.
  const run = () => {
    if (navigator.onLine === false) setState("offline");
    else autosave.mutate({ ...latest.current });
  };
  const runRef = useRef(run);
  runRef.current = run;
  useEffect(() => {
    if (!dirty || offered) return;
    if (navigator.onLine === false) {
      setState("offline");
      return;
    }
    setState((s) => (s === "saving" ? s : "dirty"));
    const id = window.setTimeout(() => runRef.current(), AUTOSAVE_AFTER_MS);
    return () => window.clearTimeout(id);
  }, [dirty, title, body, offered]);
  useEffect(() => {
    const online = () => {
      if (dirtyRef.current) runRef.current();
    };
    const offline = () => {
      if (dirtyRef.current) setState("offline");
    };
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => {
    function warn(e: BeforeUnloadEvent) {
      if (dirty) e.preventDefault();
    }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useMutation({
    mutationFn: () => apiPatch<Draft>(`/drafts/${draftId}`, { title, body }),
    onSuccess: async () => {
      setDirty(false);
      setState("saved");
      clearLocal(draftId);
      await qc.invalidateQueries({ queryKey: ["draft", draftId] });
      await qc.invalidateQueries({ queryKey: ["drafts"] });
      toast.success("Draft saved");
    },
    onError: (e) => {
      setState(e instanceof NetworkError || navigator.onLine === false ? "offline" : "failed");
      toast.error(describe(e));
    },
  });

  const remove = useMutation({
    mutationFn: () => apiDelete(`/drafts/${draftId}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["drafts"] });
      toast.success("Draft deleted");
      navigate("/drafts");
    },
    onError: (e) => toast.error(describe(e)),
  });

  function leave() {
    if (dirty) setGuardOpen(true);
    else navigate("/drafts");
  }

  return (
    <AppShell title={draft.data?.title ?? "Draft"}>
      <div className="mx-auto max-w-3xl">
        <Button
          variant="ghost"
          size="sm"
          onClick={leave}
          className="mb-4"
          data-testid="draft-back-button"
        >
          ← Back to drafts
        </Button>
        {draft.data?.template_id && (
          <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note" data-testid="template-banner">
            <p className="font-medium">
              {draft.data.template_review?.reviewed
                ? `Built from a template whose wording was reviewed by ${draft.data.template_review.reviewed_by} on ${draft.data.template_review.reviewed_on}.`
                : "Built from a template that no lawyer has reviewed yet."}
            </p>
            <p className="mt-1 text-muted-foreground">
              Check every line against your facts and the law that applies before anyone signs or sends it.{" "}
              {openItems(body) > 0 ? `${openItems(body)} item(s) in [square brackets] still need to be filled in or confirmed.` : "No items in [square brackets] are left."}
            </p>
          </div>
        )}
        {offered && (
          <div className="mb-4 rounded-lg border border-border p-3 text-sm" role="alert" data-testid="draft-restore">
            <p>This phone holds text for this draft that was never saved. Bring it back?</p>
            <div className="mt-2 flex gap-2">
              <Button
                size="sm"
                data-testid="draft-restore-yes"
                onClick={() => {
                  setTitle(offered.title);
                  setBody(offered.body);
                  setDirty(true);
                  setOffered(null);
                }}
              >
                Bring it back
              </Button>
              <Button
                size="sm"
                variant="outline"
                data-testid="draft-restore-no"
                onClick={() => {
                  clearLocal(draftId);
                  setOffered(null);
                }}
              >
                Discard it
              </Button>
            </div>
          </div>
        )}
        <Input
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setDirty(true);
          }}
          className="font-heading text-lg"
          aria-label="Draft title"
          data-testid="draft-editor-title"
        />
        <Textarea
          value={body}
          onChange={(e) => {
            setBody(e.target.value);
            setDirty(true);
          }}
          rows={18}
          ref={bodyRef}
          className="mt-4"
          placeholder="Draft your submission. Link statements to verified sources from Research."
          aria-label="Draft text"
          data-testid="draft-editor-body"
        />
        <div className="mt-4 flex items-center gap-3">
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || !dirty}
            data-testid="draft-save-button"
          >
            {save.isPending ? "Saving…" : dirty ? "Save" : "Saved"}
          </Button>
          <Button
            variant="destructive"
            onClick={() => remove.mutate()}
            data-testid="draft-delete-button"
          >
            Delete
          </Button>
          <span className="text-xs text-muted-foreground">
            Version {draft.data?.version ?? 1}
          </span>
        </div>
        <p role="status" aria-live="polite" className="mt-2 text-xs text-muted-foreground" data-testid="draft-status">
          {statusText(state)}
        </p>
        <DraftReview draftId={draftId} dirty={dirty} refreshKey={draft.data?.updated_at} />
        <DraftChecks
          draftId={draftId}
          getText={() => latest.current.body}
          onJump={(f: DraftFlag) => {
            const box = bodyRef.current;
            if (!box) return;
            box.focus();
            box.setSelectionRange(Math.min(f.start, box.value.length), Math.min(f.end, box.value.length));
            // a text area does not scroll to a selection by itself: put the line near the top of the box
            const lineHeight = parseFloat(getComputedStyle(box).lineHeight) || 20;
            box.scrollTop = Math.max(0, (f.line - 3) * lineHeight);
            box.scrollIntoView({ block: "nearest" });
          }}
        />
      </div>

      <Dialog open={guardOpen} onOpenChange={setGuardOpen}>
        <DialogContent data-testid="unsaved-changes-dialog">
          <DialogHeader>
            <DialogTitle>You have unsaved changes. Leave without saving?</DialogTitle>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setGuardOpen(false)} data-testid="guard-stay">
              Stay
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate("/drafts")}
              data-testid="guard-discard"
            >
              Discard
            </Button>
            <Button
              onClick={async () => {
                await save.mutateAsync();
                navigate("/drafts");
              }}
              data-testid="guard-save-leave"
            >
              Save &amp; leave
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
