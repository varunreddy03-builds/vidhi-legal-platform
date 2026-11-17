import { Link } from "react-router-dom";

/** Shown on accounts made with a pilot invitation: what to paste, and where to say what went wrong. */
export default function PilotBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p className="mb-4 rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground" role="note" data-testid="pilot-banner">
      <strong className="text-foreground">Pilot account.</strong> Use sample or public drafts only, never client papers. When a result looks wrong, tell us:{" "}
      <Link to="/feedback" className="underline underline-offset-2" data-testid="pilot-banner-link">
        give feedback
      </Link>
      .
    </p>
  );
}
