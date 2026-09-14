/*
 * ПРУФ · web/js/session.js
 * Сессия защиты понимания: 15 минут, вопросы из мутаций собственного кода, протокол.
 *
 * Два режима:
 *  1) сервер запущен — вопросы и протокол строит движок (engine/session.py, engine/protocol.py);
 *  2) сервер не запущен — вопросы собираются в браузере из демо-снимка анализа.
 *     Второй режим нужен только для демонстрации без бэкенда и помечен в интерфейсе.
 */
(function (global) {
  "use strict";
  var P = global.PRUF;
  var $ = P.$, el = P.el, esc = P.escapeHtml;

  var TOTAL_SECONDS = 900;
  var TITLES = {
    danger: "\u041a\u0430\u043a\u0430\u044f \u043f\u0440\u0430\u0432\u043a\u0430 \u043e\u043f\u0430\u0441\u043d\u0430?",
    gap: "\u0417\u0430\u043c\u0435\u0442\u044f\u0442 \u043b\u0438 \u0432\u0430\u0448\u0438 \u0442\u0435\u0441\u0442\u044b \u044d\u0442\u0443 \u043f\u0440\u0430\u0432\u043a\u0443?",
    first_failure: "\u041a\u0430\u043a\u043e\u0439 \u0442\u0435\u0441\u0442 \u0443\u043f\u0430\u0434\u0451\u0442 \u043f\u0435\u0440\u0432\u044b\u043c?",
    consequence: "\u0427\u0442\u043e \u0438\u043c\u0435\u043d\u043d\u043e \u0441\u043b\u043e\u043c\u0430\u0435\u0442\u0441\u044f?"
  };
  var NO_TEST = "\u041d\u0438 \u043e\u0434\u0438\u043d \u0442\u0435\u0441\u0442 \u043d\u0435 \u0437\u0430\u043c\u0435\u0442\u0438\u0442 \u043f\u0440\u0430\u0432\u043a\u0443";
  var LETTERS = "ABCDE";

  var S = {
    demo: false, id: null, questions: [], index: 0, answers: [],
    left: TOTAL_SECONDS, timer: null, analysis: null, meta: {}, finished: false, protocol: null,
    questionStart: 0
  };

  function param(name) {
    return new URLSearchParams(location.search).get(name);
  }

  function pick(obj, keys, fallback) {
    if (!obj) return fallback;
    for (var i = 0; i < keys.length; i += 1) {
      if (obj[keys[i]] !== undefined && obj[keys[i]] !== null) return obj[keys[i]];
    }
    return fallback;
  }

  /* ---------- клиентский сборщик вопросов (только демо-режим) ---------- */
  function shuffle(list, seed) {
    var arr = list.slice();
    var state = seed || 7;
    for (var i = arr.length - 1; i > 0; i -= 1) {
      state = (state * 1103515245 + 12345) % 2147483648;
      var j = state % (i + 1);
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  function options(texts, correctText, seed) {
    var unique = [];
    texts.forEach(function (text) { if (text && unique.indexOf(text) === -1) unique.push(text); });
    if (unique.indexOf(correctText) === -1) unique.push(correctText);
    var ordered = shuffle(unique.slice(0, 4), seed);
    if (ordered.indexOf(correctText) === -1) ordered[ordered.length - 1] = correctText;
    return ordered.map(function (text, index) {
      return { id: "o" + index, letter: LETTERS[index], text: text, correct: text === correctText };
    });
  }

  function buildDemoQuestions(analysis) {
    var mutations = (analysis.mutations || []).slice();
    if (!mutations.length) return [];
    var survived = mutations.filter(function (m) { return m.status === "survived"; });
    var killed = mutations.filter(function (m) { return m.status === "killed"; });
    var tests = (analysis.tests || []).map(function (t) { return t.name; });
    var kinds = ["danger", "gap", "first_failure", "consequence"];
    var questions = [];
    var order = killed.concat(survived);

    order.forEach(function (mutation, position) {
      kinds.forEach(function (kind, kindIndex) {
        if (questions.length >= 13) return;
        if ((position + kindIndex) % 3 !== 0 && questions.length > 5) return;
        var seed = position * 17 + kindIndex * 7 + 3;
        var question = { id: "q" + (questions.length + 1), kind: kind, mutation: mutation.id, title: TITLES[kind] };
        question.fragment = { line: mutation.line, before: mutation.before, after: mutation.after };

        if (kind === "danger") {
          var target = survived[position % Math.max(1, survived.length)] || mutation;
          var texts = shuffle(mutations, seed).slice(0, 3).map(function (m) {
            return m.id + ": " + m.before + " \u2192 " + m.after;
          });
          question.prompt = "\u041a\u0430\u043a\u0430\u044f \u0438\u0437 \u043f\u0440\u0430\u0432\u043e\u043a \u043f\u0440\u043e\u0439\u0434\u0451\u0442 \u043c\u0438\u043c\u043e \u0432\u0430\u0448\u0435\u0433\u043e \u043d\u0430\u0431\u043e\u0440\u0430 \u0442\u0435\u0441\u0442\u043e\u0432 \u2014 \u0442\u043e \u0435\u0441\u0442\u044c \u0441\u043b\u043e\u043c\u0430\u0435\u0442 \u043b\u043e\u0433\u0438\u043a\u0443, \u043d\u043e \u043e\u0441\u0442\u0430\u0432\u0438\u0442 \u0442\u0435\u0441\u0442\u044b \u0437\u0435\u043b\u0451\u043d\u044b\u043c\u0438?";
          question.fragment = { line: target.line, before: target.before, after: target.after };
          question.mutation = target.id;
          question.options = options(texts, target.id + ": " + target.before + " \u2192 " + target.after, seed);
          question.explanation = "\u041f\u0440\u0430\u0432\u043a\u0430 " + target.id + " \u0432 \u0441\u0442\u0440\u043e\u043a\u0435 " + target.line +
            " \u043f\u0440\u043e\u0448\u043b\u0430 \u043d\u0435\u0437\u0430\u043c\u0435\u0447\u0435\u043d\u043d\u043e\u0439 \u043f\u0440\u0438 \u0440\u0435\u0430\u043b\u044c\u043d\u043e\u043c \u043f\u0440\u043e\u0433\u043e\u043d\u0435. " + (target.suggestion || "");
        } else if (kind === "gap") {
          var correctGap = mutation.status === "survived"
            ? NO_TEST
            : "\u0414\u0430, \u0443\u043f\u0430\u0434\u0451\u0442 " + ((mutation.killed_by || [])[0] || "\u0442\u0435\u0441\u0442");
          var gapTexts = [NO_TEST, "\u041f\u0440\u043e\u0433\u043e\u043d \u0443\u043f\u0430\u0434\u0451\u0442 \u0446\u0435\u043b\u0438\u043a\u043e\u043c: \u043e\u0448\u0438\u0431\u043a\u0430 \u0438\u043b\u0438 \u0442\u0430\u0439\u043c\u0430\u0443\u0442"];
          tests.slice(0, 3).forEach(function (name) { gapTexts.push("\u0414\u0430, \u0443\u043f\u0430\u0434\u0451\u0442 " + name); });
          question.prompt = "\u041f\u0440\u0430\u0432\u043a\u0430 " + mutation.id + " \u0432\u043d\u0435\u0441\u0435\u043d\u0430 \u0432 \u0441\u0442\u0440\u043e\u043a\u0443 " + mutation.line +
            ". \u0417\u0430\u043c\u0435\u0442\u0438\u0442 \u043b\u0438 \u0435\u0451 \u0432\u0430\u0448 \u043d\u0430\u0431\u043e\u0440 \u0442\u0435\u0441\u0442\u043e\u0432?";
          question.options = options(gapTexts, correctGap, seed);
          question.explanation = mutation.status === "survived"
            ? "\u041d\u0438 \u043e\u0434\u0438\u043d \u0442\u0435\u0441\u0442 \u043d\u0435 \u0443\u043f\u0430\u043b: \u044d\u0442\u043e \u0434\u044b\u0440\u0430 \u0432 \u043d\u0430\u0431\u043e\u0440\u0435. " + (mutation.suggestion || "")
            : "\u041f\u0440\u0430\u0432\u043a\u0443 \u043f\u043e\u0439\u043c\u0430\u043b\u0438: " + (mutation.killed_by || []).join(", ") + ".";
        } else if (kind === "first_failure") {
          var correctFirst = (mutation.killed_by || [])[0] || NO_TEST;
          var failTexts = tests.slice(0, 3).concat([NO_TEST]);
          question.prompt = "\u0415\u0441\u043b\u0438 \u043f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c " + mutation.id + " (" + mutation.before + " \u2192 " + mutation.after +
            "), \u043a\u0430\u043a\u043e\u0439 \u0442\u0435\u0441\u0442 \u0443\u043f\u0430\u0434\u0451\u0442 \u043f\u0435\u0440\u0432\u044b\u043c?";
          question.options = options(failTexts, correctFirst, seed);
          question.explanation = correctFirst === NO_TEST
            ? "\u041d\u0438 \u043e\u0434\u0438\u043d \u0442\u0435\u0441\u0442 \u043d\u0435 \u0440\u0435\u0430\u0433\u0438\u0440\u0443\u0435\u0442 \u043d\u0430 \u044d\u0442\u0443 \u043f\u0440\u0430\u0432\u043a\u0443."
            : "\u041f\u0435\u0440\u0432\u044b\u043c \u0443\u043f\u0430\u043b " + correctFirst + ".";
        } else {
          var consequences = shuffle(mutations, seed).slice(0, 3).map(function (m) { return m.consequence; });
          question.prompt = "\u0427\u0442\u043e \u0438\u043c\u0435\u043d\u043d\u043e \u0438\u0437\u043c\u0435\u043d\u0438\u0442\u0441\u044f \u0432 \u043f\u043e\u0432\u0435\u0434\u0435\u043d\u0438\u0438 \u043a\u043e\u0434\u0430 \u043f\u043e\u0441\u043b\u0435 \u043f\u0440\u0430\u0432\u043a\u0438 " + mutation.id + "?";
          question.options = options(consequences, mutation.consequence, seed);
          question.explanation = "\u041f\u0440\u0430\u0432\u043a\u0430 \u0432 \u0441\u0442\u0440\u043e\u043a\u0435 " + mutation.line + ": " + mutation.consequence + ".";
        }
        question.skill = mutation.skill;
        question.skill_title = mutation.skill_title;
        questions.push(question);
      });
    });
    return questions.slice(0, 13);
  }

  /* ---------- таймер ---------- */
  function paintTimer() {
    var node = $("#timer");
    if (!node) return;
    node.textContent = P.clock(S.left);
    node.classList.toggle("is-low", S.left <= 120);
  }

  function startTimer() {
    paintTimer();
    S.timer = setInterval(function () {
      S.left -= 1;
      paintTimer();
      if (S.left <= 0) {
        clearInterval(S.timer);
        P.toast("\u0412\u0440\u0435\u043c\u044f \u0432\u044b\u0448\u043b\u043e: \u0441\u0435\u0441\u0441\u0438\u044f \u0437\u0430\u043a\u0440\u044b\u0442\u0430", "warn", 6000);
        finish();
      }
    }, 1000);
  }

  /* ---------- рендер вопроса ---------- */
  function paintProgress() {
    var done = S.answers.length;
    var total = S.questions.length;
    var label = $("#progress-label");
    if (label) label.textContent = "\u041c\u0443\u0442\u0430\u0446\u0438\u0439 \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043d\u043e " + done + " \u0438\u0437 " + total;
    var bar = $("#progress-bar");
    if (bar) bar.style.width = (total ? Math.round((done / total) * 100) : 0) + "%";
    var correct = S.answers.filter(function (a) { return a.correct; }).length;
    var score = $("#live-score");
    if (score) score.textContent = correct + " / " + done;
  }

  function paintQuestion() {
    var question = S.questions[S.index];
    var host = $("#question");
    if (!host) return;
    if (!question) { finish(); return; }
    S.questionStart = Date.now();
    host.innerHTML = "";
    host.appendChild(el("div", { class: "q__head" }, [
      el("span", { class: "badge badge--accent", text: "\u0412\u043e\u043f\u0440\u043e\u0441 " + (S.index + 1) + " / " + S.questions.length }),
      el("span", { class: "badge", text: question.mutation || "" }),
      question.skill_title ? el("span", { class: "badge", text: question.skill_title }) : null
    ]));
    host.appendChild(el("h2", { class: "q__title", text: question.title || TITLES[question.kind] || "\u0412\u043e\u043f\u0440\u043e\u0441" }));
    host.appendChild(el("p", { class: "q__prompt", text: pick(question, ["prompt", "text"], "") }));

    var fragment = question.fragment || {};
    if (fragment.before || fragment.after) {
      host.appendChild(el("div", { class: "mut__diff" }, [
        el("code", { class: "mut__before", text: "\u2212 " + (fragment.before || "") }),
        el("code", { class: "mut__after", text: "+ " + (fragment.after || "") }),
        fragment.line ? el("span", { class: "muted", text: "\u0441\u0442\u0440\u043e\u043a\u0430 " + fragment.line }) : null
      ]));
    }

    var list = el("div", { class: "options" });
    (question.options || []).forEach(function (option) {
      var button = el("button", { class: "option", type: "button" }, [
        el("span", { class: "option__letter", text: option.letter || "" }),
        el("span", { class: "option__text", text: pick(option, ["text", "label"], "") })
      ]);
      button.addEventListener("click", function () { answer(option, button); });
      list.appendChild(button);
    });
    host.appendChild(list);
    host.appendChild(el("div", { class: "q__review", id: "review" }));
    paintProgress();
  }

  function paintReview(payload, correct) {
    var host = $("#review");
    if (!host) return;
    host.innerHTML = "";
    host.appendChild(el("h3", { text: "\u0420\u0430\u0437\u0431\u043e\u0440 \u043e\u0442\u0432\u0435\u0442\u0430" }));
    host.appendChild(el("p", {
      class: "badge " + (correct ? "badge--ok" : "badge--bad"),
      text: correct ? "\u0412\u0435\u0440\u043d\u043e" : "\u041d\u0435\u0432\u0435\u0440\u043d\u043e"
    }));
    var explanation = pick(payload, ["explanation", "review", "detail"], "");
    if (explanation) host.appendChild(el("p", { text: explanation }));

    var runLines = pick(payload, ["run", "console"], null);
    var consoleBox = el("div", { class: "console console--sm" });
    var question = S.questions[S.index] || {};
    var mutationId = question.mutation;
    var mutation = (S.analysis && (S.analysis.mutations || []).filter(function (m) { return m.id === mutationId; })[0]) || null;
    var tests = (S.analysis && S.analysis.tests) || [];
    if (runLines && runLines.tests) {
      runLines.tests.forEach(function (test) {
        consoleBox.appendChild(el("div", { class: "console__line " + (test.status === "passed" ? "is-ok" : "is-bad"), text: (test.status === "passed" ? "\u2713 " : "\u2717 ") + test.name + " \u00b7 " + test.status }));
      });
    } else if (mutation && tests.length) {
      var killedBy = mutation.killed_by || [];
      consoleBox.appendChild(el("div", { class: "console__line", text: "$ \u043f\u0440\u043e\u0433\u043e\u043d \u0442\u0435\u0441\u0442\u043e\u0432 \u043d\u0430 \u043c\u0443\u0442\u0430\u043d\u0442\u0435 " + mutation.id }));
      tests.forEach(function (test) {
        var failed = killedBy.indexOf(test.name) !== -1;
        consoleBox.appendChild(el("div", {
          class: "console__line " + (failed ? "is-bad" : "is-ok"),
          text: (failed ? "\u2717 " : "\u2713 ") + test.name + " \u00b7 " + (failed ? "failed" : "passed")
        }));
      });
      consoleBox.appendChild(el("div", {
        class: "console__line " + (killedBy.length ? "is-ok" : "is-warn"),
        text: killedBy.length ? "\u041c\u0443\u0442\u0430\u043d\u0442 \u0443\u0431\u0438\u0442: \u0442\u0435\u0441\u0442\u044b \u0437\u0430\u043c\u0435\u0442\u0438\u043b\u0438 \u043f\u0440\u0430\u0432\u043a\u0443" : "\u041c\u0443\u0442\u0430\u043d\u0442 \u0432\u044b\u0436\u0438\u043b: \u043d\u0438 \u043e\u0434\u0438\u043d \u0442\u0435\u0441\u0442 \u043d\u0435 \u0443\u043f\u0430\u043b"
      }));
    }
    host.appendChild(consoleBox);

    var next = el("button", { class: "btn btn--sm", type: "button", text: S.index + 1 >= S.questions.length ? "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u0438 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b" : "\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0432\u043e\u043f\u0440\u043e\u0441" });
    next.addEventListener("click", function () {
      S.index += 1;
      if (S.index >= S.questions.length) finish();
      else paintQuestion();
    });
    host.appendChild(next);
  }

  function answer(option, button) {
    var question = S.questions[S.index];
    if (!question || button.closest(".options").classList.contains("is-locked")) return;
    var box = button.closest(".options");
    box.classList.add("is-locked");
    var seconds = Math.round((Date.now() - S.questionStart) / 1000);

    function settle(correct, payload) {
      Array.prototype.forEach.call(box.children, function (node) { node.disabled = true; });
      button.classList.add(correct ? "is-correct" : "is-wrong");
      if (!correct) {
        var correctId = pick(payload, ["correct", "correct_option"], null);
        Array.prototype.forEach.call(box.children, function (node, index) {
          var candidate = (question.options || [])[index];
          if (candidate && (candidate.correct === true || (correctId && candidate.id === correctId))) node.classList.add("is-correct");
        });
      }
      S.answers.push({ question: question.id, mutation: question.mutation, skill: question.skill, skill_title: question.skill_title, correct: correct, seconds: seconds });
      paintProgress();
      paintReview(payload, correct);
    }

    if (S.demo) {
      settle(option.correct === true, { explanation: question.explanation });
      return;
    }
    P.engine.answer(S.id, question.id, option.id, seconds).then(function (payload) {
      var correct = pick(payload, ["correct", "is_correct", "ok"], false) === true;
      settle(correct, payload);
    }).catch(function (error) {
      P.toast("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0441\u0447\u0438\u0442\u0430\u0442\u044c \u043e\u0442\u0432\u0435\u0442: " + error.message, "bad", 5000);
      box.classList.remove("is-locked");
    });
  }

  /* ---------- протокол ---------- */
  function buildDemoProtocol() {
    var total = S.answers.length || 1;
    var correct = S.answers.filter(function (a) { return a.correct; }).length;
    var controlPct = Math.round((correct / total) * 100);
    var bySkill = {};
    S.answers.forEach(function (item) {
      var key = item.skill || "other";
      bySkill[key] = bySkill[key] || { skill: key, title: item.skill_title || "\u041f\u0440\u043e\u0447\u0435\u0435", total: 0, correct: 0 };
      bySkill[key].total += 1;
      if (item.correct) bySkill[key].correct += 1;
    });
    var skills = Object.keys(bySkill).map(function (key) {
      var row = bySkill[key];
      row.ratio = row.total ? row.correct / row.total : 0;
      row.level = row.ratio >= 0.8 ? "control" : row.ratio >= 0.5 ? "shaky" : "weak";
      row.label = row.level === "control" ? "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u0438\u0440\u0443\u0435\u0442" : row.level === "shaky" ? "\u0428\u0430\u0442\u043a\u043e" : "\u041d\u0435 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u0438\u0440\u0443\u0435\u0442";
      return row;
    });
    var analysis = S.analysis || {};
    var risks = (analysis.gaps || []).slice(0, 3).map(function (gap) {
      return { kind: "tests", title: "\u0414\u044b\u0440\u0430 \u0432 \u0442\u0435\u0441\u0442\u0430\u0445: " + gap.id, detail: gap.suggestion || "" };
    });
    skills.filter(function (row) { return row.level !== "control"; }).forEach(function (row) {
      risks.push({ kind: "skill", title: row.label + ": " + row.title, detail: row.correct + " \u0438\u0437 " + row.total + " \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432 \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043d\u044b \u0432\u0435\u0440\u043d\u043e." });
    });
    var spent = TOTAL_SECONDS - S.left;
    return {
      id: "p-local" + Date.now().toString(36).slice(-6),
      candidate: { name: S.meta.candidate || "\u0413\u043e\u0441\u0442\u044c", vacancy: S.meta.vacancy || "" },
      task: { title: S.meta.task || "\u0421\u0432\u043e\u0451 \u0440\u0435\u0448\u0435\u043d\u0438\u0435", language: "Python", lines: analysis.lines, sites: analysis.sites },
      control_pct: controlPct,
      passed: controlPct >= 70,
      pass_threshold_pct: 70,
      verdict: {
        level: controlPct >= 80 ? "good" : controlPct >= 70 ? "medium" : controlPct >= 50 ? "low" : "bad",
        label: controlPct >= 80 ? "\u041f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e"
          : controlPct >= 70 ? "\u041f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e \u0441 \u043e\u0433\u043e\u0432\u043e\u0440\u043a\u0430\u043c\u0438"
          : controlPct >= 50 ? "\u0428\u0430\u0442\u043a\u043e\u0435 \u043f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u0435" : "\u041f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043d\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e",
        summary: "\u0420\u0430\u0437\u043e\u0431\u0440\u0430\u043d\u043e " + correct + " \u0438\u0437 " + total + " \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432 \u043f\u043e \u043c\u0443\u0442\u0430\u0446\u0438\u044f\u043c \u0441\u0432\u043e\u0435\u0433\u043e \u0440\u0435\u0448\u0435\u043d\u0438\u044f.",
        tests_note: "\u041d\u0430\u0431\u043e\u0440 \u0442\u0435\u0441\u0442\u043e\u0432 \u043b\u043e\u0432\u0438\u0442 " + (analysis.mutation_score_pct || 0) + " % \u043f\u0440\u0430\u0432\u043e\u043a."
      },
      mutation: {
        total: analysis.mutation_total || 0, killed: analysis.killed || 0,
        survived: analysis.survived || 0, score_pct: analysis.mutation_score_pct || 0,
        verdict: (analysis.verdict || {}).label || ""
      },
      questions: { total: S.questions.length, answered: total, correct: correct },
      skills: skills,
      risks: risks,
      quotes: (analysis.gaps || []).slice(0, 2).map(function (gap) {
        var m = (analysis.mutations || []).filter(function (item) { return item.id === gap.id; })[0] || {};
        return { id: gap.id, line: gap.line, before: m.before, after: m.after, note: gap.suggestion };
      }),
      timeline: S.answers.map(function (item) {
        return { id: item.mutation, ok: item.correct, clock: P.clock(item.seconds), label: item.correct ? "\u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043b" : "\u043d\u0435 \u0437\u0430\u043c\u0435\u0442\u0438\u043b" };
      }),
      duration_seconds: spent,
      duration_clock: P.clock(spent),
      reproducible: true,
      __demo: true
    };
  }

  function renderProtocol(protocol) {
    S.protocol = protocol;
    if (S.timer) clearInterval(S.timer);
    var stage = $("#stage");
    var host = $("#protocol");
    if (stage) stage.hidden = true;
    if (!host) return;
    host.hidden = false;
    var verdict = protocol.verdict || {};
    var control = pick(protocol, ["control_pct"], 0);
    host.innerHTML = "";

    host.appendChild(el("div", { class: "card card--accent" }, [
      el("div", { class: "row row--between" }, [
        el("div", {}, [
          el("h2", { text: "\u041f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u044f" }),
          el("p", { class: "muted", text: (protocol.candidate || {}).name + " \u00b7 " + ((protocol.task || {}).title || "") })
        ]),
        el("div", { class: "protocol__score" }, [
          el("div", { class: "kpi__value", text: control + " %" }),
          el("div", { class: "kpi__label", text: "\u043a\u043e\u043d\u0442\u0440\u043e\u043b\u0438\u0440\u0443\u0435\u0442 \u043a\u043e\u0434" })
        ])
      ]),
      el("p", { class: "badge " + P.levelClass(verdict.level), text: verdict.label || "" }),
      el("p", { text: verdict.summary || "" }),
      verdict.tests_note ? el("p", { class: "muted", text: verdict.tests_note }) : null,
      protocol.__demo ? el("p", { class: "muted", text: "\u0414\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c: \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u0441\u043e\u0431\u0440\u0430\u043d \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435. \u0421 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043d\u044b\u043c \u0434\u0432\u0438\u0436\u043a\u043e\u043c \u0435\u0433\u043e \u0441\u0442\u0440\u043e\u0438\u0442 engine/protocol.py \u0438 \u0432\u044b\u0433\u0440\u0443\u0436\u0430\u0435\u0442 PDF." }) : null
    ]));

    var mutation = protocol.mutation || {};
    var questions = protocol.questions || {};
    host.appendChild(el("div", { class: "kpi" }, [
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: String(mutation.total || 0) }), el("div", { class: "kpi__label", text: "\u043c\u0443\u0442\u0430\u0446\u0438\u0439" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: (mutation.score_pct || 0) + " %" }), el("div", { class: "kpi__label", text: "\u0442\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: (questions.correct || 0) + " / " + (questions.answered || 0) }), el("div", { class: "kpi__label", text: "\u0432\u0435\u0440\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432" })]),
      el("div", { class: "kpi__item" }, [el("div", { class: "kpi__value", text: protocol.duration_clock || "" }), el("div", { class: "kpi__label", text: "\u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c" })])
    ]));

    var skills = protocol.skills || [];
    if (skills.length) {
      var table = el("table", { class: "table" }, [el("thead", {}, [el("tr", {}, [
        el("th", { text: "\u041d\u0430\u0432\u044b\u043a" }), el("th", { text: "\u0412\u043e\u043f\u0440\u043e\u0441\u044b" }), el("th", { text: "\u0412\u0435\u0440\u043d\u043e" }), el("th", { text: "\u0412\u0435\u0440\u0434\u0438\u043a\u0442" })
      ])])]);
      var body = el("tbody");
      skills.forEach(function (row) {
        var level = row.level === "control" ? "badge--ok" : row.level === "shaky" ? "badge--warn" : "badge--bad";
        body.appendChild(el("tr", {}, [
          el("td", { text: row.title || row.skill }),
          el("td", { text: String(row.total || 0) }),
          el("td", { text: String(row.correct || 0) }),
          el("td", {}, [el("span", { class: "badge " + level, text: row.label || "" })])
        ]));
      });
      table.appendChild(body);
      host.appendChild(el("div", { class: "card" }, [el("h3", { text: "\u041a\u0430\u0440\u0442\u0430 \u043d\u0430\u0432\u044b\u043a\u043e\u0432" }), table]));
    }

    var risks = protocol.risks || [];
    if (risks.length) {
      var riskList = el("ul", { class: "list" });
      risks.forEach(function (risk) {
        riskList.appendChild(el("li", { html: "<b>" + esc(risk.title || "") + "</b> \u2014 " + esc(risk.detail || "") }));
      });
      host.appendChild(el("div", { class: "card" }, [el("h3", { text: "\u0420\u0438\u0441\u043a\u0438 \u0434\u043b\u044f \u0440\u0430\u0431\u043e\u0442\u043e\u0434\u0430\u0442\u0435\u043b\u044f" }), riskList]));
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
      host.appendChild(el("div", { class: "card" }, [el("h3", { text: "\u0422\u0430\u0439\u043c\u043b\u0430\u0439\u043d \u0441\u0435\u0441\u0441\u0438\u0438" }), line]));
    }

    var actions = el("div", { class: "row row--wrap" });
    var pdf = el("button", { class: "btn", type: "button", text: "\u0421\u043a\u0430\u0447\u0430\u0442\u044c PDF" });
    pdf.addEventListener("click", function () { downloadProtocol(protocol); });
    var send = el("button", { class: "btn btn--ghost", type: "button", text: "\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0440\u0430\u0431\u043e\u0442\u043e\u0434\u0430\u0442\u0435\u043b\u044e" });
    send.addEventListener("click", function () { sendProtocol(protocol); });
    var again = el("a", { class: "btn btn--quiet", href: "studio.html", text: "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0434\u0440\u0443\u0433\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435" });
    var cabinet = el("a", { class: "btn btn--quiet", href: "candidate.html", text: "\u041c\u043e\u0439 \u043a\u0430\u0431\u0438\u043d\u0435\u0442" });
    actions.appendChild(pdf); actions.appendChild(send); actions.appendChild(again); actions.appendChild(cabinet);
    host.appendChild(actions);
    host.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function downloadProtocol(protocol) {
    if (!protocol.__demo && S.id) {
      global.open("/api/protocol/" + encodeURIComponent(protocol.id || S.id) + ".pdf", "_blank");
      return;
    }
    var lines = [
      "\u041f\u0420\u0423\u0424 \u00b7 \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043f\u043e\u043d\u0438\u043c\u0430\u043d\u0438\u044f",
      "\u041a\u0430\u043d\u0434\u0438\u0434\u0430\u0442: " + ((protocol.candidate || {}).name || ""),
      "\u0417\u0430\u0434\u0430\u0447\u0430: " + ((protocol.task || {}).title || ""),
      "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c: " + protocol.control_pct + " % \u00b7 \u043f\u043e\u0440\u043e\u0433 " + protocol.pass_threshold_pct + " %",
      "\u0412\u0435\u0440\u0434\u0438\u043a\u0442: " + ((protocol.verdict || {}).label || ""),
      "\u041c\u0443\u0442\u0430\u0446\u0438\u0438: " + (protocol.mutation || {}).total + ", \u0442\u0435\u0441\u0442\u044b \u043b\u043e\u0432\u044f\u0442 " + (protocol.mutation || {}).score_pct + " %",
      ""
    ];
    (protocol.skills || []).forEach(function (row) {
      lines.push("\u2022 " + (row.title || row.skill) + ": " + (row.label || "") + " (" + row.correct + "/" + row.total + ")");
    });
    lines.push("");
    (protocol.risks || []).forEach(function (risk) { lines.push("! " + risk.title + " \u2014 " + risk.detail); });
    var blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    var link = el("a", { href: URL.createObjectURL(blob), download: "pruf-protocol.txt" });
    document.body.appendChild(link); link.click(); link.remove();
    P.toast("\u0412 \u0434\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c\u0435 \u0432\u044b\u0433\u0440\u0443\u0436\u0430\u0435\u0442\u0441\u044f \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u0430\u044f \u0432\u0435\u0440\u0441\u0438\u044f. PDF \u0441\u043e\u0431\u0438\u0440\u0430\u0435\u0442 \u0434\u0432\u0438\u0436\u043e\u043a.", "", 5200);
  }

  function sendProtocol(protocol) {
    if (protocol.__demo) {
      P.toast("\u0414\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c: \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u0432 HR \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \u043f\u0440\u0438 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043d\u043e\u043c \u0434\u0432\u0438\u0436\u043a\u0435 (\u0432\u0435\u0431\u0445\u0443\u043a).", "warn", 5200);
      return;
    }
    P.post("/api/protocol/" + encodeURIComponent(protocol.id) + "/send", { channel: "webhook" })
      .then(function () { P.toast("\u041f\u0440\u043e\u0442\u043e\u043a\u043e\u043b \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u0440\u0430\u0431\u043e\u0442\u043e\u0434\u0430\u0442\u0435\u043b\u044e", "ok"); })
      .catch(function (error) { P.toast("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c: " + error.message, "bad"); });
  }

  function finish() {
    if (S.finished) return;
    S.finished = true;
    if (S.demo) { renderProtocol(buildDemoProtocol()); return; }
    P.engine.finish(S.id).then(function (payload) {
      var protocol = pick(payload, ["protocol"], payload);
      renderProtocol(protocol || buildDemoProtocol());
    }).catch(function (error) {
      P.toast("\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435 \u0432\u044b\u0434\u0430\u043b \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b: " + error.message, "bad", 5000);
      renderProtocol(buildDemoProtocol());
    });
  }

  /* ---------- старт ---------- */
  function startDemo() {
    S.demo = true;
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem("pruf.demoSession") || "null"); } catch (error) { saved = null; }
    var promise = (saved && saved.analysis)
      ? Promise.resolve({ analysis: saved.analysis, meta: saved.meta || {} })
      : P.demoData().then(function (data) { return { analysis: data.analysis, meta: { candidate: "\u0413\u043e\u0441\u0442\u044c", task: (data.tasks || [])[0] ? data.tasks[0].title : "" } }; });
    return promise.then(function (bundle) {
      S.analysis = bundle.analysis;
      S.meta = bundle.meta || {};
      S.questions = buildDemoQuestions(S.analysis || {});
      if (!S.questions.length) throw new Error("\u041d\u0435\u0442 \u043c\u0443\u0442\u0430\u0446\u0438\u0439 \u0434\u043b\u044f \u0432\u043e\u043f\u0440\u043e\u0441\u043e\u0432");
      var banner = $("#session-mode");
      if (banner) {
        banner.hidden = false;
        banner.innerHTML = "\u0414\u0435\u043c\u043e-\u0440\u0435\u0436\u0438\u043c: \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u0441\u043e\u0431\u0440\u0430\u043d\u044b \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435 \u0438\u0437 \u0441\u043d\u0438\u043c\u043a\u0430 \u0430\u043d\u0430\u043b\u0438\u0437\u0430. \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 <code>python3 -m engine.cli serve</code>, \u0447\u0442\u043e\u0431\u044b \u0441\u0435\u0441\u0441\u0438\u044e \u0432\u0451\u043b \u0434\u0432\u0438\u0436\u043e\u043a.";
      }
      paintQuestion();
      startTimer();
    });
  }

  function startLive(id) {
    S.id = id;
    return P.engine.sessionGet(id).then(function (session) {
      if (session.__demo) return startDemo();
      S.questions = session.questions || [];
      S.meta = session.meta || {};
      S.analysis = session.analysis || null;
      S.left = pick(session, ["seconds_left", "left_seconds"], TOTAL_SECONDS);
      paintQuestion();
      startTimer();
    });
  }

  P.ready(function () {
    if (!$("#question")) return;
    var id = param("id");
    var demo = param("demo");
    var boot = (id && !demo) ? startLive(id) : startDemo();
    boot.catch(function (error) {
      var host = $("#question");
      if (host) {
        host.innerHTML = "";
        host.appendChild(el("div", { class: "card" }, [
          el("h2", { text: "\u0421\u0435\u0441\u0441\u0438\u044e \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c" }),
          el("p", { class: "muted", text: error.message }),
          el("a", { class: "btn", href: "studio.html", text: "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u0432 \u0441\u0442\u0443\u0434\u0438\u044e \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438" })
        ]));
      }
    });
    var stop = $("#btn-finish");
    if (stop) stop.addEventListener("click", function () { finish(); });
  });
})(window);
