/**
 * ПРУФ · браузерная проверка: прокликивает каждую кнопку на каждой странице и ловит ошибки.
 *
 *   python3 -m engine.cli serve --port 8777 &
 *   node tools/qa_browser.js --base http://127.0.0.1:8777 --out /data/qa [--only landing]
 *
 * На каждой странице:
 *   1. загрузка, пролистывание до конца (чтобы сработали reveal-анимации), скриншот 1440px;
 *   2. то же на 390px + две разные проверки верстки:
 *        • страница реально ездит вбок (window.scrollX после scrollTo);
 *        • контент обрезан за краем экрана (элементы вне viewport без скроллируемого предка);
 *   3. клик по каждой видимой кнопке на десктопе, каждый раз на свежей странице;
 *   4. добор кнопок, которые есть только в мобильной верстке (бургер и прочее) — в контексте 390px.
 *
 * Клик, перекрытый открытым модальным окном, — не ошибка, а ожидаемое поведение (пометка skip).
 * Код возврата 0 — всё чисто, 1 — есть падения, 2 — прогон не стартовал.
 */

const { chromium } = require("playwright")
const fs = require("fs")

const arg = (name, fallback) => {
	const index = process.argv.indexOf("--" + name)
	return index > -1 ? process.argv[index + 1] : fallback
}

const BASE = arg("base", "http://127.0.0.1:8777").replace(/\/$/, "")
const OUT = arg("out", "/data/qa")
const ONLY = arg("only", "")

const DESKTOP = { width: 1440, height: 900 }
const MOBILE = { width: 390, height: 844 }

const PAGES = [
	{ name: "landing", url: "/index.html" },
	{ name: "studio", url: "/studio.html" },
	{ name: "session", url: "/session.html?demo=1" },
	{ name: "employer", url: "/employer.html" },
	{ name: "candidate", url: "/candidate.html" },
	{ name: "docs", url: "/docs.html" },
]

const CLICKABLE =
	'button, [role="button"], .btn, .tab, [data-act], [data-tab], [data-view], [data-plan], input[type="submit"], a[href^="#"]'

const IGNORE = [/favicon/i, /React DevTools/i]

const failures = []
const skipped = []
let clicks = 0

function listen(page, bag) {
	page.on("console", (message) => {
		if (message.type() !== "error") return
		const text = message.text()
		if (IGNORE.some((re) => re.test(text))) return
		bag.push("console: " + text.slice(0, 220))
	})
	page.on("pageerror", (error) => bag.push("pageerror: " + String(error.message).slice(0, 220)))
	page.on("requestfailed", (request) => {
		const url = request.url().replace(BASE, "")
		if (IGNORE.some((re) => re.test(url))) return
		bag.push("requestfailed: " + url + " :: " + ((request.failure() || {}).errorText || ""))
	})
	page.on("response", (response) => {
		if (response.status() < 400) return
		const url = response.url().replace(BASE, "")
		if (IGNORE.some((re) => re.test(url))) return
		bag.push("http " + response.status() + ": " + url)
	})
}

const describe = (item) =>
	`${item.tag}${item.id ? "#" + item.id : ""}${item.text ? ' "' + item.text + '"' : ""}`
const keyOf = (item) => `${item.tag}|${item.id}|${item.text}`

async function collect(page) {
	return page.$$eval(CLICKABLE, (nodes) =>
		nodes.map((node, index) => {
			const rect = node.getBoundingClientRect()
			const style = window.getComputedStyle(node)
			return {
				index,
				tag: node.tagName.toLowerCase(),
				id: node.id || "",
				text: (node.innerText || node.value || node.getAttribute("aria-label") || "")
					.trim()
					.replace(/\s+/g, " ")
					.slice(0, 44),
				visible:
					rect.width > 0 &&
					rect.height > 0 &&
					style.visibility !== "hidden" &&
					style.display !== "none" &&
					Number(style.opacity) > 0.05,
				disabled: !!node.disabled,
			}
		}),
	)
}

// Пролистываем страницу сверху вниз и обратно — иначе reveal-секции останутся прозрачными.
async function scrollThrough(page) {
	await page.evaluate(async () => {
		const step = Math.max(240, window.innerHeight * 0.8)
		const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
		for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
			window.scrollTo(0, y)
			await wait(160)
		}
		window.scrollTo(0, 0)
		await wait(200)
	})
	await page.waitForTimeout(700)
}

