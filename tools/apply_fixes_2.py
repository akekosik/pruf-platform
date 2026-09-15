# -*- coding: utf-8 -*-
"""ПРУФ · правки 0.9.2 поверх свежего клона.

Запуск: python3 tools/apply_fixes_2.py
Скрипт идемпотентен — повторный запуск ничего не ломает.
Порядок восстановления: apply_fixes.py → apply_fixes_2.py (или просто tools/restore.sh).
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

CSS_MARK = "0.9.2 · код прокручивается внутри своей карточки"
CSS_BLOCK = """
/* ----------------------------------------------------------------------------
   0.9.2 · код прокручивается внутри своей карточки, а не тянет страницу
   ---------------------------------------------------------------------------- */
.code-body { overflow-x: auto; max-width: 100%; overscroll-behavior-x: contain; }
.code-line { min-width: max-content; }
.code-wrap, .code-card, .panel, .card { min-width: 0; }
@media (max-width: 620px) {
\t.code-body { font-size: 12px; }
\t.code-line { gap: 10px; padding: 0 12px; }
}
/* если JS не загрузился — секции видны без анимации появления */
html:not(.has-js) .reveal { opacity: 1 !important; transform: none !important; }
"""

JS_OLD = '\tfunction reveal(root) {\n\t\tvar nodes = (root || document).querySelectorAll(".reveal")\n'
JS_NEW = (
	'\tfunction reveal(root) {\n'
	'\t\t// без JS контент обязан остаться видимым: класс включает стартовую прозрачность\n'
	'\t\tdocument.documentElement.classList.add("has-js")\n'
	'\t\tvar nodes = (root || document).querySelectorAll(".reveal")\n'
)


def patch_css() -> str:
	path = ROOT / "web" / "css" / "app.css"
	text = path.read_text(encoding="utf-8")
	if CSS_MARK in text:
		return "already"
	path.write_text(text.rstrip("\n") + "\n" + CSS_BLOCK, encoding="utf-8")
	return "applied"


def patch_reveal() -> str:
	path = ROOT / "web" / "js" / "app.js"
	text = path.read_text(encoding="utf-8")
	if "has-js" in text:
		return "already"
	if text.count(JS_OLD) != 1:
		return "missing-anchor"
	path.write_text(text.replace(JS_OLD, JS_NEW), encoding="utf-8")
	return "applied"


def main() -> int:
	steps = (
		("код прокручивается внутри карточки (мобильная верстка)", patch_css),
		("секции видны без JS (класс has-js)", patch_reveal),
	)
	applied = already = broken = 0
	for title, step in steps:
		try:
			result = step()
		except Exception as error:  # noqa: BLE001
			result = "error: %s" % error
		if result == "applied":
			applied += 1
			print("  применено   %s" % title)
		elif result == "already":
			already += 1
			print("  уже было    %s" % title)
		else:
			broken += 1
			print("  НЕ СМОГ    %s — %s" % (title, result))
	print("Итого 0.9.2: применено %d, уже было %d, не смог %d из %d" % (applied, already, broken, len(steps)))
	return 1 if broken else 0


if __name__ == "__main__":
	sys.exit(main())
