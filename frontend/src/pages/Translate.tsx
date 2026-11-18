import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { ListenButton, VoiceInput } from "@/components/Voice";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost, apiUpload } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Languages = { languages: { code: string; name: string }[]; notes: string[]; max_chars: number };
type Result = { translation: string; language: string; language_name: string; checks: { ok: boolean; problems: string[] }; truncated: boolean; note: string };

// Translate text, and turn a recording into text first if that is what you have. Nothing is stored. The program checks that every number survived; the quality of the language is for a person to judge.
export default function Translate() {
  const [text, setText] = useState("");
  const [target, setTarget] = useState("hi");
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const langs = useQuery<Languages>({ queryKey: ["translate-languages"], queryFn: () => apiGet<Languages>("/translate/languages") });
  const max = langs.data?.max_chars ?? 12000;

  const run = useMutation({
    mutationFn: () => apiPost<Result>("/translate", { target, text }),
    onError: (e) => toast.error(describe(e)),
  });
  const result = run.data;

  async function transcribe(f: File | undefined) {
    if (!f) return;
    setBusy(true);
    try {
      const out = await apiUpload<{ text: string }>("/voice/transcribe", f);
      setText((cur) => (cur ? cur + "\n" : "") + out.text);
      toast.success("Recording written out as text");
    } catch (e) {
      toast.error(describe(e));
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }

  const select = "h-9 rounded-lg border border-input bg-background px-2 text-sm";
  return (
    <AppShell title="Translate">
      <div className="mx-auto max-w-4xl vidhi-rise">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Legal Intelligence</p>
        <h2 className="mt-1 text-3xl tracking-tight">Translate and transcribe</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground" data-testid="translate-notes">
          {(langs.data?.notes ?? []).map((n) => <li key={n}>{n}</li>)}
        </ul>

        <section className="glass mt-6 rounded-xl p-5" aria-labelledby="tr-in-h">
          <h3 id="tr-in-h" className="text-lg font-medium">Text</h3>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <VoiceInput onText={(t) => setText((cur) => (cur ? cur + " " : "") + t)} />
            <input ref={file} type="file" accept="audio/*" className="sr-only" aria-label="Choose a recording to write out as text" data-testid="translate-audio" onChange={(e) => void transcribe(e.target.files?.[0])} />
            <Button type="button" variant="outline" disabled={busy} onClick={() => file.current?.click()} data-testid="translate-audio-button">{busy ? "Reading the recording…" : "Write out a recording"}</Button>
          </div>
          <Label htmlFor="tr-text" className="sr-only">Text to translate</Label>
          <Textarea id="tr-text" className="mt-3" rows={9} maxLength={max} value={text} onChange={(e) => setText(e.target.value)} data-testid="translate-text" />
          <div className="mt-1 text-xs text-muted-foreground">{text.length} of {max} characters</div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Label htmlFor="tr-lang">Translate into</Label>
            <select id="tr-lang" className={select} value={target} onChange={(e) => setTarget(e.target.value)} data-testid="translate-target">
              {(langs.data?.languages ?? [{ code: "hi", name: "Hindi" }]).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
            <Button type="button" disabled={run.isPending || text.trim().length < 2} onClick={() => run.mutate()} data-testid="translate-run">{run.isPending ? "Translating…" : "Translate"}</Button>
          </div>
        </section>

        {result && (
          <section className="glass mt-6 rounded-xl p-5" aria-labelledby="tr-out-h" data-testid="translate-result">
            <h3 id="tr-out-h" className="text-lg font-medium">{result.language_name}</h3>
            <p className="mt-2 whitespace-pre-wrap text-sm" lang={result.language} data-testid="translate-output">{result.translation}</p>
            <div className="mt-3 text-sm" role="status" data-testid="translate-checks">
              {result.checks.ok ? <p>Every number in the original is still there.</p> : <ul className="list-disc pl-5">{result.checks.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
              <p className="mt-1 text-muted-foreground">{result.note}</p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => void navigator.clipboard.writeText(result.translation).then(() => toast.success("Copied"), () => toast.error("Could not copy"))} data-testid="translate-copy">Copy</Button>
              <ListenButton text={result.translation} />
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
