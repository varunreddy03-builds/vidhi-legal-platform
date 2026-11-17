/* VIDHI service worker. It does three things: it lets the app be installed, it shows reminder notifications, and it keeps the
   app's own SCREENS (the page shell and its fixed, version-named script/style/font/icon files) so the app opens with no connection.
   It never keeps anything from /api, uploads or any other request: legal documents and account data must never sit in a cache on a
   shared device. The page itself is fetched from the network first, so the app never runs from an out-of-date copy when online. */
const SHELL = "vidhi-shell-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches.keys().then((names) => Promise.all(names.filter((n) => n.startsWith("vidhi-shell-") && n !== SHELL).map((n) => caches.delete(n)))).then(() => self.clients.claim())
  )
);
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; /* the browser handles it: nothing private is ever stored */
  if (req.mode === "navigate") {
    /* network first; offline, fall back to the last copy of the page shell */
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(SHELL).then((c) => c.put("/index.html", copy)); }
        return res;
      }).catch(() => caches.match("/index.html").then((r) => r || Response.error()))
    );
    return;
  }
  if (url.pathname.startsWith("/assets/") || /\.(?:woff2?|png|svg|ico|webmanifest)$/.test(url.pathname)) {
    /* version-named files never change under the same name, so a stored copy is always correct */
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(SHELL).then((c) => c.put(req, copy)); }
        return res;
      }))
    );
  }
});

/* Reminder messages carry no case details, only that a saved date is near (the server decides the words). */
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const target = typeof data.url === "string" && data.url.startsWith("/") && !data.url.startsWith("//") ? data.url : "/deadlines";
  event.waitUntil(
    self.registration.showNotification(String(data.title || "VIDHI").slice(0, 80), {
      body: String(data.body || "").slice(0, 200),
      icon: "/icon-192.png",
      badge: "/favicon-32x32.png",
      tag: "vidhi-reminder",
      data: { url: target },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/deadlines", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if (w.url.startsWith(self.location.origin) && "focus" in w) return w.navigate(url).then((c) => c && c.focus());
      }
      return self.clients.openWindow(url);
    })
  );
});