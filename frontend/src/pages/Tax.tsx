import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { buildOutline, toLines } from "@/lib/taxOutline";
import type { Matter } from "@/lib/types";

function Field({ id, label, value, set, area }: { id: string; label: string; value: string; set: (v: string) => void; area?: boolean }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {area ? <Textarea id={id} value={value} onChange={(e) => set(e.target.value)} rows={4} data-testid={id} /> : <Input id={id} value={value} onChange={(e) => set(e.target.value)} data-testid={id} />}
    </div>
  );
}

export default function Tax() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [f, setF] = useState({ authority: "", reference: "", noticeDate: "", period: "", taxpayer: "", sectionNamed: "", points: "", documents: "" });
  const [outline, setOutline] = useState("");
  const up = (k: keyof typeof f) => (v: string) => setF((cur) => ({ ...cur, [k]: v }));

  const matters = useQuery<Matter[]>({ queryKey: ["matters"], queryFn: () => apiGet<Matter[]>("/matters") });
  const taxMatters = (matters.data ?? []).filter((m) => m.area === "tax" && m.kind !== "VAULT");
  const create = useMutation({
    mutationFn: () => apiPost<Matter>("/matters", { title: title.trim(), description: "", parties: "", jurisdiction_id: "IN", area: "tax" }),
    onSuccess: async (m) => {
      await qc.invalidateQueries({ queryKey: ["matters"] });
      navigate(`/matters/${m.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  const make = () => setOutline(buildOutline({ ...f, points: toLines(f.points), documents: toLines(f.documents) }));
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(outline);
      toast.success("Copied");
    } catch {
      toast.error("Could not copy. Select the text and copy it.");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([outline], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "tax-notice-reply-outline.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <AppShell title="Tax">
      <div className="mx-auto max-w-4xl vidhi-rise">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Legal Intelligence</p>
        <h2 className="mt-1 text-3xl tracking-tight">Tax workspace</h2>
        <p className="mt-1 text-sm text-muted-foreground" data-testid="tax-note">
          For tax matters and notices. VIDHI does not carry tax law of its own: nothing here states what a tax provision, rate or time limit is. The outline below is filled in by the program from what you type, and each legal point is left
          blank for you to complete from a source you have checked. Research answers cite only sources that have been loaded and reviewed.
        </p>

        <section className="glass vidhi-rise mt-6 rounded-xl p-5 sm:p-6" aria-labelledby="tax-matters-h">
          <h3 id="tax-matters-h" className="text-lg font-medium">Tax matters</h3>
          <form className="mt-2 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate(); }}>
            <div className="min-w-56 flex-1 space-y-1.5">
              <Label htmlFor="tax-title">New tax matter</Label>
              <Input id="tax-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} data-testid="tax-title-input" />
            </div>
            <Button type="submit" disabled={create.isPending || !title.trim()} data-testid="tax-create">{create.isPending ? "Creating…" : "Create"}</Button>
          </form>
          <ul className="mt-3 space-y-2">
            {taxMatters.length === 0 && !matters.isLoading && <li className="text-sm text-muted-foreground" data-testid="tax-empty">No tax matters yet.</li>}
            {taxMatters.map((m) => (
              <li key={m.id}><Link to={`/matters/${m.id}`} className="glass glass-lift block rounded-xl p-3" data-testid="tax-matter">{m.title}</Link></li>
            ))}
          </ul>
          <p className="mt-2 text-sm text-muted-foreground">
            Useful with a tax matter: <Link to="/katalyst/dates" className="underline underline-offset-4">list of dates from the client's documents</Link>,{" "}
            <Link to="/katalyst/deadlines" className="underline underline-offset-4">deadline engine</Link> and <Link to="/research" className="underline underline-offset-4">research</Link>.
          </p>
        </section>

        <section className="glass vidhi-rise mt-6 rounded-xl p-5 sm:p-6" aria-labelledby="tax-outline-h">
          <h3 id="tax-outline-h" className="text-lg font-medium">Notice reply outline</h3>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <Field id="tax-authority" label="Authority the notice is from" value={f.authority} set={up("authority")} />
            <Field id="tax-reference" label="Notice reference" value={f.reference} set={up("reference")} />
            <Field id="tax-date" label="Date of the notice" value={f.noticeDate} set={up("noticeDate")} />
            <Field id="tax-period" label="Period or year" value={f.period} set={up("period")} />
            <Field id="tax-taxpayer" label="Taxpayer" value={f.taxpayer} set={up("taxpayer")} />
            <Field id="tax-section" label="Provision named in the notice, as written there" value={f.sectionNamed} set={up("sectionNamed")} />
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field id="tax-points" label="Points the notice raises (one per line)" value={f.points} set={up("points")} area />
            <Field id="tax-docs" label="Documents the client has (one per line)" value={f.documents} set={up("documents")} area />
          </div>
          <Button type="button" className="mt-3" onClick={make} data-testid="tax-make">Make the outline</Button>
          {outline && (
            <div className="mt-4">
              <label htmlFor="tax-result" className="sr-only">Outline</label>
              <Textarea id="tax-result" value={outline} onChange={(e) => setOutline(e.target.value)} rows={18} className="font-mono text-xs" data-testid="tax-result" />
              <div className="mt-2 flex gap-2">
                <Button type="button" variant="outline" onClick={() => void copy()} data-testid="tax-copy">Copy</Button>
                <Button type="button" variant="outline" onClick={download} data-testid="tax-download">Download .txt</Button>
              </div>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
