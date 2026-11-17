import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { Draft, Matter } from "@/lib/types";

interface Review { status: string; reviewed: boolean; reviewed_by: string | null; reviewed_on: string | null; note: string | null }
interface Summary { id: string; title: string; description: string; jurisdiction: string; review: Review }
interface Field { key: string; label: string; type: "text" | "textarea" | "date" | "money" | "int" | "decimal" | "choice"; required: boolean; help?: string; choices?: string[]; min?: number; max?: number }
interface Full extends Summary { fields: Field[]; clauses: { id: string; label: string; default: boolean }[]; lawyer_checks: string[]; notice: string }

function ReviewBadge({ review }: { review: Review }) {
  return review.reviewed ? (
    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400">Wording reviewed by {review.reviewed_by} on {review.reviewed_on}</span>
  ) : (
    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400" title={review.note ?? undefined}>Not reviewed by a lawyer</span>
  );
}

function FieldInput({ f, value, onChange }: { f: Field; value: string; onChange: (v: string) => void }) {
  const id = `f-${f.key}`;
  const common = { id, value, required: f.required, "data-testid": `tpl-${f.key}` };
  const select = "h-9 w-full rounded-md border border-border bg-background px-2 text-sm";
  return (
    <div className={`space-y-1.5 ${f.type === "textarea" ? "sm:col-span-2" : ""}`}>
      <Label htmlFor={id}>{f.label}{f.required ? "" : " (optional)"}</Label>
      {f.type === "textarea" ? (
        <Textarea {...common} rows={2} maxLength={2000} onChange={(e) => onChange(e.target.value)} />
      ) : f.type === "choice" ? (
        <select {...common} className={select} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose…</option>
          {f.choices?.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      ) : (
        <Input
          {...common}
          type={f.type === "date" ? "date" : f.type === "int" ? "number" : "text"}
          inputMode={f.type === "money" || f.type === "decimal" ? "decimal" : undefined}
          min={f.type === "int" ? f.min : undefined}
          max={f.type === "int" ? f.max : undefined}
          maxLength={200}
          placeholder={f.type === "money" ? "e.g. 25000" : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {f.help && <p className="text-xs text-muted-foreground">{f.help}</p>}
    </div>
  );
}

export default function Templates() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const chosen = params.get("t");
  const list = useQuery({ queryKey: ["templates"], queryFn: () => apiGet<{ items: Summary[] }>("/templates?jurisdiction=IN") });
  const detail = useQuery({ queryKey: ["template", chosen], queryFn: () => apiGet<Full>(`/templates/${chosen}`), enabled: !!chosen });
  const matters = useQuery({ queryKey: ["matters"], queryFn: () => apiGet<Matter[]>("/matters"), retry: false });
  const [values, setValues] = useState<Record<string, string>>({});
  const [clauses, setClauses] = useState<Record<string, boolean> | null>(null);
  const [matterId, setMatterId] = useState("");

  const t = detail.data;
  const picked = clauses ?? Object.fromEntries((t?.clauses ?? []).map((c) => [c.id, c.default]));
  const make = useMutation({
    mutationFn: () => apiPost<Draft>(`/templates/${chosen}/draft`, { values: Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "")), clauses: Object.keys(picked).filter((k) => picked[k]), matter_id: matterId || null }),
    onSuccess: (d) => {
      toast.success("Draft created. Review it before using it.");
      navigate(`/drafts/${d.id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AppShell title="Templates">
      <div className="mx-auto max-w-4xl space-y-6" data-testid="templates-page">
        <div>
          <h2 className="text-2xl">Document templates</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Starting drafts for India. You answer a few questions and VIDHI fills the wording in; nothing is written by AI. Points of law are left as [LAWYER TO CONFIRM] for a lawyer. This is not legal advice.
          </p>
        </div>

        {!chosen && (
          <div className="grid gap-3 sm:grid-cols-2" data-testid="template-list">
            {(list.data?.items ?? []).map((x) => (
              <button key={x.id} className="glass rounded-lg p-4 text-left transition-transform hover:-translate-y-0.5" onClick={() => { setValues({}); setClauses(null); setParams({ t: x.id }); }} data-testid="template-card">
                <p className="font-medium">{x.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{x.description}</p>
                <div className="mt-2"><ReviewBadge review={x.review} /></div>
              </button>
            ))}
          </div>
        )}

        {chosen && t && (
          <form className="glass space-y-5 rounded-lg p-4" onSubmit={(e) => { e.preventDefault(); make.mutate(); }} data-testid="template-form">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-lg">{t.title}</h3>
                <div className="mt-1"><ReviewBadge review={t.review} /></div>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={() => setParams({})}>← All templates</Button>
            </div>
            <p className="text-sm text-muted-foreground">{t.notice}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {t.fields.map((f) => <FieldInput key={f.key} f={f} value={values[f.key] ?? ""} onChange={(v) => setValues((cur) => ({ ...cur, [f.key]: v }))} />)}
            </div>
            {t.clauses.length > 0 && (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Optional parts</legend>
                {t.clauses.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={!!picked[c.id]} onChange={(e) => setClauses({ ...picked, [c.id]: e.target.checked })} />
                    {c.label}
                  </label>
                ))}
              </fieldset>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="tpl-matter">Attach to a matter (optional)</Label>
              <select id="tpl-matter" value={matterId} onChange={(e) => setMatterId(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm">
                <option value="">None</option>
                {(matters.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
              </select>
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer">What a lawyer should check in this template</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">{t.lawyer_checks.map((c) => <li key={c}>{c}</li>)}</ul>
            </details>
            <Button type="submit" loading={make.isPending} data-testid="template-create">Create editable draft</Button>
          </form>
        )}
      </div>
    </AppShell>
  );
}