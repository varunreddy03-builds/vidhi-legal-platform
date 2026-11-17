// Runs before the page paints so there is no flash of the wrong theme. Kept as a file (not inline) because the CSP forbids inline scripts.
(function () {
  try {
    var c = localStorage.getItem("vidhi-theme") || "dark";
    var light = c === "light" || (c === "system" && window.matchMedia("(prefers-color-scheme: light)").matches);
    var r = document.documentElement;
    r.classList.toggle("dark", !light);
    r.classList.toggle("light", light);
  } catch (e) {}
})();
