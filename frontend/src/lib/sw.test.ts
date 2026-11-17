import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

// public/sw.js runs in a service worker, which a unit test cannot start. Here it runs against a stand-in for the worker's scope instead,
// so what happens on a push and on a click is still checked.
const source = readFileSync(resolve(__dirname, "../../public/sw.js"), "utf8");

type Handler = (event: Record<string, unknown>) => void;
function load() {
  const handlers: Record<string, Handler> = {};
  const shown: { title: string; options: Record<string, unknown> }[] = [];
  const opened: string[] = [];
  const focused: string[] = [];
  let windows: { url: string; focus: () => Promise<unknown>; navigate: (u: string) => Promise<unknown> }[] = [];
  const scope = {
    location: { origin: "https://app.example.in" },
    addEventListener: (name: string, fn: Handler) => (handlers[name] = fn),
    skipWaiting: vi.fn(),
    registration: { showNotification: (title: string, options: Record<string, unknown>) => (shown.push({ title, options }), Promise.resolve()) },
    clients: {
      claim: vi.fn(),
      matchAll: () => Promise.resolve(windows),
      openWindow: (url: string) => (opened.push(url), Promise.resolve(null)),
    },
  };
  new Function("self", source)(scope);
  const waitUntil = (p: Promise<unknown>) => void p;
  const run = async (name: string, event: Record<string, unknown>) => {
    let pending: Promise<unknown> = Promise.resolve();
    handlers[name]({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) });
    await pending;
  };
  return {
    handlers, shown, opened, focused, scope, waitUntil, run,
    setWindows: (w: string[]) => (windows = w.map((url) => ({ url, focus: () => (focused.push(url), Promise.resolve()), navigate: (u: string) => (focused.push("navigate " + u), Promise.resolve({ focus: () => Promise.resolve() })) }))),
  };
}
const push = (data: unknown) => ({ data: { json: () => (typeof data === "string" ? JSON.parse(data) : data) } });

describe("service worker", () => {
  it("takes over at once", () => {
    const sw = load();
    expect(Object.keys(sw.handlers).sort()).toEqual(["activate", "fetch", "install", "notificationclick", "push"]);
  });

  it("keeps only the app's own screens for offline use, never anything private", async () => {
    const stored: string[] = [];
    const cache = { put: (k: unknown) => (stored.push(typeof k === "string" ? k : (k as Request).url), Promise.resolve()) };
    const sw = load();
    const g = globalThis as Record<string, unknown>;
    g.caches = { open: () => Promise.resolve(cache), match: () => Promise.resolve(undefined), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
    g.fetch = () => Promise.resolve({ ok: true, clone: () => ({}) });
    const fetchEvent = (url: string, extra: Record<string, unknown> = {}) => {
      let answered: Promise<unknown> | null = null;
      sw.handlers.fetch({ request: { url, method: "GET", mode: "cors", ...extra }, respondWith: (p: Promise<unknown>) => (answered = p) });
      return answered as Promise<unknown> | null;
    };
    const o = "https://app.example.in";
    expect(fetchEvent(`${o}/api/matters`)).toBeNull(); // account data: the browser handles it, nothing stored
    expect(fetchEvent(`${o}/api/documents/1/download`)).toBeNull();
    expect(fetchEvent("https://other.example.com/assets/x.js")).toBeNull(); // another site
    expect(fetchEvent(`${o}/assets/index-abc123.js`, { method: "POST" })).toBeNull();
    await fetchEvent(`${o}/assets/index-abc123.js`);
    await fetchEvent(`${o}/matters`, { mode: "navigate" });
    await new Promise((r) => setTimeout(r, 0));
    expect(stored.sort()).toEqual(["/index.html", `${o}/assets/index-abc123.js`].sort());
    expect(stored.some((k) => k.includes("/api/"))).toBe(false);
  });

  it("opens the last stored page when there is no connection", async () => {
    const sw = load();
    const g = globalThis as Record<string, unknown>;
    g.caches = { open: () => Promise.resolve({ put: () => Promise.resolve() }), match: (k: string) => Promise.resolve(k === "/index.html" ? { body: "shell" } : undefined) };
    g.fetch = () => Promise.reject(new TypeError("offline"));
    let answered: Promise<unknown> | null = null;
    sw.handlers.fetch({ request: { url: "https://app.example.in/matters", method: "GET", mode: "navigate" }, respondWith: (p: Promise<unknown>) => (answered = p) });
    expect(await answered).toEqual({ body: "shell" });
  });

  it("shows the reminder it is sent, with a link inside the app", async () => {
    const sw = load();
    await sw.run("push", push({ title: "VIDHI reminder", body: "A date you saved in VIDHI is coming up in one hour.", url: "/deadlines" }));
    expect(sw.shown).toHaveLength(1);
    expect(sw.shown[0].title).toBe("VIDHI reminder");
    expect(sw.shown[0].options).toMatchObject({ body: "A date you saved in VIDHI is coming up in one hour.", data: { url: "/deadlines" } });
  });

  it("never follows a link that leaves the app, and copes with a damaged message", async () => {
    const sw = load();
    for (const url of ["https://evil.example.com/x", "//evil.example.com", "javascript:alert(1)"]) await sw.run("push", push({ title: "t", body: "b", url }));
    expect(sw.shown.map((s) => (s.options.data as { url: string }).url)).toEqual(["/deadlines", "/deadlines", "/deadlines"]);
    await sw.run("push", { data: { json: () => { throw new Error("not json"); } } });
    await sw.run("push", {});
    expect(sw.shown.at(-1)?.title).toBe("VIDHI");
    expect(sw.shown).toHaveLength(5);
  });

  it("opens the app on a click, or reuses the window that is already open", async () => {
    const sw = load();
    const close = vi.fn();
    sw.setWindows([]);
    await sw.run("notificationclick", { notification: { close, data: { url: "/deadlines" } } });
    expect(close).toHaveBeenCalled();
    expect(sw.opened).toEqual(["https://app.example.in/deadlines"]);
    sw.setWindows(["https://app.example.in/matters"]);
    await sw.run("notificationclick", { notification: { close, data: { url: "/deadlines" } } });
    expect(sw.opened).toHaveLength(1);
    expect(sw.focused[0]).toBe("navigate https://app.example.in/deadlines");
  });
});