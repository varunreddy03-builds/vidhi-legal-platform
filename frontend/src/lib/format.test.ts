import { describe, expect, it } from "vitest";
import { formatDate, formatDateText, formatDateTime } from "./format";

describe("formatDate", () => {
  it("never produces an ambiguous numeric date", () => {
    expect(formatDate("2026-06-10")).toBe("10 Jun 2026");
    expect(formatDate("2026-10-06")).toBe("6 Oct 2026");
  });

  it("keeps a calendar date on the same day regardless of time zone", () => {
    expect(formatDate("2026-01-01")).toBe("1 Jan 2026");
  });

  it("reads zone-less server timestamps as UTC", () => {
    const d = formatDateTime("2026-06-10T10:00:00");
    expect(d).toMatch(/^10 Jun 2026/);
    expect(formatDateTime("2026-06-10T10:00:00")).toBe(formatDateTime("2026-06-10T10:00:00Z"));
  });

  it("falls back to a dash for missing or invalid values", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("not a date")).toBe("—");
  });
});

describe("formatDateText", () => {
  it("reformats ISO dates only", () => {
    expect(formatDateText("2026-03-05")).toBe("5 Mar 2026");
  });

  it("leaves ambiguous free text exactly as written", () => {
    expect(formatDateText("10/6/2026")).toBe("10/6/2026");
    expect(formatDateText("date unknown")).toBe("date unknown");
    expect(formatDateText("")).toBe("");
  });
});
