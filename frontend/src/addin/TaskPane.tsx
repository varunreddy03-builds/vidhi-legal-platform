import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { describe } from "@/lib/interaction";
import { GROUPS, STATUS_STYLE, analyze, commentText, comment, groupIssues, loadOffice, locate, readParagraphs, replaceTracked, type Analysis, type Issue, type Para } from "./wordService";

/** The VIDHI AI Checker task pane inside Word: scan the document, read the findings by group, click one to jump to it, add a comment or accept a reviewed suggestion as a tracked change.
 * Plain code on the server, no AI. Every finding only points to a place to look; a lawyer decides. */
export default function TaskPane() {
  const [ready, setReady] = useState<"loading" | "ready" | "not_word">("loading");
  const [paras, setParas] = useState<Para[]>([]);
  const [result, setResult] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState("");

  useEffect(() => {
    loadOffice().then(() => setReady("ready"), () => setReady("not_word"));
  }, []);

  const scan = useCallback(async () => {
    setBusy(true);
    setMessage("");
    try {
      const p = await readParagraphs();
      setParas(p);
      setResult(await analyze(p));
    } catch (e) {
      const text = describe(e);
      setMessage(/not authenticated|session/i.test(text) ? "Sign in to VIDHI first: open VIDHI in your browser, sign in, then press Scan again." : text);
    } finally {
      setBusy(false);
    }
  }, []);

  const run = async (fn: () => Promise<void>, done: string) => {
    try {
      await fn();
      setMessage(done);
    } catch (e) {
      setMessage(describe(e));
    }
  };

  if (ready === "loading") return <p className="p-4 text-sm text-muted-foreground">Opening…</p>;
  if (ready === "not_word") return <p className="p-4 text-sm" role="alert">This panel works inside Microsoft Word. Open a document in Word and open VIDHI AI Checker from the Home tab.</p>;

  const groups = result ? groupIssues(result.issues) : null;
  const card = (i: Issue) => (
    <li key={i.id} className={`rounded-lg border p-2 text-sm ${selected === i.id ? "border-primary" : ""}`} data-testid="addin-issue">
      <button type="button" className="w-full text-left" onClick={() => { setSelected(i.id); void run(() => locate(i, paras), "Selected in the document."); }} aria-label={`Go to: ${i.text}`}>
        {i.status_label && <span className={`mr-2 rounded border px-1 text-xs ${STATUS_STYLE[i.status_label].className}`}>{STATUS_STYLE[i.status_label].text}</span>}
        <span className="font-medium">{i.text || "(empty)"}</span>
        <span className="mt-1 block text-xs text-muted-foreground">{i.message}</span>
      </button>
      {i.reviewer_source_note && <p className="mt-1 text-xs text-muted-foreground">{i.reviewer_source_note}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {i.suggested_replacement && (
          <Button size="xs" variant="outline" onClick={() => run(() => replaceTracked(i, paras, i.suggested_replacement!), "Replaced with Track Changes on. Accept or reject it in Word.")}>
            Replace with {i.suggested_replacement}
          </Button>
        )}
        <Button size="xs" variant="ghost" onClick={() => run(() => comment(i, paras, commentText(i)), "Comment added in the document.")}>
          Add comment
        </Button>
      </div>
    </li>
  );

  return (
    <div className="space-y-3 p-3" data-testid="addin-pane">
      <h1 className="text-base font-medium">VIDHI AI Checker</h1>
      <p className="text-xs text-muted-foreground">Points to places to look. It does not say anything is wrong, and a lawyer decides.</p>
      <Button onClick={scan} disabled={busy} data-testid="addin-scan">{busy ? "Scanning…" : "Scan document"}</Button>
      {message && <p className="text-xs" role="status" data-testid="addin-message">{message}</p>}
      {result && groups && (
        <>
          {Object.entries(result.checks).filter(([, v]) => v !== "ran").map(([k, v]) => (
            <p key={k} className="text-xs text-muted-foreground">The {k.replace("_", " ")} check did not run on this server ({v.replace(/_/g, " ")}). Nothing is claimed about it.</p>
          ))}
          {GROUPS.map((g) => (
            <section key={g.key} aria-label={g.title}>
              <h2 className="text-sm font-medium">{g.title} <span className="text-xs text-muted-foreground">({groups[g.key].length})</span></h2>
              {groups[g.key].length ? <ul className="mt-1 space-y-2">{groups[g.key].map(card)}</ul> : <p className="text-xs text-muted-foreground">Nothing pointed out.</p>}
            </section>
          ))}
          <section aria-label="List of dates">
            <h2 className="text-sm font-medium">List of dates <span className="text-xs text-muted-foreground">({result.dates.length})</span></h2>
            <ul className="mt-1 space-y-1">
              {result.dates.map((d, n) => (
                <li key={n} className="text-sm">
                  <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => void run(() => locate({ paragraph_id: d.paragraph_id, start_index: d.start_index, text: d.text }, paras), "Selected in the document.")}>
                    {d.date ?? "?"} <span className="text-xs text-muted-foreground">as written “{d.text}”, {d.paragraph_id.replace("p", "paragraph ")}{d.flags.length ? `. ${d.flags.join(" ")}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <p className="text-xs text-muted-foreground">{result.caveat}</p>
        </>
      )}
    </div>
  );
}
