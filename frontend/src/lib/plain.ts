// Plain-language wording for things the engine reports in technical terms. The engine's decisions are never changed
// here: only how they are said to someone who has never used software like this.

export const PLAIN_CLAIM_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" }> = {
  VERIFIED: { label: "Backed up by a real source", tone: "good" },
  PARTIALLY_VERIFIED: { label: "Partly backed up", tone: "warn" },
  UNSUPPORTED: { label: "Not backed up yet. Check before relying on it", tone: "warn" },
  UNVERIFIED: { label: "Not backed up yet. Check before relying on it", tone: "warn" },
  UNAVAILABLE: { label: "Could not be checked", tone: "bad" },
};

export const TONE_COLOR = { good: "#7FE3B0", warn: "#F5B35C", bad: "#FF8A73" } as const;

export const PLAIN_CLAIM_KIND: Record<string, string> = {
  LEGAL: "About the law",
  FACTUAL: "From your papers",
  PROCEDURAL: "A suggested step",
  ABSENCE: "Not found in your papers",
};

export const PLAIN_MATTER_STATUS: Record<string, string> = {
  OPEN: "Open",
  ON_HOLD: "On hold",
  CLOSED: "Closed",
};

export const EXAMPLE_QUESTIONS = [
  "My customer has not paid my invoice for two months. What can I do?",
  "What should I check before signing a rent agreement?",
  "Is a promise made on WhatsApp valid as an agreement?",
  "What does 'indemnity' mean in a contract?",
  "मेरे किरायेदार ने तीन महीने से किराया नहीं दिया। मैं क्या करूँ?",
];

export function firstName(full?: string | null): string {
  const f = (full ?? "").trim().split(/\s+/)[0];
  return f || "friend";
}
