/** Which message to show for the `error` the server adds to /login after a Google round trip (see backend/routers/auth.py). */
export function callbackErrorKey(code: string | null): "login.err.google" | "login.err.cancelled" | "login.err.twostep" | "login.err.suspended" | null {
  if (!code) return null;
  if (code === "google_cancelled") return "login.err.cancelled";
  if (code.startsWith("two_step")) return "login.err.twostep";
  if (code === "suspended") return "login.err.suspended";
  return "login.err.google";
}

