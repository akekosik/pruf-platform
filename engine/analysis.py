"""
ПРУФ · engine.analysis

Мутационный анализ: сколько правок тесты ловят, где дыры и что именно добавить.
Всё считается детерминированно: те же входы — те же цифры, спор разбирается пересчётом.
"""

from __future__ import annotations

import ast
import time
from typing import Any, Dict, List, Optional

from . import mutations as mut
from . import sandbox

SCHEMA_VERSION = "pruf.analysis/1"

# Что конкретно добавить в тесты, если мутант выжил.
SUGGESTIONS: Dict[str, str] = {
    "CMP_BOUNDARY": "Добавьте тест со значением ровно на границе условия — сейчас граница не проверяется.",
    "CMP_EQUALITY": "Нужен тест, где условие не выполняется: сейчас проверяется только одна ветка.",
    "CMP_MEMBERSHIP": "Добавьте случай, когда элемента в коллекции нет.",
    "CMP_IDENTITY": "Проверьте поведение на None и на пустом значении отдельно.",
    "BOOL_OP": "Нужны два теста: выполнено только первое условие и только второе.",
    "NOT_DROP": "Проверьте охранное условие: пустой ввод или некорректные данные.",
    "ARITH_OP": "Добавьте тест с проверкой конкретного числового результата, а не только типа.",
    "DIV_KIND": "Проверьте дробный случай: целое и вещественное деление дадут разный ответ.",
    "AUG_OP": "Добавьте тест с несколькими элементами: накопление в цикле не проверено.",
    "CONST_INT": "Зафиксируйте точные значения или длины в ассертах, а не «больше нуля».",
    "CONST_BOOL": "Проверьте оба состояния флага — сейчас тесты не заметят его переключение.",
    "CONST_STR_IO": "Добавьте тест с не-ASCII данными или с другим режимом файла.",
    "CALL_DROP_METHOD": "Добавьте вход с лишними пробелами или разделителями: нормализация не проверена.",
    "CALL_SWAP_METHOD": "Добавьте вход, где важен регистр или сторона обработки строки.",
    "SLICE_SHIFT": "Проверьте крайние элементы среза: первый и последний.",
    "RANGE_BOUND": "Добавьте тест на число обработанных элементов, а не только на факт работы.",
    "EXCEPT_SWALLOW": "Нужен тест на ошибку: проверьте, что исключение доходит до вызывающего кода.",
    "RETURN_DROP": "Зафиксируйте в ассерте возвращаемое значение и его тип.",
}


def _killed_by(report: Dict[str, Any]) -> List[str]:
    return [
        test["name"]
        for test in report.get("tests", [])
        if test.get("status") in {"failed", "errored"}
    ]


def _mutant_status(report: Dict[str, Any]) -> str:
    if report.get("timeout") or report.get("import_error"):
        return "killed"
    if report.get("failed", 0) or report.get("errored", 0):
        return "killed"
    return "survived"


def verdict_for(score: float, survived: int) -> Dict[str, str]:
    if score >= 0.85:
        return {
            "level": "good",
            "label": "Набор тестов держит код",
            "summary": "Тесты замечают почти все точечные правки — автор думал о крайних случаях.",
        }
    if score >= 0.6:
        return {
            "level": "medium",
            "label": "Есть дыры в тестах",
            "summary": "Часть правок проходит незамеченной: %d мутаций выжило." % survived,
        }
    return {
        "level": "bad",
        "label": "Зелёные тесты ничего не доказывают",
        "summary": "Большинство правок тесты не заметили: %d мутаций выжило." % survived,
    }


def syntax_check(code: str) -> Optional[Dict[str, Any]]:
    """Описание ошибки синтаксиса или None."""
    try:
        ast.parse(code)
        return None
    except SyntaxError as exc:
        return {
            "message": exc.msg or "ошибка синтаксиса",
            "line": exc.lineno or 0,
            "offset": exc.offset or 0,
            "text": (exc.text or "").rstrip(),
        }


def preview(code: str, limit: int = mut.DEFAULT_LIMIT) -> Dict[str, Any]:
    """Только мутации, без прогона тестов — быстрый режим для студии кода."""
    syntax = syntax_check(code)
    if syntax is not None:
        return {
            "schema": SCHEMA_VERSION,
            "ok": False,
            "stage": "syntax",
            "error": "Решение не разбирается: строка %s — %s" % (syntax["line"], syntax["message"]),
            "syntax": syntax,
            "mutations": [],
        }
    generated = mut.generate(code, limit=limit)
    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "stage": "preview",
        "fingerprint": mut.code_fingerprint(code),
        "lines": len(code.split("\n")),
        "sites": mut.count_sites(code),
        "mutation_total": len(generated),
        "mutations": [item.as_dict() for item in generated],
        "skills": mut.skill_histogram(generated),
    }


