/*
 * ПРУФ · web/js/employer.js
 * Кабинет работодателя: пул кандидатов, сравнение протоколов, выдача проверок.
 */
(function (global) {
  "use strict";
  var P = global.PRUF;
  var $ = P.$, el = P.el, esc = P.escapeHtml;

  var S = { rows: [], vacancies: [], stats: {}, filter: "all", query: "", sort: "control", selected: null, demo: false };

  function badgeFor(row) {
    var level = row.level || (row.control_pct >= 80 ? "good" : row.control_pct >= 70 ? "medium" : row.control_pct >= 50 ? "low" : "bad");
    return P.levelClass(level);
  }

  function paintStats() {
    var host = $("#kpi");
    if (!host) return;
    var stats = S.stats || {};
    var hours = stats.saved_hours !== undefined ? stats.saved_hours : Math.round(S.rows.length * 2);
    host.innerHTML = "";
    [[String(stats.total || S.rows.length), "\u043f\u0440\u043e\u0432\u0435\u0440\u043e\u043a \u0432 \u0440\u0430\u0431\u043e\u0442\u0435"],
     [String(stats.passed || S.rows.filter(function (r) { return r.passed; }).length), "\u043f\u0440\u043e\u0448\u043b\u0438 \u043f\u043e\u0440\u043e\u0433 70 %"],
     [(stats.average_control !== undefined ? stats.average_control : 0) + " %", "\u0441\u0440\u0435\u0434\u043d\u0438\u0439 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044c"],
     [hours + " \u0447", "\u0441\u044d\u043a\u043e\u043d\u043e\u043c\u043b\u0435\u043d\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438 senior"]
    ].forEach(function (pair) {
      host.appendChild(el("div", { class: "kpi__item" }, [
        el("div", { class: "kpi__value", text: pair[0] }),
        el("div", { class: "kpi__label", text: pair[1] })
      ]));
    });
  }

  function paintVacancies() {
    var host = $("#vacancies");
    if (!host) return;
    host.innerHTML = "";
    var all = el("button", { class: "btn btn--sm " + (S.filter === "all" ? "" : "btn--quiet"), type: "button", text: "\u0412\u0441\u0435 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438" });
    all.addEventListener("click", function () { S.filter = "all"; render(); });
    host.appendChild(all);
    S.vacancies.forEach(function (vacancy) {
      var count = S.rows.filter(function (row) { return row.vacancy_id === vacancy.id || row.vacancy === vacancy.title; }).length;
      var button = el("button", {
        class: "btn btn--sm " + (S.filter === vacancy.id ? "" : "btn--quiet"), type: "button",
        text: vacancy.title + " \u00b7 " + count
      });
      button.addEventListener("click", function () { S.filter = vacancy.id; render(); });
      host.appendChild(button);
    });
  }

  function visibleRows() {
    var rows = S.rows.filter(function (row) {
      if (S.filter !== "all" && row.vacancy_id !== S.filter) return false;
      if (!S.query) return true;
      var haystack = (row.name + " " + row.vacancy + " " + row.task + " " + row.status).toLowerCase();
      return haystack.indexOf(S.query.toLowerCase()) !== -1;
    });
    rows.sort(function (a, b) {
      if (S.sort === "control") return (b.control_pct || 0) - (a.control_pct || 0);
      if (S.sort === "risks") return (b.risks || 0) - (a.risks || 0);
      return String(b.submitted || "").localeCompare(String(a.submitted || ""));
    });
    return rows;
  }

  function paintTable() {
    var host = $("#candidates");
    if (!host) return;
    var rows = visibleRows();
    host.innerHTML = "";
    if (!rows.length) {
      host.appendChild(el("p", { class: "muted", text: "\u041d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u043d\u0430\u0448\u043b\u043e\u0441\u044c \u043f\u043e \u0444\u0438\u043b\u044c\u0442\u0440\u0443." }));
      return;
    }
    var table = el("table", { class: "table" }, [el("thead", {}, [el("tr", {}, [
      el("th", { text: "\u041a\u0430\u043d\u0434\u0438\u0434\u0430\u0442" }), el("th", { text: "\u0412\u0430\u043a\u0430\u043d\u0441\u0438\u044f" }),
      el("th", { text: "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c" }), el("th", { text: "\u0422\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442" }),
      el("th", { text: "\u0420\u0438\u0441\u043a\u0438" }), el("th", { text: "\u0421\u0442\u0430\u0442\u0443\u0441" }), el("th", { text: "" })
    ])])]);
    var body = el("tbody");
    rows.forEach(function (row) {
      var open = el("button", { class: "btn btn--sm btn--quiet", type: "button", text: "\u041f\u0440\u043e\u0442\u043e\u043a\u043e\u043b" });
      open.addEventListener("click", function () { select(row.id); });
      body.appendChild(el("tr", { class: S.selected === row.id ? "is-active" : "" }, [
        el("td", {}, [el("b", { text: row.name }), el("div", { class: "muted", text: row.task || "" })]),
        el("td", { text: row.vacancy || "" }),
        el("td", {}, [el("span", { class: "badge " + badgeFor(row), text: (row.control_pct || 0) + " %" })]),
        el("td", { text: (row.mutation_score_pct || 0) + " %" }),
        el("td", { text: String(row.risks || 0) }),
        el("td", { text: row.status || "" }),
        el("td", {}, [open])
      ]));
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  function paintDetail(bundle) {
    var host = $("#detail");
    if (!host) return;
    var candidate = bundle.candidate || bundle.summary || {};
    var protocol = bundle.protocol || {};
    var verdict = protocol.verdict || {};
    host.innerHTML = "";
    host.appendChild(el("div", { class: "row row--between" }, [
      el("div", {}, [
        el("h3", { text: candidate.name || "\u041a\u0430\u043d\u0434\u0438\u0434\u0430\u0442" }),
        el("p", { class: "muted", text: (candidate.vacancy || "") + " \u00b7 " + (candidate.task || (protocol.task || {}).title || "") })
      ]),
      el("span", { class: "badge " + badgeFor(candidate), text: (candidate.control_pct || protocol.control_pct || 0) + " % \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044f" })
    ]));
    if (verdict.label) host.appendChild(el("p", { class: "badge " + P.levelClass(verdict.level), text: verdict.label }));
    if (verdict.summary) host.appendChild(el("p", { text: verdict.summary }));

    (protocol.quotes || []).slice(0, 2).forEach(function (quote) {
      host.appendChild(el("div", { class: "card card--flat" }, [
        el("div", { class: "muted", text: "\u0426\u0438\u0442\u0430\u0442\u0430 \u043c\u0443\u0442\u0430\u0446\u0438\u0438 " + (quote.id || "") + " \u00b7 \u0441\u0442\u0440\u043e\u043a\u0430 " + (quote.line || "") }),
        el("div", { class: "mut__diff" }, [
          el("code", { class: "mut__before", text: "\u2212 " + (quote.before || "") }),
          el("code", { class: "mut__after", text: "+ " + (quote.after || "") })
        ]),
        quote.note ? el("p", { class: "muted", text: quote.note }) : null
      ]));
    });

    var skills = protocol.skills || [];
    if (skills.length) {
      var list = el("div", { class: "grid grid--2" });
      skills.forEach(function (row) {
        var cls = row.level === "control" ? "badge--ok" : row.level === "shaky" ? "badge--warn" : "badge--bad";
        list.appendChild(el("div", { class: "card card--flat" }, [
          el("b", { text: row.title || row.skill }),
          el("p", {}, [el("span", { class: "badge " + cls, text: row.label || "" })]),
          el("div", { class: "progress" }, [el("span", { style: "width:" + Math.round((row.ratio || 0) * 100) + "%" })])
        ]));
      });
      host.appendChild(el("h4", { text: "\u041a\u0430\u0440\u0442\u0430 \u043d\u0430\u0432\u044b\u043a\u043e\u0432" }));
      host.appendChild(list);
    }

    var risks = protocol.risks || [];
    if (risks.length) {
      var riskList = el("ul", { class: "list" });
      risks.forEach(function (risk) {
        riskList.appendChild(el("li", { html: "<b>" + esc(risk.title || "") + "</b> \u2014 " + esc(risk.detail || "") }));
      });
      host.appendChild(el("h4", { text: "\u0420\u0438\u0441\u043a\u0438" }));
      host.appendChild(riskList);
    }

    var timeline = protocol.timeline || [];
    if (timeline.length) {
      var line = el("div", { class: "timeline" });
      timeline.forEach(function (item) {
        line.appendChild(el("div", { class: "timeline__item " + (item.ok ? "is-ok" : "is-bad") }, [
          el("span", { class: "timeline__id", text: item.id || "" }),
          el("span", { class: "timeline__label", text: item.label || "" }),
          el("span", { class: "timeline__clock", text: item.clock || "" })
        ]));
      });
      host.appendChild(el("h4", { text: "\u0422\u0430\u0439\u043c\u043b\u0430\u0439\u043d \u0441\u0435\u0441\u0441\u0438\u0438" }));
      host.appendChild(line);
    }

    var actions = el("div", { class: "row row--wrap" });
    var invite = el("button", { class: "btn btn--ok btn--sm", type: "button", text: "\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c \u043d\u0430 \u0441\u043e\u0431\u0435\u0441" });
    invite.addEventListener("click", function () { setStatus(candidate, "\u041f\u0440\u0438\u0433\u043b\u0430\u0448\u0451\u043d \u043d\u0430 \u0441\u043e\u0431\u0435\u0441", "ok"); });
    var reject = el("button", { class: "btn btn--danger btn--sm", type: "button", text: "\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c" });
    reject.addEventListener("click", function () { setStatus(candidate, "\u041e\u0442\u043a\u043b\u043e\u043d\u0451\u043d", "warn"); });
    var pdf = el("button", { class: "btn btn--ghost btn--sm", type: "button", text: "\u0421\u043a\u0430\u0447\u0430\u0442\u044c PDF" });
    pdf.addEventListener("click", function () {
      if (protocol.id && !bundle.__demo) global.open("/api/protocol/" + encodeURIComponent(protocol.id) + ".pdf", "_blank");
      else P.toast("\u0414\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c: PDF \u0441\u043e\u0431\u0438\u0440\u0430\u0435\u0442 \u0434\u0432\u0438\u0436\u043e\u043a \u043f\u0440\u0438 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043d\u043e\u043c \u0441\u0435\u0440\u0432\u0435\u0440\u0435.", "warn", 5000);
    });
    [invite, reject, pdf].forEach(function (node) { actions.appendChild(node); });
    host.appendChild(actions);
    host.classList.add("is-visible");
  }

  function setStatus(candidate, status, kind) {
    S.rows.forEach(function (row) { if (row.id === candidate.id) row.status = status; });
    paintTable();
    P.toast(candidate.name + ": " + status, kind || "ok");
  }

  function select(id) {
    S.selected = id;
    paintTable();
    var host = $("#detail");
    if (host) host.innerHTML = "<p class=\"muted\">\u0413\u0440\u0443\u0437\u0438\u043c \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b\u2026</p>";
    P.engine.candidate(id).then(function (bundle) {
      if (!bundle) throw new Error("\u041f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d");
      bundle.__demo = bundle.__demo === true;
      var row = S.rows.filter(function (item) { return item.id === id; })[0];
      if (row && !bundle.candidate) bundle.candidate = row;
      paintDetail(bundle);
    }).catch(function (error) {
      if (host) host.innerHTML = "<p class=\"muted\">" + esc(error.message) + "</p>";
    });
  }

  function exportCsv() {
    var rows = visibleRows();
    var header = ["\u041a\u0430\u043d\u0434\u0438\u0434\u0430\u0442", "\u0412\u0430\u043a\u0430\u043d\u0441\u0438\u044f", "\u0417\u0430\u0434\u0430\u0447\u0430", "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c %", "\u0422\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442 %", "\u0420\u0438\u0441\u043a\u0438", "\u0421\u0442\u0430\u0442\u0443\u0441"];
    var lines = [header.join(";")];
    rows.forEach(function (row) {
      lines.push([row.name, row.vacancy, row.task, row.control_pct, row.mutation_score_pct, row.risks, row.status]
        .map(function (value) { return String(value === undefined ? "" : value).replace(/;/g, ","); }).join(";"));
    });
    var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var link = el("a", { href: URL.createObjectURL(blob), download: "pruf-candidates.csv" });
    document.body.appendChild(link); link.click(); link.remove();
    P.toast("CSV \u0432\u044b\u0433\u0440\u0443\u0436\u0435\u043d", "ok");
  }

  function initNewCheck() {
    var form = $("#new-check");
    if (!form) return;
    var select = $("#check-vacancy");
    if (select) {
      select.innerHTML = "";
      S.vacancies.forEach(function (vacancy) {
        select.appendChild(el("option", { value: vacancy.id, text: vacancy.title }));
      });
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var data = new FormData(form);
      var token = Math.random().toString(36).slice(2, 10);
      var origin = location.protocol === "file:" ? "https://proof.dev" : location.origin;
      var link = origin + "/studio.html?vacancy=" + encodeURIComponent(data.get("vacancy") || "") + "&invite=" + token;
      var output = $("#check-link");
      if (output) {
        output.hidden = false;
        output.innerHTML = "";
        output.appendChild(el("code", { text: link }));
        var copy = el("button", { class: "btn btn--sm btn--quiet", type: "button", text: "\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c" });
        copy.addEventListener("click", function () {
          if (navigator.clipboard) navigator.clipboard.writeText(link).then(function () { P.toast("\u0421\u0441\u044b\u043b\u043a\u0430 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0430", "ok"); });
        });
        output.appendChild(copy);
      }
      P.toast("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0430: \u0441\u0441\u044b\u043b\u043a\u0430 \u0436\u0438\u0432\u0451\u0442 15 \u043c\u0438\u043d\u0443\u0442 \u043f\u043e\u0441\u043b\u0435 \u0441\u0442\u0430\u0440\u0442\u0430", "ok", 5200);
    });
  }

  function render() {
    paintStats();
    paintVacancies();
    paintTable();
  }

  P.ready(function () {
    if (!$("#candidates")) return;
    P.engine.candidates().then(function (payload) {
      S.demo = payload.__demo === true;
      S.rows = payload.candidates || [];
      S.vacancies = payload.vacancies || [];
      S.stats = payload.stats || {};
      render();
      initNewCheck();
      if (S.rows.length) select(S.rows[0].id);
    }).catch(function (error) {
      var host = $("#candidates");
      if (host) host.innerHTML = "<p class=\"muted\">\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u043a\u0430\u043d\u0434\u0438\u0434\u0430\u0442\u043e\u0432: " + esc(error.message) + "</p>";
    });
    var search = $("#search");
    if (search) search.addEventListener("input", function () { S.query = search.value; paintTable(); });
    var sort = $("#sort");
    if (sort) sort.addEventListener("change", function () { S.sort = sort.value; paintTable(); });
    var csv = $("#btn-csv");
    if (csv) csv.addEventListener("click", exportCsv);
  });
})(window);
