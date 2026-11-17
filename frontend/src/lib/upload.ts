// Upload with progress and retry for weak networks. Same session handling as lib/api.ts (cookie in browsers; bearer token and server address in the Android app),
// same ApiError / NetworkError contract. fetch cannot report upload progress, so this uses XMLHttpRequest.
import { ApiError, NetworkError } from "./api";
import { authToken, isNative, serverBase, setAuthToken } from "./native";

export type UploadOptions = {
  fields?: Record<string, string>;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
  /** How many times a failed attempt is repeated on its own (network trouble, 502/503/504). Default 2. */
  retries?: number;
  /** Called before each automatic repeat, so the screen can say "Retrying…". */
  onRetry?: (attempt: number) => void;
};

/** If no part of the file has gone out for this long, the line is treated as cut: a request on a dead connection can otherwise hang for the whole ten minutes. */
export const STALL_MS = 30_000;

export class UploadAborted extends Error {
  constructor() {
    super("upload cancelled");
    this.name = "UploadAborted";
  }
}

/** Only trouble that can pass by itself is repeated: no connection, a timeout, or the service being busy. A refused file (4xx) or a bug (500) is never repeated. */
export function shouldRetry(err: unknown): boolean {
  if (err instanceof NetworkError) return true;
  return err instanceof ApiError && (err.status === 502 || err.status === 503 || err.status === 504);
}

/** Wait before repeat n (1-based): 1 s, 2 s, 4 s, capped at 8 s. */
export const backoffMs = (n: number): number => Math.min(8000, 1000 * 2 ** (n - 1));

function once<T>(path: string, file: File, o: UploadOptions): Promise<T> {
  let cleanup = () => {};
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    // The line is cut when the device says it is offline, or when nothing has gone out for STALL_MS before the file is fully sent. That is a network failure (so it is repeated and the
    // person is told), not a person's cancel. Once the whole file is out, waiting for the server to read it is normal and takes as long as it takes.
    let cut = false;
    let sent = false;
    let lastMove = Date.now();
    const cutNow = () => {
      cut = true;
      xhr.abort();
    };
    const onOffline = () => {
      if (!sent) cutNow();
    };
    const watchdog = setInterval(() => {
      if (!sent && Date.now() - lastMove > STALL_MS) cutNow();
    }, 5000);
    const win = typeof window === "undefined" ? null : window; // the unit tests run without a browser window
    win?.addEventListener("offline", onOffline);
    cleanup = () => {
      clearInterval(watchdog);
      win?.removeEventListener("offline", onOffline);
    };
    const native = isNative();
    xhr.open("POST", native ? `${serverBase()}/api${path}` : `/api${path}`);
    if (native) {
      xhr.setRequestHeader("X-VIDHI-App", "1");
      const token = authToken();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.responseType = "text";
    xhr.timeout = 10 * 60 * 1000; // a big scan on a slow line may take minutes; after that the person can retry
    xhr.upload.onload = () => {
      sent = true;
    };
    xhr.upload.onprogress = (e) => {
      lastMove = Date.now();
      if (e.lengthComputable && o.onProgress) o.onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
    };
    xhr.onerror = () => reject(new NetworkError());
    xhr.ontimeout = () => reject(new NetworkError());
    xhr.onabort = () => reject(cut ? new NetworkError() : new UploadAborted());
    xhr.onload = () => {
      if (native) {
        const next = xhr.getResponseHeader("X-VIDHI-Token");
        if (next !== null) setAuthToken(next);
      }
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(xhr.status, body));
    };
    o.signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    for (const [k, v] of Object.entries(o.fields ?? {})) form.append(k, v);
    form.append("file", file);
    xhr.send(form);
  }).finally(() => cleanup());
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(id); reject(new UploadAborted()); }, { once: true });
  });

export async function uploadWithProgress<T>(path: string, file: File, o: UploadOptions = {}): Promise<T> {
  const retries = o.retries ?? 2;
  for (let attempt = 0; ; attempt++) {
    if (o.signal?.aborted) throw new UploadAborted();
    try {
      o.onProgress?.(0);
      return await once<T>(path, file, o);
    } catch (e) {
      if (attempt >= retries || !shouldRetry(e)) throw e;
      // The device itself says it is offline: repeating now only waits for nothing. Stop at once so the screen can say the file is kept and will go again when the connection returns.
      if (e instanceof NetworkError && typeof navigator !== "undefined" && navigator.onLine === false) throw e;
      o.onRetry?.(attempt + 1);
      await wait(backoffMs(attempt + 1), o.signal);
    }
  }
}
