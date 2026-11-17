// Typed fetch layer over the FastAPI backend. Base is the relative "/api" prefix so the
// same code works in dev (Vite proxies /api → :8001) and behind a single origin in prod.
import { authToken, isNative, serverBase, setAuthToken } from "./native";

const BASE = "/api";

// Fields are declared, not constructor parameter properties: tsconfig sets
// erasableSyntaxOnly, which rejects `constructor(readonly status: number)`.
export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** The request never got an answer (no connection, server down, blocked). Only this is shown as "Cannot reach VIDHI"; any other TypeError is a bug, not the network. */
export class NetworkError extends Error {
  constructor() {
    super("network request failed");
    this.name = "NetworkError";
  }
}

async function send(url: string, init: RequestInit): Promise<Response> {
  if (isNative()) return sendFromApp(url, init);
  try {
    return await fetch(url, init);
  } catch {
    throw new NetworkError();
  }
}

// In the Android app the server is another origin and cookies are not used: the session is a bearer token the server
// hands back in X-VIDHI-Token whenever it starts or ends a session (backend/lib/native_bridge.py).
async function sendFromApp(url: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-VIDHI-App", "1");
  const token = authToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    const res = await fetch(`${serverBase()}${url}`, { ...init, headers, credentials: "omit" });
    const next = res.headers.get("X-VIDHI-Token");
    if (next !== null) setAuthToken(next);
    return res;
  } catch {
    throw new NetworkError();
  }
}

/** A raw request to an /api path with the same session handling as the helpers below (for downloads, audio, images). */
export const apiFetch = (path: string, init: RequestInit = {}): Promise<Response> => send(path, init);

type JsonBody = unknown;

async function request<T>(method: string, path: string, body?: JsonBody): Promise<T> {
  // Auth rides the httpOnly session cookie automatically — never add auth headers here.
  const res = await send(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // FastAPI reports request-validation failures as 422 with a {detail: [...]} body.
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new ApiError(res.status, errBody);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// The response type is yours to declare: nothing infers across the Python boundary, so a
// TS interface here mirrors the endpoint's Pydantic model by hand — keep the two in sync.
export const apiGet = <T>(path: string) => request<T>("GET", path);
export const apiPost = <T>(path: string, body?: JsonBody) => request<T>("POST", path, body ?? null);
export const apiPut = <T>(path: string, body?: JsonBody) => request<T>("PUT", path, body ?? null);
export const apiPatch = <T>(path: string, body?: JsonBody) =>
  request<T>("PATCH", path, body ?? null);
export const apiDelete = <T>(path: string, body?: JsonBody) => request<T>("DELETE", path, body);

// Multipart upload through the same /api base and the same ApiError contract.
export async function apiUpload<T>(path: string, file: File, fields?: Record<string, string>): Promise<T> {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields ?? {})) form.append(k, v);
  form.append("file", file);
  const res = await send(`${BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  return (await res.json()) as T;
}
