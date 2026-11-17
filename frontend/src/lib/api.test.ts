import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from "./api";

function reply(status: number, body: unknown, jsonFails = false) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => (jsonFails ? Promise.reject(new Error("not json")) : Promise.resolve(body)),
  } as unknown as Response;
}

function mockFetch(response: Response) {
  const fn = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("the API layer", () => {
  it("sends every request under /api with no auth header (the session cookie does that)", async () => {
    const fetchFn = mockFetch(reply(200, { ok: true }));
    await apiGet("/matters");
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/matters");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(JSON.stringify(init)).not.toMatch(/authorization/i);
  });

  it("returns the parsed body on success", async () => {
    mockFetch(reply(200, { id: "m1", title: "A v. B" }));
    expect(await apiGet<{ id: string }>("/matters/m1")).toEqual({ id: "m1", title: "A v. B" });
  });

  it("returns undefined for 204 No Content", async () => {
    mockFetch(reply(204, null));
    expect(await apiDelete("/x")).toBeUndefined();
  });

  it("posts JSON with a content type", async () => {
    const fetchFn = mockFetch(reply(200, {}));
    await apiPost("/auth/login", { email: "a@example.com" });
    const [, init] = fetchFn.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({ email: "a@example.com" });
  });

  it.each([
    ["PUT", apiPut],
    ["PATCH", apiPatch],
  ])("%s uses the right verb and sends null instead of nothing", async (verb, call) => {
    const fetchFn = mockFetch(reply(200, {}));
    await call("/x");
    const [, init] = fetchFn.mock.calls[0];
    expect(init.method).toBe(verb);
    expect(init.body).toBe("null");
  });

  it("throws an ApiError carrying the status and the server's body", async () => {
    mockFetch(reply(422, { detail: "Bad date" }));
    const error = (await apiGet("/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.body).toEqual({ detail: "Bad date" });
  });

  it("still throws an ApiError when the error body is not JSON", async () => {
    mockFetch(reply(502, null, true));
    const error = (await apiGet("/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.body).toBeNull();
  });

  it("uploads a file as multipart form data with extra fields", async () => {
    const fetchFn = mockFetch(reply(200, { id: "p1" }));
    const file = new File(["hello"], "challan.txt", { type: "text/plain" });
    expect(await apiUpload("/recovery/cases/c1/proofs", file, { kind: "INVOICE" })).toEqual({ id: "p1" });
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/recovery/cases/c1/proofs");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get("kind")).toBe("INVOICE");
    expect((init.body.get("file") as File).name).toBe("challan.txt");
    expect(init.headers).toBeUndefined(); // the browser sets the multipart boundary itself
  });

  it("reports a failed upload the same way as any other failure", async () => {
    mockFetch(reply(413, { detail: "File too large" }));
    const error = (await apiUpload("/x", new File(["x"], "a.txt")).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(413);
  });
});
