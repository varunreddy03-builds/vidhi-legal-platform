import { CheckCircle2, FilePlus2, FileSignature, ListChecks, MailCheck, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Readiness, RecoveryCase } from "@/lib/types";

interface Props {
  c: RecoveryCase;
  readiness?: Readiness;
  proofCount: number;
  workflowState: string;
  reading: boolean;
  writing: boolean;
  onAddPaper: () => void;
  onRead: () => void;
  onWrite: () => void;
  goTo: (id: string) => void;
}

/**
 * "Your next step": the ONE thing to do now, in plain words, with one big button. Everything else on the page is
 * there when you want it, but nobody has to work out where to click next.
 */
export default function NextStepCard({ c, readiness, proofCount, workflowState, reading, writing, onAddPaper, onRead, onWrite, goTo }: Props) {
  let step = 1;
  let title = "";
  let body = "";
  let label = "";
  let Icon = FilePlus2;
  let run: () => void = () => undefined;
  let busy = false;
  let done = false;

  if (c.status === "RESOLVED") {
    done = true;
    title = "All done. This recovery is closed.";
    body = "You can still open any part below to look at your papers and records.";
    step = 5;
  } else if (proofCount === 0 || c.status === "DRAFT") {
    step = 1;
    Icon = FilePlus2;
    title = "Add your papers";
    body = "Add the invoice or bill, proof that you delivered the goods or did the work, and any chat or email where they promised to pay. Photos and PDFs are fine.";
    label = "Add a paper";
    run = onAddPaper;
  } else if (c.status === "PROOF_ADDED") {
    step = 2;
    Icon = Sparkles;
    title = "Let us read your case";
    body = "We will read your papers, put the events in order and point out anything that is missing. This takes about a minute.";
    label = "Read my case";
    run = onRead;
    busy = reading;
  } else if (c.status === "TIMELINE_READY") {
    step = 3;
    const blockers = readiness?.draft_blockers ?? [];
    if (blockers.length > 0) {
      Icon = ListChecks;
      title = "A few details are missing";
      body = `${blockers.slice(0, 3).join(" ")} We need these to write a proper notice.`;
      label = "Fill in the details";
      run = () => goTo("step-4");
    } else if (readiness?.route_acknowledgement_needed) {
      Icon = ListChecks;
      title = "Please read a warning first";
      body = "Something in your answers means an ordinary letter may not be the right step. Read it, then decide.";
      label = "Read the warning";
      run = () => goTo("step-4");
    } else {
      Icon = FileSignature;
      title = "Write your notice";
      body = "We will write a polite, clear notice from the facts you gave us. You read it and change anything before it goes anywhere.";
      label = "Write my notice";
      run = onWrite;
      busy = writing;
    }
  } else if (workflowState === "APPROVED") {
    step = 4;
    Icon = Send;
    title = "Your notice is approved. Send it";
    body = "Choose how it should reach them. Nothing is sent until you confirm the address.";
    label = "Go to sending";
    run = () => goTo("step-4");
  } else if (workflowState === "SENT" || workflowState === "RESPONSE_RECEIVED") {
    step = 5;
    Icon = MailCheck;
    title = workflowState === "SENT" ? "Sent. Now wait for their reply" : "They have replied";
    body = "Write down what happens next so you have a clear record: replies, calls, payments, or a posted copy.";
    label = "Record what happened";
    run = () => goTo("step-4");
  } else {
    step = 4;
    Icon = FileSignature;
    title = "Read your notice, then approve it";
    body = "Read every line. If it is right, approve it. If a lawyer should look first, ask for a review. Only an approved notice can be sent.";
    label = "Review the notice";
    run = () => goTo("step-4");
  }

  return (
    <section className="glass vidhi-rise mt-5 rounded-3xl p-5 md:p-7" data-testid="recovery-next-step" aria-label="Your next step">
      <div className="flex items-start gap-4 md:gap-5">
        <div className="hidden shrink-0 sm:block">{done ? <CheckCircle2 className="size-12 text-[#7FE3B0]" /> : <span className="grid size-12 place-items-center rounded-2xl border border-[#5B8CFF]/40 bg-[#5B8CFF]/10"><Icon className="size-6 text-[#5B8CFF]" /></span>}</div>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-[0.3em] text-[#C8A96B]">{done ? "Finished" : `Your next step · ${Math.min(step, 5)} of 5`}</p>
          <h3 className="mt-1.5 text-xl md:text-2xl">{title}</h3>
          <p className="mt-2 text-base text-muted-foreground">{body}</p>
          {!done && (
            <Button size="lg" className="mt-5 w-full sm:w-auto" loading={busy} onClick={run} data-testid="next-step-button">
              <Icon /> {busy ? "Working on it…" : label}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
