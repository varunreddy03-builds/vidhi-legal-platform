import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError } from "./api";
import { backoffMs, shouldRetry, STALL_MS, uploadWithProgress } from "./upload";

class FakeXHR {
  static plan: Array<{ kind: "ok"; body: unknown } | { kind: "status"; status: number; body: unknown } | { kind: "network" } | { kind: "hang" } | { kind: "sent-then-hang" }> = [];
  static sent = 0;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null; onload: (() => void) | null } = { onprogress: null, onload: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = "";
  responseType = "";
  timeout = 0;
  open() {}
  setRequestHeader() {}
  getResponseHeader() {
    return null;
  }
  abort() {
    this.onabort?.();
  }
  send() {
    FakeXHR.sent++;
    const step = FakeXHR.plan.shift() ?? { kind: "network" as const };
    queueMicrotask(() => {
      if (step.kind === "hang") return; // the line is dead: nothing ever comes back
      if (step.kind === "sent-then-hang") return this.upload.onload?.(); // the whole file went out; the server is still reading it
      if (step.kind === "network") return this.onerror?.();
      this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
      this.status = step.kind === "ok" ? 200 : step.status;
      this.responseText = JSON.stringify(step.body);
      this.onload?.();
    });
  }
}

const file = () => new File(["hello"], "a.txt", { type: "text/plain" });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  FakeXHR.plan = [];
  FakeXHR.sent = 0;
});

describe("upload retry rules", () => {
  it("repeats only trouble that can pass by itself", () => {
    expect(shouldRetry(new NetworkError())).toBe(true);
    expect(shouldRetry(new ApiError(503, null))).toBe(true);
    expect(shouldRetry(new ApiError(502, null))).toBe(true);
    expect(shouldRetry(new ApiError(400, null))).toBe(false);
    expect(shouldRetry(new ApiError(413, null))).toBe(false);
    expect(shouldRetry(new ApiError(500, null))).toBe(false);
    expect(shouldRetry(new Error("x"))).toBe(false);
  });
  it("waits 1, 2, 4 then at most 8 seconds", () => {
    expect([1, 2, 3, 4, 5].map(backoffMs)).toEqual([1000, 2000, 4000, 8000, 8000]);
  });
});

describe("uploadWithProgress", () => {
  it("reports progress and returns the server's answer", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "ok", body: { id: "d1" } }];
    const seen: number[] = [];
    const out = await uploadWithProgress<{ id: string }>("/x", file(), { onProgress: (p) => seen.push(p) });
    expect(out.id).toBe("d1");
    expect(seen).toContain(50);
  });
  it("repeats after a network failure and then succeeds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "network" }, { kind: "ok", body: { id: "d2" } }];
    const retries: number[] = [];
    const p = uploadWithProgress<{ id: string }>("/x", file(), { onRetry: (n) => retries.push(n) });
    await vi.advanceTimersByTimeAsync(1500);
    expect((await p).id).toBe("d2");
    expect(retries).toEqual([1]);
    expect(FakeXHR.sent).toBe(2);
  });
  it("does not repeat a refused file", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "status", status: 400, body: { detail: "Empty file" } }];
    await expect(uploadWithProgress("/x", file())).rejects.toMatchObject({ status: 400 });
    expect(FakeXHR.sent).toBe(1);
  });
  it("gives up after the allowed repeats with the network error", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "network" }, { kind: "network" }, { kind: "network" }];
    const p = uploadWithProgress("/x", file(), { retries: 2 });
    const caught = p.catch((e) => e);
    await vi.advanceTimersByTimeAsync(10000);
    expect(await caught).toBeInstanceOf(NetworkError);
    expect(FakeXHR.sent).toBe(3);
  });
});

describe("a cut or stalled line", () => {
  it("is a network error as soon as the device goes offline, not a cancel and not ten minutes of waiting", async () => {
    vi.useFakeTimers();
    const win = new EventTarget();
    vi.stubGlobal("window", win);
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "hang" }];
    const caught = uploadWithProgress("/x", file(), { retries: 0 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(100);
    win.dispatchEvent(new Event("offline"));
    expect(await caught).toBeInstanceOf(NetworkError);
  });
  it("is a network error when nothing has gone out for the stall time", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "hang" }];
    const caught = uploadWithProgress("/x", file(), { retries: 0 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(STALL_MS + 6000);
    expect(await caught).toBeInstanceOf(NetworkError);
  });
  it("is repeated after a stall and the second try can succeed", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "hang" }, { kind: "ok", body: { id: "d3" } }];
    const p = uploadWithProgress<{ id: string }>("/x", file());
    await vi.advanceTimersByTimeAsync(STALL_MS + 9000);
    expect((await p).id).toBe("d3");
    expect(FakeXHR.sent).toBe(2);
  });
  it("is not a stall once the whole file is out: the server may take a long time to read it", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "sent-then-hang" }];
    let settled = false;
    uploadWithProgress("/x", file(), { retries: 0 }).then(() => (settled = true), () => (settled = true));
    await vi.advanceTimersByTimeAsync(STALL_MS * 3);
    expect(settled).toBe(false);
  });
  it("a person's cancel is still a cancel", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "hang" }];
    const ctl = new AbortController();
    const caught = uploadWithProgress("/x", file(), { retries: 0, signal: ctl.signal }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(100);
    ctl.abort();
    expect(((await caught) as Error).name).toBe("UploadAborted");
  });
});

describe("when the device says it is offline", () => {
  it("does not keep repeating: the network error comes straight back so the file can be kept and sent when the connection returns", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("navigator", { onLine: false });
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.plan = [{ kind: "network" }, { kind: "network" }, { kind: "network" }];
    const caught = uploadWithProgress("/x", file(), { retries: 2 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(50);
    expect(await caught).toBeInstanceOf(NetworkError);
    expect(FakeXHR.sent).toBe(1);
  });
});
