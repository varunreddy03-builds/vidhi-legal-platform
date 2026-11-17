import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api";

export interface DraftFlag {
  code: string;
  severity: "fix" | "look";
  message: string;
  start: number;
  end: number;
  line: number;
  snippet: string;
}
interface CheckResult {
  flags: DraftFlag[];
  counts: { fix: number; look: number };
  from_template: boolean;
  note: string;
}

/** "Check this draft": lists what looks unfinished or inconsistent, each item a button that jumps to the place in the text. It only points; it changes nothing. */
export function DraftChecks({ draftId, getText, onJump }: { draftId: string; getText: () => string; onJump: (flag: DraftFlag) => void }) {
  const check = useMutation({ mutationFn: () => apiPost<CheckResult>(`/drafts/${draftId}/check`, { body: getText() }) });
  const data = check.data;
  return (
    <section className="mt-6 rounded-lg border border-border p-3" aria-label="Check this draft" data-testid="draft-checks">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => check.mutate()} disabled={check.isPending} data-testid="draft-check-button">
          {check.isPending ? "Checking…" : "Check this draft"}
        </Button>
        <span className="text-xs text-muted-foreground">Look for blanks, unfinished items, names, dates and amounts that do not match. Nothing is changed.</span>
      </div>
      {check.isError && (
        <p role="alert" className="mt-2 text-sm text-destructive" data-testid="draft-check-error">
          The check did not run. Please try again.
        </p>
      )}
      {data && (
        <div role="status" aria-live="polite" className="mt-3" data-testid="draft-check-result">
          <p className="text-sm font-medium" data-testid="draft-check-summary">
            {data.flags.length === 0
              ? "Nothing found. This is not a check of the law or of your facts."
              : `${data.counts.fix} to fix, ${data.counts.look} to look at.`}
          </p>
          {data.flags.length > 0 && (
            <ul className="mt-2 space-y-1">
              {data.flags.map((f, i) => (
                <li key={`${f.code}-${f.start}-${i}`}>
                  <button
                    type="button"
                    onClick={() => onJump(f)}
                    className="min-h-11 w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent md:min-h-9"
                    data-testid="draft-check-item"
                    data-code={f.code}
                  >
                    <span className="font-medium">{f.severity === "fix" ? "Fix" : "Look"}</span>
                    {f.end > f.start ? ` · line ${f.line}` : ""} · {f.message}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-muted-foreground">{data.note}</p>
        </div>
      )}
    </section>
  );
}
