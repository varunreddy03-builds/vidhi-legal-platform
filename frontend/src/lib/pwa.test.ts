import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pub = (f: string) => readFileSync(resolve(__dirname, "../../public", f), "utf-8");

describe("installable app (PWA)", () => {
  const manifest = JSON.parse(pub("manifest.webmanifest"));
  it("has what iPhone and Android need to install it", () => {
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url).toBe("/start");
    expect(manifest.scope).toBe("/");
    const sizes = manifest.icons.map((i: { sizes: string; purpose: string }) => `${i.sizes}:${i.purpose}`);
    expect(sizes).toEqual(expect.arrayContaining(["192x192:any", "512x512:any", "512x512:maskable"]));
    for (const i of manifest.icons) expect(() => readFileSync(resolve(__dirname, "../../public", i.src.replace(/^\//, "")))).not.toThrow();
  });
  it("names itself VIDHI", () => {
    expect(manifest.name).toBe("VIDHI");
  });
});

describe("service worker keeps the app shell only", () => {
  const sw = pub("sw.js");
  it("never touches /api, never handles anything but GET on this site", () => {
    expect(sw).toContain('req.method !== "GET"');
    expect(sw).toContain('url.origin !== self.location.origin');
    expect(sw).toContain('url.pathname.startsWith("/api/")');
  });
  it("stores only the page shell and version-named assets, never documents or reports", () => {
    expect(sw).toContain('url.pathname.startsWith("/assets/")');
    expect(sw).not.toMatch(/\.(pdf|docx|xlsx|txt|csv|mp3|mp4|mov|wav)\b/i);
    expect(sw).not.toMatch(/caches\.open\([^)]*\)\.then\(\(c\) => c\.addAll/); // no bulk pre-caching of arbitrary URLs
    const cached = [...sw.matchAll(/c\.put\(([^,]+),/g)].map((m) => m[1].trim());
    expect(cached.sort()).toEqual(['"/index.html"', "req"]); // the page shell, and the asset requests accepted above
  });
});
