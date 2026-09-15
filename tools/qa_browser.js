/**
 * ПРУФ · браузерная проверка: прокликивает каждую кнопку на каждой странице и ловит ошибки.
 *
 *   python3 -m engine.cli serve --port 8777 &
 *   node tools/qa_browser.js --base http://127.0.0.1:8777 --out /data/qa
 *
 * Для каждой кнопки страница загружается заново, поэтому порядок элементов детерминирован,
 * а клики не влияют друг на друга. После клика собираются ошибки консоли, необработанные
 * исключения, упавшие запросы и ответы 4xx/5xx. Скриншоты (1440px и 390px) складываются в --out.
 *
 * Код возврата 0 — все клики без ошибок, 1 — есть падения, 2 — сам прогон не смог стартовать.
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

	const failures = []
	let clicks = 0

	for (const target of PAGES) {
		if (ONLY && target.name !== ONLY) continue
		const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
		const page = await context.newPage()
		const loadBag = []
		listen(page, loadBag)

		process.stdout.write(`\n── ${target.name} (${target.url})\n`)
		await page.goto(BASE + target.url, { waitUntil: "load", timeout: 45000 })
		await page.waitForTimeout(2200)
		await page.screenshot({ path: `${OUT}/${target.name}-desktop.png`, fullPage: true })
		if (loadBag.length) {
			process.stdout.write("  FAIL загрузка страницы\n")
			loadBag.forEach((line) => process.stdout.write(`        → ${line}\n`))
			failures.push({ page: target.name, what: "загрузка страницы", errors: [...loadBag] })
		} else {
			process.stdout.write("  ok   загрузка без ошибок\n")
		}

		await page.setViewportSize({ width: 390, height: 844 })
		await page.waitForTimeout(900)
		await page.screenshot({ path: `${OUT}/${target.name}-mobile.png`, fullPage: true })
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - window.innerWidth,
		)
		if (overflow > 4) {
			process.stdout.write(`  FAIL горизонтальная прокрутка на 390px: +${overflow}px\n`)
			failures.push({
				page: target.name,
				what: `горизонтальная прокрутка +${overflow}px на 390px`,
				errors: [],
			})
		} else {
			process.stdout.write("  ok   без горизонтальной прокрутки на 390px\n")
		}

		const items = (await collect(page)).filter((item) => item.visible && !item.disabled)
		process.stdout.write(`  кнопок и вкладок к проверке: ${items.length}\n`)
		await page.close()

		for (const item of items) {
			const bag = []
			const clickPage = await context.newPage()
			listen(clickPage, bag)
			try {
				await clickPage.goto(BASE + target.url, { waitUntil: "load", timeout: 45000 })
				await clickPage.waitForTimeout(1100)
				bag.length = 0 // ошибки загрузки уже учтены выше
				const handles = await clickPage.$$(CLICKABLE)
				const handle = handles[item.index]
				if (!handle) throw new Error("элемент не найден после перезагрузки")
				const before = clickPage.url()
				await handle.click({ timeout: 4000 })
				await clickPage.waitForTimeout(800)
				const after = clickPage.url()
				const moved = after !== before ? ` → ${after.replace(BASE, "")}` : ""
				clicks += 1
				if (bag.length) {
					process.stdout.write(`  FAIL ${describe(item)}${moved}\n`)
					bag.forEach((line) => process.stdout.write(`        → ${line}\n`))
					failures.push({ page: target.name, what: describe(item), errors: [...bag] })
				} else {
					process.stdout.write(`  ok   ${describe(item)}${moved}\n`)
				}
			} catch (error) {
				process.stdout.write(`  FAIL ${describe(item)} :: ${String(error.message).slice(0, 140)}\n`)
				failures.push({
					page: target.name,
					what: describe(item),
					errors: [String(error.message).slice(0, 220)],
				})
			} finally {
				await clickPage.close()
			}
		}
		await context.close()
	}

	fs.writeFileSync(`${OUT}/report.json`, JSON.stringify({ clicks, failures }, null, 2), "utf8")
	process.stdout.write("\n" + "=".repeat(64) + "\n")
	process.stdout.write(`Кликов проверено: ${clicks} · падений: ${failures.length}\n`)
	failures.forEach((item) => process.stdout.write(`  · ${item.page}: ${item.what}\n`))
	process.stdout.write("=".repeat(64) + "\n")
	process.exit(failures.length ? 1 : 0)
})().catch((error) => {
	console.error("QA упал:", error)
	process.exit(2)
})
