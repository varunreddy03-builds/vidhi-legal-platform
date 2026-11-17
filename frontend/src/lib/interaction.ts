/**
 * InteractionContract — the single source of truth for UI interaction state.
 * Components compose these states; no component invents its own semantics.
 */
import { ApiError, NetworkError } from "@/lib/api";

export type InteractionState =
  | "IDLE"
  | "LOADING"
  | "SUCCESS"
  | "ERROR"
  | "EMPTY"
  | "DISABLED"
  | "PERMISSION_DENIED"
  | "CANCELLED";

export interface Interaction {
  state: InteractionState;
  message: string;
  recoverable: boolean;
}

export const IDLE: Interaction = { state: "IDLE", message: "", recoverable: false };

export function loading(message = "Working…"): Interaction {
  return { state: "LOADING", message, recoverable: false };
}

export function success(message = "Done"): Interaction {
  return { state: "SUCCESS", message, recoverable: false };
}

export function empty(message: string): Interaction {
  return { state: "EMPTY", message, recoverable: false };
}

/** Normalises every failure — including FastAPI 422 detail arrays — into one contract state. */
export function fromError(err: unknown): Interaction {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return { state: "PERMISSION_DENIED", message: "Please sign in again.", recoverable: true };
    }
    if (err.status === 403) {
      return {
        state: "PERMISSION_DENIED",
        message: "You do not have permission to do this.",
        recoverable: false,
      };
    }
    return { state: "ERROR", message: describe(err), recoverable: true };
  }
  return { state: "ERROR", message: "Something went wrong. Try again.", recoverable: true };
}

/** Plain-language message for an error that arrived without a usable `detail` from the server. */
function statusMessage(status: number): string {
  if (status === 429) return "You are doing that too quickly. Please wait a moment and try again.";
  if (status === 413) return "That file is too large.";
  if (status === 502 || status === 503 || status === 504) {
    return "The service is busy or temporarily unavailable. Please try again in a minute.";
  }
  if (status >= 500) return "Something went wrong on our side. Please try again.";
  if (status === 404) return "We could not find that. It may have been removed.";
  return "That did not work. Please check what you entered and try again.";
}

export function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
        return field ? `${field}: ${first.msg}` : first.msg;
      }
    }
    return statusMessage(err.status);
  }
  if (err instanceof NetworkError) return "Cannot reach VIDHI. Check your internet connection and try again.";
  return "Something went wrong. Try again.";
}
