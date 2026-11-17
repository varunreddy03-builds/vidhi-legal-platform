import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

type Wrong = { id: string; user_email: string; ref: string; ref_kind?: string; tool_label?: string; problem: string; note?: string; created_at: string };
type Form = { id: string; user_email: string; created_at: string; answers: Record<string, string | number | boolean> };
type Feedback = { wrong_results: Wrong[]; forms: Form[]; answers_marked_down: { comment?: string; created_at?: string }[]; pilot_organisations: number };

const PROBLEM: Record<string, string> = {
  says_not_found_but_it_exists: "said not found / could not check, but it is real",
  says_found_but_it_is_wrong: "said found, but it is wrong",
  unclear_or_confusing: "unclear why it got this label",
  other: "other",
};
const humanise = (label?: string) => (label ? label.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()) : "?");
const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "");

/** What pilot lawyers said: results marked wrong (reference and label only), feedback forms, and answers marked down. Read it after each session. */
export default function PilotFeedbackList() {
  const q = useQuery({ queryKey: ["pilot-feedback"], queryFn: () => apiGet<Feedback>("/admin/pilot/feedback") });
  const d = q.data;
  return (
    <div className="mt-8 space-y-6" data-testid="pilot-feedback-list">
      <h2 className="text-lg">Pilot feedback</h2>
      {q.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {d && (
        <>
          <section>
            <h4 className="text-sm font-medium">Results marked wrong or unclear ({d.wrong_results.length})</h4>
            <ul className="mt-2 space-y-2" data-testid="pf-wrong-list">
              {d.wrong_results.map((w) => (
                <li key={w.id} className="glass rounded-lg p-3 text-sm" data-testid="pf-wrong-row">
                  <p className="break-words font-medium">{w.ref}</p>
                  <p className="text-xs text-muted-foreground">
                    The tool said: {humanise(w.tool_label)} · The lawyer says it {PROBLEM[w.problem] ?? w.problem} · {w.user_email} · {day(w.created_at)}
                  </p>
                  {w.note && <p className="mt-1 text-xs">Note: {w.note}</p>}
                </li>
              ))}
              {d.wrong_results.length === 0 && <li className="text-sm text-muted-foreground">None yet.</li>}
            </ul>
          </section>
          <section>
            <h4 className="text-sm font-medium">Feedback forms ({d.forms.length})</h4>
            <ul className="mt-2 space-y-2">
              {d.forms.map((f) => (
                <li key={f.id} className="glass rounded-lg p-3 text-xs" data-testid="pf-form-row">
                  <p className="text-muted-foreground">
                    {f.user_email} · {day(f.created_at)} · could do it: {String(f.answers.did_task)} · understood: {String(f.answers.understood_report)} · rely: {String(f.answers.trust)}/5 · would use:{" "}
                    {String(f.answers.would_use)} · may contact: {f.answers.can_contact ? "yes" : "no"}
                  </p>
                  {f.answers.wrong_or_confusing && <p className="mt-1 text-sm">Wrong or confusing: {String(f.answers.wrong_or_confusing)}</p>}
                  {f.answers.missing && <p className="mt-1 text-sm">Missing: {String(f.answers.missing)}</p>}
                  {f.answers.other && <p className="mt-1 text-sm">Other: {String(f.answers.other)}</p>}
                </li>
              ))}
              {d.forms.length === 0 && <li className="text-sm text-muted-foreground">None yet.</li>}
            </ul>
          </section>
          <section>
            <h4 className="text-sm font-medium">Answers marked down in pilot organisations ({d.answers_marked_down.length})</h4>
            <ul className="mt-2 space-y-1 text-sm">
              {d.answers_marked_down.map((a, i) => (
                <li key={i}>
                  {day(a.created_at)} {a.comment ? `· ${a.comment}` : "· (no comment)"}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
