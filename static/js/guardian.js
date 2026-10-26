// Guardian Mode page: talks to the real DRF endpoints. Nothing here is simulated in the browser;
// all state, timing and notification records come from the server. Text is inserted with textContent only.
(function () {
  "use strict";
  var root = document.getElementById("guardian-app");
  if (!root) { return; }

  var api = root.getAttribute("data-api-base");
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  var $ = function (id) { return document.getElementById(id); };
  var current = null, pollTimer = null, pendingKey = null;

  function call(method, path, body) {
    return fetch(api + path, {
      method: method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "Accept": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { var err = new Error(data.detail || "Something went wrong. Please try again."); err.status = r.status; throw err; }
        return data;
      });
    });
  }

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined) { n.textContent = text; }
    if (cls) { n.className = cls; }
    return n;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function fmt(iso) { return iso ? new Date(iso).toLocaleTimeString() : ""; }
  function say(text) { $("g-status-msg").textContent = text || ""; }

  function render(a) {
    current = a;
    var panel = $("g-panel");
    if (!a) { panel.hidden = true; $("g-start").hidden = false; return; }
    panel.hidden = false;
    $("g-start").hidden = a.is_open;
    if (!a.is_open) { $("g-begin").hidden = false; $("g-confirm").hidden = true; }
    $("g-state").textContent = a.state_label;
    $("g-notice").textContent = a.notice || "";
    $("g-notice").hidden = !a.notice;
    $("g-deadline").textContent = a.ack_deadline ? "Waiting for acknowledgement until " + fmt(a.ack_deadline) : "";

    var steps = $("g-steps"); clear(steps);
    a.steps.forEach(function (s) { steps.appendChild(el("li", s.rank + ". " + s.name + " - " + s.status + (s.detail ? " (" + s.detail + ")" : ""))); });

    var dl = $("g-deliveries"); clear(dl);
    if (!a.deliveries.length) { dl.appendChild(el("li", "No notification has been attempted yet.")); }
    a.deliveries.forEach(function (d) {
      var li = el("li", d.contact + " via " + d.channel + " (attempt " + d.attempt + "): " + d.status + (d.simulated ? " [simulated]" : "") + (d.error ? " - " + d.error : ""));
      if (d.responder_link) {
        li.appendChild(document.createTextNode(" "));
        var link = el("a", "Open as this responder (simulation)");
        link.href = d.responder_link; link.target = "_blank"; link.rel = "noopener noreferrer";
        li.appendChild(link);
      }
      dl.appendChild(li);
    });

    var acks = $("g-acks"); clear(acks);
    if (!a.acknowledgements.length) { acks.appendChild(el("li", "Nobody has acknowledged yet.")); }
    a.acknowledgements.forEach(function (k) { acks.appendChild(el("li", k.contact + " acknowledged at " + fmt(k.at) + " (they saw it - this is not confirmation that help is coming).")); });

    var tl = $("g-timeline"); clear(tl);
    a.events.forEach(function (e) {
      var li = el("li"); li.appendChild(el("time", fmt(e.time))); li.appendChild(el("span", e.message)); tl.appendChild(li);
    });

    var open = a.is_open;
    $("g-resolve").hidden = !open; $("g-cancel").hidden = !open;
    var waiting = a.is_simulation && (a.state === "awaiting_acknowledgement" || a.state === "backup_contacted");
    $("g-skip").hidden = !waiting;
    schedulePoll(open);
  }

  function schedulePoll(open) {
    clearTimeout(pollTimer);
    if (open) { pollTimer = setTimeout(refresh, 3000); }
  }

  function refresh() {
    call("GET", "current/").then(function (d) { render(d.activation); }).catch(function (e) { say(e.message); schedulePoll(true); });
  }

  $("g-begin").addEventListener("click", function () {
    $("g-confirm").hidden = false; $("g-begin").hidden = true; $("g-yes").focus();
  });
  $("g-no").addEventListener("click", function () { $("g-confirm").hidden = true; $("g-begin").hidden = false; $("g-begin").focus(); });
  $("g-yes").addEventListener("click", function () {
    if (!pendingKey) { pendingKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random(); }
    var btn = $("g-yes"); btn.disabled = true; say("Starting Guardian Mode...");
    var fail = $("g-fail") ? $("g-fail").checked : false;
    call("POST", "activate/", { idempotency_key: pendingKey, simulate_primary_failure: fail })
      .then(function (a) { pendingKey = null; $("g-confirm").hidden = true; say(""); render(a); })
      .catch(function (e) { say(e.message); })   // the same key is reused on retry, so a double tap cannot double-send
      .then(function () { btn.disabled = false; });
  });

  function action(id, path, confirmText) {
    $(id).addEventListener("click", function () {
      if (confirmText && !window.confirm(confirmText)) { return; }
      call("POST", current.id + "/" + path + "/").then(render).catch(function (e) { say(e.message); });
    });
  }
  action("g-resolve", "resolve");
  action("g-cancel", "cancel", "Stop Guardian Mode? Notifications already submitted cannot be recalled.");
  action("g-skip", "simulate-timeout");

  refresh();
})();
