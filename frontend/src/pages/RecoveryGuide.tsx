import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink } from "lucide-react";
import AppShell from "@/components/AppShell";
import SendNoticeDialog from "@/components/recovery/SendNoticeDialog";
import TodoVerify from "@/components/recovery/TodoVerify";
import NoticeHelp from "@/components/recovery/NoticeHelp";
import { useRecoveryMode } from "@/lib/recovery/useRecoveryMode";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { openApiFile } from "@/lib/files";
import { describe } from "@/lib/interaction";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { guideStrings } from "@/lib/recovery/guideStrings";
import { renderNotice } from "@/lib/recovery/noticeTemplate";
import { FACT_STRING_KEYS, FACTS, LAST_VERIFIED, PORTAL_RULES, routeFor } from "@/lib/recovery/portalRules";
import type { RecoveryCase } from "@/lib/types";

type Answers = NonNullable<NonNullable<RecoveryCase["guide"]>["answers"]>;
type Step = "q1" | "q2" | "q3" | "q4" | "q5" | "who" | "route" | "form" | "preview" | "sent" | "escalate";
const QUESTIONS: Step[] = ["q1", "q2", "q3", "q4", "q5"];
const PROGRESS: Record<Step, number> = { q1: 0, q2: 0, q3: 0, q4: 0, q5: 0, who: 0, route: 1, form: 2, preview: 2, sent: 2, escalate: 3 };

const bigButton = "min-h-14 w-full justify-start px-5 text-left text-base";

function prettyDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** The guided recovery: a few questions, the free government portal first when it fits, then a legal notice, then a lawyer. One question per screen. */
export default function RecoveryGuide() {
  const { caseId } = useParams();
  const { lang } = useI18n();
  const g = guideStrings(lang);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("q1");
  const [answers, setAnswers] = useState<Answers>({});
  const [amount, setAmount] = useState("");
  const [names, setNames] = useState({ seller: "", buyer: "" });
  const [form, setForm] = useState({ seller_address: "", seller_email: "", buyer_address: "", buyer_email: "", invoice_number: "", invoice_date: "", due_date: "", description: "", days: "15" });
  const [confirmed, setConfirmed] = useState(false);
  const [approveBox, setApproveBox] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [resumed, setResumed] = useState(false);
  const [portalRef, setPortalRef] = useState("");
  const [dates, setDates] = useState({ notice_date: "", due_date: "", next_date: "" });
  const { full, ready } = useRecoveryMode(); // off: the small free helper (no email sending, no escalation steps)

  const saved = useQuery<RecoveryCase>({ queryKey: ["recovery-case", caseId], queryFn: () => apiGet<RecoveryCase>(`/recovery/cases/${caseId}`), enabled: !!caseId });
  const c = saved.data;
  const emails = useQuery<{ id: string; kind: string; to: string; status: string; created_at: string }[]>({
    queryKey: ["recovery-case-emails", caseId],
    queryFn: () => apiGet(`/recovery/cases/${caseId}/emails`),
    enabled: !!caseId && step === "sent" && full,
  });
  const workflow = useQuery<{ state: string; current_version: { id: string } | null }>({
    queryKey: ["recovery-case-workflow", caseId],
    queryFn: () => apiGet(`/recovery/cases/${caseId}/notice/workflow`),
    enabled: !!caseId && step === "preview" && full,
  });

  // Coming back to a saved recovery: land on the screen that matches where the person stopped.
  useEffect(() => {
    if (!c || resumed || !ready) return;
    setResumed(true);
    const a = c.guide?.answers ?? {};
    setAnswers(a);
    setNames({ seller: c.creditor_name, buyer: c.debtor_name });
    setForm((f) => ({
      ...f,
      seller_address: c.creditor_address ?? "",
      buyer_address: c.debtor_address ?? "",
      buyer_email: c.debtor_email ?? "",
      seller_email: c.intake?.creditor_email ?? "",
      invoice_number: c.intake?.invoice_number ?? "",
      invoice_date: c.intake?.invoice_date ?? "",
      due_date: c.due_date ?? "",
      description: c.intake?.supply_description ?? "",
    }));
    setPortalRef(c.guide?.portal_reference ?? "");
    setDates({ notice_date: c.guide?.tracker?.notice_date ?? "", due_date: c.guide?.tracker?.due_date ?? "", next_date: c.guide?.tracker?.next_date ?? "" });
    const stage = c.guide?.stage ?? "NOT_STARTED";
    setStep(stage === "ESCALATED" ? (full ? "escalate" : "sent") : stage === "NOTICE_SENT" ? "sent" : c.notice_body ? "preview" : "route");
  }, [c, resumed, ready, full]);

  const saveGuide = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/guide`, body),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["recovery-case", caseId] });
      await qc.invalidateQueries({ queryKey: ["recovery-cases"] });
    },
    onError: (e) => toast.error(describe(e)),
  });

  const create = useMutation({
    mutationFn: async () => {
      const made = await apiPost<RecoveryCase>("/recovery/cases", { creditor_name: names.seller.trim(), debtor_name: names.buyer.trim(), amount: Number(amount) || 0, currency: "INR" });
      await apiPatch(`/recovery/cases/${made.id}/guide`, { answers: { ...answers, amount: Number(amount) || 0 }, stage: "NOT_STARTED" });
      return made;
    },
    onSuccess: async (made) => {
      await qc.invalidateQueries({ queryKey: ["recovery-cases"] });
      navigate(`/recovery/guide/${made.id}`, { replace: true });
    },
    onError: (e) => toast.error(describe(e)),
  });

  const makeNotice = useMutation({
    mutationFn: async () => {
      await apiPatch(`/recovery/cases/${caseId}/details`, { creditor_address: form.seller_address, debtor_address: form.buyer_address, due_date: form.due_date });
      await apiPatch(`/recovery/cases/${caseId}/intake`, {
        amount: Number(amount || answers.amount) || undefined,
        debtor_email: form.buyer_email || undefined,
        creditor_email: form.seller_email || undefined,
        invoice_number: form.invoice_number,
        invoice_date: form.invoice_date,
        supply_description: form.description,
        response_days: Number(form.days) || 15,
      });
      const text = renderNotice({
        date: prettyDate(new Date().toISOString()),
        buyer_name: names.buyer,
        buyer_address: form.buyer_address,
        seller_name: names.seller,
        seller_address: form.seller_address,
        invoice_number: form.invoice_number,
        invoice_date: prettyDate(form.invoice_date),
        due_date: prettyDate(form.due_date),
        description: form.description,
        days: form.days || "15",
      });
      return apiPost<RecoveryCase>(`/recovery/cases/${caseId}/notice/template`, { text, response_days: Number(form.days) || 15 });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["recovery-case", caseId] });
      setConfirmed(false);
      setStep("preview");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const approve = useMutation({
    mutationFn: () => apiPost(`/recovery/cases/${caseId}/notice/approve`, { version_id: workflow.data?.current_version?.id, acknowledged: true }),
    onSuccess: async () => {
      await workflow.refetch();
      toast.success("Approved. You can email it now.");
    },
    onError: (e) => toast.error(describe(e)),
  });

  async function markSent(method: "downloaded" | "emailed" | "lawyer") {
    try {
      await apiPatch(`/recovery/cases/${caseId}/guide`, { delivery_method: method });
      await apiPatch(`/recovery/cases/${caseId}/guide`, { stage: "NOTICE_SENT" });
      await qc.invalidateQueries({ queryKey: ["recovery-case", caseId] });
      await qc.invalidateQueries({ queryKey: ["recovery-cases"] });
      setStep("sent");
    } catch (e) {
      toast.error(describe(e));
    }
  }

  const set = (patch: Partial<Answers>, next: Step) => {
    setAnswers((a) => ({ ...a, ...patch }));
    setStep(next);
  };
  const route = answers.udyam && answers.buyer ? routeFor(answers.udyam, answers.buyer) : null;
  const field = (key: keyof typeof form, label: string, opts: { type?: string; testid: string; area?: boolean }) => (
    <div className="space-y-1.5">
      <Label htmlFor={`g-${key}`}>{label}</Label>
      {opts.area ? (
        <Textarea id={`g-${key}`} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} rows={2} data-testid={opts.testid} />
      ) : (
        <Input id={`g-${key}`} type={opts.type ?? "text"} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} data-testid={opts.testid} />
      )}
    </div>
  );
  const formReady = form.seller_address.trim() && form.buyer_address.trim() && form.invoice_number.trim() && form.invoice_date && form.due_date && form.description.trim() && Number(amount || answers.amount) > 0;
  const choice = (label: string, testid: string, onClick: () => void) => (
    <Button type="button" variant="outline" className={bigButton} onClick={onClick} data-testid={testid}>
      {label}
    </Button>
  );
  const q = (n: number, title: string, body: ReactNode) => (
    <section data-testid={`guide-q${n}`}>
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{n} / 5</p>
      <h2 className="mt-1 text-xl md:text-2xl">{title}</h2>
      <div className="mt-5 space-y-3">{body}</div>
    </section>
  );
  const sentRow = (emails.data ?? []).find((e) => e.kind === "notice-debtor" && e.status !== "FAILED");

  return (
    <AppShell title={g.title} back="/recovery">
      <div className="mx-auto max-w-xl" data-testid="recovery-guide">
        <ol className="flex gap-1" aria-label="Progress" data-testid="guide-progress">
          {(full ? g.steps : g.stepsSmall).map((label, i) => (
            <li key={label} className="min-w-0 flex-1" aria-current={i === PROGRESS[step] ? "step" : undefined}>
              <div className="h-1.5 rounded-full" style={{ background: i <= PROGRESS[step] ? "#C8A96B" : "var(--color-border)" }} />
              <p className={`mt-1 truncate text-[11px] ${i === PROGRESS[step] ? "text-foreground" : "text-muted-foreground"}`}>{label}</p>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-sm font-medium" data-testid="guide-tagline">
          {g.tagline}
        </p>
        {c?.guide?.stage && (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="guide-status">
            {g.statusPrefix} {g.status[c.guide.stage]}
            {c.guide.portal_reference ? ` · ${c.guide.portal_reference}` : ""}
          </p>
        )}

        <div className="mt-6">
          {step === "q1" &&
            q(1, g.q1, <>
              {choice(g.yes, "guide-a-yes", () => set({ udyam: "yes" }, "q2"))}
              {choice(g.no, "guide-a-no", () => set({ udyam: "no" }, "q2"))}
              {choice(g.notSure, "guide-a-notsure", () => set({ udyam: "not_sure" }, "q2"))}
              <p className="text-xs text-muted-foreground" data-testid="guide-udyam-note">{g.udyamNote}</p>
            </>)}
          {step === "q2" &&
            q(2, g.q2, <>
              {choice(g.business, "guide-a-business", () => set({ buyer: "business" }, "q3"))}
              {choice(g.individual, "guide-a-individual", () => set({ buyer: "individual" }, "q3"))}
            </>)}
          {step === "q3" &&
            q(3, g.q3, <>
              {choice(g.yes, "guide-a-docs-yes", () => set({ has_documents: true }, "q4"))}
              {choice(g.no, "guide-a-docs-no", () => set({ has_documents: false }, "q4"))}
            </>)}
          {step === "q4" &&
            q(4, g.q4, <>
              {choice(g.under15, "guide-a-under15", () => set({ overdue: "under_15" }, "q5"))}
              {choice(g.d15to45, "guide-a-15to45", () => set({ overdue: "15_to_45" }, "q5"))}
              {choice(g.over45, "guide-a-over45", () => set({ overdue: "over_45" }, "q5"))}
            </>)}
          {step === "q5" &&
            q(5, g.q5, (
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (Number(amount) > 0) {
                    setAnswers((a) => ({ ...a, amount: Number(amount) }));
                    setStep("who");
                  }
                }}
              >
                <Label htmlFor="g-amount">{g.amountLabel}</Label>
                <Input id="g-amount" type="number" inputMode="decimal" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-14 text-lg" data-testid="guide-amount" />
                <Button type="submit" size="lg" className="w-full" disabled={!(Number(amount) > 0)} data-testid="guide-amount-next">
                  {g.next}
                </Button>
              </form>
            ))}

          {step === "who" && (
            <section data-testid="guide-who">
              <h2 className="text-xl md:text-2xl">{g.who}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{g.whoSub}</p>
              <form
                className="mt-5 space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (names.seller.trim() && names.buyer.trim()) create.mutate();
                }}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="g-seller">{g.yourName}</Label>
                  <Input id="g-seller" value={names.seller} onChange={(e) => setNames({ ...names, seller: e.target.value })} data-testid="guide-seller-name" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="g-buyer">{g.buyerName}</Label>
                  <Input id="g-buyer" value={names.buyer} onChange={(e) => setNames({ ...names, buyer: e.target.value })} data-testid="guide-buyer-name" />
                </div>
                <Button type="submit" size="lg" className="w-full" loading={create.isPending} disabled={!names.seller.trim() || !names.buyer.trim()} data-testid="guide-who-next">
                  {g.saveCase}
                </Button>
              </form>
            </section>
          )}

          {step === "route" && route && (
            <section data-testid="guide-route" className="space-y-4">
              {route === "portal_first" && (
                <div className="glass rounded-2xl p-5" data-testid="guide-portal-card">
                  <p className="text-xs uppercase tracking-wider" style={{ color: "#C8A96B" }}>Recommended</p>
                  <h2 className="mt-1 text-xl">
                    {g.portalTitle}
                    <TodoVerify ids={FACT_STRING_KEYS.portalTitle} />
                  </h2>
                  <p className="mt-3 text-sm">
                    {FACTS.portalExists.text} {FACTS.whatItCovers.text}
                    <TodoVerify ids={["portalExists", "whatItCovers"]} />
                  </p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {g.portalWhy}: {FACTS.whoMustUse.text} (from {FACTS.effectiveDate.text})
                    <TodoVerify ids={["whoMustUse", "effectiveDate"]} />
                  </p>
                  {PORTAL_RULES.eligibilityNotes.length > 0 && (
                    <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">
                      {PORTAL_RULES.eligibilityNotes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-4 text-sm font-medium">
                    {g.portalChecklist}
                    <TodoVerify ids={["portalChecklist"]} />
                  </p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                    {PORTAL_RULES.checklist.map((i) => (
                      <li key={i}>{i}</li>
                    ))}
                  </ul>
                  <a href={FACTS.portalUrl.text} target="_blank" rel="noopener noreferrer" className={`${buttonVariants({ size: "lg" })} mt-5 w-full`} data-testid="guide-portal-open">
                    {g.portalOpen} <ExternalLink />
                  </a>
                  <p className="mt-2 text-xs text-muted-foreground" data-testid="guide-last-verified">
                    {g.lastVerified}: {LAST_VERIFIED || g.notVerifiedYet}
                    <TodoVerify ids={["portalUrl"]} />
                  </p>
                  <div className="mt-4 space-y-1.5">
                    <Label htmlFor="g-portalref">{g.portalRef}</Label>
                    <Input id="g-portalref" value={portalRef} onChange={(e) => setPortalRef(e.target.value)} maxLength={60} data-testid="guide-portal-ref" />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground" data-testid="guide-self-declared">{g.selfDeclared}</p>
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-2 w-full"
                    disabled={saveGuide.isPending}
                    onClick={async () => {
                      await saveGuide.mutateAsync({ stage: "PORTAL_FILED", portal_reference: portalRef.trim() });
                      toast.success(g.status.PORTAL_FILED);
                    }}
                    data-testid="guide-portal-filed"
                  >
                    {g.portalFiled}
                  </Button>
                </div>
              )}
              {route === "skip_not_registered" && (
                <p className="glass rounded-2xl p-5 text-sm" data-testid="guide-skip-reason">
                  {g.skipNotRegistered}
                  <TodoVerify ids={FACT_STRING_KEYS.skipNotRegistered} />
                </p>
              )}
              {route === "skip_individual" && (
                <p className="glass rounded-2xl p-5 text-sm" data-testid="guide-skip-reason">
                  {g.skipIndividual}
                  <TodoVerify ids={FACT_STRING_KEYS.skipIndividual} />
                </p>
              )}
              {route === "unsure" && (
                <div className="glass rounded-2xl p-5" data-testid="guide-unsure">
                  <h2 className="text-lg">{g.unsureTitle}</h2>
                  <p className="mt-2 text-sm">
                    {g.unsureBody}
                    <TodoVerify ids={FACT_STRING_KEYS.unsureBody} />
                  </p>
                </div>
              )}
              <Button type="button" size="lg" variant={route === "portal_first" ? "outline" : "default"} className="w-full" onClick={() => setStep("form")} data-testid="guide-to-notice">
                {route === "unsure" ? g.unsureGo : route === "portal_first" ? g.portalSkip : g.unsureGo}
              </Button>
            </section>
          )}

          {step === "form" && (
            <section data-testid="guide-form">
              <NoticeHelp />
              <p className="mt-4 text-sm text-muted-foreground">{g.noticeFraming}</p>
              <form
                className="mt-4 space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (formReady && confirmed) makeNotice.mutate();
                }}
              >
                <p className="text-sm font-medium">{names.seller}</p>
                {field("seller_address", g.yourAddress, { testid: "guide-seller-address", area: true })}
                {field("seller_email", g.yourEmail, { type: "email", testid: "guide-seller-email" })}
                <p className="pt-2 text-sm font-medium">{names.buyer}</p>
                {field("buyer_address", g.buyerAddress, { testid: "guide-buyer-address", area: true })}
                {field("buyer_email", g.buyerEmail, { type: "email", testid: "guide-buyer-email" })}
                {field("invoice_number", g.invoiceNumber, { testid: "guide-invoice-number" })}
                {field("invoice_date", g.invoiceDate, { type: "date", testid: "guide-invoice-date" })}
                <div className="space-y-1.5">
                  <Label htmlFor="g-amount2">{g.amountDue}</Label>
                  <Input id="g-amount2" type="number" inputMode="decimal" min="0" value={amount || String(answers.amount ?? "")} onChange={(e) => setAmount(e.target.value)} data-testid="guide-amount-due" />
                </div>
                {field("due_date", g.dueDate, { type: "date", testid: "guide-due-date" })}
                {field("description", g.description, { testid: "guide-description", area: true })}
                <label className="flex min-h-12 items-start gap-3 text-sm">
                  <input type="checkbox" className="mt-1 size-5" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} data-testid="guide-confirm-details" />
                  {g.confirmDetails}
                </label>
                <Button type="submit" size="lg" className="w-full" loading={makeNotice.isPending} disabled={!formReady || !confirmed} data-testid="guide-make-notice">
                  {g.makeNotice}
                </Button>
              </form>
            </section>
          )}

          {step === "preview" && c && (
            <section data-testid="guide-preview" className="space-y-4">
              <NoticeHelp />
              <h2 className="text-xl">{g.previewTitle}</h2>
              <pre className="glass max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-sm" tabIndex={0} role="region" aria-label="The notice text. Use the arrow keys to scroll." data-testid="guide-notice-text">
                {c.notice_body}
              </pre>
              <h2 className="text-lg">{g.deliveryTitle}</h2>
              <Button type="button" variant="outline" className={bigButton} onClick={() => openApiFile(`/api/recovery/cases/${caseId}/notice.pdf`)} data-testid="guide-download">
                {g.download}
              </Button>
              <Button
                type="button"
                variant="outline"
                className={bigButton}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(c.notice_body);
                    toast.success(g.copied);
                  } catch {
                    toast.error(g.copyFailed);
                  }
                }}
                data-testid="guide-copy-text"
              >
                {g.copyText}
              </Button>
              <Button type="button" variant="outline" className="w-full" onClick={() => markSent("downloaded")} data-testid="guide-mark-downloaded">
                {g.iSentIt}
              </Button>
              {full && (<>
              <div className="glass space-y-3 rounded-2xl p-4">
                <p className="text-sm font-medium">{g.email}</p>
                <p className="text-xs text-muted-foreground" data-testid="guide-email-note">
                  {g.emailNote}
                  <TodoVerify ids={FACT_STRING_KEYS.emailNote} />
                </p>
                {workflow.data?.state !== "APPROVED" ? (
                  <>
                    <p className="text-sm">{g.needApproval}</p>
                    <label className="flex min-h-12 items-start gap-3 text-sm">
                      <input type="checkbox" className="mt-1 size-5" checked={approveBox} onChange={(e) => setApproveBox(e.target.checked)} data-testid="guide-approve-box" />
                      {g.approveBox}
                    </label>
                    <Button type="button" className="w-full" disabled={!approveBox || approve.isPending || !workflow.data?.current_version} onClick={() => approve.mutate()} data-testid="guide-approve">
                      {g.approve}
                    </Button>
                  </>
                ) : (
                  <Button type="button" size="lg" className="w-full" onClick={() => setSendOpen(true)} data-testid="guide-email-open">
                    {g.email}
                  </Button>
                )}
              </div>
              <Link to="/lawyers" className={`${buttonVariants({ variant: "outline" })} ${bigButton} inline-flex`} data-testid="guide-lawyer">
                {g.lawyer}
              </Link>
              <Button type="button" variant="outline" className="w-full" onClick={() => markSent("lawyer")} data-testid="guide-mark-lawyer">
                {g.markEscalated}
              </Button>
              <SendNoticeDialog
                open={sendOpen}
                onOpenChange={setSendOpen}
                caseId={caseId ?? ""}
                defaultEmail={c.debtor_email ?? ""}
                confirmedAccountants={c.accountant_emails ?? []}
                onSent={async () => {
                  await markSent("emailed");
                }}
              />
              </>)}
            </section>
          )}

          {step === "sent" && c && (
            <section data-testid="guide-sent" className="space-y-4">
              <div className="glass rounded-2xl p-5">
                <h2 className="text-xl">{g.sentTitle}</h2>
                <p className="mt-2 text-sm" data-testid="guide-sent-date">
                  {g.sentDate}: {prettyDate(c.guide?.stage_changed_at ?? new Date().toISOString())}
                </p>
                <p className="text-sm" data-testid="guide-sent-method">
                  {c.guide?.delivery_method === "emailed" ? g.email : c.guide?.delivery_method === "lawyer" ? g.lawyer : g.download}
                </p>
                {c.guide?.delivery_method === "emailed" && sentRow && (
                  <p className="text-sm" data-testid="guide-sent-to">
                    {g.sentTo}: {sentRow.to}
                  </p>
                )}
                <Button type="button" variant="outline" className="mt-4" onClick={() => openApiFile(`/api/recovery/cases/${caseId}/notice.pdf`)} data-testid="guide-copy">
                  {g.downloadCopy}
                </Button>
              </div>
              <form
                className="glass space-y-3 rounded-2xl p-5"
                data-testid="guide-tracker"
                onSubmit={async (e) => {
                  e.preventDefault();
                  await saveGuide.mutateAsync({ tracker: dates });
                  toast.success(g.trackerSaved);
                }}
              >
                <h2 className="text-lg">{g.trackerTitle}</h2>
                <p className="text-xs text-muted-foreground">{g.trackerSub}</p>
                {(
                  [
                    ["notice_date", g.trackerNotice],
                    ["due_date", g.trackerDue],
                    ["next_date", g.trackerNext],
                  ] as const
                ).map(([key, label]) => (
                  <div key={key} className="space-y-1.5">
                    <Label htmlFor={`g-track-${key}`}>{label}</Label>
                    <Input id={`g-track-${key}`} type="date" value={dates[key]} onChange={(e) => setDates({ ...dates, [key]: e.target.value })} data-testid={`guide-track-${key}`} />
                  </div>
                ))}
                <Button type="submit" variant="outline" className="w-full" disabled={saveGuide.isPending} data-testid="guide-track-save">
                  {g.trackerSave}
                </Button>
              </form>
              {full && (
              <div className="glass rounded-2xl p-5" data-testid="guide-escalate-card">
                <h2 className="text-lg">{g.escalateTitle}</h2>
                <p className="mt-1 text-sm">
                  {g.escalateBody}
                  <TodoVerify ids={FACT_STRING_KEYS.escalateBody} />
                </p>
                <Link to="/lawyers" className={`${buttonVariants({ size: "lg" })} mt-4 w-full`} data-testid="guide-escalate-lawyers">
                  {g.escalateCta}
                </Link>
                <Button
                  type="button"
                  variant="outline"
                  className="mt-3 w-full"
                  onClick={async () => {
                    await saveGuide.mutateAsync({ stage: "ESCALATED" });
                    setStep("escalate");
                  }}
                  data-testid="guide-mark-escalated"
                >
                  {g.markEscalated}
                </Button>
              </div>
              )}
            </section>
          )}

          {step === "escalate" && (
            <section className="glass rounded-2xl p-5" data-testid="guide-escalated">
              <h2 className="text-lg">{g.escalateTitle}</h2>
              <p className="mt-1 text-sm">
                {g.escalateBody}
                <TodoVerify ids={FACT_STRING_KEYS.escalateBody} />
              </p>
              <Link to="/lawyers" className={`${buttonVariants({ size: "lg" })} mt-4 w-full`}>
                {g.escalateCta}
              </Link>
              <Link to={`/recovery/cases/${caseId}`} className="mt-3 inline-block text-sm underline underline-offset-4">
                Open the full case
              </Link>
            </section>
          )}
        </div>

        {step === "route" && !route && (
          <Button type="button" variant="outline" onClick={() => setStep("q1")}>
            {g.back}
          </Button>
        )}
        {QUESTIONS.includes(step) && step !== "q1" && (
          <Button type="button" variant="ghost" className="mt-4" onClick={() => setStep(QUESTIONS[QUESTIONS.indexOf(step) - 1])} data-testid="guide-back">
            {g.back}
          </Button>
        )}
        <p className="mt-8 text-xs text-muted-foreground" data-testid="guide-disclaimer">
          {g.disclaimer}
        </p>
      </div>
    </AppShell>
  );
}
