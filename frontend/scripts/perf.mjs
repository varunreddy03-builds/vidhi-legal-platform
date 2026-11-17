// First-screen load time and page weight on a mid-range Android phone setting.
//   node scripts/perf.mjs <label> [--runs 5] [--backend http://127.0.0.1:8001] [--profile mid|fast]
// Serves frontend/dist the way deploy/nginx.conf does (gzip for text, one-year immutable caching for /assets, no-cache for index.html, SPA fallback) and proxies /api to the backend.
// "mid" = Lighthouse's mobile profile: 4x CPU slowdown, 1.6 Mbit/s down, 750 kbit/s up, 150 ms round trip, a 412x915 phone with a touch screen. Every run starts with an EMPTY cache
// (a first visit); "repeat" runs reuse the cache (a return visit). Writes ../docs/perf/perf-<label>-<date>.json (never overwrites) and prints a table. Uses the installed Edge or Chrome.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.resolve(here, "../dist");
const arg = (n, d) => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : d; };
const label = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : "run";
const runs = Number(arg("--runs", "5"));
const backend = new URL(arg("--backend", "http://127.0.0.1:8001"));
const profile = arg("--profile", "mid");
const PROFILES = { slow: { cpu: 4, down: (400 * 1024) / 8, up: (400 * 1024) / 8, rtt: 400 }, mid: { cpu: 4, down: (1.6 * 1024 * 1024) / 8, up: (750 * 1024) / 8, rtt: 150 }, fast: { cpu: 1, down: -1, up: -1, rtt: 0 } };
const P = PROFILES[profile];
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json", ".txt": "text/plain" };
const GZ = new Set([".html", ".js", ".css", ".json", ".svg", ".webmanifest", ".txt"]);

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname.startsWith("/api/")) {
    const p = http.request({ host: backend.hostname, port: backend.port, path: req.url, method: req.method, headers: { ...req.headers, host: backend.host } }, (r) => {
      const h = { ...r.headers };
      if (/json/.test(h["content-type"] || "") && /gzip/.test(req.headers["accept-encoding"] || "") && !h["content-encoding"]) {
        const chunks = []; r.on("data", (c) => chunks.push(c)); r.on("end", () => { const b = zlib.gzipSync(Buffer.concat(chunks), { level: 5 }); delete h["content-length"]; h["content-encoding"] = "gzip"; res.writeHead(r.statusCode, h); res.end(b); });
      } else { res.writeHead(r.statusCode, h); r.pipe(res); }
    });
    p.on("error", () => { res.writeHead(502); res.end(); });
    req.pipe(p);
    return;
  }
  let file = path.join(dist, decodeURIComponent(url.pathname));
  if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const ext = path.extname(file);
  const headers = { "Content-Type": MIME[ext] || "application/octet-stream", "Cache-Control": url.pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache" };
  let body = fs.readFileSync(file);
  if (GZ.has(ext) && body.length > 1024 && /gzip/.test(req.headers["accept-encoding"] || "")) { body = zlib.gzipSync(body, { level: 5 }); headers["Content-Encoding"] = "gzip"; headers.Vary = "Accept-Encoding"; }
  res.writeHead(200, headers);
  res.end(body);
});
await new Promise((r) => server.listen(4173, "127.0.0.1", r));
const base = "http://127.0.0.1:4173";

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || "msedge" });
const UA = "Mozilla/5.0 (Linux; Android 13; Moto G Power) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36";

async function newPage(storageState) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, userAgent: UA, storageState });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  return { ctx, page, cdp };
}

// a throwaway account, signed in once, whose cookies the timed visits reuse (the sign-in itself is not timed)
let state;
{
  const { ctx, page } = await newPage();
  const id = Date.now().toString(36);
  await page.goto(base + "/login?mode=signup");
  await page.getByTestId("auth-fullname-input").fill("Perf Lawyer");
  await page.getByTestId("auth-org-input").fill("Perf Chambers " + id);
  await page.getByTestId("auth-email-input").fill(`perf-${id}@example.com`);
  await page.getByTestId("auth-password-input").fill(`Zq9-${Math.random().toString(36).slice(2, 10)}-Xv7`);
  await page.getByTestId("auth-privacy-checkbox").check();
  await page.waitForTimeout(1600);
  await page.getByTestId("auth-submit-button").click();
  await page.getByTestId("start-greeting").waitFor({ timeout: 30000 }).catch(async (e) => {
    console.error("Sign-in for the test account did not reach the home screen. At:", page.url(), "|", (await page.locator("body").innerText()).slice(0, 400));
    throw e;
  });
  state = await ctx.storageState();
  await ctx.close();
}

