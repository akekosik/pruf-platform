/* Студия проверки кода: песочница, мутации, запуск сессии защиты. */
(function () {
	"use strict"
	var P = window.PRUF
	var S = { tasks: [], task: null, muts: [], active: null, original: null, analysis: null, busy: false }

	function $(id) {
		return document.getElementById(id)
	}

	/* ------------------------------------------------------------ консоль */
	function log(msg, kind) {
		var box = $("console")
		if (!box) return
		var row = document.createElement("div")
		row.className = "console-line" + (kind ? " " + kind : "")
		row.textContent = msg
		box.appendChild(row)
		box.scrollTop = box.scrollHeight
	}

	function step(n, state) {
		var items = document.querySelectorAll("#stepper .stepper-item")
		for (var i = 0; i < items.length; i++) {
			var v = Number(items[i].getAttribute("data-step"))
			items[i].classList.toggle("is-active", v === n)
			if (v < n || (v === n && state === "done")) items[i].classList.add("is-done")
		}
	}

	/* ----------------------------------------------------------- редактор */
	function sync(areaId, gutterId, metaId) {
		var area = $(areaId),
			gutter = $(gutterId)
		if (!area || !gutter) return
		var n = area.value.split("\n").length
		var out = []
		for (var i = 1; i <= n; i++) out.push(i)
		gutter.textContent = out.join("\n")
		if (metaId) $(metaId).textContent = n + " строк"
	}

	function bindEditor(areaId, gutterId, metaId) {
		var area = $(areaId)
		if (!area) return
		area.addEventListener("input", function () {
			sync(areaId, gutterId, metaId)
		})
		area.addEventListener("scroll", function () {
			$(gutterId).style.transform = "translateY(" + -area.scrollTop + "px)"
		})
		area.addEventListener("keydown", function (e) {
			if (e.key !== "Tab") return
			e.preventDefault()
			var s = area.selectionStart,
				el = area.selectionEnd
			area.value = area.value.slice(0, s) + "    " + area.value.slice(el)
			area.selectionStart = area.selectionEnd = s + 4
			sync(areaId, gutterId, metaId)
		})
		sync(areaId, gutterId, metaId)
	}

	function code() {
		return $("codeArea").value
	}
	function tests() {
		return $("testsArea").value
	}
	function setCode(v) {
		$("codeArea").value = v || ""
		sync("codeArea", "codeGutter", "codeMeta")
	}
	function setTests(v) {
		$("testsArea").value = v || ""
		sync("testsArea", "testsGutter", "testsMeta")
	}

	function showLine(n) {
		var area = $("codeArea")
		var lines = area.value.split("\n")
		var from = 0
		for (var i = 0; i < n - 1 && i < lines.length; i++) from += lines[i].length + 1
		var to = from + (lines[n - 1] ? lines[n - 1].length : 0)
		area.focus()
		area.setSelectionRange(from, to)
		area.scrollTop = Math.max(0, (n - 6) * 22)
		$("codeGutter").style.transform = "translateY(" + -area.scrollTop + "px)"
	}

	/* ------------------------------------------------------------ мутации */
	function statusOf(m) {
		if (m.status === "survived") return { cls: "survived", label: "выжила" }
		if (m.status === "killed") return { cls: "killed", label: "убита" }
		return { cls: "queued", label: "не проверена" }
	}

	function paintMuts() {
		var box = $("mutList")
		$("mutCount").textContent = String(S.muts.length)
		if (!S.muts.length) {
			box.innerHTML = '<div class="empty">Мутации не построены.</div>'
			return
		}
		var out = []
		for (var i = 0; i < S.muts.length; i++) {
			var m = S.muts[i],
				st = statusOf(m)
			out.push(
				'<button type="button" class="mut-row" data-id="' + P.escAttr(m.id) + '">' +
					'<span class="mut-id">' + P.esc(m.id) + "</span><span>" +
					'<span class="mut-kind">' + P.esc(m.skill_title || m.kind) + " · строка " + m.line + "</span>" +
					'<span class="mut-sub">' + P.esc(m.intent || m.operator) + "</span></span>" +
					'<span class="mut-status ' + st.cls + '">' + st.label + "</span></button>"
			)
		}
		box.innerHTML = out.join("")
	}

	function selectMut(id) {
		for (var i = 0; i < S.muts.length; i++) if (S.muts[i].id === id) S.active = S.muts[i]
		var rows = document.querySelectorAll("#mutList .mut-row")
		for (var k = 0; k < rows.length; k++) rows[k].classList.toggle("is-active", rows[k].getAttribute("data-id") === id)
		var m = S.active
		if (!m) return
		var st = statusOf(m)
		$("mutDetailTitle").textContent = m.id + " · " + m.operator + " · строка " + m.line
		$("mutDetailStatus").className = "mut-status " + st.cls
		$("mutDetailStatus").textContent = st.label
		$("mutDetailDiff").innerHTML = P.renderDiff(m.diff)
		var note = m.consequence || m.intent || ""
		if (m.status === "survived") note += " Ни один тест не заметил правку. " + (m.suggestion || "")
		else if (m.first_failed) note += " Первым падает тест " + m.first_failed + "."
		$("mutDetailNote").textContent = note
	}

	/* -------------------------------------------------------------- задачи */
	function paintTask(t) {
		S.task = t
		if (!t) return
		$("taskMeta").textContent = t.language + " · " + t.level + " · " + t.minutes + " минут"
		$("taskStatement").textContent = t.statement
		var sk = t.skills || [],
			out = []
		for (var i = 0; i < sk.length; i++) out.push('<span class="chip">' + P.esc(sk[i]) + "</span>")
		$("taskSkills").innerHTML = out.join("")
		setCode(t.code)
		setTests(t.tests)
		S.original = t.code
		S.muts = []
		S.active = null
		S.analysis = null
		paintMuts()
		$("mutMeta").textContent = "ещё не построены"
		$("verdictCard").classList.add("hidden")
		step(1)
		log("Загружено задание: " + t.title, "note")
	}

	/* -------------------------------------------------------------- действия */
	function lock(on, btn, label) {
		S.busy = on
		if (!btn) return
		btn.disabled = on
		btn.textContent = on ? "Считаем…" : label
	}

	function doRun() {
		if (S.busy) return
		var btn = $("btnRun")
		lock(true, btn, "Прогнать тесты")
		log("Прогон тестов в песочнице…", "note")
		P.api
			.run(code(), tests())
			.then(function (r) {
				if (r.import_error) log("Ошибка импорта: " + r.import_error, "fail")
				if (r.timeout) log("Превышен лимит времени", "fail")
				var list = r.tests || []
				for (var i = 0; i < list.length; i++) {
					var t = list[i]
					var ok = t.status === "passed"
					log((ok ? "✓ " : "✗ ") + t.name + " · " + t.duration_ms + " мс" + (t.message ? " · " + t.message : ""), ok ? "ok" : "fail")
				}
				if (r.stdout) log("stdout: " + r.stdout.slice(0, 400), "note")
				log("Итог: " + r.passed + " прошло, " + r.failed + " упало, " + r.errored + " ошибок · " + r.duration_ms + " мс" + (r.cached ? " (из кеша)" : ""), r.ok ? "ok" : "fail")
				$("kpiTests").textContent = r.passed + " / " + (list.length || 0)
				step(2, "done")
				P.toast(r.ok ? "Тесты зелёные" : "Тесты падают", r.ok ? "ok" : "err")
			})
			.catch(function (e) {
				log("Ошибка: " + e.message, "fail")
				P.toast(e.message, "err")
			})
			.then(function () {
				lock(false, btn, "Прогнать тесты")
			})
	}

	function doMutate() {
		if (S.busy) return
		var btn = $("btnMutate")
		lock(true, btn, "Построить мутации")
		log("Разбор в AST и построение мутаций…", "note")
		P.api
			.mutations(code(), 15)
			.then(function (r) {
				S.muts = r.mutations || []
				S.original = code()
				paintMuts()
				$("mutMeta").textContent = r.lines + " строк · " + r.sites + " мест правки · без прогона тестов"
				$("kpiFinger").textContent = r.fingerprint
				log("Построено мутаций: " + S.muts.length + " · отпечаток " + r.fingerprint, "ok")
				if (S.muts.length) selectMut(S.muts[0].id)
				step(3, "done")
			})
			.catch(function (e) {
				log("Ошибка: " + e.message, "fail")
				P.toast(e.message, "err")
			})
			.then(function () {
				lock(false, btn, "Построить мутации")
			})
	}

	function paintAnalysis(a) {
		S.analysis = a
		S.muts = a.mutations || []
		S.original = code()
		paintMuts()
		$("mutMeta").textContent = a.killed + " убито · " + a.survived + " выжило · счёт " + a.mutation_score_pct + " %"
		$("kpiTests").textContent = a.baseline.passed + " / " + (a.baseline.tests || []).length
		$("kpiScore").textContent = a.mutation_score_pct + " %"
		$("kpiSurvived").textContent = String(a.survived)
		$("kpiFinger").textContent = a.fingerprint
		var card = $("verdictCard")
		card.classList.remove("hidden")
		$("verdictChip").className = "verdict " + P.verdictClass(a.verdict.level)
		$("verdictChip").textContent = a.verdict.label
		$("verdictText").textContent = a.verdict.summary
		var rows = a.tests || [],
			out = []
		for (var i = 0; i < rows.length; i++) {
			var t = rows[i]
			out.push(
				"<tr><td><code>" + P.esc(t.name) + "</code></td><td>" + (t.status === "passed" ? '<span class="u-teal">прошёл</span>' : '<span class="u-red">упал</span>') +
					"</td><td>" + (t.kills != null ? t.kills : 0) + "</td><td>" + P.esc(t.verdict || "") + "</td></tr>"
			)
		}
		$("testsTable").innerHTML = out.join("")
		var gaps = a.gaps || [],
			g = []
		for (var k = 0; k < gaps.length; k++) {
			var x = gaps[k]
			g.push(
				'<div class="card card-pad-sm" style="background: var(--surface-3)">' +
					'<div class="tiny u-red mb-8">строка ' + x.line + " · " + P.esc(x.skill_title || x.skill || "") + "</div>" +
					'<div class="small">' + P.esc(x.text || x.intent || "") + "</div>" +
					(x.action ? '<div class="tiny dim mt-16">' + P.esc(x.action) + "</div>" : "") +
					"</div>"
			)
		}
		$("gapsList").innerHTML = g.join("") || '<p class="tiny dim mb-0">Дыр не найдено: тесты ловят все правки.</p>'
		var useless = a.useless_tests || []
		if (useless.length) log("Тесты без пользы (не убили ни одну мутацию): " + useless.join(", "), "fail")
		if (S.muts.length) {
			var first = null
			for (var q = 0; q < S.muts.length && !first; q++) if (S.muts[q].status === "survived") first = S.muts[q]
			selectMut((first || S.muts[0]).id)
		}
		step(4)
	}

	function doAnalyze() {
		if (S.busy) return
		var btn = $("btnAnalyze")
		lock(true, btn, "Полный анализ")
		log("Полный анализ: базовый прогон, мутации, оценка набора тестов…", "note")
		P.api
			.analyze(code(), tests(), 15)
			.then(function (a) {
				if (!a.baseline.ok) log("Внимание: базовые тесты не зелёные, мутационный счёт некорректен", "fail")
				paintAnalysis(a)
				log("Готово: " + a.mutation_total + " мутаций, убито " + a.killed + ", выжило " + a.survived + " · " + a.duration_ms + " мс", "ok")
				P.toast("Анализ готов: счёт " + a.mutation_score_pct + " %", a.survived ? "err" : "ok")
			})
			.catch(function (e) {
				log("Ошибка: " + e.message, "fail")
				P.toast(e.message, "err")
			})
			.then(function () {
				lock(false, btn, "Полный анализ")
			})
	}

	function doSession() {
		if (S.busy) return
		var btn = $("btnSession")
		lock(true, btn, "Начать 15-минутную защиту")
		var meta = {
			candidate: $("sessName").value.trim() || "Кандидат",
			vacancy: $("sessVacancy").value.trim(),
			task: (S.task && S.task.title) || "Своё решение",
			language: "Python",
		}
		P.api
			.sessionStart({ code: code(), tests: tests(), meta: meta, limit: 15, questions: Number($("sessQuestions").value) })
			.then(function (s) {
				P.store.save({ id: s.id, candidate: meta.candidate, vacancy: meta.vacancy, task: meta.task, created_at: s.created_at, status: s.status })
				log("Сессия создана: " + s.id + " · вопросов " + s.questions_total, "ok")
				P.toast("Переходим к защите", "ok")
				location.href = "/session.html?id=" + encodeURIComponent(s.id)
			})
			.catch(function (e) {
				log("Ошибка: " + e.message, "fail")
				P.toast(e.message, "err")
				lock(false, btn, "Начать 15-минутную защиту")
			})
	}

	/* ----------------------------------------------------------------- init */
	function init() {
		bindEditor("codeArea", "codeGutter", "codeMeta")
		bindEditor("testsArea", "testsGutter", "testsMeta")

		$("mutList").addEventListener("click", function (e) {
			var row = e.target.closest(".mut-row")
			if (row) selectMut(row.getAttribute("data-id"))
		})
		$("btnRun").addEventListener("click", doRun)
		$("btnMutate").addEventListener("click", doMutate)
		$("btnAnalyze").addEventListener("click", doAnalyze)
		$("btnSession").addEventListener("click", doSession)
		$("btnClearConsole").addEventListener("click", function () {
			$("console").innerHTML = ""
			log("Консоль очищена.", "note")
		})
		$("btnShowLine").addEventListener("click", function () {
			if (S.active) showLine(S.active.line)
			else P.toast("Сначала выберите мутацию", "err")
		})
		$("btnApplyMut").addEventListener("click", function () {
			if (!S.active) {
				P.toast("Сначала выберите мутацию", "err")
				return
			}
			var m = S.active
			var lines = code().split("\n")
			var i = m.line - 1
			if (lines[i] != null && m.before && lines[i].indexOf(m.before) >= 0) {
				lines[i] = lines[i].replace(m.before, m.after)
				setCode(lines.join("\n"))
				showLine(m.line)
				log("Применена мутация " + m.id + " в строке " + m.line + ". Прогоните тесты и сравните результат.", "note")
				P.toast("Мутация в коде — проверьте тесты", "ok")
			} else {
				P.toast("Код изменён, постройте мутации заново", "err")
			}
		})
		$("btnUndoMut").addEventListener("click", function () {
			if (S.original == null) return
			setCode(S.original)
			log("Исходное решение восстановлено.", "note")
			P.toast("Оригинал восстановлен", "ok")
		})
		$("btnLoadTask").addEventListener("click", function () {
			if (S.task) setTests(S.task.tests)
			P.toast("Подставлены эталонные тесты", "ok")
		})
		$("btnWeakTests").addEventListener("click", function () {
			if (S.task && S.task.weak_tests) {
				setTests(S.task.weak_tests)
				log("Подставлен слабый набор тестов: пройдёт зелёным, но мутации пропустит.", "note")
				P.toast("Подставлены слабые тесты", "ok")
			}
		})
		$("btnClearAll").addEventListener("click", function () {
			setCode("")
			setTests("")
			S.muts = []
			S.active = null
			paintMuts()
			step(1)
			log("Редакторы очищены.", "note")
		})

		P.api
			.tasks()
			.then(function (r) {
				S.tasks = r.tasks || []
				var sel = $("taskSelect"),
					out = []
				for (var i = 0; i < S.tasks.length; i++) {
					out.push('<option value="' + P.escAttr(S.tasks[i].id) + '">' + P.esc(S.tasks[i].title) + "</option>")
				}
				sel.innerHTML = out.join("")
				sel.addEventListener("change", function () {
					for (var k = 0; k < S.tasks.length; k++) if (S.tasks[k].id === sel.value) paintTask(S.tasks[k])
				})
				var want = P.qs("task", S.tasks.length ? S.tasks[0].id : "")
				var found = null
				for (var j = 0; j < S.tasks.length; j++) if (S.tasks[j].id === want) found = S.tasks[j]
				found = found || S.tasks[0]
				if (found) {
					sel.value = found.id
					paintTask(found)
				}
			})
			.catch(function (e) {
				log("Не удалось загрузить задания: " + e.message, "fail")
			})

		P.api
			.health()
			.then(function (h) {
				$("engineMeta").textContent = "PRUF " + h.version + " · операторов " + h.operators + (h.offline ? " · офлайн" : "")
			})
			.catch(function () {
				$("engineMeta").textContent = "движок недоступен"
			})
	}

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init)
	else init()
})()
