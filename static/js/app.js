// Quick Exit + service worker registration. No inline scripts are used anywhere (CSP forbids them).
(function () {
  "use strict";

  var exit = document.getElementById("quick-exit");
  function quickExit(e) {
    if (e) { e.preventDefault(); }
    var url = exit ? exit.getAttribute("data-exit-url") : "https://www.wikipedia.org";
    // replace() keeps this page out of the Back-button chain for this tab. It does NOT erase browser history,
    // cached files, DNS/network logs or anything installed on the device.
    window.location.replace(url);
  }
  if (exit) { exit.addEventListener("click", quickExit); }

  var escapes = 0, timer = null;
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    escapes += 1;
    clearTimeout(timer);
    timer = setTimeout(function () { escapes = 0; }, 1200);
    if (escapes >= 3) { quickExit(); }
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* offline support is optional */ });
  }
})();
