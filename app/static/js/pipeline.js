/* AEP pipeline -- Today tab.
   Fetches JSON and repaints SINGLE ROWS. Never re-renders the whole page on a
   change: that is the DOM problem the commission Fidelity view already solved
   (~4,000 hidden per-row forms). The only full paint is the first load.

   Every value that reaches innerHTML goes through esc(). Names, counties and
   detail strings come from the database and are not trusted markup. */
(function () {
  "use strict";

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return ESCAPES[ch];
    });
  }

  /* reason_code -> plain language. The API returns ingredients
     (reason_code / reason_plan_id / reason_county / reason_days_left); the
     sentence is assembled here so SQL never builds display strings.

     Every code app/pipeline/triage.py can emit is handled. An unknown code
     returns "" and the row simply shows no reason line -- it must never
     render "undefined". */
  function reasonText(r) {
    var days = r.reason_days_left;
    var county = r.reason_county;
    switch (r.reason_code) {
      case "sar":
        return county
          ? "Plan is ending in " + esc(county) + " County"
          : "Plan is ending in their county";
      case "shp_pending":
        if (days == null) return "State retiree opt-out call not done";
        if (days <= 0) return "State retiree opt-out call -- last day";
        return "State retiree opt-out call, " + esc(days) +
               (days === 1 ? " day left" : " days left");
      case "shp_closed":
        return "State retiree opt-out window has closed";
      case "rating_major":
        return "Big changes to their plan";
      case "rating_some":
        return "Plan changes to review";
      case "rating_little":
        return "Little plan change";
      case "unrated":
        return "Plan not reviewed yet";
      case "sep_urgent":
        if (days == null) return "Enrollment window closing";
        if (days <= 0) return "Last day to enroll";
        return esc(days) + (days === 1 ? " day left to enroll" : " days left to enroll");
      case "sep_future":
        return "Enrollment window still open";
      case "sep_closed":
        return "Their enrollment window has closed";
      case "no_deadline":
        return "No deadline on file";
      case "override":
        return "You moved this one up";
      default:
        return "";
    }
  }

  /* What an agent can do from the list without opening the record. Anything
     plan-specific (thinking it over / waiting on carrier) is gated server-side
     on the scope form; we surface the server's message rather than guess. */
  var ACTIONS = [
    { action: "contact",   label: "Needs a call" },
    { action: "scheduled", label: "Appointment set" },
    { action: "deciding",  label: "Thinking it over" }
  ];

  function actionsHtml(r) {
    var html = ACTIONS.map(function (a) {
      var on = r.stage === a.action ? " pl-on" : "";
      return '<button type="button" class="pl-act' + on + '" data-action="' +
             esc(a.action) + '">' + esc(a.label) + "</button>";
    }).join("");
    html += '<button type="button" class="pl-act pl-done" data-action="done">' +
            "Finished</button>";
    return html;
  }

  function rowInnerHtml(r) {
    var reason = reasonText(r);
    var tel = r.phone
      ? '<a class="pl-tel" href="tel:' + esc(r.phone) + '">' + esc(r.phone) + "</a>"
      : '<span class="pl-nophone">No phone on file</span>';

    return (
      '<div class="pl-who">' +
        '<a class="pl-name" href="/customers/' + encodeURIComponent(r.id) + '">' +
          esc(r.name) +
        "</a>" +
        (reason ? '<span class="pl-reason">' + reason + "</span>" : "") +
        '<span class="pl-meta">' + esc(r.stage_label || "") +
          (r.outcome_label ? " &middot; " + esc(r.outcome_label) : "") +
          (r.county ? " &middot; " + esc(r.county) + " County" : "") +
        "</span>" +
      "</div>" +
      '<div class="pl-do">' + tel +
        '<div class="pl-acts">' + actionsHtml(r) + "</div>" +
      "</div>" +
      '<p class="pl-say" role="status" aria-live="polite"></p>'
    );
  }

  function rowHtml(r) {
    return '<div class="pl-row" data-id="' + esc(r.id) + '">' +
           rowInnerHtml(r) + "</div>";
  }

  /* THE repaint. One row, in place -- no reload, no re-render of the list. */
  function repaintRow(r, message) {
    var el = document.querySelector('.pl-row[data-id="' + CSS.escape(String(r.id)) + '"]');
    if (!el) return;
    el.innerHTML = rowInnerHtml(r);
    el.classList.toggle("pl-settled-row", !!r.settled);
    if (message) say(el, message);
  }

  function say(rowEl, message) {
    var out = rowEl.querySelector(".pl-say");
    if (out) out.textContent = message;
  }

  function cardHtml(card) {
    var extra = card.count - card.rows.length;
    return (
      '<section class="pl-card' + (card.urgent ? " urgent" : "") + '">' +
        "<h3>" + esc(card.title) + "</h3>" +
        '<p class="pl-sub">' + esc(card.count) +
          (card.count === 1 ? " person" : " people") + "</p>" +
        card.rows.map(rowHtml).join("") +
        (extra > 0 ? '<p class="pl-sub pl-more">' + esc(extra) + " more not shown</p>" : "") +
      "</section>"
    );
  }

  function headline(data) {
    document.getElementById("pl-settled").textContent =
      data.settled + " of " + data.total + " settled for 2027";

    var parts = [];
    if (data.remaining > 0) {
      parts.push(data.remaining + " to go");
      if (data.days_left != null && data.days_left > 0) {
        parts.push(data.days_left + (data.days_left === 1 ? " day left" : " days left"));
      }
      if (data.pace) parts.push("about " + data.pace + " a day");
    }
    var line = parts.length ? parts.join(", ") + "." : "Everyone is settled.";
    if (data.never_contacted > 0) {
      line += " " + data.never_contacted + " have not been contacted at all.";
    }
    document.getElementById("pl-pace").textContent = line;
  }

  function render(data) {
    headline(data);
    var main = document.getElementById("pl-main");
    main.innerHTML = data.cards.length
      ? data.cards.map(cardHtml).join("")
      : '<p class="pl-empty">Nothing needs you right now.</p>';
  }

  /* An outcome the agent picks on the row. `done` needs one, and the choice is
     three plain words -- no jargon, no hidden modal. */
  function askOutcome() {
    var answer = window.prompt(
      "How did it end? Type enrolled, staying put, or closed.", "enrolled");
    if (answer == null) return null;
    var a = answer.trim().toLowerCase();
    if (a === "enrolled") return "enrolled";
    if (a === "staying put" || a === "staying" || a === "kept") return "kept";
    if (a === "closed" || a === "lost") return "lost";
    return undefined;            // typed something we do not recognise
  }

  function setBusy(rowEl, busy) {
    var btns = rowEl.querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) btns[i].disabled = busy;
  }

  function onClick(ev) {
    var btn = ev.target.closest ? ev.target.closest("button.pl-act") : null;
    if (!btn) return;
    var rowEl = btn.closest(".pl-row");
    if (!rowEl) return;

    var body = { action: btn.getAttribute("data-action") };
    if (body.action === "done") {
      var outcome = askOutcome();
      if (outcome === null) return;                       // cancelled
      if (outcome === undefined) {
        say(rowEl, "Type enrolled, staying put, or closed.");
        return;
      }
      body.outcome = outcome;
    }

    var id = rowEl.getAttribute("data-id");
    setBusy(rowEl, true);
    say(rowEl, "Saving…");

    fetch("/pipeline/api/customer/" + encodeURIComponent(id) + "/outcome", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; })
          .then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
      })
      .then(function (out) {
        if (out.ok && out.data && out.data.customer) {
          repaintRow(out.data.customer, "Saved.");
          return;
        }
        setBusy(rowEl, false);
        if (out.status === 409) {
          say(rowEl, (out.data && out.data.message) || "Fill in the scope form first.");
        } else if (out.status === 403) {
          say(rowEl, "This is not your customer to change.");
        } else {
          say(rowEl, (out.data && out.data.error) || "Could not save. Try again.");
        }
      })
      .catch(function () {
        setBusy(rowEl, false);
        say(rowEl, "Could not save. Try again.");
      });
  }

  function load() {
    fetch("/pipeline/api/today", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(render)
      .catch(function () {
        document.getElementById("pl-settled").textContent = "Could not load.";
        document.getElementById("pl-pace").textContent =
          "Reload the page. If it keeps happening, tell Tim.";
      });
  }

  function start() {
    var main = document.getElementById("pl-main");
    if (main) main.addEventListener("click", onClick);
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
