/* ============================================================================
   Кабинет работодателя: пул кандидатов, протоколы, сравнение, решения.
   Всё читается из /api: ни одного зашитого числа в интерфейсе.
   ============================================================================ */
(function () {
	"use strict"
	var P = window.PRUF
	var LS_DECISIONS = "pruf.employer.decisions"
	var LS_COMPANY = "pruf.employer.company"
	var LS_SETTINGS = "pruf.employer.settings"

	var S = {
		rows: [],
		vacancies: [],
		stats: null,
		tasks: [],
		filter: { vacancy: "", status: "", decision: "", q: "" },
		sort: "control-desc",
		selected: null,
		bundles: {},
		compare: false,
		picked: [],
		fileCode: "",
		fileName: "",
		sendProtocolId: "",
	}

	function $(id) {
		return document.getElementById(id)
	}
	function esc(value) {
		return P.esc(value === undefined || value === null ? "" : String(value))
	}
	function readJson(key, fallback) {
		try {
			var raw = localStorage.getItem(key)
			return raw ? JSON.parse(raw) : fallback
		} catch (e) {
			return fallback
		}
	}
	function writeJson(key, value) {
		try {
			localStorage.setItem(key, JSON.stringify(value))
		} catch (e) {
			/* приватный режим — молча живём без памяти */
		}
	}
	function decisions() {
		return readJson(LS_DECISIONS, {}) || {}
	}
	function decisionOf(id) {
		var map = decisions()
		return map[id] ? map[id].decision : ""
	}
	function decisionLabel(value) {
		if (value === "invited") return "Приглашён"
		if (value === "rejected") return "Отказ"
		return "Без решения"
	}
	function bar(pct) {
		var cls = P.barClass(pct)
		return (
			'<div class="cab-bar ' + cls + '"><i style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></div>'
		)
	}

	/* ------------------------------------------------------------- боковое меню */
	function renderSide() {
		var vacNav = $("vacNav")
		var html = sideItem("vacancy", "", "Все кандидаты", S.rows.length)
		S.vacancies.forEach(function (vacancy) {
			var count = S.rows.filter(function (row) {
				return row.vacancy_id === vacancy.id
			}).length
			html += sideItem("vacancy", vacancy.id, vacancy.title, count)
		})
		vacNav.innerHTML = html

		var statuses = {}
		S.rows.forEach(function (row) {
			statuses[row.status] = (statuses[row.status] || 0) + 1
		})
		var statusHtml = sideItem("status", "", "Любой статус", S.rows.length)
		Object.keys(statuses).forEach(function (name) {
			statusHtml += sideItem("status", name, name, statuses[name])
		})
		$("statusNav").innerHTML = statusHtml

		var map = decisions()
		var counts = { invited: 0, rejected: 0, none: 0 }
		S.rows.forEach(function (row) {
			var value = map[row.id] ? map[row.id].decision : ""
			counts[value || "none"] = (counts[value || "none"] || 0) + 1
		})
		var decHtml = sideItem("decision", "", "Все", S.rows.length)
		decHtml += sideItem("decision", "invited", "Приглашёны", counts.invited)
		decHtml += sideItem("decision", "rejected", "Отказано", counts.rejected)
		decHtml += sideItem("decision", "none", "Без решения", counts.none)
		$("decisionNav").innerHTML = decHtml
	}
	function sideItem(kind, value, label, count) {
		var active = S.filter[kind] === value ? " is-active" : ""
		return (
			'<button class="side-item' +
			active +
			'" type="button" data-filter="' +
			kind +
			'" data-value="' +
			P.escAttr(value) +
			'"><span>' +
			esc(label) +
			'</span><span class="side-count">' +
			count +
			"</span></button>"
		)
	}

	/* --------------------------------------------------------------------- KPI */
	function renderKpi() {
		var shown = visibleRows()
		var stats = S.stats || {}
		var avg = shown.length
			? Math.round(
					shown.reduce(function (sum, row) {
						return sum + (row.control_pct || 0)
					}, 0) / shown.length
			  )
			: 0
		var passed = shown.filter(function (row) {
			return row.passed
		}).length
		var risky = shown.filter(function (row) {
			return !row.passed
		}).length
		$("kpi").innerHTML =
			stat(shown.length, "кандидатов в выборке") +
			stat(passed, "понимание подтверждено") +
			stat(risky, "требуют разбора") +
			stat(avg + " %", "средний контроль") +
			stat((stats.saved_hours || shown.length * 2) + " ч", "сэкономлено senior-времени")
	}
	function stat(value, label) {
		return '<div class="stat"><div class="stat-num">' + esc(value) + '</div><div class="stat-label">' + esc(label) + "</div></div>"
	}

	/* ------------------------------------------------------------------ таблица */
	function visibleRows() {
		var query = S.filter.q.trim().toLowerCase()
		var map = decisions()
		var rows = S.rows.filter(function (row) {
			if (S.filter.vacancy && row.vacancy_id !== S.filter.vacancy) return false
			if (S.filter.status && row.status !== S.filter.status) return false
			if (S.filter.decision) {
				var value = map[row.id] ? map[row.id].decision : ""
				if (S.filter.decision === "none" ? value : value !== S.filter.decision) return false
			}
			if (query) {
				var blob = [row.name, row.vacancy, row.task, row.status, row.verdict, row.source].join(" ").toLowerCase()
				if (blob.indexOf(query) === -1) return false
			}
			return true
		})
		rows.sort(function (a, b) {
			if (S.sort === "control-asc") return a.control_pct - b.control_pct
			if (S.sort === "date-desc") return String(b.submitted).localeCompare(String(a.submitted))
			if (S.sort === "risks-desc") return (b.risks || 0) - (a.risks || 0)
			if (S.sort === "name-asc") return String(a.name).localeCompare(String(b.name), "ru")
			return b.control_pct - a.control_pct
		})
		return rows
	}

	function renderRows() {
		var rows = visibleRows()
		var body = $("candRows")
		var hiddenCol = S.compare ? "" : " hidden"
		var head = document.querySelector("#tableHead .cab-cmp-col")
		if (head) head.className = "cab-cmp-col" + hiddenCol
		$("rowsMeta").textContent = rows.length + " из " + S.rows.length

		if (!rows.length) {
			body.innerHTML = '<tr><td colspan="7" class="cab-empty">Ничего не нашлось. Снимите фильтр или очистите поиск.</td></tr>'
			return
		}
		body.innerHTML = rows
			.map(function (row) {
				var decision = decisionOf(row.id)
				var chip =
					row.status === "Протокол готов" ? "chip-teal" : row.passed ? "chip-blue" : "chip-amber"
				var risks =
					'<span class="chip ' +
					(row.risks > 6 ? "chip-red" : row.risks > 3 ? "chip-amber" : "chip-teal") +
					'">' +
					esc(row.risks) +
					" найдено</span>" +
					(row.survived ? ' <span class="chip chip-red">' + esc(row.survived) + " выжило</span>" : "")
				return (
					'<tr data-id="' +
					P.escAttr(row.id) +
					'" class="' +
					(S.selected === row.id ? "is-selected" : "") +
					'">' +
					'<td class="cab-cmp-col' +
					hiddenCol +
					'"><input class="cab-check" type="checkbox" data-pick="' +
					P.escAttr(row.id) +
					'"' +
					(S.picked.indexOf(row.id) >= 0 ? " checked" : "") +
					" /></td>" +
					"<td><span class=\"cab-name\">" +
					esc(row.name) +
					'</span><span class="cab-sub">' +
					esc(row.source) +
					(decision ? " · " + esc(decisionLabel(decision)) : "") +
					"</span></td>" +
					"<td>" +
					esc(row.vacancy) +
					'<span class="cab-sub">' +
					esc(row.task) +
					"</span></td>" +
					'<td class="mono tiny">' +
					esc(row.submitted) +
					"</td>" +
					'<td><div class="row" style="gap:8px;align-items:center"><span class="cab-pct">' +
					esc(row.control_pct) +
					" %</span>" +
					bar(row.control_pct) +
					"</div></td>" +
					"<td>" +
					risks +
					"</td>" +
					'<td><span class="chip ' +
					chip +
					'">' +
					esc(row.status) +
					"</span></td>" +
					"</tr>"
				)
			})
			.join("")
	}

	/* ------------------------------------------------------------ карточка справа */
	function selectRow(id) {
		S.selected = id
		renderRows()
		var host = $("detail")
		if (S.bundles[id]) {
			renderDetail(S.bundles[id])
			return
		}
		host.innerHTML = '<div class="card"><p class="cab-empty mb-0">Грузим протокол…</p></div>'
		P.api
			.candidate(id)
			.then(function (bundle) {
				S.bundles[id] = bundle
				if (S.selected === id) renderDetail(bundle)
			})
			.catch(function (error) {
				host.innerHTML = '<div class="card"><p class="cab-empty mb-0">' + esc(error.message) + "</p></div>"
			})
	}

	function renderDetail(bundle) {
		var candidate = bundle.candidate || {}
		var protocol = bundle.protocol || {}
		var summary = bundle.summary || {}
		var verdict = protocol.verdict || {}
		var mutation = protocol.mutation || {}
		var questions = protocol.questions || {}
		var decision = decisionOf(candidate.id)

		var skills = (protocol.skills || [])
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
			.join("")

		var risks = (protocol.risks || [])
			.map(function (risk) {
				return (
					'<div class="cab-risk' +
					(String(risk.kind).indexOf("дыра") >= 0 ? " is-gap" : "") +
					'"><span class="chip chip-red">' +
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
			.join("")

		var timeline = (protocol.timeline || [])
			.map(function (item) {
				return (
					'<div class="cab-tl-item"><span class="cab-tl-dot' +
					(item.correct ? "" : " is-miss") +
					'"></span><span>' +
					'<span class="mono tiny dim">' +
					esc(item.mutation) +
					"</span> " +
					esc(item.result) +
					' <span class="cab-sub">· ' +
					esc(item.skill) +
					"</span></span>" +
					'<span class="cab-tl-time">' +
					esc(item.clock) +
					"</span></div>"
				)
			})
			.join("")

		var quote = quoteHtml(bundle)

		$("detail").innerHTML =
			'<div class="stack">' +
			'<div class="card card-glow">' +
			'<div class="card-head"><div><h3 class="card-title mb-0">' +
			esc(candidate.name) +
			'</h3><span class="cab-sub">' +
			esc(candidate.vacancy) +
			" · " +
			esc(candidate.submitted) +
			"</span></div>" +
			'<span class="chip ' +
			(summary.passed ? "chip-teal" : "chip-red") +
			'">' +
			esc(summary.passed ? "допуск" : "разбор") +
			"</span></div>" +
			'<div class="gauge" id="detailGauge">' +
			'<svg width="148" height="148" viewBox="0 0 148 148"><circle class="gauge-c gauge-bg" cx="74" cy="74" r="62"></circle><circle class="gauge-c gauge-fg" cx="74" cy="74" r="62"></circle></svg>' +
			'<div class="gauge-val"><div><b>0</b><span>контроль понимания</span></div></div></div>' +
			'<p class="center small mb-0 mt-16 ' +
			P.verdictClass(verdict.level) +
			'">' +
			esc(verdict.label) +
			"</p>" +
			'<p class="center tiny dim mt-8 mb-0">порог допуска ' +
			esc(protocol.pass_threshold_pct) +
			" % · мутационный счёт " +
			esc(mutation.score_pct) +
			" %</p>" +
			'<p class="small dim" style="margin-top:14px">' +
			esc(verdict.summary) +
			"</p>" +
			'<dl class="cab-kv" style="margin-top:14px">' +
			kv("Задача", candidate.task) +
			kv("Мутаций", mutation.total + " · сломано " + mutation.killed + " · выжило " + mutation.survived) +
			kv("Вопросов", questions.correct + " верно из " + questions.total) +
			kv("Отпечаток", protocol.fingerprint) +
			kv("Решение", decisionLabel(decision)) +
			"</dl>" +
			'<div class="cab-actions" style="margin-top:16px">' +
			'<button class="btn btn-teal btn-sm" type="button" data-act="invite">Пригласить на собес</button>' +
			'<button class="btn btn-danger btn-sm" type="button" data-act="reject">Отклонить</button>' +
			'<button class="btn btn-quiet btn-sm" type="button" data-act="pdf">Скачать PDF</button>' +
			'<button class="btn btn-quiet btn-sm" type="button" data-act="send">Отправить</button>' +
			'<button class="btn btn-ghost btn-sm" type="button" data-act="code">Посмотреть код</button>' +
			"</div></div>" +
			'<div class="card card-pad-sm"><div class="card-head"><h4 class="card-title mb-0">Протокол понимания</h4><span class="cab-sub">' +
			esc((protocol.skills || []).length) +
			" навыков</span></div>" +
			(skills || '<p class="cab-empty mb-0">Нет данных</p>') +
			"</div>" +
			'<div class="card card-pad-sm"><h4 class="card-title mb-16">Цитата из мутации</h4>' +
			quote +
			"</div>" +
			'<div class="card card-pad-sm"><h4 class="card-title mb-16">Риски</h4>' +
			(risks || '<p class="cab-empty mb-0">Рисков не найдено</p>') +
			"</div>" +
			'<div class="card card-pad-sm"><h4 class="card-title mb-16">Таймлайн сессии</h4><div class="cab-tl">' +
			(timeline || '<p class="cab-empty mb-0">Сессия не проводилась</p>') +
			"</div></div>" +
			"</div>"

		var gaugeEl = $("detailGauge")
		if (gaugeEl) P.gauge(gaugeEl, Number(protocol.control_pct || summary.control_pct || 0))
		P.tilt($("detail"))
	}
	function kv(key, value) {
		return "<dt>" + esc(key) + "</dt><dd>" + esc(value) + "</dd>"
	}
	function quoteHtml(bundle) {
		var protocol = bundle.protocol || {}
		var quote = (protocol.quotes || [])[0]
		var diff = quote && (quote.diff || quote.patch)
		if (!diff) {
			var gap = ((bundle.analysis || {}).gaps || [])[0]
			diff = gap && (gap.diff || gap.patch || gap.preview)
			if (!diff && gap) {
				diff = "- " + (gap.before || gap.original || "") + "\n+ " + (gap.after || gap.mutated || "")
			}
		}
		if (!diff) {
			var risk = (protocol.risks || [])[0]
			if (!risk) return '<p class="cab-empty mb-0">Нет выживших мутаций — набор тестов плотный.</p>'
			return (
				'<div class="cab-quote">' +
				esc(risk.mutation + " · строка " + risk.line + "\n" + risk.text) +
				"</div>"
			)
		}
		return '<div class="cab-quote">' + P.renderDiff(diff) + "</div>"
	}

	/* --------------------------------------------------------------- сравнение */
	function renderCompare() {
		var card = $("cmpCard")
		if (!S.compare) {
			card.classList.add("hidden")
			return
		}
		card.classList.remove("hidden")
		if (S.picked.length < 2) {
			$("cmpBody").innerHTML =
				'<p class="cab-empty mb-0">Отметьте двух кандидатов в таблице — покажу разницу по навыкам.</p>'
			return
		}
		Promise.all(
			S.picked.slice(0, 2).map(function (id) {
				return S.bundles[id]
					? Promise.resolve(S.bundles[id])
					: P.api.candidate(id).then(function (bundle) {
							S.bundles[id] = bundle
							return bundle
					  })
			})
		).then(function (pair) {
			var left = pair[0]
			var right = pair[1]
			var leftPct = Number((left.protocol || {}).control_pct || 0)
			var rightPct = Number((right.protocol || {}).control_pct || 0)
			var names = {}
			var order = []
			;[left, right].forEach(function (bundle, index) {
				((bundle.protocol || {}).skills || []).forEach(function (skill) {
					if (!names[skill.title]) {
						names[skill.title] = [0, 0]
						order.push(skill.title)
					}
					names[skill.title][index] = Number(skill.score_pct || 0)
				})
			})
			var rows = order
				.map(function (title) {
					var a = names[title][0]
					var b = names[title][1]
					return (
						'<div class="cmp-row">' +
						'<div><div class="cmp-bar is-left"><i style="width:' +
						a +
						'%"></i></div><div class="tiny dim" style="text-align:right">' +
						a +
						" %</div></div>" +
						'<div class="cmp-skill">' +
						esc(title) +
						"</div>" +
						'<div><div class="cmp-bar is-right"><i style="width:' +
						b +
						'%"></i></div><div class="tiny dim">' +
						b +
						" %</div></div>" +
						"</div>"
					)
				})
				.join("")
			var leader = leftPct === rightPct ? "паритет" : leftPct > rightPct ? left.candidate.name : right.candidate.name
			$("cmpBody").innerHTML =
				'<div class="cmp-head">' +
				'<div><b>' +
				esc(left.candidate.name) +
				'</b><div class="tiny dim">контроль ' +
				leftPct +
				" %</div></div>" +
				'<div class="center"><span class="chip chip-teal">Лидер · ' +
				esc(leader) +
				"</span></div>" +
				'<div style="text-align:right"><b>' +
				esc(right.candidate.name) +
				'</b><div class="tiny dim">контроль ' +
				rightPct +
				" %</div></div>" +
				"</div>" +
				rows
		})
	}

	/* --------------------------------------------------------------------- CSV */
	function exportCsv() {
		var rows = visibleRows()
		if (!rows.length) {
			P.toast("Нет строк для выгрузки", "err")
			return
		}
		var company = readJson(LS_COMPANY, {}) || {}
		var head = [
			"Кандидат",
			"Вакансия",
			"Задача",
			"Дата",
			"Контроль %",
			"Мутационный счёт %",
			"Выжило мутаций",
			"Рисков",
			"Статус",
			"Вердикт",
			"Решение",
			"Компания",
		]
		var lines = [head]
		rows.forEach(function (row) {
			lines.push([
				row.name,
				row.vacancy,
				row.task,
				row.submitted,
				row.control_pct,
				row.mutation_score_pct,
				row.survived,
				row.risks,
				row.status,
				row.verdict,
				decisionLabel(decisionOf(row.id)),
				company.name || "",
			])
		})
		var csv = lines
			.map(function (line) {
				return line
					.map(function (cell) {
						var text = cell === undefined || cell === null ? "" : String(cell)
						return '"' + text.replace(/"/g, '""') + '"'
					})
					.join(";")
			})
			.join("\r\n")
		var blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" })
		var url = URL.createObjectURL(blob)
		var link = document.createElement("a")
		link.href = url
		link.download = "pruf-candidates.csv"
		document.body.appendChild(link)
		link.click()
		document.body.removeChild(link)
		setTimeout(function () {
			URL.revokeObjectURL(url)
		}, 1000)
		P.toast("CSV с " + rows.length + " строками выгружен", "ok")
	}

	/* ------------------------------------------------------------ новая проверка */
	function checkLink() {
		var vacancyId = $("checkVacancy").value
		var vacancy = S.vacancies.filter(function (item) {
			return item.id === vacancyId
		})[0]
		var task = vacancy ? vacancy.task : "orders"
		var minutes = $("checkMinutes").value
		return location.origin + "/studio.html?task=" + encodeURIComponent(task) + "&minutes=" + encodeURIComponent(minutes)
	}
	function showLink() {
		var link = checkLink()
		$("checkLink").textContent = link
		$("btnOpenLink").href = link
		$("checkLinkBox").classList.remove("hidden")
		P.toast("Ссылка готова", "ok")
	}
	function sendCheck() {
		var name = $("checkName").value.trim()
		var email = $("checkEmail").value.trim()
		var company = readJson(LS_COMPANY, {}) || {}
		var vacancyId = $("checkVacancy").value
		var vacancy = S.vacancies.filter(function (item) {
			return item.id === vacancyId
		})[0]
		if (!name) {
			P.toast("Укажите имя кандидата", "err")
			return
		}
		if (email.indexOf("@") === -1) {
			P.toast("Нужен корректный e-mail", "err")
			return
		}
		P.api
			.lead({
				name: name,
				email: email,
				company: company.name || "",
				plan: "Проверка: " + (vacancy ? vacancy.title : vacancyId),
				comment: checkLink() + " · " + (company.note || ""),
			})
			.then(function () {
				showLink()
				P.toast("Приглашение сохранено в data/leads", "ok")
			})
			.catch(function (error) {
				P.toast(error.message, "err")
			})
	}
	function analyzeFile() {
		var vacancyId = $("checkVacancy").value
		var vacancy = S.vacancies.filter(function (item) {
			return item.id === vacancyId
		})[0]
		var taskId = vacancy ? vacancy.task : "orders"
		var task = S.tasks.filter(function (item) {
			return item.id === taskId
		})[0]
		if (!task) {
			P.toast("Не нашёл тесты для вакансии", "err")
			return
		}
		var out = $("analyzeOut")
		out.innerHTML = '<p class="cab-empty mb-0">Строим мутации и гоняем тесты в песочнице…</p>'
		P.api
			.analyze(S.fileCode, task.tests, 12)
			.then(function (data) {
				var analysis = data.analysis || data
				var verdict = analysis.verdict || {}
				var total = analysis.mutation_total || (analysis.mutations || []).length
				out.innerHTML =
					'<div class="stat-strip">' +
					stat(total, "мутаций построено") +
					stat(analysis.killed, "сломали тесты") +
					stat(analysis.survived, "прошли незамеченными") +
					stat((analysis.score_pct !== undefined ? analysis.score_pct : analysis.mutation_score_pct) + " %", "мутационный счёт") +
					"</div>" +
					'<p class="small" style="margin-top:12px">' +
					esc(verdict.label || "") +
					' <span class="dim">' +
					esc(verdict.summary || verdict.tests_note || "") +
					"</span></p>" +
					'<a class="btn btn-teal btn-sm" href="/studio.html?task=' +
					P.escAttr(taskId) +
					'">Открыть в студии и запустить сессию</a>'
				P.toast("Прогон завершён", "ok")
			})
			.catch(function (error) {
				out.innerHTML = '<p class="cab-empty mb-0">' + esc(error.message) + "</p>"
			})
	}

	/* -------------------------------------------------------------------- связка */
	function bind() {
		document.addEventListener("click", function (event) {
			var filterBtn = event.target.closest("[data-filter]")
			if (filterBtn) {
				S.filter[filterBtn.getAttribute("data-filter")] = filterBtn.getAttribute("data-value")
				renderSide()
				renderKpi()
				renderRows()
				return
			}
			var tab = event.target.closest("[data-ctab]")
			if (tab) {
				var name = tab.getAttribute("data-ctab")
				Array.prototype.forEach.call(document.querySelectorAll("[data-ctab]"), function (node) {
					node.classList.toggle("is-active", node === tab)
				})
				Array.prototype.forEach.call(document.querySelectorAll("[data-cpanel]"), function (node) {
					node.classList.toggle("hidden", node.getAttribute("data-cpanel") !== name)
				})
				return
			}
			var act = event.target.closest("[data-act]")
			if (act) {
				handleAct(act.getAttribute("data-act"))
				return
			}
			var pick = event.target.closest("[data-pick]")
			if (pick) {
				var id = pick.getAttribute("data-pick")
				var at = S.picked.indexOf(id)
				if (at >= 0) S.picked.splice(at, 1)
				else {
					S.picked.push(id)
					if (S.picked.length > 2) S.picked.shift()
				}
				renderRows()
				renderCompare()
				event.stopPropagation()
				return
			}
			var row = event.target.closest("tr[data-id]")
			if (row) selectRow(row.getAttribute("data-id"))
		})

		$("search").addEventListener("input", function (event) {
			S.filter.q = event.target.value
			renderKpi()
			renderRows()
		})
		$("sort").addEventListener("change", function (event) {
			S.sort = event.target.value
			renderRows()
		})
		$("btnCompare").addEventListener("click", function () {
			S.compare = !S.compare
			$("btnCompare").classList.toggle("is-active", S.compare)
			$("btnCompare").textContent = S.compare ? "Выйти из сравнения" : "Сравнить"
			renderRows()
			renderCompare()
		})
		$("cmpClear").addEventListener("click", function () {
			S.picked = []
			renderRows()
			renderCompare()
		})
		$("btnCsv").addEventListener("click", exportCsv)
		$("btnLink").addEventListener("click", showLink)
		$("btnSendCheck").addEventListener("click", sendCheck)
		$("btnCopyLink").addEventListener("click", function () {
			P.copy($("checkLink").textContent)
		})
		$("btnAnalyze").addEventListener("click", analyzeFile)
		$("checkFile").addEventListener("change", function (event) {
			var file = event.target.files && event.target.files[0]
			if (!file) return
			var reader = new FileReader()
			reader.onload = function () {
				S.fileCode = String(reader.result || "")
				S.fileName = file.name
				$("fileMeta").textContent = file.name + " · " + S.fileCode.split("\n").length + " строк"
				$("btnAnalyze").disabled = false
			}
			reader.readAsText(file)
		})
		$("btnCoSave").addEventListener("click", function () {
			writeJson(LS_COMPANY, { name: $("coName").value, email: $("coEmail").value, note: $("coNote").value })
			P.modal("modal-company", false)
			P.toast("Профиль компании сохранён", "ok")
		})
		$("btnSetSave").addEventListener("click", function () {
			writeJson(LS_SETTINGS, {
				pass: Number($("setPass").value),
				mutations: Number($("setMuts").value),
				language: $("setLang").value,
			})
			P.modal("modal-settings", false)
			P.toast("Настройки сохранены", "ok")
		})
		$("btnSendProtocol").addEventListener("click", function () {
			var email = $("sendEmail").value.trim()
			if (!S.sendProtocolId) {
				P.toast("Сначала выберите кандидата", "err")
				return
			}
			P.api
				.protocolSend(S.sendProtocolId, email)
				.then(function (data) {
					P.modal("modal-send", false)
					P.toast(data.message || "Протокол в очереди", "ok")
				})
				.catch(function (error) {
					P.toast(error.message, "err")
				})
		})
	}

	function handleAct(act) {
		var bundle = S.bundles[S.selected]
		if (!bundle) return
		var protocolId = (bundle.protocol || {}).id
		if (act === "invite" || act === "reject") {
			var map = decisions()
			map[S.selected] = { decision: act === "invite" ? "invited" : "rejected", at: Date.now() }
			writeJson(LS_DECISIONS, map)
			renderSide()
			renderRows()
			renderDetail(bundle)
			P.toast(act === "invite" ? "Кандидат приглашён на собес" : "Кандидат отклонён", "ok")
			return
		}
		if (act === "pdf") {
			window.open("/api/protocol/" + encodeURIComponent(protocolId) + ".pdf", "_blank")
			return
		}
		if (act === "send") {
			S.sendProtocolId = protocolId
			$("sendTitle").textContent = "Отправить протокол: " + (bundle.candidate || {}).name
			P.modal("modal-send", true)
			return
		}
		if (act === "code") {
			$("codeTitle").textContent = "solution.py · " + (bundle.candidate || {}).name
			$("codeBody").textContent = bundle.code || "Код недоступен"
			P.modal("modal-code", true)
		}
	}

	function fillForms() {
		var company = readJson(LS_COMPANY, {}) || {}
		$("coName").value = company.name || ""
		$("coEmail").value = company.email || ""
		$("coNote").value = company.note || ""
		var settings = readJson(LS_SETTINGS, {}) || {}
		if (settings.pass) $("setPass").value = settings.pass
		if (settings.mutations) $("setMuts").value = settings.mutations
		if (settings.language) $("setLang").value = settings.language
		$("checkVacancy").innerHTML = S.vacancies
			.map(function (vacancy) {
				return '<option value="' + P.escAttr(vacancy.id) + '">' + esc(vacancy.title + " · " + vacancy.team) + "</option>"
			})
			.join("")
	}

	function boot() {
		bind()
		P.api
			.candidates()
			.then(function (data) {
				S.rows = data.candidates || []
				S.vacancies = data.vacancies || []
				S.stats = data.stats || null
				renderSide()
				renderKpi()
				renderRows()
				fillForms()
				var wanted = P.qs("id", "")
				var first = S.rows.filter(function (row) {
					return row.id === wanted
				})[0] || visibleRows()[0]
				if (first) selectRow(first.id)
			})
			.catch(function (error) {
				$("candRows").innerHTML = '<tr><td colspan="7" class="cab-empty">' + esc(error.message) + "</td></tr>"
			})
		P.api
			.tasks()
			.then(function (data) {
				S.tasks = data.tasks || []
			})
			.catch(function () {
				S.tasks = []
			})
		P.api
			.health()
			.then(function (data) {
				var label = data.engine || data.schema || "ядро активно"
				$("engineChip").innerHTML = '<span class="dot"></span> ' + esc(label) + " · изолятор активен"
			})
			.catch(function () {
				$("engineChip").innerHTML = '<span class="dot"></span> ядро недоступно'
			})
	}

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot)
	else boot()
})()
