/*
 * ПРУФ · web/js/studio.js
 * Студия проверки кода: редактор, прогон тестов, генерация мутаций, полный анализ.
 */
(function (global) {
  "use strict";
  var P = global.PRUF;
  var $ = P.$, $$ = P.$$, el = P.el, esc = P.escapeHtml;

  var store = { tasks: [], task: null, analysis: null, mutations: [], demoTasks: null };

  function pick(obj, keys, fallback) {
    if (!obj) return fallback;
    for (var i = 0; i < keys.length; i += 1) {
      if (obj[keys[i]] !== undefined && obj[keys[i]] !== null) return obj[keys[i]];
    }
    return fallback;
  }

  /* ---------- консоль ---------- */
  function consoleClear() {
    var box = $("#console");
    if (box) box.innerHTML = "";
  }

  function log(text, kind) {
    var box = $("#console");
    if (!box) return;
    box.appendChild(el("div", { class: "console__line " + (kind ? "is-" + kind : ""), text: text }));
    box.scrollTop = box.scrollHeight;
  }

  function busy(button, on, label) {
    if (!button) return;
    if (on) {
      button.dataset.prev = button.textContent;
      button.textContent = label || "\u0421\u0447\u0438\u0442\u0430\u0435\u043c\u2026";
      button.disabled = true;
    } else {
      button.textContent = button.dataset.prev || button.textContent;
      button.disabled = false;
    }
  }

  function demoWarning(result) {
    if (result && result.__demo) {
      log("\u0414\u0432\u0438\u0436\u043e\u043a \u043d\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d \u2014 \u043f\u043e\u043a\u0430\u0437\u0430\u043d \u0434\u0435\u043c\u043e-\u0441\u043d\u0438\u043c\u043e\u043a \u0443\u0447\u0435\u0431\u043d\u043e\u0433\u043e \u0440\u0435\u0448\u0435\u043d\u0438\u044f, \u0430 \u043d\u0435 \u0432\u0430\u0448 \u043a\u043e\u0434.", "warn");
      log("\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435: python3 -m engine.cli serve \u2014 \u0438 \u043a\u043d\u043e\u043f\u043a\u0438 \u043d\u0430\u0447\u043d\u0443\u0442 \u0441\u0447\u0438\u0442\u0430\u0442\u044c \u0432\u0430\u0448\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435.", "warn");
    }
  }

  /* ---------- задачи ---------- */
  function fillTaskSelect() {
    var select = $("#task-select");
    if (!select) return;
    select.innerHTML = "";
    store.tasks.forEach(function (task) {
      select.appendChild(el("option", { value: task.id, text: task.title + " \u00b7 " + (task.level || "") }));
    });
    select.addEventListener("change", function () { applyTask(select.value); });
  }

  function applyTask(id) {
    var task = store.tasks.filter(function (item) { return item.id === id; })[0] || store.tasks[0];
    if (!task) return;
    store.task = task;
    $("#code").value = task.code || "";
    $("#tests").value = task.tests || "";
    var statement = $("#task-statement");
    if (statement) {
      statement.innerHTML = "<b>" + esc(task.title) + "</b><br>" + esc(task.statement || "") +
        "<br><span class=\"muted\">" + esc((task.skills || []).join(" \u00b7 ")) + "</span>";
    }
    resetResults();
    syncGutter();
  }

  function loadTasks() {
    return P.engine.tasks().then(function (payload) {
      store.tasks = payload.tasks || [];
      if (!store.tasks.length) throw new Error("\u041d\u0435\u0442 \u0437\u0430\u0434\u0430\u0447");
      fillTaskSelect();
      applyTask(store.tasks[0].id);
    }).catch(function () {
      log("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u043a\u0430\u0442\u0430\u043b\u043e\u0433 \u0437\u0430\u0434\u0430\u0447. \u041c\u043e\u0436\u043d\u043e \u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u0441\u043e \u0441\u0432\u043e\u0438\u043c \u043a\u043e\u0434\u043e\u043c.", "warn");
    });
  }

  /* ---------- редактор ---------- */
  function syncGutter() {
    var area = $("#code");
    var gutter = $("#gutter");
    if (!area || !gutter) return;
    var lines = area.value.split("\n").length;
    var out = [];
    for (var i = 1; i <= lines; i += 1) out.push(i);
    gutter.textContent = out.join("\n");
    gutter.scrollTop = area.scrollTop;
  }

  function initEditor() {
    ["#code", "#tests"].forEach(function (selector) {
      var area = $(selector);
      if (!area) return;
      area.addEventListener("keydown", function (event) {
        if (event.key === "Tab") {
          event.preventDefault();
          var start = area.selectionStart, end = area.selectionEnd;
          area.value = area.value.slice(0, start) + "    " + area.value.slice(end);
          area.selectionStart = area.selectionEnd = start + 4;
        }
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          runTests();
        }
      });
    });
    var code = $("#code");
    if (code) {
      code.addEventListener("input", function () { syncGutter(); resetResults(); });
      code.addEventListener("scroll", function () {
        var gutter = $("#gutter");
        if (gutter) gutter.scrollTop = code.scrollTop;
      });
    }
    var tests = $("#tests");
    if (tests) tests.addEventListener("input", resetResults);
  }

  function resetResults() {
    store.analysis = null;
    var start = $("#btn-session");
    if (start) start.disabled = true;
  }

  /* ---------- рендер мутаций ---------- */
  function statusClass(mutation) {
    if (!mutation.status) return "";
    return mutation.status === "killed" ? "is-killed" : "is-survived";
  }

  function statusLabel(mutation) {
    if (!mutation.status) return "\u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u0430";
    return mutation.status === "killed" ? "\u0442\u0435\u0441\u0442\u044b \u043f\u043e\u0439\u043c\u0430\u043b\u0438" : "\u043f\u0440\u043e\u0448\u043b\u0430 \u043d\u0435\u0437\u0430\u043c\u0435\u0447\u0435\u043d\u043d\u043e\u0439";
  }

  function renderMutations(list) {
    store.mutations = list || [];
    var host = $("#mutations");
    if (!host) return;
    host.innerHTML = "";
    if (!store.mutations.length) {
      host.appendChild(el("p", { class: "muted", text: "\u041c\u0443\u0442\u0430\u0446\u0438\u0439 \u043d\u0435\u0442: \u043a\u043e\u0434 \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u0438\u043b\u0438 \u0432 \u043d\u0451\u043c \u043d\u0435\u0442 \u043c\u0435\u0441\u0442, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u043c\u043e\u0436\u043d\u043e \u0441\u043b\u043e\u043c\u0430\u0442\u044c." }));
      return;
    }
    store.mutations.forEach(function (mutation) {
      var killedBy = (mutation.killed_by || []).join(", ");
      var node = el("div", { class: "mut " + statusClass(mutation) }, [
        el("div", { class: "mut__head" }, [
          el("span", { class: "mut__id", text: mutation.id }),
          el("span", { class: "mut__line", text: "\u0441\u0442\u0440\u043e\u043a\u0430 " + (mutation.line || "?") }),
          el("span", { class: "mut__status", text: statusLabel(mutation) })
        ]),
        el("div", { class: "mut__diff" }, [
          el("code", { class: "mut__before", text: "\u2212 " + (mutation.before || "") }),
          el("code", { class: "mut__after", text: "+ " + (mutation.after || "") })
        ]),
        el("div", { class: "mut__meta" }, [
          el("span", { class: "badge badge--accent", text: mutation.skill_title || mutation.skill || "" }),
          el("span", { class: "muted", text: mutation.operator || "" })
        ]),
        mutation.consequence ? el("p", { class: "mut__why", text: "\u0427\u0442\u043e \u0441\u043b\u043e\u043c\u0430\u0435\u0442\u0441\u044f: " + mutation.consequence }) : null,
        killedBy ? el("p", { class: "mut__kill", text: "\u041f\u043e\u0439\u043c\u0430\u043b\u0438: " + killedBy }) : null,
        (mutation.status === "survived" && mutation.suggestion)
          ? el("p", { class: "mut__fix", text: "\u0427\u0442\u043e \u0434\u043e\u0431\u0430\u0432\u0438\u0442\u044c: " + mutation.suggestion }) : null
      ]);
      host.appendChild(node);
    });
  }

  function renderScore(analysis) {
    var host = $("#score");
    if (!host) return;
    var pct = pick(analysis, ["mutation_score_pct"], Math.round((analysis.mutation_score || 0) * 100));
    var verdict = analysis.verdict || {};
    var level = verdict.level || (pct >= 85 ? "good" : pct >= 60 ? "medium" : "bad");
    host.innerHTML = "";
    host.appendChild(el("div", { class: "kpi" }, [
      el("div", { class: "kpi__item" }, [
        el("div", { class: "kpi__value", text: pct + " %" }),
        el("div", { class: "kpi__label", text: "\u0442\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442 \u043f\u0440\u0430\u0432\u043e\u043a" })
      ]),
      el("div", { class: "kpi__item" }, [
        el("div", { class: "kpi__value", text: String(analysis.mutation_total || 0) }),
        el("div", { class: "kpi__label", text: "\u043c\u0443\u0442\u0430\u0446\u0438\u0439 \u043f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u043e" })
      ]),
      el("div", { class: "kpi__item" }, [
        el("div", { class: "kpi__value", text: String(analysis.killed || 0) }),
        el("div", { class: "kpi__label", text: "\u043f\u043e\u0439\u043c\u0430\u043d\u043e" })
      ]),
      el("div", { class: "kpi__item" }, [
        el("div", { class: "kpi__value", text: String(analysis.survived || 0) }),
        el("div", { class: "kpi__label", text: "\u043f\u0440\u043e\u0448\u043b\u043e \u043d\u0435\u0437\u0430\u043c\u0435\u0447\u0435\u043d\u043d\u044b\u043c\u0438" })
      ])
    ]));
    host.appendChild(el("div", { class: "progress" }, [el("span", { style: "width:" + pct + "%" })]));
    host.appendChild(el("p", { class: "badge " + P.levelClass(level), text: verdict.label || "\u0412\u0435\u0440\u0434\u0438\u043a\u0442 \u043f\u043e \u0442\u0435\u0441\u0442\u0430\u043c" }));
    if (verdict.summary) host.appendChild(el("p", { class: "muted", text: verdict.summary }));
  }

  function renderGaps(analysis) {
    var host = $("#gaps");
    if (!host) return;
    var gaps = analysis.gaps || [];
    host.innerHTML = "";
    if (!gaps.length) {
      host.appendChild(el("p", { class: "muted", text: "\u0414\u044b\u0440 \u043d\u0435 \u043d\u0430\u0448\u043b\u043e\u0441\u044c: \u043d\u0430\u0431\u043e\u0440 \u0442\u0435\u0441\u0442\u043e\u0432 \u043f\u043e\u0439\u043c\u0430\u043b \u0432\u0441\u0435 \u043f\u0440\u0430\u0432\u043a\u0438." }));
      return;
    }
    var list = el("ol", { class: "list" });
    gaps.forEach(function (gap) {
      list.appendChild(el("li", {
        html: "<b>" + esc(gap.id) + "</b> \u00b7 \u0441\u0442\u0440\u043e\u043a\u0430 " + esc(gap.line) + " \u2014 " + esc(gap.suggestion || "")
      }));
    });
    host.appendChild(list);
  }

  function renderTestTable(analysis) {
    var host = $("#tests-table");
    if (!host) return;
    var rows = analysis.tests || [];
    host.innerHTML = "";
    if (!rows.length) return;
    var table = el("table", { class: "table" }, [
      el("thead", {}, [el("tr", {}, [
        el("th", { text: "\u0422\u0435\u0441\u0442" }), el("th", { text: "\u0421\u0442\u0430\u0442\u0443\u0441" }),
        el("th", { text: "\u041b\u043e\u0432\u0438\u0442 \u043f\u0440\u0430\u0432\u043e\u043a" }), el("th", { text: "\u0412\u0435\u0440\u0434\u0438\u043a\u0442" })
      ])])
    ]);
    var body = el("tbody");
    rows.forEach(function (row) {
      var kills = pick(row, ["kills", "killed"], 0);
      body.appendChild(el("tr", {}, [
        el("td", {}, [el("code", { text: row.name })]),
        el("td", {}, [el("span", { class: "badge " + (row.status === "passed" ? "badge--ok" : "badge--bad"), text: row.status === "passed" ? "\u043f\u0440\u043e\u0448\u0451\u043b" : "\u0443\u043f\u0430\u043b" })]),
        el("td", { text: String(kills) }),
        el("td", { text: row.verdict || (kills ? "\u041f\u043e\u043b\u0435\u0437\u043d\u044b\u0439" : "\u041d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u0434\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442") })
      ]));
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  /* ---------- действия ---------- */
  function currentCode() { return ($("#code") || {}).value || ""; }
  function currentTests() { return ($("#tests") || {}).value || ""; }

  function runTests(event) {
    var button = event && event.currentTarget;
    consoleClear();
    log("$ \u043f\u0440\u043e\u0433\u043e\u043d \u0442\u0435\u0441\u0442\u043e\u0432 \u0432 \u0438\u0437\u043e\u043b\u044f\u0442\u043e\u0440\u0435\u2026");
    busy(button, true);
    return P.engine.run(currentCode(), currentTests()).then(function (report) {
      demoWarning(report);
      if (report.import_error) log("\u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043c\u043f\u043e\u0440\u0442\u0430: " + report.import_error, "bad");
      if (report.timeout) log("\u0422\u0430\u0439\u043c\u0430\u0443\u0442 \u043f\u0440\u043e\u0433\u043e\u043d\u0430: \u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u043d\u0435 \u0443\u043b\u043e\u0436\u0438\u043b\u043e\u0441\u044c \u0432 \u043b\u0438\u043c\u0438\u0442.", "bad");
      (report.tests || []).forEach(function (test) {
        var ok = test.status === "passed";
        log((ok ? "\u2713 " : "\u2717 ") + test.name + " \u00b7 " + test.status + (test.duration_ms ? " \u00b7 " + test.duration_ms + " \u043c\u0441" : "") +
          (test.message ? " \u2014 " + test.message : ""), ok ? "ok" : "bad");
      });
      log("\u0418\u0442\u043e\u0433: \u043f\u0440\u043e\u0448\u043b\u043e " + (report.passed || 0) + ", \u0443\u043f\u0430\u043b\u043e " + (report.failed || 0) +
        ", \u043e\u0448\u0438\u0431\u043a\u0438 " + (report.errored || 0) + " \u00b7 " + (report.duration_ms || 0) + " \u043c\u0441",
        report.ok ? "ok" : "warn");
      if (report.stdout) log("stdout: " + String(report.stdout).slice(0, 400));
      return report;
    }).catch(function (error) {
      log("\u041e\u0448\u0438\u0431\u043a\u0430: " + error.message, "bad");
    }).then(function (result) {
      busy(button, false);
      return result;
    });
  }

  function buildMutations(event) {
    var button = event && event.currentTarget;
    consoleClear();
    log("$ \u0440\u0430\u0437\u0431\u043e\u0440 AST \u0438 \u043f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u0435 \u043c\u0443\u0442\u0430\u0446\u0438\u0439\u2026");
    busy(button, true, "\u041b\u043e\u043c\u0430\u0435\u043c\u2026");
    return P.engine.mutate(currentCode(), 13).then(function (preview) {
      demoWarning(preview);
      if (preview.ok === false) {
        log("\u0421\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0441 \u043d\u0435 \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043b\u0441\u044f: " + (preview.error || ""), "bad");
        return preview;
      }
      var list = (preview.mutations || []).map(function (item) {
        var copy = Object.assign({}, item);
        delete copy.status;
        return copy;
      });
      renderMutations(list);
      log("\u041c\u0435\u0441\u0442 \u0434\u043b\u044f \u043f\u0440\u0430\u0432\u043a\u0438: " + (preview.sites || list.length) + ", \u043f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u043e \u043c\u0443\u0442\u0430\u0446\u0438\u0439: " + list.length, "ok");
      log("\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433 \u2014 \u00ab\u041f\u043e\u043b\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437\u00bb: \u043a\u0430\u0436\u0434\u0430\u044f \u043c\u0443\u0442\u0430\u0446\u0438\u044f \u043f\u0440\u043e\u0433\u043e\u043d\u044f\u0435\u0442\u0441\u044f \u0447\u0435\u0440\u0435\u0437 \u0432\u0430\u0448\u0438 \u0442\u0435\u0441\u0442\u044b.");
      return preview;
    }).catch(function (error) {
      log("\u041e\u0448\u0438\u0431\u043a\u0430: " + error.message, "bad");
    }).then(function (result) {
      busy(button, false);
      return result;
    });
  }

  function fullAnalysis(event) {
    var button = event && event.currentTarget;
    consoleClear();
    log("$ \u043f\u043e\u043b\u043d\u044b\u0439 \u043c\u0443\u0442\u0430\u0446\u0438\u043e\u043d\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437: \u0431\u0430\u0437\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d + \u043c\u0443\u0442\u0430\u043d\u0442\u044b\u2026");
    busy(button, true, "\u0421\u0447\u0438\u0442\u0430\u0435\u043c\u2026");
    return P.engine.analyze(currentCode(), currentTests(), 13).then(function (analysis) {
      demoWarning(analysis);
      if (analysis.ok === false) {
        log("\u0410\u043d\u0430\u043b\u0438\u0437 \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d: " + (analysis.error || analysis.stage || ""), "bad");
        if (analysis.baseline && analysis.baseline.ok === false) {
          log("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0434\u043e\u0431\u0435\u0439\u0442\u0435\u0441\u044c \u0437\u0435\u043b\u0451\u043d\u044b\u0445 \u0442\u0435\u0441\u0442\u043e\u0432 \u043d\u0430 \u0438\u0441\u0445\u043e\u0434\u043d\u043e\u043c \u043a\u043e\u0434\u0435 \u2014 \u043c\u0443\u0442\u0430\u0446\u0438\u0438 \u0441\u0447\u0438\u0442\u0430\u044e\u0442\u0441\u044f \u0442\u043e\u043b\u044c\u043a\u043e \u043e\u0442 \u0440\u0430\u0431\u043e\u0442\u0430\u044e\u0449\u0435\u0433\u043e \u0440\u0435\u0448\u0435\u043d\u0438\u044f.", "warn");
        }
        return analysis;
      }
      store.analysis = analysis;
      renderMutations(analysis.mutations || []);
      renderScore(analysis);
      renderGaps(analysis);
      renderTestTable(analysis);
      var baseline = analysis.baseline || {};
      log("\u0411\u0430\u0437\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0433\u043e\u043d: \u043f\u0440\u043e\u0448\u043b\u043e " + (baseline.passed || 0) + " \u0438\u0437 " +
        ((baseline.passed || 0) + (baseline.failed || 0) + (baseline.errored || 0)) + " \u00b7 " + (baseline.duration_ms || 0) + " \u043c\u0441", "ok");
      log("\u041c\u0443\u0442\u0430\u0446\u0438\u0438: " + (analysis.mutation_total || 0) + ", \u043f\u043e\u0439\u043c\u0430\u043d\u043e " + (analysis.killed || 0) +
        ", \u043f\u0440\u043e\u0448\u043b\u043e \u043d\u0435\u0437\u0430\u043c\u0435\u0447\u0435\u043d\u043d\u044b\u043c\u0438 " + (analysis.survived || 0));
      log("\u0412\u0435\u0440\u0434\u0438\u043a\u0442: " + ((analysis.verdict || {}).label || "\u2014") + " \u00b7 " + (analysis.mutation_score_pct || 0) + " %",
        (analysis.verdict || {}).level === "good" ? "ok" : "warn");
      (analysis.useless_tests || []).forEach(function (name) {
        log("\u0422\u0435\u0441\u0442 " + name + " \u043d\u0435 \u043f\u043e\u0439\u043c\u0430\u043b \u043d\u0438 \u043e\u0434\u043d\u043e\u0439 \u043f\u0440\u0430\u0432\u043a\u0438.", "warn");
      });
      var start = $("#btn-session");
      if (start) start.disabled = false;
      return analysis;
    }).catch(function (error) {
      log("\u041e\u0448\u0438\u0431\u043a\u0430: " + error.message, "bad");
    }).then(function (result) {
      busy(button, false);
      return result;
    });
  }

  function weakenTests() {
    var area = $("#tests");
    if (!area) return;
    var blocks = area.value.split(/\n(?=def test)/);
    if (blocks.length < 2) {
      P.toast("\u0412 \u043d\u0430\u0431\u043e\u0440\u0435 \u0438 \u0442\u0430\u043a \u043e\u0434\u0438\u043d \u0442\u0435\u0441\u0442", "warn");
      return;
    }
    area.value = blocks.slice(0, Math.max(1, blocks.length - 2)).join("\n");
    resetResults();
    P.toast("\u0423\u0431\u0440\u0430\u043b\u0438 \u0447\u0430\u0441\u0442\u044c \u0442\u0435\u0441\u0442\u043e\u0432: \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u0430\u043d\u0430\u043b\u0438\u0437 \u0438 \u0441\u0440\u0430\u0432\u043d\u0438\u0442\u0435 \u043f\u0440\u043e\u0446\u0435\u043d\u0442");
  }

  function startSession(event) {
    var button = event && event.currentTarget;
    var meta = {
      candidate: ($("#candidate-name") || {}).value || "\u0413\u043e\u0441\u0442\u044c",
      task: store.task ? store.task.title : "\u0421\u0432\u043e\u0451 \u0440\u0435\u0448\u0435\u043d\u0438\u0435",
      vacancy: ($("#vacancy-name") || {}).value || ""
    };
    busy(button, true, "\u0413\u043e\u0442\u043e\u0432\u0438\u043c \u0441\u0435\u0441\u0441\u0438\u044e\u2026");
    var payload = { code: currentCode(), tests: currentTests(), question_limit: 13, meta: meta };
    sessionStorage.setItem("pruf.draft", JSON.stringify(payload));
    return P.engine.sessionStart(payload).then(function (session) {
      if (session.__demo) {
        sessionStorage.setItem("pruf.demoSession", JSON.stringify({ analysis: store.analysis, meta: meta }));
        location.href = "session.html?demo=1";
        return;
      }
      var id = pick(session, ["id", "session_id"], null);
      if (!id) throw new Error("\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435 \u0432\u0435\u0440\u043d\u0443\u043b \u043d\u043e\u043c\u0435\u0440 \u0441\u0435\u0441\u0441\u0438\u0438");
      location.href = "session.html?id=" + encodeURIComponent(id);
    }).catch(function (error) {
      busy(button, false);
      log("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043d\u0430\u0447\u0430\u0442\u044c \u0441\u0435\u0441\u0441\u0438\u044e: " + error.message, "bad");
    });
  }

  function copyCode() {
    var text = currentCode();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () { P.toast("\u041a\u043e\u0434 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d", "ok"); });
    } else {
      P.toast("\u0411\u0443\u0444\u0435\u0440 \u043e\u0431\u043c\u0435\u043d\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d", "warn");
    }
  }

  function downloadReport() {
    if (!store.analysis) {
      P.toast("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u043f\u043e\u043b\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437", "warn");
      return;
    }
    var blob = new Blob([JSON.stringify(store.analysis, null, 2)], { type: "application/json" });
    var link = el("a", { href: URL.createObjectURL(blob), download: "pruf-analysis.json" });
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  P.ready(function () {
    if (!$("#code")) return;
    initEditor();
    consoleClear();
    log("\u0418\u0437\u043e\u043b\u044f\u0442\u043e\u0440 \u0433\u043e\u0442\u043e\u0432. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0438\u043b\u0438 \u0432\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u0432\u043e\u0439 \u043a\u043e\u0434.");
    loadTasks();
    var handlers = [
      ["#btn-run", runTests], ["#btn-mutate", buildMutations], ["#btn-analyze", fullAnalysis],
      ["#btn-session", startSession], ["#btn-weaken", weakenTests], ["#btn-copy", copyCode],
      ["#btn-report", downloadReport],
      ["#btn-reset", function () { if (store.task) applyTask(store.task.id); }]
    ];
    handlers.forEach(function (pair) {
      var node = $(pair[0]);
      if (node) node.addEventListener("click", pair[1]);
    });
    var start = $("#btn-session");
    if (start) start.disabled = true;
  });

  global.PRUFStudio = { runTests: runTests, buildMutations: buildMutations, fullAnalysis: fullAnalysis };
})(window);
