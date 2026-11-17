import { apiPost } from "@/lib/api";

/** Browser notifications and "install the app" helpers. Nothing here stores anything in the browser except the notification subscription itself. */

export const pushSupported = () => typeof navigator !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

const toBytes = (b64: string) => {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};

async function registration(): Promise<ServiceWorkerRegistration> {
  const wait = new Promise<never>((_, reject) => setTimeout(() => reject(new Error("Notifications need the installed or published app (not a development server).")), 5000));
  return Promise.race([navigator.serviceWorker.ready, wait]);
}

/** Is this browser already subscribed on this device? */
export async function isSubscribed(): Promise<boolean> {
  if (!pushSupported()) return false;
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    return !!(await reg?.pushManager.getSubscription());
  } catch {
    return false;
  }
}

export async function enablePush(publicKey: string): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked for this site. Allow them in your browser's site settings, then try again.");
  const reg = await registration();
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toBytes(publicKey) }));
  const json = sub.toJSON();
  await apiPost("/push/subscribe", { endpoint: json.endpoint, keys: json.keys });
}

export async function disablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await apiPost("/push/unsubscribe", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let deferred: InstallEvent | null = null;
const listeners = new Set<() => void>();
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as InstallEvent;
    listeners.forEach((f) => f());
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    listeners.forEach((f) => f());
  });
}
export const canInstall = () => deferred !== null;

/** True on an iPhone or iPad in a browser tab (not yet added to the home screen). iOS has no install prompt, so the person is told the steps. iPadOS reports itself as a Mac with a touch screen. */
export function needsIosInstallSteps(): boolean {
  if (typeof navigator === "undefined") return false;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true || (typeof window !== "undefined" && window.matchMedia?.("(display-mode: standalone)").matches);
  return ios && !standalone;
}
export const onInstallChange = (f: () => void) => {
  listeners.add(f);
  return () => void listeners.delete(f);
};
export async function install(): Promise<void> {
  if (!deferred) return;
  await deferred.prompt();
  await deferred.userChoice;
  deferred = null;
  listeners.forEach((f) => f());
}