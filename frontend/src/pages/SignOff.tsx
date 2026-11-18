import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Act = { id: string; title: string; provisions: number; reviewed: number; waiting: number };
type Reviewer = { id: string; label: string; private_name: string; enrolment_no: string; bar_council: string; user_id: string | null; active: boolean };
type Outcome = { confirmed: number; skipped: { provision_id: string; number: string | null; reason: string }[]; instrument: string; reviewer: string; note: string };

const select = "h-9 w-full rounded-lg border border-input bg-background px-2 text-sm";
const today = () => new Date().toISOString().slice(0, 10);

function Result({ r }: { r: Outcome }) {
  return (
    <div className="mt-3 rounded-lg border bg-background/40 p-3 text-sm" role="status" data-testid="signoff-result">
      <p>{r.reviewer} confirmed {r.confirmed} provision{r.confirmed === 1 ? "" : "s"} of {r.instrument}.</p>
      {r.skipped.length > 0 && (
        <>
          <p className="mt-1">{r.skipped.length} skipped. {r.note}</p>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">{r.skipped.slice(0, 20).map((s) => <li key={s.provision_id}>{s.number ?? s.provision_id}: {s.reason}</li>)}</ul>
        </>
      )}
    </div>
  );
}

function ConfirmForm({ acts, path, reviewers, onDone }: { acts: Act[]; path: string; reviewers?: Reviewer[]; onDone: () => void }) {
  const [act, setAct] = useState("");
  const [who, setWho] = useState("");
  const [on, setOn] = useState(today());
  const [ref, setRef] = useState("");
  const [compared, setCompared] = useState(false);
  const operator = !!reviewers;
  const run = useMutation({
    mutationFn: () => apiPost<Outcome>(operator ? `/admin/legal/reviewers/${who}/record-confirmation` : "/reviewer/confirm-act", { instrument_id: act, on, compared_with_official_text: compared, ...(operator ? { reference: ref } : {}) }),
    onSuccess: onDone,
    onError: (e) => toast.error(describe(e)),
  });
  const ready = act && compared && on && (!operator || (who && ref.trim().length >= 5));
  return (
    <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (ready) run.mutate(); }} data-testid={`signoff-form-${path}`}>
      {operator && (
        <div className="space-y-1.5">
          <Label htmlFor={`so-who-${path}`}>Reviewer</Label>
          <select id={`so-who-${path}`} className={select} value={who} onChange={(e) => setWho(e.target.value)} data-testid="signoff-reviewer">
            <option value="">Choose…</option>
            {reviewers!.filter((r) => r.active).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor={`so-act-${path}`}>Act</Label>
        <select id={`so-act-${path}`} className={select} value={act} onChange={(e) => setAct(e.target.value)} data-testid="signoff-act">
          <option value="">Choose…</option>
          {acts.map((a) => <option key={a.id} value={a.id}>{a.title} ({a.waiting} waiting of {a.provisions})</option>)}
        </select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`so-on-${path}`}>Date compared</Label>
        <Input id={`so-on-${path}`} type="date" value={on} onChange={(e) => setOn(e.target.value)} data-testid="signoff-date" />
      </div>
      {operator && (
        <div className="space-y-1.5">
          <Label htmlFor="so-ref">Where the reviewer's written confirmation is kept</Label>
          <Input id="so-ref" value={ref} maxLength={200} onChange={(e) => setRef(e.target.value)} data-testid="signoff-reference" />
        </div>
      )}
      <label className="flex items-start gap-2 text-sm sm:col-span-2">
        <input type="checkbox" className="mt-1" checked={compared} onChange={(e) => setCompared(e.target.checked)} data-testid="signoff-compared" />
        <span>Every provision of this Act was compared, word by word, with the official text. (Provisions read from a scan by a machine, or worded differently in a second source, are skipped and must be compared one by one.)</span>
      </label>
      <div className="sm:col-span-2">
        <Button type="submit" disabled={!ready || run.isPending} data-testid="signoff-submit">{run.isPending ? "Recording…" : operator ? "Record the confirmation" : "Confirm this Act"}</Button>
        {run.data && <Result r={run.data} />}
      </div>
    </form>
  );
}

