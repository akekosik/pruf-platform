/* Сессия защиты: таймер, вопросы из строк решения, протокол понимания. */
(function () {
	"use strict"
	var P = window.PRUF
	var S = { id: null, sess: null, qs: [], idx: 0, picked: null, correct: 0, left: 900, tick: null, qAt: 0, proto: null, busy: false }

	var TYPES = {
		danger: "Опасная правка",
		gap: "Дыра в тестах",
		first_failure: "Первый падающий тест",
		consequence: "Последствие правки",
	}

	function $(id) {
		return document.getElementById(id)
	}
	function show(id, on) {
		var el = $(id)
		if (el) el.classList.toggle("hidden", !on)
	}
	function overlay(id, on) {
		var el = $(id)
		if (el) el.classList.toggle("is-open", !!on)
	}

	/* --------------------------------------------------------------- таймер */
	function paintTimer() {
		var el = $("timer")
		el.textContent = P.clock(Math.max(0, S.left))
		el.classList.toggle("is-warn", S.left <= 300 && S.left > 60)
		el.classList.toggle("is-danger", S.left <= 60)
	}

	function startTimer() {
		stopTimer()
		paintTimer()
		S.tick = setInterval(function () {
			S.left -= 1
			paintTimer()
			if (S.left <= 0) {
				stopTimer()
				$("ovTimeStat").textContent = "Отвечено " + S.idx + " из " + S.qs.length + " вопросов. Протокол считается по фактическим ответам."
				overlay("ovTime", true)
			}
		}, 1000)
	}

	function stopTimer() {
		if (S.tick) clearInterval(S.tick)
		S.tick = null
	}

	/* --------------------------------------------------------------- вопрос */
	function paintStats() {
		var sum = (S.sess && S.sess.summary) || {}
		$("stMut").textContent = sum.mutation_total != null ? String(sum.mutation_total) : "\u2014"
		$("stSurvived").textContent = sum.survived != null ? String(sum.survived) : "\u2014"
		$("stScore").textContent = sum.mutation_score_pct != null ? sum.mutation_score_pct + " %" : "\u2014"
		$("stCorrect").textContent = S.correct + " из " + S.idx
	}

	function paintProgress() {
		var total = S.qs.length || 1
		$("progressBar").style.width = Math.round((S.idx / total) * 100) + "%"
		$("qCounter").textContent = Math.min(S.idx + 1, total) + " / " + total
	}

	function renderQuestion() {
		var q = S.qs[S.idx]
		if (!q) return finish()
		S.picked = null
		S.qAt = Date.now()
		$("qType").textContent = TYPES[q.type] || "Вопрос"
		$("qWeight").textContent = "вес " + q.weight
		$("qTitle").textContent = q.title
		$("qPrompt").textContent = q.prompt
		$("qSkill").textContent = q.skill_title || ""
		$("qHint").textContent = q.hint || ""
		$("qHint").classList.add("hidden")
		$("qDiff").innerHTML = P.renderDiff(q.mutation.diff)
		$("sessCode").innerHTML = P.renderCode(S.sess.code, { hot: q.mutation.line })
		var hot = document.querySelector("#sessCode .code-line.is-hot")
		if (hot && hot.scrollIntoView) hot.scrollIntoView({ block: "center" })

		var out = []
		for (var i = 0; i < q.options.length; i++) {
			var o = q.options[i]
			var body = o.kind === "diff" ? '<pre class="diff mb-0">' + P.renderDiff(o.label) + "</pre>" : "<span>" + P.esc(o.label) + "</span>"
			out.push('<button type="button" class="q-option" data-id="' + P.escAttr(o.id) + '"><span class="key">' + P.esc(o.id) + "</span>" + body + "</button>")
		}
		$("qOptions").innerHTML = out.join("")
		show("qFeedback", false)
		$("btnAnswer").disabled = true
		$("btnAnswer").classList.remove("hidden")
		$("btnNext").classList.add("hidden")
		paintProgress()
		paintStats()
	}

	function pick(id) {
		S.picked = id
		var rows = document.querySelectorAll("#qOptions .q-option")
		for (var i = 0; i < rows.length; i++) rows[i].classList.toggle("is-selected", rows[i].getAttribute("data-id") === id)
		$("btnAnswer").disabled = false
	}

	function answer() {
		if (!S.picked || S.busy) return
		var q = S.qs[S.idx]
		S.busy = true
		$("btnAnswer").disabled = true
		P.api
			.sessionAnswer(S.id, { question_id: q.id, option_id: S.picked, seconds: Math.round((Date.now() - S.qAt) / 1000) })
			.then(function (r) {
				var a = r.answer || {}
				S.sess = r.session || S.sess
				if (a.correct) S.correct += 1
				var right = a.correct_options || []
				var rows = document.querySelectorAll("#qOptions .q-option")
				for (var i = 0; i < rows.length; i++) {
					var id = rows[i].getAttribute("data-id")
					var isRight = right.indexOf(id) >= 0
					rows[i].classList.toggle("is-correct", isRight)
					rows[i].classList.toggle("is-wrong", id === S.picked && !isRight)
					rows[i].disabled = true
				}
				$("fbTitle").textContent = a.correct ? "Верно — эту строку вы контролируете" : "Мимо — правка прошла незамеченной"
				$("fbChip").className = "verdict " + (a.correct ? "control" : "none")
				$("fbChip").textContent = a.correct ? "верно" : "ошибка"
				$("fbText").textContent = a.explanation || ""
				$("fbSuggestion").textContent = a.suggestion || ""
				show("qFeedback", true)
				$("btnAnswer").classList.add("hidden")
				var last = S.idx >= S.qs.length - 1
				$("btnNext").textContent = last ? "Завершить и получить протокол" : "Следующий вопрос"
				$("btnNext").classList.remove("hidden")
				S.idx += 1
				paintProgress()
				paintStats()
			})
			.catch(function (e) {
				P.toast(e.message, "err")
				$("btnAnswer").disabled = false
			})
			.then(function () {
				S.busy = false
			})
	}

	function next() {
		if (S.idx >= S.qs.length) return finish()
		renderQuestion()
	}

	/* ------------------------------------------------------------- протокол */
	function finish() {
		if (S.busy) return
		S.busy = true
		stopTimer()
		overlay("ovTime", false)
		P.api
			.sessionFinish(S.id)
			.then(function (r) {
				renderProtocol(r.protocol || r)
			})
			.catch(function (e) {
				P.toast(e.message, "err")
			})
			.then(function () {
				S.busy = false
			})
	}

	function renderProtocol(p) {
		S.proto = p
		var cand = p.candidate || {}
		var task = p.task || {}
		$("pWho").textContent = cand.name || "Кандидат"
		$("pTask").textContent =
			(task.title || "") + " · " + (task.language || "") + " · " + (task.lines || 0) + " строк · " + (task.sites || 0) + " мест правки" + (cand.vacancy ? " · " + cand.vacancy : "")
		$("pControl").textContent = p.control_pct + " %"
		$("pAnswers").textContent = p.questions.correct + " / " + p.questions.total
		$("pScore").textContent = p.mutation.score_pct + " %"
		$("pDuration").textContent = p.duration_clock
		$("pVerdictChip").className = "verdict " + P.verdictClass(p.verdict.level)
		$("pVerdictChip").textContent = p.passed ? "допуск подтверждён" : "допуск не подтверждён"
		$("pVerdictLabel").textContent = p.verdict.label
		$("pVerdictText").textContent = p.verdict.summary + " " + (p.verdict.tests_note || "")
		$("pReproducible").textContent = p.reproducible || ""
		$("pThreshold").textContent = "Порог допуска — " + p.pass_threshold_pct + " %. Вердикт воспроизводим: тот же код и те же мутации дадут те же цифры."

		var skills = p.skills || [],
			sk = []
		for (var i = 0; i < skills.length; i++) {
			var s = skills[i]
			sk.push(
				"<tr><td>" + P.esc(s.title) + "</td><td>" + s.correct + " / " + s.questions + "</td>" +
					'<td><span class="bar"><i class="' + P.barClass(s.score_pct) + '" style="width: ' + s.score_pct + '%"></i></span> ' + s.score_pct + " %</td>" +
					'<td><span class="verdict ' + P.verdictClass(s.verdict) + '">' + P.esc(s.verdict_label) + "</span></td></tr>"
			)
		}
		$("pSkills").innerHTML = sk.join("")

		var risks = p.risks || [],
			rs = []
		for (var k = 0; k < risks.length; k++) {
			var r = risks[k]
			rs.push(
				'<div class="card card-pad-sm" style="background: var(--surface-3)">' +
					'<div class="tiny u-red mb-8">' + P.esc(r.kind) + " · строка " + r.line + " · " + P.esc(r.mutation) + "</div>" +
					'<div class="small">' + P.esc(r.text) + "</div>" +
					(r.action ? '<div class="tiny dim mt-16">' + P.esc(r.action) + "</div>" : "") +
					"</div>"
			)
		}
		$("pRisks").innerHTML = rs.join("") || '<p class="tiny dim mb-0">Рисков не зафиксировано.</p>'

		var quotes = (p.quotes || []).slice(0, 4),
			qs = []
		for (var q = 0; q < quotes.length; q++) {
			var c = quotes[q]
			qs.push(
				'<div class="quote"><div class="tiny dim mb-8">' + P.esc(c.mutation) + " · строка " + c.line + " · " + P.esc(c.kind) + "</div>" +
					'<pre class="diff mb-0">' + P.renderDiff(c.diff) + "</pre></div>"
			)
		}
		$("pQuotes").innerHTML = qs.join("") || '<p class="tiny dim mb-0">Цитат нет.</p>'

		var tl = p.timeline || [],
			ts = []
		for (var t = 0; t < tl.length; t++) {
			var x = tl[t]
			ts.push(
				'<div class="tl-item' + (x.correct ? "" : " is-bad") + '">' +
					'<span class="tl-time">' + P.esc(x.clock) + "</span>" +
					"<b>" + P.esc(x.title) + "</b>" +
					'<div class="tiny dim">' + P.esc(x.mutation) + " · строка " + x.line + " · " + P.esc(x.result) + " · " + x.seconds + " с</div></div>"
			)
		}
		$("pTimeline").innerHTML = ts.join("")

		$("pPdf").href = "/api/protocol/" + encodeURIComponent(p.id) + ".pdf"
		$("pTxt").href = "/api/protocol/" + encodeURIComponent(p.id) + ".txt"
		P.gauge($("pGauge"), p.control_pct)

		try {
			P.store.save({
				id: p.session_id,
				protocol: p.id,
				candidate: cand.name,
				vacancy: cand.vacancy || "",
				task: task.title,
				control_pct: p.control_pct,
				passed: p.passed,
				created_at: p.created_at,
				status: "finished",
			})
		} catch (e) {}

		show("viewLoading", false)
		show("viewSession", false)
		show("viewProtocol", true)
		overlay("ovStart", false)
		window.scrollTo(0, 0)
	}

	/* ------------------------------------------------------------------ старт */
	function fillOverlay() {
		var meta = S.sess.meta || {}
		$("ovWho").textContent = meta.candidate || "Кандидат"
		$("ovTask").textContent = meta.task || "Своё решение"
		$("ovCount").textContent = String(S.sess.questions_total)
		$("ovFinger").textContent = S.sess.fingerprint
		$("sessWho").textContent = meta.candidate || "Кандидат"
		$("sessTask").textContent = (meta.task || "") + " · " + (meta.language || "Python")
		$("sessFinger").textContent = "отпечаток " + S.sess.fingerprint
	}

	function useSession(s) {
		S.sess = s
		S.id = s.id
		S.qs = s.questions || []
		S.idx = s.answered || 0
		S.left = s.remaining_seconds != null ? s.remaining_seconds : s.seconds_total || 900
		var answers = s.answers || {}
		S.correct = 0
		for (var key in answers) if (answers[key] && answers[key].correct) S.correct += 1
		show("viewLoading", false)
		fillOverlay()
		if (s.status === "finished") {
			var pid = String(s.id).replace(/^s-/, "p-")
			return P.api
				.protocol(pid)
				.then(function (r) {
					renderProtocol(r.protocol || r)
				})
				.catch(function () {
					finish()
				})
		}
		overlay("ovStart", true)
	}

	function begin() {
		overlay("ovStart", false)
		show("viewSession", true)
		renderQuestion()
		startTimer()
	}

	function fail(msg) {
		show("viewLoading", false)
		show("viewError", true)
		if (msg) $("errText").textContent = msg
	}

	function init() {
		$("btnStart").addEventListener("click", begin)
		$("btnAnswer").addEventListener("click", answer)
		$("btnNext").addEventListener("click", next)
		$("btnFinish").addEventListener("click", finish)
		$("btnTimeFinish").addEventListener("click", finish)
		$("btnHint").addEventListener("click", function () {
			$("qHint").classList.toggle("hidden")
		})
		$("qOptions").addEventListener("click", function (e) {
			var row = e.target.closest(".q-option")
			if (row && !row.disabled) pick(row.getAttribute("data-id"))
		})
		$("btnCopyLink").addEventListener("click", function () {
			P.copy(location.origin + "/session.html?id=" + encodeURIComponent(S.id))
		})
		$("btnSend").addEventListener("click", function () {
			var mail = $("sendEmail").value.trim()
			if (!mail || mail.indexOf("@") < 0) {
				P.toast("Укажите email", "err")
				return
			}
			P.api
				.protocolSend(S.proto.id, mail)
				.then(function (r) {
					$("sendStatus").textContent = r.message || "Протокол сохранён в очереди отправки."
					P.toast("Протокол отправлен", "ok")
				})
				.catch(function (e) {
					P.toast(e.message, "err")
				})
		})
		document.addEventListener("visibilitychange", function () {
			if (document.hidden || !S.id || !S.tick) return
			P.api
				.sessionGet(S.id)
				.then(function (s) {
					if (s.remaining_seconds != null) {
						S.left = s.remaining_seconds
						paintTimer()
					}
				})
				.catch(function () {})
		})

		var id = P.qs("id", "")
		var demo = P.qs("demo", "")
		if (id) {
			P.api
				.sessionGet(id)
				.then(useSession)
				.catch(function (e) {
					fail(e.message)
				})
			return
		}
		if (demo) {
			P.api
				.demo("orders")
				.then(function (d) {
					return P.api.sessionStart({
						code: d.code,
						tests: d.tests,
						meta: { candidate: "Демо-кандидат", task: "Разбор заказов из текстового файла", language: "Python", vacancy: "Python-разработчик" },
						limit: 15,
						questions: 13,
					})
				})
				.then(function (s) {
					if (history.replaceState) history.replaceState(null, "", "/session.html?id=" + encodeURIComponent(s.id))
					useSession(s)
				})
				.catch(function (e) {
					fail(e.message)
				})
			return
		}
		fail("Откройте ссылку на сессию или запустите демо-сессию.")
	}

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init)
	else init()
})()
