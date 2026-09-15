# -*- coding: utf-8 -*-
"""ПРУФ · правки 0.9.2–0.9.3 поверх свежего клона.

Запуск: python3 tools/apply_fixes_2.py
Скрипт идемпотентен — повторный запуск ничего не ломает.
Полное восстановление одной командой: bash tools/restore.sh
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINK = '<link rel="stylesheet" href="/css/fixes.css" />'
ANCHOR = 'var nodes = (root || document).querySelectorAll(".reveal")'


def patch_reveal() -> str:
	"""Без JS контент обязан остаться видимым: класс has-js включает reveal-анимации."""
	path = ROOT / "web" / "js" / "app.js"
	text = path.read_text(encoding="utf-8")
	if "has-js" in text:
		return "already"
	if text.count(ANCHOR) != 1:
		return "missing-anchor"
	insert = 'document.documentElement.classList.add("has-js")\n\t\t'
	path.write_text(text.replace(ANCHOR, insert + ANCHOR), encoding="utf-8")
	return "applied"


def patch_html() -> str:
	"""Подключает css/fixes.css последним в <head> каждой страницы."""
	touched = []
	for page in sorted((ROOT / "web").glob("*.html")):
		text = page.read_text(encoding="utf-8")
		if "css/fixes.css" in text:
			continue
		if "</head>" not in text:
			continue
		page.write_text(text.replace("</head>", LINK + "\n</head>", 1), encoding="utf-8")
		touched.append(page.name)
	if not touched:
		return "already"
	return "applied — %d стр." % len(touched)


def main() -> int:
	steps = (
		("секции видны без JS (класс has-js)", patch_reveal),
		("подключён css/fixes.css (мобильная верстка)", patch_html),
	)
	applied = already = broken = 0
	for title, step in steps:
		try:
			result = step()
		except Exception as error:  # noqa: BLE001
			result = "error: %s" % error
		if result.startswith("applied"):
			applied += 1
			print("  применено   %s %s" % (title, result.replace("applied", "").strip()))
		elif result == "already":
			already += 1
			print("  уже было    %s" % title)
		else:
			broken += 1
			print("  НЕ СМОГ    %s — %s" % (title, result))
	print(
		"Итого 0.9.3: применено %d, уже было %d, не смог %d из %d"
		% (applied, already, broken, len(steps))
	)
	return 1 if broken else 0


if __name__ == "__main__":
	sys.exit(main())
