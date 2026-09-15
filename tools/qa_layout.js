/**
 * ПРУФ · быстрая проверка вёрстки (без кликов, ~30 секунд).
 *
 *   node tools/qa_layout.js [--base http://127.0.0.1:8777]
 *
 * Проверяет две разные боли на каждой странице при 390px и 1440px:
 *   • страница реально ездит вбок (window.scrollX после scrollTo) — это видит пользователь;
 *   • контент обрезан за краем экрана без скроллируемого предка — текст пропадает насовсем.
 * Содержимое блоков с overflow: auto (например .code-body) легально выходит за границу и не считается ошибкой.
 * Код возврата 0 — всё чисто, 1 — есть проблемы.
 */

const { chromium } = require("playwright")

const arg = (name, fallback) => {
	const index = process.argv.indexOf("--" + name)
	return index > -1 ? process.argv[index + 1] : fallback
}

const BASE = arg("base", "http://127.0.0.1:8777").replace(/\/$/, "")
const PAGES = [
	"/index.html",
	"/studio.html",
	"/session.html?demo=1",
	"/employer.html",
	"/candidate.html",
	"/docs.html",
]
const VIEWPORTS = [
	{ width: 390, height: 844 },
	{ width: 1440, height: 900 },
]

const PROBE = () => {
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
		cut: deepest.slice(0, 5).map((el) => {
			const rect = el.getBoundingClientRect()
			return sel(el) + " right=" + Math.round(rect.right)
		}),
	}
}

;(async () => {
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
	let bad = 0
	for (const viewport of VIEWPORTS) {
		const context = await browser.newContext({ viewport })
		for (const target of PAGES) {
			const page = await context.newPage()
			try {
				await page.goto(BASE + target, { waitUntil: "load", timeout: 40000 })
				await page.waitForTimeout(1300)
				const result = await page.evaluate(PROBE)
				const broken = result.scrolledX > 4 || result.cut.length > 0
				if (broken) bad += 1
				process.stdout.write(
					`${broken ? "BAD " : "ok  "}${viewport.width} ${target} · вбок=${result.scrolledX}` +
						(result.cut.length ? ` · обрезано: ${result.cut.join(" | ")}` : "") +
						"\n",
				)
			} catch (error) {
				bad += 1
				process.stdout.write(`ERR ${viewport.width} ${target} :: ${String(error.message).slice(0, 90)}\n`)
			}
			await page.close()
		}
		await context.close()
	}
	process.stdout.write(`\nПроверок: ${PAGES.length * VIEWPORTS.length} · проблемных: ${bad}\n`)
	process.exit(bad ? 1 : 0)
})().catch((error) => {
	console.error("Проверка вёрстки упала:", error)
	process.exit(2)
})
