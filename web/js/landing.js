/* Лендинг ПРУФ: всё, что показано на странице, приходит из движка. */
(function () {
	"use strict"
	var P = window.PRUF
	var S = { code: "", muts: [], active: null, broken: false, demo: null, tryOffset: 0 }

	function $(id) {
		return document.getElementById(id)
	}
	function set(id, text) {
		var el = $(id)
		if (el) el.textContent = text
	}

	/* ------------------------------------------------------------ hero-код */
	function mutatedCode(m) {
		var lines = S.code.split("\n")
		var i = (m.line || 1) - 1
		if (lines[i] != null && m.before && lines[i].indexOf(m.before) >= 0) {
			lines[i] = lines[i].replace(m.before, m.after)
		}
		return lines.join("\n")
	}

	function paintCode(useMutated) {
		var box = $("heroCode")
		if (!box) return
		var m = S.active
		var line = m ? m.line : 0
		var code = useMutated && m ? mutatedCode(m) : S.code
		box.innerHTML = P.renderCode(code, { hot: line ? [line] : [] })
		var row = box.querySelector('.code-line[data-line="' + line + '"]')
		if (row && useMutated) {
			row.classList.add("is-flash")
			setTimeout(function () {
				row.classList.remove("is-flash")
			}, 900)
		}
		S.broken = !!useMutated
	}

	function paintDetail() {
		var m = S.active
		if (!m) return
		set("heroDetailTitle", m.operator + " · строка " + m.line)
		var st = $("heroDetailStatus")
		if (st) {
			var survived = m.status === "survived"
			st.className = "mut-status " + (survived ? "survived" : "killed")
			st.textContent = survived ? "выжила" : "убита"
		}
		var d = $("heroDetailDiff")
		if (d) d.innerHTML = P.renderDiff(m.diff)
		var note = $("heroDetailNote")
		if (note) {
			var txt = m.consequence || m.intent || ""
			if (m.status === "survived") {
				txt += " Ни один тест не заметил правку — это дыра в наборе тестов."
				if (m.suggestion) txt += " " + m.suggestion
			} else if (m.first_failed) {
				txt += " Первым падает тест " + m.first_failed + "."
			}
			note.textContent = txt
		}
	}

	function selectMutation(id) {
		for (var i = 0; i < S.muts.length; i++) {
			if (S.muts[i].id === id) S.active = S.muts[i]
		}
		var rows = document.querySelectorAll("#heroMut .mut-row")
		for (var k = 0; k < rows.length; k++) {
			rows[k].classList.toggle("is-active", rows[k].getAttribute("data-id") === id)
		}
		paintCode(false)
		paintDetail()
	}

	function paintMutList() {
		var box = $("heroMut")
		if (!box) return
		var out = []
		for (var i = 0; i < S.muts.length; i++) {
			var m = S.muts[i]
			var survived = m.status === "survived"
			out.push(
				'<button type="button" class="mut-row" data-id="' + P.escAttr(m.id) + '">' +
					'<span class="mut-id">' + P.esc(m.id) + "</span>" +
					"<span>" +
					'<span class="mut-kind">' + P.esc(m.skill_title || m.kind) + " · строка " + m.line + "</span>" +
					'<span class="mut-sub">' + P.esc(m.intent || m.operator) + "</span>" +
					"</span>" +
					'<span class="mut-status ' + (survived ? "survived" : "killed") + '">' + (survived ? "выжила" : "убита") + "</span>" +
					"</button>"
			)
		}
		box.innerHTML = out.join("")
		box.addEventListener("click", function (e) {
			var row = e.target.closest(".mut-row")
			if (row) selectMutation(row.getAttribute("data-id"))
		})
	}

	/* --------------------------------------------------------- интерактив */
	function paintTry() {
		var box = $("tryOptions")
		var codeBox = $("tryCode")
		var res = $("tryResult")
		if (!box || !codeBox) return
		var survived = [],
			killed = []
		for (var i = 0; i < S.muts.length; i++) {
			;(S.muts[i].status === "survived" ? survived : killed).push(S.muts[i])
		}
		if (!survived.length || killed.length < 2) {
			box.innerHTML = '<div class="empty">Недостаточно мутаций для викторины</div>'
			return
		}
		var o = S.tryOffset
		var pick = [survived[o % survived.length], killed[o % killed.length], killed[(o + 1) % killed.length]]
		/* детерминированная перестановка: сдвиг по номеру попытки */
		var order = [[0, 1, 2], [1, 0, 2], [2, 1, 0], [1, 2, 0]][o % 4]
		var opts = [pick[order[0]], pick[order[1]], pick[order[2]]]
		var hot = []
		for (var h = 0; h < opts.length; h++) hot.push(opts[h].line)
		codeBox.innerHTML = P.renderCode(S.code, { hot: hot })
		var out = []
		for (var j = 0; j < opts.length; j++) {
			var m = opts[j]
			out.push(
				'<button type="button" class="try-option" data-id="' + P.escAttr(m.id) + '">' +
					"<b>Строка " + m.line + "</b> · " +
					'<code>' + P.esc(m.before) + "</code> → <code>" + P.esc(m.after) + "</code>" +
					'<span class="mut-sub">' + P.esc(m.intent || m.operator) + "</span>" +
					"</button>"
			)
		}
		box.innerHTML = out.join("")
		if (res) {
			res.classList.add("hidden")
			res.innerHTML = ""
		}
		var answered = false
		box.onclick = function (e) {
			var btn = e.target.closest(".try-option")
			if (!btn || answered) return
			answered = true
			var id = btn.getAttribute("data-id")
			var chosen = null
			for (var q = 0; q < opts.length; q++) if (opts[q].id === id) chosen = opts[q]
			var right = chosen && chosen.status === "survived"
			var all = box.querySelectorAll(".try-option")
			for (var a = 0; a < all.length; a++) {
				var aid = all[a].getAttribute("data-id")
				var mm = null
				for (var w = 0; w < opts.length; w++) if (opts[w].id === aid) mm = opts[w]
				all[a].classList.add(mm && mm.status === "survived" ? "is-correct" : aid === id ? "is-wrong" : "is-selected")
			}
			if (res) {
				var surv = null
				for (var s = 0; s < opts.length; s++) if (opts[s].status === "survived") surv = opts[s]
				res.classList.remove("hidden")
				res.innerHTML =
					"<b>" + (right ? "Верно." : "Мимо.") + "</b> Правка " + P.esc(surv.id) + " в строке " + surv.line +
					" проходит незамеченной: " + P.esc(surv.consequence || surv.intent) +
					(surv.suggestion ? " " + P.esc(surv.suggestion) : "") +
					" Остальные правки тесты ловят."
			}
			P.toast(right ? "Точно: эту дыру тесты не видят" : "Эту правку тесты поймали", right ? "ok" : "err")
		}
	}

	/* ----------------------------------------------------------- протокол */
	function paintProtocol(pr) {
		if (!pr) return
		var tb = $("protoSkills")
		if (tb) {
			var out = []
			var sk = pr.skills || []
			for (var i = 0; i < sk.length; i++) {
				var s = sk[i]
				var pct = s.score_pct != null ? s.score_pct : Math.round((s.score || 0) * 100)
				out.push(
					"<tr><td><b>" + P.esc(s.title) + "</b></td><td>" + s.questions + "</td><td>" + s.correct + "</td>" +
						'<td><div class="bar"><i class="' + P.barClass(pct) + '" style="width:' + pct + '%"></i></div><span class="tiny dim">' + pct + " %</span></td>" +
						'<td><span class="verdict ' + P.verdictClass(s.verdict) + '">' + P.esc(s.verdict_label) + "</span></td></tr>"
				)
			}
			tb.innerHTML = out.join("") || '<tr><td colspan="5" class="empty">Нет данных</td></tr>'
		}
		var g = $("protoGauge")
		if (g) P.gauge(g, pr.control_pct || 0)
		var v = pr.verdict || {}
		set("protoVerdict", (v.label || "") + " · " + (pr.passed ? "допуск подтверждён" : "порог " + pr.pass_threshold_pct + " % не пройден") + ". " + (v.tests_note || ""))
		var q = (pr.quotes || [])[0]
		var qb = $("protoQuote")
		if (qb && q) {
			qb.innerHTML =
				'<div class="tiny dim mb-8">Цитата защиты · строка ' + q.line + " · " + P.esc(q.kind) + "</div>" +
				'<pre class="diff">' + P.renderDiff(q.diff) + "</pre>" +
				"<p class=\"small mb-0\">" + P.esc(q.question) + "</p>"
		}
		var tl = $("protoTimeline")
		if (tl) {
			var rows = (pr.timeline || []).slice(0, 6),
				t = []
			for (var k = 0; k < rows.length; k++) {
				var r = rows[k]
				t.push(
					'<div class="tl-item' + (r.correct ? "" : " is-bad") + '">' +
						'<span class="tl-time">' + P.esc(r.clock) + "</span>" +
						"<span>" + P.esc(r.title) + ' <span class="dim">· строка ' + r.line + " · " + P.esc(r.result) + "</span></span>" +
						"</div>"
				)
			}
			tl.innerHTML = t.join("")
		}
		var pdf = $("protoPdf"),
			txt = $("protoTxt")
		if (pdf) pdf.href = "/api/protocol/" + encodeURIComponent(pr.id) + ".pdf"
		if (txt) txt.href = "/api/protocol/" + encodeURIComponent(pr.id) + ".txt"
	}

	/* ---------------------------------------------------------- экономика */
	function paintEconomics(e) {
		if (!e) return
		var pr = e.prices || {},
			u = e.unit || {},
			b = e.breakeven || {}
		if (pr.verification) set("priceVerification", pr.verification.replace(" за сессию", ""))
		if (pr.subscription) set("priceSub", pr.subscription.replace(" в год", ""))
		if (pr.onprem) set("priceOnprem", pr.onprem.replace(" в год", ""))
		if (u.client_saving_pct != null) set("priceSaving", "Дешевле ручной проверки на " + u.client_saving_pct + " %")
		if (u.variable_cost != null) set("pillCost", P.money(u.variable_cost))
		if (b.sessions_needed) {
			set("priceIntro", "Безубыточность — " + b.sessions_needed + " верификаций в год, это " + b.companies_needed + " активных компаний. В прежней вузовской модели требовалось 3 745 студентов и 2–3 вуза.")
		}
		if (u.price != null) {
			set(
				"priceUnit",
				"Юнит-экономика: цена " + P.money(u.price) + ", переменная себестоимость " + P.money(u.variable_cost) +
					", маржа " + u.margin_pct + " %. Ручная альтернатива — " + P.money(u.manual_alternative) + " за кандидата."
			)
		}
	}

	/* -------------------------------------------------------------- форма */
	function initLead() {
		var form = $("leadForm")
		if (!form) return
		form.addEventListener("submit", function (e) {
			e.preventDefault()
			var btn = $("leadSubmit"),
				status = $("leadStatus")
			var payload = {
				name: $("leadName").value.trim(),
				email: $("leadEmail").value.trim(),
				company: $("leadCompany").value.trim(),
				plan: $("leadPlan").value,
				comment: $("leadComment").value.trim(),
			}
			if (!payload.name || !payload.email) {
				P.toast("Заполните имя и рабочую почту", "err")
				return
			}
			btn.disabled = true
			btn.textContent = "Отправляем…"
			P.api
				.lead(payload)
				.then(function (r) {
					P.toast("Заявка принята", "ok")
					if (status) status.textContent = (r && r.message) || "Заявка сохранена локально."
					form.reset()
				})
				.catch(function (err) {
					P.toast(err.message || "Не удалось отправить", "err")
				})
				.then(function () {
					btn.disabled = false
					btn.textContent = "Отправить заявку"
				})
		})
	}

	/* --------------------------------------------------------------- boot */
	function initButtons() {
		var b = $("btnBreak"),
			r = $("btnRestore")
		if (b)
			b.addEventListener("click", function () {
				if (!S.active) {
					P.toast("Сначала выберите мутацию справа", "err")
					return
				}
				paintCode(true)
				P.toast(
					S.active.status === "survived" ? "Правка применена — тесты всё ещё зелёные" : "Правка применена — тесты падают",
					S.active.status === "survived" ? "err" : "ok"
				)
			})
		if (r)
			r.addEventListener("click", function () {
				paintCode(false)
				P.toast("Исходное решение восстановлено", "ok")
			})
		var tr = $("tryReset")
		if (tr)
			tr.addEventListener("click", function () {
				S.tryOffset += 1
				paintTry()
			})
	}

	function start() {
		initButtons()
		initLead()
		P.api
			.demo("orders")
			.then(function (d) {
				S.demo = d
				S.code = d.code || ""
				var a = d.analysis || {}
				S.muts = a.mutations || []
				set("heroFingerprint", "отпечаток " + (a.fingerprint || "—"))
				set("heroMutMeta", (d.task && d.task.title ? d.task.title + " · " : "") + a.lines + " строк · " + a.sites + " мест правки")
				set("heroKilled", "убито " + a.killed)
				set("heroSurvived", "выжило " + a.survived)
				set("floatSurvived", String(a.survived))
				set("floatControl", ((d.protocol && d.protocol.control_pct) || 0) + " %")
				paintMutList()
				var first = null
				for (var i = 0; i < S.muts.length && !first; i++) if (S.muts[i].status === "survived") first = S.muts[i]
				S.active = first || S.muts[0] || null
				if (S.active) selectMutation(S.active.id)
				else paintCode(false)
				paintTry()
				paintProtocol(d.protocol)
			})
			.catch(function (err) {
				var box = $("heroCode")
				if (box) box.innerHTML = '<div class="code-line"><span class="lc">Движок недоступен: ' + P.esc(err.message) + "</span></div>"
				P.toast("Не удалось загрузить демо-разбор", "err")
			})
		P.api
			.economics()
			.then(paintEconomics)
			.catch(function () {})
	}

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start)
	else start()
})()
