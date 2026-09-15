/* ============================================================================
   Кабинет кандидата: свой протокол, карта пробелов, история и отправка.
   ============================================================================ */
(function () {
	"use strict"
	var P = window.PRUF
	var LS_SESSIONS = "pruf.candidate.sessions"

	var S = { rows: [], bundle: null, id: "" }

	function $(id) {
		return document.getElementById(id)
	}
	function esc(value) {
		return P.esc(value === undefined || value === null ? "" : String(value))
	}
	function bar(pct) {
		return '<div class="cab-bar ' + P.barClass(pct) + '"><i style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></div>'
	}
	function stat(value, label) {
		return '<div class="stat"><div class="stat-num">' + esc(value) + '</div><div class="stat-label">' + esc(label) + "</div></div>"
	}
	function localSessions() {
		try {
			var raw = localStorage.getItem(LS_SESSIONS)
			var parsed = raw ? JSON.parse(raw) : []
			return Array.isArray(parsed) ? parsed : []
		} catch (e) {
			return []
		}
	}

	function render(bundle) {
		S.bundle = bundle
		var candidate = bundle.candidate || {}
		var protocol = bundle.protocol || {}
		var verdict = protocol.verdict || {}
		var mutation = protocol.mutation || {}
		var questions = protocol.questions || {}

		$("kpi").innerHTML =
			stat(protocol.control_pct + " %", "контроль понимания") +
			stat(mutation.total, "мутаций в сессии") +
			stat(questions.correct + " / " + questions.total, "верных ответов") +
			stat(mutation.score_pct + " %", "мутационный счёт тестов") +
			stat(protocol.duration_clock || "—", "длительность защиты")

		P.gauge($("gauge"), Number(protocol.control_pct || 0))
		var verdictEl = $("verdict")
		verdictEl.className = "center small mt-16 mb-0 " + P.verdictClass(verdict.level)
		verdictEl.textContent = verdict.label || "—"
		$("threshold").textContent =
			"порог допуска " + protocol.pass_threshold_pct + " % · " + (protocol.passed ? "пройден" : "не пройден")

		$("skillsMeta").textContent = (protocol.skills || []).length + " навыков"
		$("skills").innerHTML =
			(protocol.skills || [])
				.map(function (skill) {
					return (
						'<div class="cab-skill"><b>' +
						esc(skill.title) +
						'</b><span class="' +
						P.verdictClass(skill.verdict) +
						' tiny">' +
						esc(skill.verdict_label) +
						'</span><span class="cab-sub">' +
						esc(skill.correct) +
						" из " +
						esc(skill.questions) +
						" · " +
						esc(skill.score_pct) +
						" %</span>" +
						bar(skill.score_pct) +
						"</div>"
					)
				})
				.join("") || '<p class="cab-empty mb-0">Нет данных</p>'

		$("risks").innerHTML =
			(protocol.risks || [])
				.map(function (risk) {
					return (
						'<div class="cab-risk' +
						(String(risk.kind).indexOf("дыра") >= 0 ? " is-gap" : "") +
						'"><span class="chip chip-amber">' +
						esc(risk.kind) +
						'</span> <span class="mono tiny dim">' +
						esc(risk.mutation) +
						" · строка " +
						esc(risk.line) +
						'</span><p class="small mb-0" style="margin-top:6px">' +
						esc(risk.text) +
						'</p><p class="tiny dim mb-0">' +
						esc(risk.action) +
						"</p></div>"
					)
				})
				.join("") || '<p class="cab-empty mb-0">Пробелов не найдено — все мутации разобраны.</p>'

		var timeline = protocol.timeline || []
		$("tlMeta").textContent = timeline.length + " вопросов"
		$("timeline").innerHTML =
			timeline
				.map(function (item) {
					return (
						'<div class="cab-tl-item"><span class="cab-tl-dot' +
						(item.correct ? "" : " is-miss") +
						'"></span><span><span class="mono tiny dim">' +
						esc(item.mutation) +
						"</span> " +
						esc(item.title) +
						' <span class="cab-sub">· ' +
						esc(item.result) +
						"</span></span>" +
						'<span class="cab-tl-time">' +
						esc(item.clock) +
						"</span></div>"
					)
				})
				.join("") || '<p class="cab-empty mb-0">Сессия ещё не проводилась</p>'

		$("meta").innerHTML =
			"<dt>Задача</dt><dd>" +
			esc((protocol.task || {}).title || candidate.task) +
			"</dd><dt>Язык</dt><dd>" +
			esc((protocol.task || {}).language || "Python") +
			"</dd><dt>Строк кода</dt><dd>" +
			esc((protocol.task || {}).lines) +
			"</dd><dt>Мутации</dt><dd>" +
			esc(mutation.total + " · выжило " + mutation.survived) +
			"</dd><dt>Отпечаток</dt><dd>" +
			esc(protocol.fingerprint) +
			"</dd><dt>Протокол</dt><dd>" +
			esc(protocol.id) +
			"</dd>"

		var quote = (protocol.quotes || [])[0]
		var diff = quote && (quote.diff || quote.patch)
		if (diff) $("quote").innerHTML = P.renderDiff(diff)
		else {
			var risk = (protocol.risks || [])[0]
			$("quote").textContent = risk
				? risk.mutation + " · строка " + risk.line + "\n" + risk.text
				: "Выживших мутаций нет — набор тестов плотный."
		}

		renderHistory()
	}

	function renderHistory() {
		var local = localSessions()
		var rows = local
			.map(function (item) {
				return (
					'<div class="cab-tl-item"><span class="cab-tl-dot"></span><span><b>' +
					esc(item.task || "Своё решение") +
					'</b> <span class="cab-sub">· контроль ' +
					esc(item.control_pct) +
					' %</span></span><span class="cab-tl-time">' +
					esc(item.date || "") +
					"</span></div>"
				)
			})
			.join("")
		var demo = S.rows
			.map(function (row) {
				return (
					'<div class="cab-tl-item"><span class="cab-tl-dot' +
					(row.passed ? "" : " is-miss") +
					'"></span><span><button class="btn btn-quiet btn-sm" type="button" data-open="' +
					P.escAttr(row.id) +
					'">' +
					esc(row.name) +
					'</button> <span class="cab-sub">· ' +
					esc(row.task) +
					" · контроль " +
					esc(row.control_pct) +
					' %</span></span><span class="cab-tl-time">' +
					esc(row.submitted) +
					"</span></div>"
				)
			})
			.join("")
		$("history").innerHTML =
			'<div class="cab-tl">' +
			(rows || '<div class="cab-tl-item"><span class="cab-tl-dot is-miss"></span><span class="cab-sub">В этом браузере вы ещё не проходили сессию — начните со студии.</span><span></span></div>') +
			demo +
			"</div>"
	}

	function load(id) {
		S.id = id
		$("skills").innerHTML = '<p class="cab-empty mb-0">Грузим протокол…</p>'
		P.api
			.candidate(id)
			.then(render)
			.catch(function (error) {
				$("skills").innerHTML = '<p class="cab-empty mb-0">' + esc(error.message) + "</p>"
			})
	}

	function bind() {
		$("whoSelect").addEventListener("change", function (event) {
			load(event.target.value)
		})
		$("btnPdf").addEventListener("click", function () {
			if (!S.bundle) return
			window.open("/api/protocol/" + encodeURIComponent(S.bundle.protocol.id) + ".pdf", "_blank")
		})
		$("btnShare").addEventListener("click", function () {
			P.copy(location.origin + "/candidate.html?id=" + encodeURIComponent(S.id))
		})
		$("btnSend").addEventListener("click", function () {
			if (!S.bundle) return
			P.api
				.protocolSend(S.bundle.protocol.id, $("sendEmail").value.trim())
				.then(function (data) {
					P.modal("modal-send", false)
					P.toast(data.message || "Протокол в очереди", "ok")
				})
				.catch(function (error) {
					P.toast(error.message, "err")
				})
		})
		document.addEventListener("click", function (event) {
			var open = event.target.closest("[data-open]")
			if (!open) return
			var id = open.getAttribute("data-open")
			$("whoSelect").value = id
			load(id)
			window.scrollTo({ top: 0, behavior: "smooth" })
		})
	}

	function boot() {
		bind()
		P.api
			.candidates()
			.then(function (data) {
				S.rows = data.candidates || []
				$("whoSelect").innerHTML = S.rows
					.map(function (row) {
						return '<option value="' + P.escAttr(row.id) + '">' + esc(row.name + " · " + row.vacancy) + "</option>"
					})
					.join("")
				var wanted = P.qs("id", "")
				var row = S.rows.filter(function (item) {
					return item.id === wanted
				})[0] || S.rows[0]
				if (!row) return
				$("whoSelect").value = row.id
				load(row.id)
			})
			.catch(function (error) {
				$("skills").innerHTML = '<p class="cab-empty mb-0">' + esc(error.message) + "</p>"
			})
	}

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot)
	else boot()
})()
