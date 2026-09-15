# -*- coding: utf-8 -*-
"""ПРУФ · восстановление правок 0.9.1 одной командой.

Правки мелкие, но лежат внутри больших файлов (server/app.py, engine/*.py, web/js/*.js).
Если рабочая копия потерялась, вернуть их можно так:

    python3 tools/apply_fixes.py

Скрипт идемпотентен: повторный запуск печатает «уже применено» и ничего не меняет.
После того как правки вошли в main, файл остаётся как история и как проверка целостности —
если якорь не найден, значит файл разошёлся с ожидаемым состоянием.

Что именно исправляется:
  1. engine/session.py  — эталонный ответ не уходит клиенту до ответа на вопрос.
  2. engine/sandbox.py  — падение на импорте тестов считается проваленным прогоном.
  3. server/app.py      — импорты shutil/tempfile для сборки PDF.
  4. server/app.py      — render_pdf пишет файл, роут отдаёт байты; протоколы демо-кандидатов.
  5. server/app.py      — favicon отдаётся сервером (иначе 404 в консоли).
  6. web/js/app.js      — renderCode принимает и число, и массив подсвеченных строк.
  7. web/js/session.js  — подсветка строки мутации передаётся массивом.
"""

from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- 1. engine/session.py -------------------------------------------------

SESSION_OLD = '''        item = {key: value for key, value in question.items() if key not in {"correct", "explanation"}}
        answer = answers.get(question["id"])'''

SESSION_NEW = '''        # ключ "answer" в вопросе — это эталонный ответ, отдавать его до ответа нельзя
        item = {key: value for key, value in question.items() if key not in {"correct", "explanation", "answer"}}
        answer = answers.get(question["id"])'''

# --- 2. engine/sandbox.py -------------------------------------------------

SANDBOX_OLD = '''except BaseException as exc:
    report["import_error"] = short("%s: %s" % (type(exc).__name__, exc))
    report["stdout"] = short(buffer.getvalue(), 2000)
    emit()
    raise SystemExit(0)'''

SANDBOX_NEW = '''except BaseException as exc:
    report["import_error"] = short("%s: %s" % (type(exc).__name__, exc))
    report["stdout"] = short(buffer.getvalue(), 2000)
    # сломанное решение часто падает ещё на импорте тестов — это тоже проваленный прогон
    report["errored"] = 1
    report["tests"] = [{
        "name": "<импорт тестов>",
        "status": "errored",
        "message": report["import_error"],
        "duration_ms": 0,
    }]
    emit()
    raise SystemExit(0)'''

# --- 3. server/app.py: импорты -------------------------------------------

IMPORTS_OLD = '''import json
import mimetypes
import os
import sys
import threading'''

IMPORTS_NEW = '''import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading'''

# --- 4. server/app.py: PDF байтами + протоколы демо-кандидатов ------------

PROTOCOL_OLD = '''def _load_protocol(protocol_id: str) -> dict:
    report = store.load("protocols", protocol_id)
    if report is None:
        session = store.load("sessions", "s-" + protocol_id[2:]) if protocol_id.startswith("p-") else None
        if session is not None:
            report = protocol.build(session)
            store.save("protocols", report["id"], report)
    if report is None:
        raise ApiError("Протокол не найден", 404)
    return report'''

