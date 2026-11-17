import { describe, expect, it } from "vitest";
import { ApiError, NetworkError } from "./api";
import { describe as describeError, empty, fromError, IDLE, loading, success } from "./interaction";

const err = (status: number, body: unknown = null) => new ApiError(status, body);

describe("describe (what a person is told when a request fails)", () => {
  it("shows the server's own sentence when it sent one", () => {
    expect(describeError(err(409, { detail: "That email is already registered." }))).toBe("That email is already registered.");
  });

  it("names the field for a validation error", () => {
    expect(describeError(err(422, { detail: [{ loc: ["body", "invoice_date"], msg: "Enter a valid date" }] }))).toBe("invoice_date: Enter a valid date");
  });

  it("shows only the message when the error has no field", () => {
    expect(describeError(err(422, { detail: [{ msg: "Something is wrong" }] }))).toBe("Something is wrong");
  });

  it.each([
    [429, "too quickly"],
    [413, "too large"],
    [502, "temporarily unavailable"],
    [503, "temporarily unavailable"],
    [504, "temporarily unavailable"],
    [500, "on our side"],
    [404, "could not find"],
    [400, "did not work"],
  ])("falls back to a plain sentence for status %i", (status, fragment) => {
    expect(describeError(err(status))).toContain(fragment);
  });

  it("falls back when the detail list has no usable message", () => {
    expect(describeError(err(422, { detail: [{}] }))).toContain("did not work");
  });

  it("never shows a raw exception to the person", () => {
    expect(describeError(new NetworkError())).toBe("Cannot reach VIDHI. Check your internet connection and try again.");
    expect(describeError(new Error("boom"))).toBe("Something went wrong. Try again.");
    expect(describeError(undefined)).toBe("Something went wrong. Try again.");
  });
});

describe("fromError", () => {
  it("treats a lost session as recoverable", () => {
    expect(fromError(err(401))).toEqual({ state: "PERMISSION_DENIED", message: "Please sign in again.", recoverable: true });
  });

  it("treats a forbidden action as not recoverable", () => {
    const out = fromError(err(403));
    expect(out.state).toBe("PERMISSION_DENIED");
    expect(out.recoverable).toBe(false);
  });

  it("treats other server errors as recoverable errors with the described message", () => {
    expect(fromError(err(422, { detail: "Bad input" }))).toEqual({ state: "ERROR", message: "Bad input", recoverable: true });
  });

  it("turns any non-API failure into a generic error", () => {
    expect(fromError(new Error("boom"))).toEqual({ state: "ERROR", message: "Something went wrong. Try again.", recoverable: true });
  });
});

describe("the other interaction states", () => {
  it("has the documented shapes", () => {
    expect(IDLE).toEqual({ state: "IDLE", message: "", recoverable: false });
    expect(loading()).toEqual({ state: "LOADING", message: "Working…", recoverable: false });
    expect(loading("Reading your file")).toMatchObject({ message: "Reading your file" });
    expect(success()).toMatchObject({ state: "SUCCESS", message: "Done" });
    expect(empty("No cases yet")).toEqual({ state: "EMPTY", message: "No cases yet", recoverable: false });
  });
});
