import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import AddToDates from "@/components/AddToDates";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Rule = {
  id: string;
  title: string;
  starts_from: string;
  period: { amount: number; unit: string };
  count_from: string;
  month_end?: string;
  when_not_working: string;
  not_applied: string[];
  authorities: string[];
  reviewed_by: string;
  verified_on: string;
};
type Result = { due: string; weekday: string; steps: string[]; moved: boolean; start: string; rule: Rule; calendar: { title: string; authorities: string[]; reviewed_by: string; verified_on: string } | null; notice: string };
type Listing = { rules: Rule[]; message: string | null };

const NOTICE =
  "This works out a date only from a rule that a person entered from an official source and a named reviewer marked as reviewed. VIDHI contains no limitation period or court rule of its own. It does not say that a rule applies to your matter, whether time can be extended, or whether another period also runs. A lawyer decides.";

const COUNT: Record<string, string> = { day_after_start: "counts from the day after the start day", start_day_included: "counts the start day as the first day" };
const MONTH_END: Record<string, string> = { last_day_of_month: "uses the last day of a shorter month", first_day_of_next_month: "uses the first day of the next month when the month is shorter" };
const MOVE: Record<string, string> = { move_to_next_working_day: "moves the date off a non-working day to the next working day", leave_as_is: "leaves the date as it falls" };

function RuleBox({ r }: { r: Rule }) {
  return (
    <div className="mt-2 space-y-1 text-xs text-muted-foreground" data-testid="dleng-rule">
      <p>
        Period: {r.period.amount} {r.period.unit}, from {r.starts_from}. The rule {COUNT[r.count_from] ?? r.count_from}
        {r.month_end ? `, ${MONTH_END[r.month_end] ?? r.month_end}` : ""}, and {MOVE[r.when_not_working] ?? r.when_not_working}.
      </p>
      <p data-testid="dleng-rule-sources">Source: {r.authorities.join("; ")}</p>
      <p data-testid="dleng-rule-reviewer">
        Reviewed by {r.reviewed_by} on {r.verified_on}.
      </p>
      {r.not_applied.length > 0 && (
        <p data-testid="dleng-rule-not-applied">VIDHI does not apply these conditions: {r.not_applied.join("; ")}</p>
      )}
    </div>
  );
}

/** Deadline engine: pick a reviewed rule, give the date the period starts from, and see the due date with every step of the working. */
export default function DeadlineEnginePage() {
  const [ruleId, setRuleId] = useState("");
  const [start, setStart] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const list = useQuery({ queryKey: ["deadline-rules"], queryFn: () => apiGet<Listing>("/deadline-rules"), retry: false });
  const run = useMutation({
    mutationFn: () => apiPost<Result>("/deadline-rules/calculate", { rule_id: ruleId, start }),
    onSuccess: (r) => setResult(r),
    onError: (e) => {
      setResult(null);
      toast.error(describe(e));
    },
  });
  const rules = list.data?.rules ?? [];
  const chosen = rules.find((r) => r.id === ruleId) ?? null;

  return (
    <AppShell title="Deadline engine">
      <div className="mx-auto max-w-3xl">
        <Link to="/katalyst" className="inline-block py-2 text-xs text-muted-foreground" data-testid="dleng-back">
          ← Legal Katalyst
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl" data-testid="dleng-title">
          Deadline engine
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="dleng-notice">
          {NOTICE}
        </p>
        {list.error instanceof ApiError && list.error.status === 404 ? (
          <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="dleng-off">
            The deadline engine is not switched on for this server.
          </p>
        ) : list.isLoading ? (
          <p className="mt-6 text-sm text-muted-foreground">Loading…</p>
        ) : rules.length === 0 ? (
          <p className="glass mt-6 rounded-xl p-5 text-sm" data-testid="dleng-none">
            {list.data?.message ?? "No reviewed rule is loaded yet, so nothing can be calculated."} Rules are added by VIDHI’s reviewing advocate, each with its official source.
          </p>
        ) : (
          <form
            className="glass mt-6 space-y-3 rounded-2xl p-5"
            data-testid="dleng-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (ruleId && start) run.mutate();
            }}
          >
            <div>
              <Label htmlFor="dl-rule">Rule</Label>
              <select
                id="dl-rule"
                value={ruleId}
                onChange={(e) => {
                  setRuleId(e.target.value);
                  setResult(null);
                }}
                className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
                data-testid="dleng-rule-select"
              >
                <option value="">Choose a rule</option>
                {rules.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title}
                  </option>
                ))}
              </select>
              {chosen && <RuleBox r={chosen} />}
            </div>
            <div>
              <Label htmlFor="dl-start">{chosen ? `Date: ${chosen.starts_from}` : "Date the period starts from"}</Label>
              <Input
                id="dl-start"
                type="date"
                value={start}
                onChange={(e) => {
                  setStart(e.target.value);
                  setResult(null);
                }}
                className="mt-1 w-48"
                data-testid="dleng-start"
              />
            </div>
            <Button type="submit" disabled={run.isPending || !ruleId || !start} data-testid="dleng-run">
              {run.isPending ? "Working it out…" : "Work out the date"}
            </Button>
          </form>
        )}
        {result && (
          <div className="glass mt-4 rounded-2xl p-5" data-testid="dleng-result">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Due date</p>
            <p className="mt-1 text-2xl" data-testid="dleng-due">
              {result.due} <span className="text-base text-muted-foreground">({result.weekday})</span>
            </p>
            <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm" data-testid="dleng-steps">
              {result.steps.map((s, k) => (
                <li key={k}>{s}</li>
              ))}
            </ol>
            <RuleBox r={result.rule} />
            {result.calendar && (
              <p className="mt-1 text-xs text-muted-foreground" data-testid="dleng-calendar">
                Calendar of non-working days: {result.calendar.title}. Source: {result.calendar.authorities.join("; ")}. Reviewed by {result.calendar.reviewed_by} on {result.calendar.verified_on}.
              </p>
            )}
            <p className="mt-3 text-xs" data-testid="dleng-result-notice">
              {result.notice}
            </p>
            <AddToDates
              key={`${result.rule.id}-${result.start}`}
              title={`${result.rule.title}: due`}
              date={result.due}
              kind="deadline"
              note={`Worked out by the deadline engine from the rule “${result.rule.title}” and the start date ${result.start}. Check it by hand against the official source.`}
              hint="Check the date by hand and against the official source before you add it. Reminders use your usual settings."
              testPrefix="dleng"
            />
          </div>
        )}
      </div>
    </AppShell>
  );
}
