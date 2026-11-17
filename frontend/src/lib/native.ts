// Support for the Android app. The app carries the web screens inside it and talks to a VIDHI server over the internet
// (a different address from the app's own), so it needs to know that address and keeps its session as a bearer token
// instead of a cookie (see backend/lib/native_bridge.py). In a normal browser none of this is active: isNative() is
// false, the server address is "" and every request stays a relative /api call with the httpOnly cookie, as before.
import { Capacitor } from "@capacitor/core";

const SERVER_KEY = "vidhi_server_url";
const TOKEN_KEY = "vidhi_app_token";

/** Pre-filled server address, set when the app is built (scripts/build-apk.ps1 -ServerUrl). */
export const DEFAULT_SERVER: string = (import.meta.env.VITE_DEFAULT_SERVER_URL as string | undefined) ?? "";

export const isNative = (): boolean => Capacitor.isNativePlatform();

function read(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* storage blocked: the app then asks again next time */
  }
}

/** "my-server.example.com/" -> "https://my-server.example.com"; "" when nothing usable was typed. */
export function cleanServerUrl(raw: string): string {
  let v = raw.trim();
  if (!v) return "";
  if (!/^https?:\/\//i.test(v)) v = `https://${v}`;
  try {
    const u = new URL(v);
    if (!u.hostname.includes(".") && u.hostname !== "localhost") return ""; // "https://" or a bare word is not a server address
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}

/** The VIDHI server this app talks to ("" in a browser, where the page's own origin is the server). */
export const serverBase = (): string => (isNative() ? read(SERVER_KEY) : "");

export function setServerBase(url: string): void {
  const next = cleanServerUrl(url);
  if (next !== read(SERVER_KEY)) write(TOKEN_KEY, ""); // a different server cannot honour the old session
  write(SERVER_KEY, next);
}

export const authToken = (): string => read(TOKEN_KEY);
export const setAuthToken = (token: string): void => write(TOKEN_KEY, token);

/** True when the server answers at all (any HTTP answer counts; only "no answer" is a failure). */
export async function serverReachable(base: string): Promise<boolean> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10000);
  try {
    await fetch(`${base}/api/org/branding`, { headers: { "X-VIDHI-App": "1" }, signal: ctl.signal, cache: "no-store" });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
