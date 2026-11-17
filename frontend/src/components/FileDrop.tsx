import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { NetworkError } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { UploadAborted, uploadWithProgress } from "@/lib/upload";

type Props<T> = {
  /** API path after /api, for example `/matters/ID/documents`. */
  path: string;
  accept: string;
  fields?: Record<string, string>;
  /** Called with the server's answer once the file is accepted. */
  onDone: (result: T, file: File) => void | Promise<void>;
  idleLabel: string;
  hint?: string;
  testId: string;
};

/** One place to add a file: tap to open the phone's file picker (Files on iPhone, Documents on Android), press Enter or Space on a laptop, or drag a file onto it.
 * Shows progress, repeats on its own after a weak-network failure, and keeps the file so one tap retries. The input keeps the id `${testId}-input` for tests. */
export default function FileDrop<T>({ path, accept, fields, onDone, idleLabel, hint, testId }: Props<T>) {
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [percent, setPercent] = useState(0);
  const [note, setNote] = useState("");
  const [failed, setFailed] = useState<File | null>(null);
  const [over, setOver] = useState(false);

  async function send(file: File) {
    abort.current = new AbortController();
    setBusy(true);
    setFailed(null);
    setNote("");
    setPercent(0);
    try {
      const result = await uploadWithProgress<T>(path, file, {
        fields,
        signal: abort.current.signal,
        onProgress: setPercent,
        onRetry: (n) => setNote(`The connection is weak. Trying again (${n})…`),
      });
      setNote("");
      await onDone(result, file);
    } catch (e) {
      if (e instanceof UploadAborted) {
        setNote("Cancelled.");
      } else if (e instanceof NetworkError) {
        // the line dropped: the file is kept on this screen and goes again by itself when the connection returns
        setFailed(file);
        const msg = "Your file was not sent: the connection dropped. It is kept here and will be sent again when you are back online, or tap Try again.";
        setNote(msg);
        toast.error("The connection dropped. Your file is kept and will be sent again when you are back online.");
      } else {
        setFailed(file);
        setNote(describe(e));
        toast.error(describe(e));
      }
    } finally {
      setBusy(false);
    }
  }

  // the latest send, so the listener below never calls a stale one
  const resend = useRef(send);
  resend.current = send;
  useEffect(() => {
    if (!failed || !note.startsWith("Your file was not sent")) return;
    const again = () => void resend.current(failed);
    window.addEventListener("online", again, { once: true });
    return () => window.removeEventListener("online", again);
  }, [failed, note]);

  const pick = (list: FileList | null) => {
    const f = list?.[0];
    if (f && !busy) void send(f);
  };

  return (
    <div className="space-y-2">
      <input ref={input} type="file" accept={accept} className="hidden" data-testid={`${testId}-input`} tabIndex={-1} aria-hidden="true" onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
      <div
        role="button"
        tabIndex={0}
        aria-disabled={busy}
        aria-describedby={`${testId}-status`}
        data-testid={testId}
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); input.current?.click(); }
        }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
        className={`glass flex min-h-[88px] cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed p-4 text-center text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring ${over ? "border-foreground" : "border-border"} ${busy ? "cursor-progress opacity-80" : ""}`}
      >
        <span className="font-medium">{busy ? `Uploading… ${percent}%` : idleLabel}</span>
        {!busy && <span className="text-xs text-muted-foreground">{hint ?? "Tap to choose a file, or drag one here."}</span>}
        {busy && (
          <span className="mt-1 h-1.5 w-full max-w-xs overflow-hidden rounded bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Upload progress">
            <span className="block h-full bg-foreground transition-all" style={{ width: `${percent}%` }} />
          </span>
        )}
      </div>
      <p id={`${testId}-status`} className="min-h-[1.25rem] text-xs text-muted-foreground" role="status" aria-live="polite" data-testid={`${testId}-status`}>
        {note}
      </p>
      <div className="flex gap-2">
        {busy && (
          <Button size="sm" variant="outline" onClick={() => abort.current?.abort()} data-testid={`${testId}-cancel`}>
            Cancel
          </Button>
        )}
        {failed && !busy && (
          <Button size="sm" variant="outline" onClick={() => void send(failed)} data-testid={`${testId}-retry`}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
