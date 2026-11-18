import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

type Answer = { reviewers: { label: string; named: boolean; acts_confirmed: number; provisions_confirmed: number }[]; note: string };

// Who has compared the law text with the official text. Counts come from recorded confirmations only; reviewers are shown by code, never by name.
export default function ReviewedBy() {
  const q = useQuery<Answer>({ queryKey: ["reviewers"], queryFn: () => apiGet<Answer>("/reviewers"), staleTime: 5 * 60_000 });
  if (!q.data) return null;
  const withWork = q.data.reviewers.filter((r) => r.provisions_confirmed > 0);
  const provisions = withWork.reduce((n, r) => n + r.provisions_confirmed, 0);
  return (
    <div className="glass mt-4 rounded-xl p-4 text-sm" data-testid="reviewed-by">
      {withWork.length === 0 ? (
        <p>No advocate's confirmation has been recorded yet, so no law text here is marked as reviewed.</p>
      ) : (
        <>
          <p data-testid="reviewed-by-summary">
            Compared with the official text by {withWork.length} practising advocate{withWork.length === 1 ? "" : "s"}: {provisions} provision{provisions === 1 ? "" : "s"} so far.
          </p>
          <ul className="mt-1 text-muted-foreground">
            {withWork.map((r) => (
              <li key={r.label}>{r.label}: {r.provisions_confirmed} provision{r.provisions_confirmed === 1 ? "" : "s"} in {r.acts_confirmed} Act{r.acts_confirmed === 1 ? "" : "s"}</li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-1 text-xs text-muted-foreground">{q.data.note}</p>
    </div>
  );
}
