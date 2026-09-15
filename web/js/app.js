/* ============================================================================
   ПРУФ · общий слой фронтенда: API-клиент, подсветка кода, UI-примитивы.
   Все страницы подключают этот файл первым. Без зависимостей и без сети наружу.
   ============================================================================ */
window.PRUF = (function () {
	"use strict"

	/* --------------------------------------------------------------- строки */
	function esc(s) {
		return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
	}
	function escAttr(s) {
		return esc(s).replace(/"/g, "&quot;")
	}
	var KW = "def|class|return|if|elif|else|for|while|in|not|and|or|try|except|finally|raise|import|from|as|with|lambda|None|True|False|break|continue|pass|yield|assert|global|is|del"
	var BI = "len|int|str|float|list|dict|set|tuple|range|enumerate|sum|min|max|abs|sorted|print|round|isinstance|zip|map|filter|any|all|open|type|repr|format|split|strip"
	var RE_PY = new RegExp("(#[^\\n]*)|('[^']*'|\"[^\"]*\")|\\b(\\d+(?:\\.\\d+)?)\\b|\\b(" + KW + ")\\b|\\b(" + BI + ")\\b", "g")

	function hl(line) {
		return esc(line).replace(RE_PY, function (m, com, str, num, kw, bi) {
			if (com) return '<span class="tok-com">' + com + "</span>"
			if (str) return '<span class="tok-str">' + str + "</span>"
			if (num) return '<span class="tok-num">' + num + "</span>"
			if (kw) return '<span class="tok-kw">' + kw + "</span>"
			if (bi) return '<span class="tok-bi">' + bi + "</span>"
			return m
		})
	}

	/* рендер кода с нумерацией; hot — массив подсвеченных строк (1-based) */
	function renderCode(code, opts) {
		opts = opts || {}
		var hot = opts.hot || []
		var ok = opts.ok || []
		var pick = !!opts.pick
		var lines = String(code || "").replace(/\t/g, "    ").split("\n")
		var out = []
		for (var i = 0; i < lines.length; i++) {
			var n = i + 1
			var cls = "code-line"
			if (hot.indexOf(n) >= 0) cls += " is-hot"
			if (ok.indexOf(n) >= 0) cls += " is-ok"
			if (pick) cls += " is-pick"
			out.push('<div class="' + cls + '" data-line="' + n + '"><span class="ln">' + n + '</span><span class="lc">' + (hl(lines[i]) || " ") + "</span></div>")
		}
		return out.join("")
	}

	function renderDiff(diff) {
		var rows = String(diff || "").split("\n")
		var out = []
		for (var i = 0; i < rows.length; i++) {
			var r = rows[i]
			var cl = r.charAt(0) === "-" ? "del" : r.charAt(0) === "+" ? "add" : ""
			out.push('<span class="' + cl + '">' + esc(r) + "</span>")
		}
		return out.join("\n")
	}

	/* --------------------------------------------------------------- формат */
	function clock(sec) {
		sec = Math.max(0, Math.round(sec || 0))
		var m = Math.floor(sec / 60),
			s = sec % 60
		return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
	}
	function money(v) {
		return Math.round(v || 0)
			.toString()
			.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0") + "\u00a0\u20bd"
	}
	function dateShort(ts) {
		var d = new Date((ts || 0) * (String(ts).length > 11 ? 1 : 1000))
		if (isNaN(d.getTime())) return "\u2014"
		var p = function (x) {
			return (x < 10 ? "0" : "") + x
		}
		return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear()
	}
	function verdictClass(level) {
		if (level === "good" || level === "control") return "control"
		if (level === "medium" || level === "shaky") return "shaky"
		return "none"
	}
	function barClass(pct) {
		return pct >= 80 ? "" : pct >= 50 ? "mid" : "low"
	}

	/* ------------------------------------------------------------------ API */
	var API = "/api"
	function request(method, path, body) {
		var opts = { method: method, headers: {} }
		if (body !== undefined) {
			opts.headers["Content-Type"] = "application/json"
			opts.body = JSON.stringify(body)
		}
		return fetch(API + path, opts).then(function (r) {
			return r.text().then(function (text) {
				var data = null
				try {
					data = text ? JSON.parse(text) : null
				} catch (e) {
					data = { raw: text }
				}
				if (!r.ok) {
					var msg = (data && (data.error || data.message)) || "Ошибка " + r.status
					var err = new Error(msg)
					err.data = data
					throw err
				}
				return data
			})
		})
	}
	var api = {
		health: function () {
			return request("GET", "/health")
		},
		tasks: function () {
			return request("GET", "/tasks")
		},
		catalog: function () {
			return request("GET", "/catalog")
		},
		economics: function () {
			return request("GET", "/economics")
		},
		demo: function (task) {
			return request("GET", "/demo?task=" + encodeURIComponent(task || "orders"))
		},
		mutations: function (code, limit) {
			return request("POST", "/mutations", { code: code, limit: limit || 12 })
		},
		run: function (code, tests) {
			return request("POST", "/run", { code: code, tests: tests })
		},
		analyze: function (code, tests, limit) {
			return request("POST", "/analyze", { code: code, tests: tests, limit: limit || 12 })
		},
		sessionStart: function (payload) {
			return request("POST", "/session/start", payload)
		},
		sessionGet: function (id) {
			return request("GET", "/session/" + encodeURIComponent(id))
		},
		sessionAnswer: function (id, payload) {
			return request("POST", "/session/" + encodeURIComponent(id) + "/answer", payload)
		},
		sessionFinish: function (id) {
			return request("POST", "/session/" + encodeURIComponent(id) + "/finish", {})
		},
		protocol: function (id) {
			return request("GET", "/protocol/" + encodeURIComponent(id))
		},
		protocolSend: function (id, email) {
			return request("POST", "/protocol/" + encodeURIComponent(id) + "/send", { email: email })
		},
		candidates: function () {
			return request("GET", "/candidates")
		},
		candidate: function (id) {
			return request("GET", "/candidates/" + encodeURIComponent(id))
		},
		vacancies: function () {
			return request("GET", "/vacancies")
		},
		lead: function (payload) {
			return request("POST", "/leads", payload)
		},
	}

	/* ------------------------------------------------------------------- UI */
	function toast(msg, kind) {
		var wrap = document.querySelector(".toast-wrap")
		if (!wrap) {
			wrap = document.createElement("div")
			wrap.className = "toast-wrap"
			document.body.appendChild(wrap)
		}
		var el = document.createElement("div")
		el.className = "toast " + (kind || "")
		el.textContent = msg
		wrap.appendChild(el)
		setTimeout(function () {
			el.style.opacity = "0"
			el.style.transform = "translateY(8px)"
			setTimeout(function () {
				if (el.parentNode) el.parentNode.removeChild(el)
			}, 320)
		}, kind === "err" ? 5200 : 3200)
	}

	function copy(text) {
		if (navigator.clipboard && navigator.clipboard.writeText) {
			return navigator.clipboard.writeText(text).then(
				function () {
					toast("Скопировано в буфер", "ok")
					return true
				},
				function () {
					toast("Не удалось скопировать: " + text, "err")
					return false
				}
			)
		}
		toast(text)
		return Promise.resolve(false)
	}

	function reveal(root) {
		var nodes = (root || document).querySelectorAll(".reveal")
		if (!window.IntersectionObserver) {
			for (var i = 0; i < nodes.length; i++) nodes[i].classList.add("is-in")
			return
		}
		var io = new IntersectionObserver(
			function (entries) {
				entries.forEach(function (e) {
					if (e.isIntersecting) {
						e.target.classList.add("is-in")
						io.unobserve(e.target)
					}
				})
			},
			{ rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
		)
		for (var k = 0; k < nodes.length; k++) io.observe(nodes[k])
	}

	function countUp(el, to, suffix, ms) {
		var from = 0,
			dur = ms || 1100,
			t0 = null
		function step(ts) {
			if (!t0) t0 = ts
			var p = Math.min(1, (ts - t0) / dur)
			var val = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)))
			el.textContent = String(val) + (suffix || "")
			if (p < 1) requestAnimationFrame(step)
		}
		requestAnimationFrame(step)
	}

	function counters(root) {
		var nodes = (root || document).querySelectorAll("[data-count]")
		function run(el) {
			countUp(el, parseFloat(el.getAttribute("data-count")), el.getAttribute("data-suffix") || "")
		}
		if (!window.IntersectionObserver) {
			for (var i = 0; i < nodes.length; i++) run(nodes[i])
			return
		}
		var io = new IntersectionObserver(function (entries) {
			entries.forEach(function (e) {
				if (e.isIntersecting) {
					run(e.target)
					io.unobserve(e.target)
				}
			})
		})
		for (var k = 0; k < nodes.length; k++) io.observe(nodes[k])
	}

	function nav() {
		var bar = document.querySelector(".nav")
		if (bar) {
			var onScroll = function () {
				bar.classList.toggle("is-stuck", window.scrollY > 8)
			}
			window.addEventListener("scroll", onScroll, { passive: true })
			onScroll()
		}
		var burger = document.querySelector(".nav-burger")
		var links = document.querySelector(".nav-links")
		if (burger && links) {
			burger.addEventListener("click", function () {
				links.classList.toggle("is-open")
			})
		}
		var here = (location.pathname.split("/").pop() || "index.html").toLowerCase()
		var all = document.querySelectorAll(".nav-link")
		for (var i = 0; i < all.length; i++) {
			var href = (all[i].getAttribute("href") || "").split("?")[0].split("#")[0].toLowerCase()
			if (href && href === here) all[i].classList.add("is-active")
		}
	}

	function faq(root) {
		var items = (root || document).querySelectorAll(".faq-item")
		Array.prototype.forEach.call(items, function (item) {
			var q = item.querySelector(".faq-q")
			var a = item.querySelector(".faq-a")
			if (!q || !a) return
			q.setAttribute("aria-expanded", "false")
			q.addEventListener("click", function () {
				var open = item.classList.toggle("is-open")
				q.setAttribute("aria-expanded", open ? "true" : "false")
				a.style.maxHeight = open ? a.scrollHeight + 40 + "px" : "0px"
			})
		})
	}

	function tabs(root) {
		var groups = (root || document).querySelectorAll("[data-tabs]")
		Array.prototype.forEach.call(groups, function (group) {
			var btns = group.querySelectorAll(".tab")
			Array.prototype.forEach.call(btns, function (btn) {
				btn.addEventListener("click", function () {
					var name = btn.getAttribute("data-tab")
					Array.prototype.forEach.call(btns, function (b) {
						b.classList.toggle("is-active", b === btn)
					})
					var scope = document.querySelector(group.getAttribute("data-tabs")) || document
					var panels = scope.querySelectorAll(".tab-panel")
					Array.prototype.forEach.call(panels, function (p) {
						p.classList.toggle("is-active", p.getAttribute("data-panel") === name)
					})
				})
			})
		})
	}

	function modal(id, open) {
		var el = typeof id === "string" ? document.getElementById(id) : id
		if (!el) return
		el.classList.toggle("is-open", open !== false)
		document.body.style.overflow = open === false ? "" : "hidden"
	}
	function modalInit() {
		document.addEventListener("click", function (e) {
			var t = e.target
			if (t.matches("[data-modal-open]")) modal(t.getAttribute("data-modal-open"), true)
			if (t.matches("[data-modal-close]") || t.classList.contains("modal-bg")) {
				var host = t.closest(".modal")
				if (host) modal(host, false)
			}
		})
		document.addEventListener("keydown", function (e) {
			if (e.key === "Escape") {
				var open = document.querySelector(".modal.is-open")
				if (open) modal(open, false)
			}
		})
	}

	function tilt(root) {
		var nodes = (root || document).querySelectorAll(".card-glow")
		Array.prototype.forEach.call(nodes, function (el) {
			el.addEventListener(
				"pointermove",
				function (e) {
					var r = el.getBoundingClientRect()
					el.style.setProperty("--mx", ((e.clientX - r.left) / r.width) * 100 + "%")
					el.style.setProperty("--my", ((e.clientY - r.top) / r.height) * 100 + "%")
				},
				{ passive: true }
			)
		})
	}

	/* --------------------------------------------------------------- хранилка */
	var KEY = "pruf.sessions.v1"
	var store = {
		list: function () {
			try {
				return JSON.parse(localStorage.getItem(KEY) || "[]")
			} catch (e) {
				return []
			}
		},
		save: function (item) {
			var all = store.list().filter(function (x) {
				return x.id !== item.id
			})
			all.unshift(item)
			try {
				localStorage.setItem(KEY, JSON.stringify(all.slice(0, 30)))
			} catch (e) {}
			return all
		},
		clear: function () {
			try {
				localStorage.removeItem(KEY)
			} catch (e) {}
		},
	}

	function qs(name, def) {
		var m = new RegExp("[?&]" + name + "=([^&]*)").exec(location.search)
		return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : def
	}

	function gauge(el, pct) {
		var circle = el.querySelector(".gauge-fg")
		var num = el.querySelector(".gauge-val b")
		var r = 62
		var c = 2 * Math.PI * r
		if (circle) {
			circle.setAttribute("stroke-dasharray", c.toFixed(1))
			circle.setAttribute("stroke-dashoffset", c.toFixed(1))
			circle.style.stroke = pct >= 80 ? "var(--teal)" : pct >= 50 ? "var(--amber)" : "var(--red)"
			setTimeout(function () {
				circle.setAttribute("stroke-dashoffset", (c * (1 - pct / 100)).toFixed(1))
			}, 60)
		}
		if (num) countUp(num, pct, "\u2009%")
	}

	function boot() {
		nav()
		reveal()
		counters()
		faq()
		tabs()
		modalInit()
		tilt()
	}
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot)
	else boot()

	return {
		api: api,
		esc: esc,
		escAttr: escAttr,
		hl: hl,
		renderCode: renderCode,
		renderDiff: renderDiff,
		clock: clock,
		money: money,
		dateShort: dateShort,
		verdictClass: verdictClass,
		barClass: barClass,
		toast: toast,
		copy: copy,
		reveal: reveal,
		counters: counters,
		countUp: countUp,
		faq: faq,
		tabs: tabs,
		modal: modal,
		tilt: tilt,
		store: store,
		qs: qs,
		gauge: gauge,
	}
})()
