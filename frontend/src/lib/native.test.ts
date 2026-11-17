import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/core", () => ({ Capacitor: { isNativePlatform: () => true } }));

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
});
afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: unknown, token?: string) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    headers: new Headers(token === undefined ? {} : { "X-VIDHI-Token": token }),
  } as unknown as Response;
}

describe("the Android app's server address", () => {
  it("cleans what people type", async () => {
    const { cleanServerUrl } = await import("./native");
    expect(cleanServerUrl("  my-server.example.com/ ")).toBe("https://my-server.example.com");
    expect(cleanServerUrl("http://192.168.1.5:3000/path")).toBe("http://192.168.1.5:3000");
    expect(cleanServerUrl("")).toBe("");
    expect(cleanServerUrl("https://")).toBe("");
  });

  it("forgets the old session when the server changes", async () => {
    const { setServerBase, setAuthToken, authToken } = await import("./native");
    setServerBase("https://a.example.com");
    setAuthToken("tok");
    setServerBase("https://a.example.com");
    expect(authToken()).toBe("tok");
    setServerBase("https://b.example.com");
    expect(authToken()).toBe("");
  });
});

describe("API calls from the Android app", () => {
  it("go to the saved server with the bearer token and no cookies, and keep the token the server returns", async () => {
    const { setServerBase, setAuthToken, authToken } = await import("./native");
    const { apiGet, apiPost } = await import("./api");
    setServerBase("https://api.example.com");
    setAuthToken("old-token");
    const fetchFn = vi.fn().mockResolvedValueOnce(reply(200, { ok: true })).mockResolvedValueOnce(reply(200, { ok: true }, "new-token"));
    vi.stubGlobal("fetch", fetchFn);

    await apiGet("/matters");
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("https://api.example.com/api/matters");
    expect(init.credentials).toBe("omit");
    expect((init.headers as Headers).get("X-VIDHI-App")).toBe("1");
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer old-token");

    await apiPost("/auth/login", { email: "a@example.com" });
    expect(authToken()).toBe("new-token");
    expect((fetchFn.mock.calls[1][1].headers as Headers).get("Content-Type")).toBe("application/json");
  });

  it("clears the token when the server says the session ended", async () => {
    const { setServerBase, setAuthToken, authToken } = await import("./native");
    const { apiPost } = await import("./api");
    setServerBase("https://api.example.com");
    setAuthToken("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, {}, "")));
    await apiPost("/auth/logout");
    expect(authToken()).toBe("");
  });

  it("reports an unreachable server as a network error", async () => {
    const { setServerBase } = await import("./native");
    const { apiGet, NetworkError } = await import("./api");
    setServerBase("https://api.example.com");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiGet("/matters")).rejects.toBeInstanceOf(NetworkError);
  });
});
