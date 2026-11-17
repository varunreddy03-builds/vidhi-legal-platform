import { describe, expect, it } from "vitest";
import { LEGAL_REVIEWED, placeholderText } from "./legal";

describe("legal placeholders", () => {
  it("shows a clear marker for a detail that is not configured, never a made-up value", () => {
    expect(placeholderText("Legal entity name")).toBe("[Legal entity name: not configured yet]");
  });
  it("keeps every legal document marked as a draft until a lawyer has reviewed it", () => {
    // Changing a flag to true is a deliberate act that must follow a real review: see LEGAL_REVIEWED in legal.tsx.
    expect(LEGAL_REVIEWED).toEqual({ terms: false, privacy: false, cookies: false });
  });
});