export default function SignOff() {
  const qc = useQueryClient();
  const me = useQuery<{ label: string }>({ queryKey: ["reviewer-me"], queryFn: () => apiGet("/reviewer/me"), retry: false });
  const op = useQuery<{ reviewers: Reviewer[] }>({ queryKey: ["reviewers-op"], queryFn: () => apiGet("/admin/legal/reviewers"), retry: false });
  const operator = !!op.data;
  const reviewer = !!me.data;
  const acts = useQuery<{ acts: Act[] }>({ queryKey: ["signoff-acts", operator], queryFn: () => apiGet(operator ? "/admin/legal/reviewers/acts" : "/reviewer/acts"), enabled: operator || reviewer });
  const done = () => Promise.all([qc.invalidateQueries({ queryKey: ["signoff-acts"] }), qc.invalidateQueries({ queryKey: ["reviewers"] })]);

  const [f, setF] = useState({ private_name: "", enrolment_no: "", bar_council: "", account_email: "" });
  const reg = useMutation({
    mutationFn: () => apiPost<Reviewer>("/admin/legal/reviewers", f),
    onSuccess: async (r) => {
      toast.success(`Registered as ${r.label}`);
      setF({ private_name: "", enrolment_no: "", bar_council: "", account_email: "" });
      await qc.invalidateQueries({ queryKey: ["reviewers-op"] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((c) => ({ ...c, [k]: e.target.value }));
  const loading = me.isLoading || op.isLoading;

  return (
    <AppShell title="Reviewer sign-off">
      <div className="mx-auto max-w-4xl vidhi-rise">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Legal Intelligence</p>
        <h2 className="mt-1 text-3xl tracking-tight">Reviewer sign-off</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          An advocate compares the library's text with the official text, and the Act's provisions become "reviewed". Reviewers are shown to everyone only by a code such as "Advocate R-01"; real names and enrolment numbers are kept private. A confirmation never makes anything
          "verified" by itself, and judgments can never be marked verified.
        </p>
        {loading && <div className="glass mt-6 h-24 rounded-xl vidhi-sweep" />}
        {!loading && !operator && !reviewer && <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="signoff-none">This page is for registered reviewers and the operator. If you are an advocate who has agreed to review, ask the operator to link your account.</p>}

        {reviewer && (
          <section className="glass mt-6 rounded-xl p-5" aria-labelledby="so-me-h">
            <h3 id="so-me-h" className="text-lg font-medium">You are {me.data!.label}</h3>
            {acts.data && <ConfirmForm path="self" acts={acts.data.acts} onDone={done} />}
          </section>
        )}

        {operator && (
          <>
            <section className="glass mt-6 rounded-xl p-5" aria-labelledby="so-reg-h">
              <h3 id="so-reg-h" className="text-lg font-medium">Register a reviewer</h3>
              <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); reg.mutate(); }}>
                <div className="space-y-1.5"><Label htmlFor="so-name">Full name (private)</Label><Input id="so-name" value={f.private_name} onChange={set("private_name")} data-testid="signoff-name" /></div>
                <div className="space-y-1.5"><Label htmlFor="so-enrol">Enrolment number (private)</Label><Input id="so-enrol" value={f.enrolment_no} onChange={set("enrolment_no")} data-testid="signoff-enrolment" /></div>
                <div className="space-y-1.5"><Label htmlFor="so-bar">Bar Council (private)</Label><Input id="so-bar" value={f.bar_council} onChange={set("bar_council")} /></div>
                <div className="space-y-1.5"><Label htmlFor="so-mail">Their account email, if they will confirm themselves</Label><Input id="so-mail" type="email" value={f.account_email} onChange={set("account_email")} data-testid="signoff-email" /></div>
                <div className="sm:col-span-2"><Button type="submit" disabled={reg.isPending || f.private_name.trim().length < 5 || f.enrolment_no.trim().length < 3} data-testid="signoff-register">Register</Button></div>
              </form>
              <ul className="mt-4 space-y-1 text-sm" data-testid="signoff-register-list">
                {op.data!.reviewers.map((r) => (
                  <li key={r.id}><span className="font-medium">{r.label}</span> <span className="text-muted-foreground">({r.private_name}, {r.enrolment_no}{r.bar_council ? `, ${r.bar_council}` : ""}){r.user_id ? " has an account" : ""}</span></li>
                ))}
                {op.data!.reviewers.length === 0 && <li className="text-muted-foreground">No reviewers registered yet.</li>}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">Visible to the operator only.</p>
            </section>
            <section className="glass mt-6 rounded-xl p-5" aria-labelledby="so-rec-h">
              <h3 id="so-rec-h" className="text-lg font-medium">Record a confirmation received in writing</h3>
              {acts.data && <ConfirmForm path="operator" acts={acts.data.acts} reviewers={op.data!.reviewers} onDone={done} />}
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