def analyze(
    code: str,
    tests_src: str,
    limit: int = mut.DEFAULT_LIMIT,
    timeout: float = sandbox.DEFAULT_TIMEOUT,
    workers: int = 4,
    include_code: bool = False,
) -> Dict[str, Any]:
    """Полный мутационный анализ решения."""
    started = time.time()

    syntax = syntax_check(code)
    if syntax is not None:
        return {
            "schema": SCHEMA_VERSION, "ok": False, "stage": "syntax",
            "error": "Решение не разбирается: строка %s — %s" % (syntax["line"], syntax["message"]),
            "syntax": syntax, "mutations": [],
        }
    tests_syntax = syntax_check(tests_src)
    if tests_syntax is not None:
        return {
            "schema": SCHEMA_VERSION, "ok": False, "stage": "syntax_tests",
            "error": "Файл тестов не разбирается: строка %s — %s" % (tests_syntax["line"], tests_syntax["message"]),
            "syntax": tests_syntax, "mutations": [],
        }

    baseline = sandbox.run_tests(code, tests_src, timeout=timeout)
    generated = mut.generate(code, limit=limit)

    if not baseline.get("ok"):
        return {
            "schema": SCHEMA_VERSION, "ok": False, "stage": "baseline",
            "error": baseline.get("import_error")
            or "Исходное решение не проходит свои же тесты — мутационный анализ невозможен",
            "baseline": baseline,
            "mutations": [item.as_dict(include_code=include_code) for item in generated],
            "duration_ms": int((time.time() - started) * 1000),
        }

    reports = sandbox.run_many(
        [(item.id, item.code) for item in generated], tests_src, workers=workers, timeout=timeout
    )

    baseline_tests = [test["name"] for test in baseline.get("tests", [])]
    kills_per_test: Dict[str, int] = {name: 0 for name in baseline_tests}

    rows: List[Dict[str, Any]] = []
    killed = 0
    for mutation in generated:
        report = reports.get(mutation.id, {})
        status = _mutant_status(report)
        catchers = _killed_by(report)
        for name in catchers:
            kills_per_test[name] = kills_per_test.get(name, 0) + 1
        if status == "killed":
            killed += 1
        row = mutation.as_dict(include_code=include_code)
        row.update({
            "status": status,
            "killed_by": catchers,
            "first_failed": catchers[0] if catchers else None,
            "suggestion": SUGGESTIONS.get(mutation.operator, "Добавьте тест на этот случай."),
            "run": {
                "passed": report.get("passed", 0),
                "failed": report.get("failed", 0),
                "errored": report.get("errored", 0),
                "timeout": bool(report.get("timeout")),
                "duration_ms": report.get("duration_ms", 0),
                "import_error": report.get("import_error"),
            },
        })
        rows.append(row)

    total = len(rows)
    survived = total - killed
    score = round(killed / total, 4) if total else 0.0

    skills: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        entry = skills.setdefault(row["skill"], {
            "skill": row["skill"], "title": row["skill_title"],
            "total": 0, "killed": 0, "survived": 0,
        })
        entry["total"] += 1
        if row["status"] == "killed":
            entry["killed"] += 1
        else:
            entry["survived"] += 1
    skill_rows = []
    for entry in skills.values():
        entry["coverage"] = round(entry["killed"] / entry["total"], 4) if entry["total"] else 0.0
        skill_rows.append(entry)
    skill_rows.sort(key=lambda item: (-item["total"], item["skill"]))

    test_rows = []
    for test in baseline.get("tests", []):
        kills = kills_per_test.get(test["name"], 0)
        test_rows.append({
            "name": test["name"],
            "status": test["status"],
            "duration_ms": test.get("duration_ms", 0),
            "kills": kills,
            "verdict": "ловит %d правок" % kills if kills else "ничего не ловит",
        })

    gaps = [
        {
            "id": row["id"], "line": row["line"], "kind": row["kind"],
            "skill": row["skill"], "skill_title": row["skill_title"],
            "diff": row["diff"], "before": row["before"], "after": row["after"],
            "consequence": row["consequence"], "suggestion": row["suggestion"],
        }
        for row in rows if row["status"] == "survived"
    ]

    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "stage": "done",
        "fingerprint": mut.code_fingerprint(code),
        "lines": len(code.split("\n")),
        "sites": mut.count_sites(code),
        "baseline": {
            "ok": True,
            "passed": baseline.get("passed", 0),
            "failed": baseline.get("failed", 0),
            "errored": baseline.get("errored", 0),
            "duration_ms": baseline.get("duration_ms", 0),
            "tests": baseline.get("tests", []),
        },
        "mutation_total": total,
        "killed": killed,
        "survived": survived,
        "mutation_score": score,
        "mutation_score_pct": int(round(score * 100)),
        "mutations": rows,
        "gaps": gaps,
        "skills": skill_rows,
        "tests": test_rows,
        "useless_tests": [row["name"] for row in test_rows if row["kills"] == 0],
        "verdict": verdict_for(score, survived),
        "duration_ms": int((time.time() - started) * 1000),
    }