async function measure(route, signedIn, warm) {
  const { ctx, page, cdp } = await newPage(signedIn ? state : undefined);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: !warm });
  const sizes = new Map();
  const info = new Map();
  cdp.on("Network.responseReceived", (e) => info.set(e.requestId, { url: e.response.url, type: e.type, status: e.response.status, fromCache: e.response.fromDiskCache || e.response.fromServiceWorker }));
  const ends = new Map(); const starts = new Map();
  cdp.on("Network.requestWillBeSent", (e) => starts.set(e.requestId, e.timestamp));
  cdp.on("Network.loadingFinished", (e) => { sizes.set(e.requestId, e.encodedDataLength); ends.set(e.requestId, e.timestamp); });
  if (warm) { await page.goto(base + route); await page.waitForLoadState("networkidle"); sizes.clear(); info.clear(); }
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: P.rtt, downloadThroughput: P.down, uploadThroughput: P.up });
  if (P.cpu > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: P.cpu });
  await page.addInitScript(() => {
    window.__m = { fcp: null, lcp: null, long: 0, cls: 0 };
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === "first-contentful-paint") window.__m.fcp = e.startTime; }).observe({ type: "paint", buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__m.lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__m.long += Math.max(0, e.duration - 50); }).observe({ type: "longtask", buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__m.cls += e.value; }).observe({ type: "layout-shift", buffered: true });
  });
  const t0 = Date.now();
  await page.goto(base + route, { waitUntil: "load", timeout: 120000 });
  const loadMs = Date.now() - t0;
  const target = signedIn ? '[data-testid="start-greeting"], [data-testid="page-title"]' : "h1, form";
  await page.locator(target).first().waitFor({ timeout: 120000 });
  const usableMs = Date.now() - t0;
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(400);
  const m = await page.evaluate(() => window.__m);
  const nav = await page.evaluate(() => { const n = performance.getEntriesByType("navigation")[0]; return { ttfb: n.responseStart, dcl: n.domContentLoadedEventEnd }; });
  const firstStart = Math.min(...starts.values());
  const by = { js: 0, css: 0, font: 0, image: 0, api: 0, other: 0 }; let total = 0, reqs = 0; const apiCalls = []; const list = [];
  for (const [id, b] of sizes) {
    const i = info.get(id); if (!i || i.fromCache) continue;
    reqs++; total += b;
    const u = new URL(i.url);
    const k = u.pathname.startsWith("/api/") ? "api" : i.type === "Script" ? "js" : i.type === "Stylesheet" ? "css" : i.type === "Font" ? "font" : i.type === "Image" ? "image" : "other";
    by[k] += b; list.push({ path: u.pathname, kb: +(b / 1024).toFixed(1), kind: k, startMs: Math.round(((starts.get(id) ?? 0) - firstStart) * 1000), endMs: Math.round(((ends.get(id) ?? 0) - firstStart) * 1000) }); if (k === "api") apiCalls.push(u.pathname);
  }
  await ctx.close();
  return { route, signedIn, warm, fcp: Math.round(m.fcp ?? -1), lcp: Math.round(m.lcp ?? -1), tbt: Math.round(m.long), cls: +m.cls.toFixed(3), ttfb: Math.round(nav.ttfb), loadMs, usableMs, requests: reqs, kb: Math.round(total / 1024), kbBy: Object.fromEntries(Object.entries(by).map(([k, v]) => [k, Math.round(v / 1024)])), apiCalls, list: list.sort((a, b) => a.startMs - b.startMs) };
}

const med = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
const SCENES = [["/login", false, false, "Sign-in page, first visit"], ["/start", true, false, "Home, first visit (signed in)"], ["/start", true, true, "Home, return visit"], ["/research", true, false, "Research, first visit"]];
const out = { label, profile, runs, when: new Date().toISOString(), scenes: [] };
for (const [route, signedIn, warm, name] of SCENES) {
  const rs = [];
  for (let i = 0; i < runs; i++) rs.push(await measure(route, signedIn, warm));
  const row = { name, route, runs: rs.length };
  for (const k of ["fcp", "lcp", "tbt", "ttfb", "usableMs", "requests", "kb"]) row[k] = med(rs.map((r) => r[k]));
  row.kbBy = rs[Math.floor(rs.length / 2)].kbBy; row.cls = med(rs.map((r) => r.cls)); row.apiCalls = rs[0].apiCalls; row.list = rs[0].list;
  out.scenes.push(row);
  console.log(`${name.padEnd(34)} FCP ${String(row.fcp).padStart(5)} ms  LCP ${String(row.lcp).padStart(5)} ms  usable ${String(row.usableMs).padStart(5)} ms  TBT ${String(row.tbt).padStart(5)} ms  ${row.requests} req  ${row.kb} KB  ${JSON.stringify(row.kbBy)}`);
}
await browser.close();
server.close();
const dir = path.resolve(here, "../../docs/perf");
fs.mkdirSync(dir, { recursive: true });
let file = path.join(dir, `perf-${label}-${new Date().toISOString().slice(0, 10)}.json`);
for (let n = 2; fs.existsSync(file); n++) file = path.join(dir, `perf-${label}-${new Date().toISOString().slice(0, 10)}-${n}.json`);
fs.writeFileSync(file, JSON.stringify(out, null, 1));
console.log("saved", file);