PROTOCOL_NEW = '''FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='8' fill='#ff3b5c'/>"
    "<text x='16' y='22' font-family='monospace' font-size='16' font-weight='bold'"
    " text-anchor='middle' fill='#140609'>P</text></svg>"
).encode("utf-8")


def _protocol_pdf_bytes(report: dict):
    """render_pdf пишет файл на диск — отдаём его байтами и чистим временную папку."""
    folder = tempfile.mkdtemp(prefix="pruf_pdf_")
    path = os.path.join(folder, "%s.pdf" % (report.get("id") or "protocol"))
    try:
        written = protocol.render_pdf(report, path)
        if not written or not os.path.isfile(path):
            return None
        with open(path, "rb") as handle:
            blob = handle.read()
        return blob or None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _protocol_from_candidate(protocol_id: str):
    """Протоколы демо-кандидатов (p-cand-*) считаются из фикстур, в хранилище их нет."""
    prefix = "p-cand-"
    if not protocol_id.startswith(prefix):
        return None
    candidate_id = protocol_id[len(prefix):]
    try:
        bundle = _cached("candidate:%s" % candidate_id, lambda: fixtures.candidate_bundle(candidate_id))
    except Exception:
        return None
    report = (bundle or {}).get("protocol")
    if not isinstance(report, dict) or report.get("id") != protocol_id:
        return None
    return report


def _load_protocol(protocol_id: str) -> dict:
    report = store.load("protocols", protocol_id)
    if report is None:
        session = store.load("sessions", "s-" + protocol_id[2:]) if protocol_id.startswith("p-") else None
        if session is not None:
            report = protocol.build(session)
            store.save("protocols", report["id"], report)
    if report is None:
        report = _protocol_from_candidate(protocol_id)
        if report is not None:
            store.save("protocols", report["id"], report)
    if report is None:
        raise ApiError("Протокол не найден", 404)
    return report'''

PDF_CALL_OLD = '            blob = protocol.render_pdf(report)'
PDF_CALL_NEW = '            blob = _protocol_pdf_bytes(report)'

# --- 5. server/app.py: favicon -------------------------------------------

STATIC_OLD = '        relative = unquote(path.lstrip("/")) or "index.html"'

STATIC_NEW = '''        relative = unquote(path.lstrip("/")) or "index.html"
        if relative in {"favicon.ico", "favicon.svg"}:
            self._send(200, FAVICON_SVG, "image/svg+xml", {"Cache-Control": "public, max-age=86400"})
            return'''

# --- 6-7. web/js (файлы на табах, поэтому якоря с \t) --------------------

APPJS_OLD = "\t\tvar hot = opts.hot || []\n\t\tvar ok = opts.ok || []"
APPJS_NEW = "\t\tvar hot = opts.hot == null ? [] : [].concat(opts.hot)\n\t\tvar ok = opts.ok == null ? [] : [].concat(opts.ok)"

SESSJS_OLD = "P.renderCode(S.sess.code, { hot: q.mutation.line })"
SESSJS_NEW = "P.renderCode(S.sess.code, { hot: [q.mutation.line] })"


FIXES = [
    ("engine/session.py", SESSION_OLD, SESSION_NEW, "эталонный ответ не уходит клиенту"),
    ("engine/sandbox.py", SANDBOX_OLD, SANDBOX_NEW, "ошибка импорта тестов = проваленный прогон"),
    ("server/app.py", IMPORTS_OLD, IMPORTS_NEW, "импорты shutil и tempfile"),
    ("server/app.py", PROTOCOL_OLD, PROTOCOL_NEW, "PDF байтами + протоколы демо-кандидатов"),
    ("server/app.py", PDF_CALL_OLD, PDF_CALL_NEW, "роут PDF отдаёт байты"),
    ("server/app.py", STATIC_OLD, STATIC_NEW, "favicon отдаётся сервером"),
    ("web/js/app.js", APPJS_OLD, APPJS_NEW, "renderCode терпит число вместо массива"),
    ("web/js/session.js", SESSJS_OLD, SESSJS_NEW, "подсветка строки мутации массивом"),
]


def main() -> int:
    applied = 0
    skipped = 0
    for relative, old, new, title in FIXES:
        path = os.path.join(ROOT, relative)
        if not os.path.isfile(path):
            print("нет файла: %s" % relative)
            return 1
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        if new in source:
            print("уже применено · %-20s · %s" % (relative, title))
            skipped += 1
            continue
        if old not in source:
            print("ЯКОРЬ НЕ НАЙДЕН · %-20s · %s" % (relative, title))
            print("  файл разошёлся с ожидаемым состоянием, правку нужно внести вручную")
            return 1
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(source.replace(old, new, 1))
        print("применено    · %-20s · %s" % (relative, title))
        applied += 1
    print("\nИтого: применено %d, уже было %d из %d правок" % (applied, skipped, len(FIXES)))
    print("Проверка: python3 -m unittest discover -s tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