/**
 * Две разные боли вместо одной неточной метрики scrollWidth:
 *   scrolledX — страница действительно ездит вбок (видит пользователь);
 *   cut       — элементы за краем экрана, у которых нет прокручиваемого предка — текст обрезан насовсем.
 * Код внутри блока с overflow: auto легально выходит за границу — его прокрутит карточка.
 */
async function layoutCheck(page) {
	return page.evaluate(() => {
		const W = window.innerWidth
		const clipRe = /(auto|hidden|scroll|clip)/
		const clipped = (el) => {
			let node = el.parentElement
			while (node && node !== document.body) {
				const style = getComputedStyle(node)
				if (clipRe.test(style.overflowX) || clipRe.test(style.overflow)) return true
				node = node.parentElement
			}
			return false
		}
		const sel = (el) =>
			el.tagName.toLowerCase() +
			(el.id ? "#" + el.id : "") +
			(typeof el.className === "string" && el.className.trim()
				? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".")
				: "")
		const all = Array.prototype.slice.call(document.querySelectorAll("body *"))
		const over = all.filter((el) => {
			const rect = el.getBoundingClientRect()
			return rect.right > W + 4 && rect.width > 0 && rect.height > 0 && !clipped(el)
		})
		const deepest = over.filter((el) => !over.some((other) => other !== el && el.contains(other)))
		window.scrollTo(2000, 0)
		const scrolledX = Math.round(window.scrollX)
		window.scrollTo(0, 0)
		return {
			scrolledX,
			cut: deepest.slice(0, 8).map((el) => {
				const rect = el.getBoundingClientRect()
				return sel(el) + " w=" + Math.round(rect.width) + " right=" + Math.round(rect.right)
			}),
		}
	})
}

const modalOpen = (page) =>
	page
		.evaluate(() => !!document.querySelector(".modal.is-open, .modal.open, .overlay.is-open"))
		.catch(() => false)

async function sweep(context, target, items, label) {
	for (const item of items) {
		const bag = []
		const page = await context.newPage()
		listen(page, bag)
		try {
			await page.goto(BASE + target.url, { waitUntil: "load", timeout: 45000 })
			await page.waitForTimeout(1100)
			bag.length = 0 // ошибки загрузки уже учтены отдельно
			const handles = await page.$$(CLICKABLE)
			const handle = handles[item.index]
			if (!handle) throw new Error("элемент не найден после перезагрузки")
			const before = page.url()
			await handle.click({ timeout: 4000 })
			await page.waitForTimeout(800)
			const moved = page.url() !== before ? ` → ${page.url().replace(BASE, "")}` : ""
			clicks += 1
			if (bag.length) {
				process.stdout.write(`  FAIL ${label} ${describe(item)}${moved}\n`)
				bag.forEach((line) => process.stdout.write(`        → ${line}\n`))
				failures.push({ page: target.name, view: label, what: describe(item), errors: [...bag] })
			} else {
				process.stdout.write(`  ok   ${label} ${describe(item)}${moved}\n`)
			}
		} catch (error) {
			const blocked = await modalOpen(page)
			const message = String(error.message).slice(0, 130)
			if (blocked) {
				process.stdout.write(`  skip ${label} ${describe(item)} — перекрыто модальным окном\n`)
				skipped.push({ page: target.name, view: label, what: describe(item), why: "модальное окно" })
			} else {
				process.stdout.write(`  FAIL ${label} ${describe(item)} :: ${message}\n`)
				failures.push({ page: target.name, view: label, what: describe(item), errors: [message] })
			}
		} finally {
			await page.close()
		}
	}
}

