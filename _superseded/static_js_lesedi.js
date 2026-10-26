// LESEDI client script. No inline scripts are used anywhere (strict CSP).
(function () {
  "use strict";

  // Quick exit: the button, or pressing Escape twice quickly. This only changes
  // what is on screen. It does NOT erase browser history, operating-system
  // records, network logs or monitoring software.
  var button = document.getElementById("quick-exit");
  var exitUrl = button ? button.getAttribute("href") : "https://www.wikipedia.org";
  function quickExit() {
    window.location.replace(exitUrl);
  }
  if (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      quickExit();
    });
  }
  var lastEscape = 0;
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var now = Date.now();
    if (now - lastEscape < 800) quickExit();
    lastEscape = now;
  });

  // Offline support: only static assets and the public offline page.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {
        /* Offline support is optional; ignore failures. */
      });
    });
  }
})();
