/*
 * ПРУФ · web/js/app.js
 * Ядро фронтенда: клиент API, офлайн-режим, 3D-сцена, анимации и UI-хелперы.
 * Без сборки, без CDN, без внешних зависимостей — работает и в закрытом контуре.
 */
(function (global) {
  "use strict";

  var state = { live: null, demo: null, checking: null };

  /* ---------- утилиты ---------- */
  function $(selector, scope) { return (scope || document).querySelector(selector); }
  function $$(selector, scope) { return Array.prototype.slice.call((scope || document).querySelectorAll(selector)); }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "class") node.className = attrs[key];
      else if (key === "html") node.innerHTML = attrs[key];
      else if (key === "text") node.textContent = attrs[key];
      else if (key.slice(0, 2) === "on" && typeof attrs[key] === "function") node.addEventListener(key.slice(2), attrs[key]);
      else if (attrs[key] !== null && attrs[key] !== undefined) node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function clock(seconds) {
    var total = Math.max(0, Math.round(seconds || 0));
    var minutes = Math.floor(total / 60);
    var rest = total % 60;
    return (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function money(value) {
    return new Intl.NumberFormat("ru-RU").format(Math.round(value || 0)) + " \u20bd";
  }

  function levelClass(level) {
    if (level === "good") return "badge--ok";
    if (level === "medium") return "badge--accent";
    if (level === "low") return "badge--warn";
    return "badge--bad";
  }

  /* ---------- тосты ---------- */
  function toast(message, kind, ms) {
    var host = $(".toasts");
    if (!host) {
      host = el("div", { class: "toasts" });
      document.body.appendChild(host);
    }
    var node = el("div", { class: "toast " + (kind || ""), text: message });
    host.appendChild(node);
    setTimeout(function () {
      node.style.transition = "opacity .3s, transform .3s";
      node.style.opacity = "0";
      node.style.transform = "translateX(20px)";
      setTimeout(function () { node.remove(); }, 320);
    }, ms || 3600);
  }

  /* ---------- сетевой слой ---------- */
  function request(path, options) {
    var config = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    return fetch(path, config).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          var error = new Error(payload.error || ("\u041e\u0448\u0438\u0431\u043a\u0430 " + response.status));
          error.status = response.status;
          error.payload = payload;
          throw error;
        }
        return payload;
      });
    });
  }

  function get(path) { return request(path, { method: "GET" }); }
  function post(path, body) { return request(path, { method: "POST", body: JSON.stringify(body || {}) }); }

  function checkEngine() {
    if (state.live !== null) return Promise.resolve(state.live);
    if (state.checking) return state.checking;
    state.checking = get("/api/health")
      .then(function (payload) { state.live = !!payload.ok; state.health = payload; return state.live; })
      .catch(function () { state.live = false; return false; });
    return state.checking;
  }

  function demoData() {
    if (state.demo) return Promise.resolve(state.demo);
    return fetch("data/demo.json").then(function (response) { return response.json(); })
      .then(function (payload) { state.demo = payload; return payload; })
      .catch(function () { return {}; });
  }

  /* Выполняет запрос к движку; если сервер не поднят — отдаёт честный демо-снимок. */
  function call(path, body, demoPicker) {
    return checkEngine().then(function (live) {
      if (live) {
        var promise = body === undefined ? get(path) : post(path, body);
        return promise.then(function (payload) { payload.__demo = false; return payload; });
      }
      return demoData().then(function (data) {
        var payload = typeof demoPicker === "function" ? demoPicker(data) : demoPicker;
        if (!payload) throw new Error("\u0414\u0432\u0438\u0436\u043e\u043a \u043d\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d, \u0430 \u0434\u0435\u043c\u043e-\u0441\u043d\u0438\u043c\u043a\u0430 \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043d\u0435\u0442");
        var copy = JSON.parse(JSON.stringify(payload));
        copy.__demo = true;
        return copy;
      });
    });
  }

  var engine = {
    health: checkEngine,
    isLive: function () { return state.live === true; },
    tasks: function () { return call("/api/tasks", undefined, function (d) { return { tasks: d.tasks || [], vacancies: d.vacancies || [] }; }); },
    catalog: function () { return call("/api/catalog", undefined, function (d) { return d.catalog; }); },
    economics: function () { return call("/api/economics", undefined, function (d) { return d.economics; }); },
    mutate: function (code, limit) { return call("/api/mutations", { code: code, limit: limit }, function (d) { return d.analysis; }); },
    run: function (code, tests) { return call("/api/run", { code: code, tests: tests }, function (d) { return d.run; }); },
    analyze: function (code, tests, limit) { return call("/api/analyze", { code: code, tests: tests, limit: limit }, function (d) { return d.analysis; }); },
    sessionStart: function (payload) { return call("/api/session/start", payload, function (d) { return d.session; }); },
    sessionGet: function (id) { return call("/api/session/" + id, undefined, function (d) { return d.session; }); },
    answer: function (id, question, option, seconds) {
      return call("/api/session/" + id + "/answer", { question: question, option: option, seconds: seconds }, null);
    },
    finish: function (id) { return call("/api/session/" + id + "/finish", {}, function (d) { return { protocol: d.protocol }; }); },
    candidates: function () { return call("/api/candidates", undefined, function (d) { return d.candidates_page; }); },
    candidate: function (id) {
      return call("/api/candidates/" + id, undefined, function (d) {
        var rows = (d.candidates_page && d.candidates_page.candidates) || [];
        var row = rows.filter(function (item) { return item.id === id; })[0];
        if (!row) return null;
        return { candidate: row, summary: row, protocol: d.protocol, analysis: d.analysis };
      });
    },
    protocol: function (id) { return call("/api/protocol/" + id, undefined, function (d) { return d.protocol; }); },
    lead: function (payload) {
      return call("/api/leads", payload, { ok: true, message: "\u0414\u0432\u0438\u0436\u043e\u043a \u043d\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d: \u0437\u0430\u044f\u0432\u043a\u0430 \u043d\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430, \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0441\u0435\u0440\u0432\u0435\u0440." });
    },
    demoBundle: function (taskId) {
      return call("/api/demo?task=" + encodeURIComponent(taskId || "orders"), undefined, function (d) { return d.demo; });
    }
  };

  /* ---------- статус движка в шапке ---------- */
  function paintEngineBadges() {
    var nodes = $$("[data-engine-badge]");
    if (!nodes.length) return;
    nodes.forEach(function (node) {
      node.classList.add("enginebar");
      node.innerHTML = '<span class="dot"></span><span>\u041f\u0440\u043e\u0432\u0435\u0440\u044f\u0435\u043c \u0434\u0432\u0438\u0436\u043e\u043a\u2026</span>';
    });
    checkEngine().then(function (live) {
      nodes.forEach(function (node) {
        node.classList.toggle("is-live", live);
        node.classList.toggle("is-demo", !live);
        node.innerHTML = live
          ? '<span class="dot"></span><span>\u0414\u0432\u0438\u0436\u043e\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d \u00b7 \u0438\u0437\u043e\u043b\u044f\u0442\u043e\u0440 \u0430\u043a\u0442\u0438\u0432\u0435\u043d</span>'
          : '<span class="dot"></span><span>\u0414\u0435\u043c\u043e-\u0441\u043d\u0438\u043c\u043e\u043a \u00b7 \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 <code>python3 -m engine.cli serve</code>, \u0447\u0442\u043e\u0431\u044b \u0441\u0447\u0438\u0442\u0430\u0442\u044c \u0432\u0430\u0448 \u043a\u043e\u0434</span>';
      });
    });
  }

  /* ---------- появление и наклон карточек ---------- */
  function initReveal() {
    var nodes = $$(".reveal");
    if (!nodes.length) return;
    if (!("IntersectionObserver" in global)) {
      nodes.forEach(function (node) { node.classList.add("is-visible"); });
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -60px" });
    nodes.forEach(function (node) { observer.observe(node); });
  }

  function initTilt() {
    if (global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    $$(".card--tilt").forEach(function (card) {
      card.addEventListener("mousemove", function (event) {
        var box = card.getBoundingClientRect();
        var px = (event.clientX - box.left) / box.width - 0.5;
        var py = (event.clientY - box.top) / box.height - 0.5;
        card.style.transform = "perspective(900px) rotateX(" + (-py * 7).toFixed(2) + "deg) rotateY(" + (px * 9).toFixed(2) + "deg) translateY(-6px)";
      });
      card.addEventListener("mouseleave", function () { card.style.transform = ""; });
    });
  }

  function initCounters() {
    $$("[data-count]").forEach(function (node) {
      var target = parseFloat(node.getAttribute("data-count"));
      var suffix = node.getAttribute("data-suffix") || "";
      var started = false;
      function run() {
        if (started) return;
        started = true;
        var start = performance.now();
        var duration = 1100;
        function frame(now) {
          var progress = Math.min(1, (now - start) / duration);
          var eased = 1 - Math.pow(1 - progress, 3);
          var value = target * eased;
          node.textContent = (target % 1 === 0 ? Math.round(value) : value.toFixed(1)) + suffix;
          if (progress < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
      }
      if ("IntersectionObserver" in global) {
        var observer = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) { if (entry.isIntersecting) { run(); observer.disconnect(); } });
        }, { threshold: 0.4 });
        observer.observe(node);
      } else { run(); }
    });
  }

  function initFaq() {
    $$(".faq__q").forEach(function (button) {
      button.addEventListener("click", function () {
        var item = button.closest(".faq");
        var open = item.classList.contains("is-open");
        $$(".faq").forEach(function (other) { other.classList.remove("is-open"); });
        if (!open) item.classList.add("is-open");
      });
    });
  }

  function initModals() {
    $$("[data-modal-open]").forEach(function (trigger) {
      trigger.addEventListener("click", function () { openModal(trigger.getAttribute("data-modal-open")); });
    });
    $$("[data-modal-close]").forEach(function (trigger) {
      trigger.addEventListener("click", function () { closeModal(trigger.closest(".modal")); });
    });
    $$(".modal__backdrop").forEach(function (backdrop) {
      backdrop.addEventListener("click", function () { closeModal(backdrop.closest(".modal")); });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") $$(".modal.is-open").forEach(closeModal);
    });
  }

  function openModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.add("is-open");
    var field = modal.querySelector("input, textarea, select");
    if (field) setTimeout(function () { field.focus(); }, 60);
  }

  function closeModal(modal) {
    if (modal) modal.classList.remove("is-open");
  }

  function initLeadForms() {
    $$("[data-lead-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var data = new FormData(form);
        var button = form.querySelector("button[type=submit]");
        if (button) { button.disabled = true; button.dataset.label = button.textContent; button.textContent = "\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u044f\u0435\u043c\u2026"; }
        engine.lead({
          name: data.get("name"), email: data.get("email"),
          company: data.get("company"), plan: data.get("plan"), comment: data.get("comment")
        }).then(function (result) {
          toast(result.__demo ? result.message : "\u0417\u0430\u044f\u0432\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430. \u041c\u044b \u0441\u0432\u044f\u0436\u0435\u043c\u0441\u044f \u0432 \u0442\u0435\u0447\u0435\u043d\u0438\u0435 \u0434\u043d\u044f.", result.__demo ? "" : "ok", 5000);
          form.reset();
          closeModal(form.closest(".modal"));
        }).catch(function (error) {
          toast(error.message, "bad", 5000);
        }).then(function () {
          if (button) { button.disabled = false; button.textContent = button.dataset.label; }
        });
      });
    });
  }

  function initNav() {
    var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    $$(".nav__links a").forEach(function (link) {
      var target = (link.getAttribute("href") || "").split("#")[0].toLowerCase();
      if (target && target === here) link.classList.add("is-active");
    });
  }

  /* ---------- 3D-сцена на canvas (без библиотек) ---------- */
  function scene(canvas) {
    if (!canvas || !canvas.getContext) return null;
    var ctx = canvas.getContext("2d");
    if (!ctx) return null;
    var reduced = global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var phi = (1 + Math.sqrt(5)) / 2;
    var base = [
      [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
      [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
      [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1]
    ];
    var faces = [
      [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
      [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
      [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
      [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
    ];
    var edges = [];
    faces.forEach(function (face) {
      [[face[0], face[1]], [face[1], face[2]], [face[2], face[0]]].forEach(function (pair) {
        var key = pair.slice().sort(function (a, b) { return a - b; }).join("-");
        if (edges.indexOf(key) === -1) edges.push(key);
      });
    });
    edges = edges.map(function (key) { return key.split("-").map(Number); });

    var particles = [];
    for (var i = 0; i < 46; i += 1) {
      var theta = Math.random() * Math.PI * 2;
      var psi = Math.acos(2 * Math.random() - 1);
      var radius = 2.35 + Math.random() * 1.5;
      particles.push({
        x: radius * Math.sin(psi) * Math.cos(theta),
        y: radius * Math.sin(psi) * Math.sin(theta),
        z: radius * Math.cos(psi),
        speed: 0.12 + Math.random() * 0.5,
        size: 0.8 + Math.random() * 1.9
      });
    }

    var mouse = { x: 0, y: 0 };
    var width = 0, height = 0, dpr = Math.min(global.devicePixelRatio || 1, 2);

    function resize() {
      var box = canvas.getBoundingClientRect();
      width = Math.max(240, box.width);
      height = Math.max(240, box.height || box.width);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function rotate(point, ax, ay) {
      var cosY = Math.cos(ay), sinY = Math.sin(ay);
      var x = point[0] * cosY - point[2] * sinY;
      var z = point[0] * sinY + point[2] * cosY;
      var cosX = Math.cos(ax), sinX = Math.sin(ax);
      var y = point[1] * cosX - z * sinX;
      z = point[1] * sinX + z * cosX;
      return [x, y, z];
    }

    function project(point) {
      var distance = 6.2;
      var scale = Math.min(width, height) * 0.19 * (distance / (distance - point[2]));
      return { x: width / 2 + point[0] * scale, y: height / 2 + point[1] * scale, depth: point[2] };
    }

    var start = performance.now();
    var raf = null;

    function frame(now) {
      var time = (now - start) / 1000;
      var ax = -0.35 + mouse.y * 0.5 + Math.sin(time * 0.24) * 0.14;
      var ay = time * (reduced ? 0.04 : 0.24) + mouse.x * 0.7;
      ctx.clearRect(0, 0, width, height);

      var points = base.map(function (vertex) { return project(rotate(vertex, ax, ay)); });

      // частицы
      particles.forEach(function (particle) {
        var spun = rotate([particle.x, particle.y, particle.z], ax, ay * particle.speed + time * 0.1);
        var flat = project(spun);
        var alpha = 0.12 + Math.max(0, (flat.depth + 3) / 7) * 0.5;
        ctx.beginPath();
        ctx.fillStyle = "rgba(167, 139, 250, " + alpha.toFixed(3) + ")";
        ctx.arc(flat.x, flat.y, particle.size, 0, Math.PI * 2);
        ctx.fill();
      });

      // рёбра
      edges.forEach(function (edge) {
        var a = points[edge[0]], b = points[edge[1]];
        var depth = (a.depth + b.depth) / 2;
        var alpha = 0.16 + Math.max(0, (depth + 2) / 4.4) * 0.6;
        ctx.beginPath();
        ctx.strokeStyle = "rgba(110, 231, 255, " + alpha.toFixed(3) + ")";
        ctx.lineWidth = depth > 0 ? 1.5 : 0.8;
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });

      // узлы-мутации
      points.forEach(function (point, index) {
        var pulse = 0.5 + 0.5 * Math.sin(time * 1.7 + index);
        var killed = index % 3 !== 0;
        var radius = 2.4 + pulse * 2.2 + (point.depth + 2) * 0.5;
        ctx.beginPath();
        ctx.fillStyle = killed
          ? "rgba(52, 211, 153, " + (0.32 + pulse * 0.45).toFixed(3) + ")"
          : "rgba(251, 113, 133, " + (0.36 + pulse * 0.5).toFixed(3) + ")";
        ctx.arc(point.x, point.y, Math.max(1.4, radius), 0, Math.PI * 2);
        ctx.fill();
      });

      // ядро
      var glow = ctx.createRadialGradient(width / 2, height / 2, 2, width / 2, height / 2, Math.min(width, height) * 0.3);
      glow.addColorStop(0, "rgba(110, 231, 255, 0.5)");
      glow.addColorStop(1, "rgba(110, 231, 255, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(width / 2, height / 2, Math.min(width, height) * 0.3, 0, Math.PI * 2);
      ctx.fill();

      raf = requestAnimationFrame(frame);
    }

    resize();
    global.addEventListener("resize", resize);
    global.addEventListener("mousemove", function (event) {
      mouse.x = (event.clientX / global.innerWidth - 0.5) * 0.6;
      mouse.y = (event.clientY / global.innerHeight - 0.5) * 0.6;
    });
    raf = requestAnimationFrame(frame);
    return { stop: function () { if (raf) cancelAnimationFrame(raf); } };
  }

  function initScene() {
    var canvas = $("[data-scene]");
    if (!canvas) return;
    var running = scene(canvas);
    var fallback = $(".scene__fallback");
    if (running && fallback) fallback.style.display = "none";
  }

  function ready(callback) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", callback);
    else callback();
  }

  ready(function () {
    initNav();
    initReveal();
    initTilt();
    initCounters();
    initFaq();
    initModals();
    initLeadForms();
    initScene();
    paintEngineBadges();
  });

  global.PRUF = {
    $: $, $$: $$, el: el, escapeHtml: escapeHtml, clock: clock, money: money, levelClass: levelClass,
    toast: toast, openModal: openModal, closeModal: closeModal, ready: ready,
    get: get, post: post, engine: engine, scene: scene, demoData: demoData,
    initReveal: initReveal, initTilt: initTilt
  };
})(window);