;(async () => {
	fs.mkdirSync(OUT, { recursive: true })
	const browser = await chromium.launch({
		executablePath: "/usr/local/bin/chromium",
		args: [
			"--no-sandbox",
			"--disable-dev-shm-usage",
			"--enable-unsafe-swiftshader",
			"--use-gl=angle",
			"--use-angle=swiftshader",
		],
	})

	for (const target of PAGES) {
		if (ONLY && target.name !== ONLY) continue
		process.stdout.write(`\n── ${target.name} (${target.url})\n`)

		/* --------------------------------------------------- десктоп 1440px */
		const deskContext = await browser.newContext({ viewport: DESKTOP })
		const desk = await deskContext.newPage()
		const loadBag = []
		listen(desk, loadBag)
		await desk.goto(BASE + target.url, { waitUntil: "load", timeout: 45000 })
		await desk.waitForTimeout(1800)
		await scrollThrough(desk)
		await desk.screenshot({ path: `${OUT}/${target.name}-desktop.png`, fullPage: true })
		if (loadBag.length) {
			process.stdout.write("  FAIL загрузка страницы\n")
			loadBag.forEach((line) => process.stdout.write(`        → ${line}\n`))
			failures.push({ page: target.name, view: "desktop", what: "загрузка страницы", errors: [...loadBag] })
		} else {
			process.stdout.write("  ok   загрузка без ошибок (1440px)\n")
		}
		const deskLayout = await layoutCheck(desk)
		if (deskLayout.cut.length) {
			process.stdout.write("  FAIL контент обрезан за краем экрана (1440px)\n")
			deskLayout.cut.forEach((line) => process.stdout.write(`        → ${line}\n`))
			failures.push({ page: target.name, view: "desktop", what: "контент обрезан", errors: deskLayout.cut })
		}
		const deskItems = (await collect(desk)).filter((item) => item.visible && !item.disabled)
		const deskKeys = new Set(deskItems.map(keyOf))
		await desk.close()

		/* ---------------------------------------------------- мобильный 390px */
		const mobContext = await browser.newContext({ viewport: MOBILE })
		const mob = await mobContext.newPage()
		const mobBag = []
		listen(mob, mobBag)
		await mob.goto(BASE + target.url, { waitUntil: "load", timeout: 45000 })
		await mob.waitForTimeout(1500)
		await scrollThrough(mob)
		await mob.screenshot({ path: `${OUT}/${target.name}-mobile.png`, fullPage: true })
		const mobLayout = await layoutCheck(mob)
		if (mobLayout.scrolledX > 4) {
			process.stdout.write(`  FAIL страница ездит вбок на 390px: ${mobLayout.scrolledX}px\n`)
			failures.push({
				page: target.name,
				view: "mobile",
				what: `горизонтальная прокрутка ${mobLayout.scrolledX}px`,
				errors: mobLayout.cut,
			})
		} else {
			process.stdout.write("  ok   страница не ездит вбок на 390px\n")
		}
		if (mobLayout.cut.length) {
			process.stdout.write("  FAIL контент обрезан за краем экрана (390px)\n")
			mobLayout.cut.forEach((line) => process.stdout.write(`        → ${line}\n`))
			failures.push({ page: target.name, view: "mobile", what: "контент обрезан", errors: mobLayout.cut })
		} else {
			process.stdout.write("  ok   ничего не обрезано на 390px\n")
		}
		const mobItems = (await collect(mob)).filter((item) => item.visible && !item.disabled)
		const mobileOnly = mobItems.filter((item) => !deskKeys.has(keyOf(item)))
		await mob.close()

		process.stdout.write(
			`  к проверке: ${deskItems.length} на десктопе + ${mobileOnly.length} только на мобильной\n`,
		)
		await sweep(deskContext, target, deskItems, "[1440]")
		await sweep(mobContext, target, mobileOnly, "[390]")
		await deskContext.close()
		await mobContext.close()
	}

	fs.writeFileSync(`${OUT}/report.json`, JSON.stringify({ clicks, failures, skipped }, null, 2), "utf8")
	process.stdout.write("\n" + "=".repeat(64) + "\n")
	process.stdout.write(
		`Кликов проверено: ${clicks} · падений: ${failures.length} · пропущено (модальные окна): ${skipped.length}\n`,
	)
	failures.forEach((item) => process.stdout.write(`  · ${item.page} ${item.view}: ${item.what}\n`))
	process.stdout.write("=".repeat(64) + "\n")
	process.exit(failures.length ? 1 : 0)
})().catch((error) => {
	console.error("QA упал:", error)
	process.exit(2)
})
