import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main id="main-content" className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="font-heading text-sm tracking-[0.3em] text-muted-foreground">◈ VIDHI</p>
      <h1 className="text-2xl">This page does not exist</h1>
      <p className="text-sm text-muted-foreground">
        The route you followed is not part of the workspace.
      </p>
      <Link to="/dashboard" className={buttonVariants({ size: "sm" })} data-testid="notfound-home">
        Back to dashboard
      </Link>
    </main>
  );
}
