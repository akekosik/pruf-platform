/*
 * ПРУФ · web/js/candidate.js
 * Кабинет кандидата: свой протокол, карта пробелов, повторное использование результата.
 */
(function (global) {
  "use strict";
  var P = global.PRUF;
  var $ = P.$, el = P.el, esc = P.escapeHtml;

  function renderProtocol(protocol, demo) {
    var host = $("#my-protocol");
    if (!host) return;
    var verdict = protocol.verdict || {};
    var mutation = protocol.mutation || {};
    var questions = protocol.questions || {};
    host.innerHTML = "";

    host.appendChild(el("div", { class: "row row--between" }, [
      el("div", {}, [
        el("h2", { text: "\u041f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u044f" }),
        el("p", { class: "muted", text: ((protocol.task || {}).title || "") + " \u00b7 " + ((protocol.task || {}).language || "Python") })
      ]),
      el("div", { class: "protocol__score" }, [
        el("div", { class: "kpi__value", text: (protocol.control_pct || 0) + " %" }),
        el("div", { class: "kpi__label", text: "\u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c \u043a\u043e\u0434\u0430" })
      ])
    ]));
    host.appendChild(el("p", { class: "badge " + P.levelClass(verdict.level), text: verdict.label || "" }));
    if (verdict.summary) host.appendChild(el("p", { text: verdict.summary }));
    host.appendChild(el("div", { class: "kpi" }, [
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: String(mutation.total || 0) }), el("div", { class: "kpi__label", text: "\u043c\u0443\u0442\u0430\u0446\u0438\u0439 \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043d\u043e" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: (mutation.score_pct || 0) + " %" }), el("div", { class: "kpi__label", text: "\u0442\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: (questions.correct || 0) + " / " + (questions.answered || 0) }), el("div", { class: "kpi__label", text: "\u0432\u0435\u0440\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: protocol.duration_clock || "" }), el("div", { class: "kpi__label", text: "\u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c" })])
    ]));

    var skills = protocol.skills || [];
    if (skills.length) {
      var grid = el("div", { class: "grid grid--2" });
      skills.forEach(function (row) {
        var cls = row.level === "control" ? "badge--ok" : row.level === "shaky" ? "badge--warn" : "badge--bad";
        grid.appendChild(el("div", { class: "card card--flat" }, [
          el("b", { text: row.title || row.skill }),
          el("p", {}, [el("span", { class: "badge " + cls, text: row.label || "" })]),
          el("div", { class: "progress" }, [el("span", { style: "width:" + Math.round((row.ratio || 0) * 100) + "%" })]),
          el("p", { class: "muted", text: (row.correct || 0) + " \u0438\u0437 " + (row.total || 0) + " \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432" })
        ]));
      });
      host.appendChild(el("h3", { text: "\u0413\u0434\u0435 \u043f\u0440\u043e\u0431\u0435\u043b\u044b" }));
      host.appendChild(grid);
    }

    var risks = protocol.risks || [];
    if (risks.length) {
      var list = el("ul", { class: "list" });
      risks.forEach(function (risk) {
        list.appendChild(el("li", { html: "<b>" + esc(risk.title || "") + "</b> \u2014 " + esc(risk.detail || "") }));
      });
      host.appendChild(el("h3", { text: "\u0427\u0442\u043e \u043f\u043e\u0434\u0442\u044f\u043d\u0443\u0442\u044c \u0434\u043e \u0441\u043e\u0431\u0435\u0441\u0435\u0434\u043e\u0432\u0430\u043d\u0438\u044f" }));
      host.appendChild(list);
    }

    var actions = el("div", { class: "row row--wrap" });
    var share = el("button", { class: "btn btn--sm", type: "button", text: "\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0441\u0441\u044b\u043b\u043a\u0443 \u0434\u043b\u044f \u0440\u0430\u0431\u043e\u0442\u043e\u0434\u0430\u0442\u0435\u043b\u044f" });
    share.addEventListener("click", function () {
      var origin = location.protocol === "file:" ? "https://proof.dev" : location.origin;
      var link = origin + "/candidate.html?protocol=" + encodeURIComponent(protocol.id || "demo");
      if (navigator.clipboard) navigator.clipboard.writeText(link).then(function () { P.toast("\u0421\u0441\u044b\u043b\u043a\u0430 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0430: \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043f\u0435\u0440\u0435\u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442\u0441\u044f \u0432 \u0434\u0440\u0443\u0433\u0438\u0445 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f\u0445", "ok", 5200); });
      else P.toast("\u0411\u0443\u0444\u0435\u0440 \u043e\u0431\u043c\u0435\u043d\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d", "warn");
    });
    var pdf = el("button", { class: "btn btn--ghost btn--sm", type: "button", text: "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b" });
    pdf.addEventListener("click", function () {
      if (!demo && protocol.id) { global.open("/api/protocol/" + encodeURIComponent(protocol.id) + ".pdf", "_blank"); return; }
      var blob = new Blob([JSON.stringify(protocol, null, 2)], { type: "application/json" });
      var link = el("a", { href: URL.createObjectURL(blob), download: "pruf-protocol.json" });
      document.body.appendChild(link); link.click(); link.remove();
      P.toast("\u0414\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c: \u0432\u044b\u0433\u0440\u0443\u0436\u0435\u043d JSON. PDF \u0441\u043e\u0431\u0438\u0440\u0430\u0435\u0442 \u0434\u0432\u0438\u0436\u043e\u043a.", "", 5000);
    });
    var again = el("a", { class: "btn btn--quiet btn--sm", href: "studio.html", text: "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043d\u043e\u0432\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435" });
    [share, pdf, again].forEach(function (node) { actions.appendChild(node); });
    host.appendChild(actions);

    if (demo) {
      host.appendChild(el("p", { class: "muted", text: "\u0414\u0435\u043c\u043e-\u0441\u043d\u0438\u043c\u043e\u043a: \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u0438\u0437 \u0440\u0435\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u0433\u043e\u043d\u0430 \u0434\u0432\u0438\u0436\u043a\u0430, \u0437\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0439 \u0432 \u0440\u0435\u043f\u043e\u0437\u0438\u0442\u043e\u0440\u0438\u0438." }));
    }
  }

  function renderHistory(rows) {
    var host = $("#history");
    if (!host) return;
    host.innerHTML = "";
    if (!rows.length) {
      host.appendChild(el("p", { class: "muted", text: "\u041f\u043e\u043a\u0430 \u043e\u0434\u043d\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430." }));
      return;
    }
    var table = el("table", { class: "table" }, [el("thead", {}, [el("tr", {}, [
      el("th", { text: "\u0414\u0430\u0442\u0430" }), el("th", { text: "\u0412\u0430\u043a\u0430\u043d\u0441\u0438\u044f" }),
      el("th", { text: "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c" }), el("th", { text: "\u0421\u0442\u0430\u0442\u0443\u0441" })
    ])])]);
    var body = el("tbody");
    rows.forEach(function (row) {
      body.appendChild(el("tr", {}, [
        el("td", { text: row.submitted || "" }),
        el("td", { text: row.vacancy || "" }),
        el("td", {}, [el("span", { class: "badge " + P.levelClass(row.level), text: (row.control_pct || 0) + " %" })]),
        el("td", { text: row.status || "" })
      ]));
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  P.ready(function () {
    if (!$("#my-protocol")) return;
    var fresh = null;
    try { fresh = JSON.parse(sessionStorage.getItem("pruf.lastProtocol") || "null"); } catch (error) { fresh = null; }
    if (fresh) {
      renderProtocol(fresh, fresh.__demo === true);
      renderHistory([]);
      return;
    }
    P.engine.protocol("last").then(function (protocol) {
      renderProtocol(protocol, protocol.__demo === true);
    }).catch(function () {
      return P.demoData().then(function (data) { renderProtocol(data.protocol || {}, true); });
    });
    P.engine.candidates().then(function (payload) {
      var rows = (payload.candidates || []).slice(0, 3);
      renderHistory(rows);
    }).catch(function () { renderHistory([]); });
  });
})(window);
