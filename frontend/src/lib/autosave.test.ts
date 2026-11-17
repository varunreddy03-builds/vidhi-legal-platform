import { afterEach, describe, expect, it, vi } from "vitest";
import { clearLocal, differsFromSaved, readLocal, statusText, writeLocal, type SaveState } from "./autosave";

function fakeStorage() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
}

afterEach(() => vi.unstubAllGlobals());

describe("the copy kept on the device", () => {
  it("is written, read back and cleared", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    expect(readLocal("d1")).toBeNull();
    writeLocal("d1", "Title", "Body typed on a train");
    expect(readLocal("d1")).toMatchObject({ title: "Title", body: "Body typed on a train" });
    clearLocal("d1");
    expect(readLocal("d1")).toBeNull();
  });
  it("keeps drafts apart", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    writeLocal("a", "A", "one");
    writeLocal("b", "B", "two");
    expect(readLocal("a")?.body).toBe("one");
    expect(readLocal("b")?.body).toBe("two");
  });
  it("survives blocked storage without throwing", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } });
    expect(() => writeLocal("d", "t", "b")).not.toThrow();
    expect(readLocal("d")).toBeNull();
    expect(() => clearLocal("d")).not.toThrow();
  });
  it("ignores something that is not a saved copy", () => {
    vi.stubGlobal("localStorage", { getItem: () => "not json", setItem: () => {}, removeItem: () => {} });
    expect(readLocal("d")).toBeNull();
    vi.stubGlobal("localStorage", { getItem: () => JSON.stringify({ title: 1 }), setItem: () => {}, removeItem: () => {} });
    expect(readLocal("d")).toBeNull();
  });
});

describe("offering the copy back", () => {
  const saved = { title: "T", body: "saved text" };
  it("only when it differs from the saved draft", () => {
    expect(differsFromSaved(null, saved)).toBe(false);
    expect(differsFromSaved({ title: "T", body: "saved text", at: 1 }, saved)).toBe(false);
    expect(differsFromSaved({ title: "T", body: "saved text and more", at: 1 }, saved)).toBe(true);
    expect(differsFromSaved({ title: "New", body: "saved text", at: 1 }, saved)).toBe(true);
  });
});

describe("what the person is told", () => {
  const states: SaveState[] = ["saved", "dirty", "saving", "offline", "failed"];
  it("has a sentence for every state, and the two trouble states say the text is kept and what to do", () => {
    for (const s of states) expect(statusText(s).length).toBeGreaterThan(5);
    expect(statusText("offline")).toMatch(/kept on this phone.*back online/);
    expect(statusText("failed")).toMatch(/kept on this phone.*Press Save/);
  });
});
