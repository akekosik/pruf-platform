"""
ПРУФ · engine.cli

Консольный интерфейс ядра. Запуск: python3 -m engine.cli <команда>

    catalog                       — каталог операторов мутаций
    mutate solution.py            — построить мутации без прогона тестов
    run solution.py tests.py      — прогнать тесты в изоляторе
    analyze solution.py tests.py  — полный мутационный анализ
    session solution.py tests.py  — собрать сессию защиты (--auto для автоответов)
    demo [--task orders]          — офлайн-демо полного цикла
    economics                     — юнит-экономика
    serve [--port 8000]           — поднять API и сайт
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Any, Dict

from . import analysis, economics, fixtures, mutations, protocol, sandbox
from . import session as session_mod

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def cmd_catalog(args: argparse.Namespace) -> int:
    rows = mutations.catalog()
    if args.json:
        _dump({"operators": rows, "skills": mutations.SKILLS})
        return 0
    print("Операторы мутаций: %d" % len(rows))
    for row in rows:
        print("  %-18s %-26s %s" % (row["code"], row["kind"], row["skill_title"]))
    return 0


def cmd_mutate(args: argparse.Namespace) -> int:
    result = analysis.preview(_read(args.solution), limit=args.limit)
    if args.json:
        _dump(result)
        return 0 if result["ok"] else 1
    if not result["ok"]:
        print("Ошибка: %s" % result["error"])
        return 1
    print("Мест для правок: %d, построено мутаций: %d" % (result["sites"], result["mutation_total"]))
    for row in result["mutations"]:
        print("  %s L%-3d %-18s %s → %s" % (
            row["id"], row["line"], row["operator"], row["before"].strip(), row["after"].strip()))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    report = sandbox.run_tests(_read(args.solution), _read(args.tests), timeout=args.timeout)
    if args.json:
        _dump(report)
        return 0 if report.get("ok") else 1
    print("Прогон: %s, прошло %d, упало %d, ошибок %d, %d мс" % (
        "зелёный" if report.get("ok") else "красный",
        report.get("passed", 0), report.get("failed", 0), report.get("errored", 0),
        report.get("duration_ms", 0)))
    for test in report.get("tests", []):
        print("  %-28s %s %s" % (test["name"], test["status"], test.get("message", "")))
    if report.get("import_error"):
        print("  ошибка загрузки: %s" % report["import_error"])
    return 0 if report.get("ok") else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    result = analysis.analyze(_read(args.solution), _read(args.tests), limit=args.limit, timeout=args.timeout)
    if args.json:
        _dump(result)
        return 0 if result["ok"] else 1
    if not result["ok"]:
        print("Анализ невозможен (%s): %s" % (result["stage"], result["error"]))
        return 1
    print("Мутаций %d · поймано %d · выжило %d · счёт %d %%" % (
        result["mutation_total"], result["killed"], result["survived"], result["mutation_score_pct"]))
    print("Вердикт: %s — %s" % (result["verdict"]["label"], result["verdict"]["summary"]))
    for row in result["mutations"]:
        mark = "✓" if row["status"] == "killed" else "✗"
        print("  %s %s L%-3d %-18s %s" % (mark, row["id"], row["line"], row["operator"],
                                          ", ".join(row["killed_by"]) or "никто не заметил"))
    if result["gaps"]:
        print("\nДыры в тестах:")
        for gap in result["gaps"]:
            print("  %s (строка %d): %s" % (gap["id"], gap["line"], gap["suggestion"]))
    if result["useless_tests"]:
        print("\nТесты, не ловящие ни одной правки: %s" % ", ".join(result["useless_tests"]))
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    session = session_mod.build(
        _read(args.solution), _read(args.tests),
        limit=args.limit, question_limit=args.questions,
    )
    if not session.get("ok"):
        print("Сессия не собрана: %s" % session.get("error"))
        return 1
    if args.auto:
        fixtures.auto_answer(session, ratio=args.ratio, seed="cli")
        report = protocol.build(session, meta={"candidate": "Автоответы CLI"})
        if args.json:
            _dump(report)
        else:
            print(protocol.render_text(report))
        return 0
    if args.json:
        _dump(session_mod.public_view(session))
        return 0
    print("Сессия %s · вопросов %d · таймер %d с" % (
        session["id"], len(session["questions"]), session["seconds_total"]))
    for question in session["questions"]:
        print("\n%s · %s [%s]" % (question["id"], question["title"], question["mutation"]["id"]))
        print("  %s" % question["prompt"])
        for option in question["options"]:
            print("    %s) %s" % (option["id"], option["label"].replace("\n", " | ")))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    result = fixtures.demo(task_id=args.task, ratio=args.ratio)
    if args.json:
        _dump(result)
        return 0
    print(protocol.render_text(result["protocol"]))
    return 0


def cmd_economics(args: argparse.Namespace) -> int:
    data = economics.report()
    if args.json:
        _dump(data)
        return 0
    figures = data["unit"]
    print("Цена верификации: %.0f ₽, переменная себестоимость: %.0f ₽, маржа: %.1f %%" % (
        figures["price"], figures["variable_cost"], figures["margin_pct"]))
    break_even = data["breakeven"]
    print("Безубыточность: %d верификаций ≈ %s компаний" % (
        break_even["sessions_needed"], break_even["companies_needed"]))
    for row in data["scenarios"]:
        print("  %-38s выручка %10.0f ₽ · результат %10.0f ₽" % (row["name"], row["revenue"], row["result"]))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    app_path = os.path.join(PROJECT_ROOT, "server", "app.py")
    spec = importlib.util.spec_from_file_location("pruf_server_app", app_path)
    if spec is None or spec.loader is None:
        print("Не найден server/app.py")
        return 1
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.serve(host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pruf", description="ПРУФ — верификация понимания кода")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="каталог операторов")
    catalog.set_defaults(func=cmd_catalog)

    mutate = subparsers.add_parser("mutate", help="построить мутации")
    mutate.add_argument("solution")
    mutate.add_argument("--limit", type=int, default=mutations.DEFAULT_LIMIT)
    mutate.set_defaults(func=cmd_mutate)

    run = subparsers.add_parser("run", help="прогнать тесты")
    run.add_argument("solution")
    run.add_argument("tests")
    run.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT)
    run.set_defaults(func=cmd_run)

    analyze = subparsers.add_parser("analyze", help="мутационный анализ")
    analyze.add_argument("solution")
    analyze.add_argument("tests")
    analyze.add_argument("--limit", type=int, default=mutations.DEFAULT_LIMIT)
    analyze.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT)
    analyze.set_defaults(func=cmd_analyze)

    session = subparsers.add_parser("session", help="сессия защиты")
    session.add_argument("solution")
    session.add_argument("tests")
    session.add_argument("--limit", type=int, default=mutations.DEFAULT_LIMIT)
    session.add_argument("--questions", type=int, default=session_mod.DEFAULT_QUESTIONS)
    session.add_argument("--auto", action="store_true", help="ответить автоматически и выдать протокол")
    session.add_argument("--ratio", type=float, default=1.0, help="доля верных автоответов")
    session.set_defaults(func=cmd_session)

    demo = subparsers.add_parser("demo", help="офлайн-демо")
    demo.add_argument("--task", default="orders")
    demo.add_argument("--ratio", type=float, default=0.7)
    demo.set_defaults(func=cmd_demo)

    econ = subparsers.add_parser("economics", help="юнит-экономика")
    econ.set_defaults(func=cmd_economics)

    serve = subparsers.add_parser("serve", help="поднять API и сайт")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
