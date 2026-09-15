#!/usr/bin/env python3
"""CI-гейт анти-релей протокола.

Проверяет не «красиво ли написано в документации», а четыре вещи, которые
ломаются при первой же правке интерфейса:

1. Решаемость. Каждое решающее задание имеет существующее решение, и это
   решение действительно проходит проверку на 100 %. Сильный инженер не должен
   терять баллы за то, что мутант оказался эквивалентным.
2. Герметичность. В клиентском payload нет ни свидетелей, ни кода мутанта,
   ни готовых объяснений. Фотография не может содержать больше, чем payload.
3. SSR. На решающих шагах ssr_static ≥ SSR_GATE, то есть кадр бесполезен.
4. Отклонение обходов. Угаданный вход, тривиальный тест и враньё про значения
   полного балла не дают.

Запуск:  python3 tools/qa_relay.py
Выход:  0 — всё зелёное, 1 — есть падения.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import analysis, audit, fixtures, relay, sandbox, witness  # noqa: E402

CHECKS = []
FAILS = []

REPR_MARKER = "@@QA_REPR@@"
EXC_MARKER = "@@QA_EXC@@"

_REPR_PROBE = '''from solution import *  # noqa: F401,F403


def test_qa_repr():
    try:
        print("%(repr_marker)s" + repr(%(expression)s))
    except BaseException as exc:
        print("%(exc_marker)s" + type(exc).__name__)
'''


def check(name, ok, detail=""):
    """Одна проверка гейта."""
    ok = bool(ok)
    CHECKS.append((name, ok, detail))
    if not ok:
        FAILS.append(name)
    print("  %-4s %-58s %s" % ("OK" if ok else "FAIL", name, detail))
    return ok


def section(title):
    print("\n== %s" % title)


def observed_literal(code, expression):
    """Значение выражения в том виде, в каком его набрал бы человек (repr).

    Нарочно не использует relay.eval_call: там значение нормализовано под JSON,
    а нам нужна ровно та строка, которую кандидат введёт в поле «наблюдаемое
    значение». Так гейт проверяет и саму привязку доказательств (claim_matches).
    """
    probe = _REPR_PROBE % {
        "expression": expression,
        "repr_marker": REPR_MARKER,
        "exc_marker": EXC_MARKER,
    }
    report = sandbox.run_tests(code, probe, timeout=6.0)
    for line in (report.get("stdout") or "").splitlines():
        if REPR_MARKER in line:
            return "value", line.split(REPR_MARKER, 1)[1].strip()
        if EXC_MARKER in line:
            return "exception", line.split(EXC_MARKER, 1)[1].strip()
    return None, None


def killer_test(expression, kind, literal):
    """Тест, который должен убить мутанта на найденном свидетеле."""
    if kind == "exception":
        return (
            "from solution import *\n\n\n"
            "def test_kills_mutant():\n"
            "    try:\n"
            "        %s\n"
            "    except %s:\n"
            "        return\n"
            "    raise AssertionError('правка не выбросила исключение')\n"
        ) % (expression, literal)
    return (
        "from solution import *\n\n\n"
        "def test_kills_mutant():\n"
        "    assert repr(%s) == %r\n"
    ) % (expression, literal)


def non_witness(code, mutant_code, corpus):
    """Вход из корпуса, на котором поведение НЕ расходится (имитация догадки)."""
    for expression in corpus[:16]:
        outcome = relay.witness_check(code, mutant_code, expression)
        if outcome.get("ok") and not outcome.get("differs"):
            return expression
    return None


def run_fixture(title, code, tests_src, session_id, deep=True):
    """Полный прогон гейта по одной задаче."""
    section(title)
    result = analysis.analyze(code, tests_src, limit=12, include_code=True)
    rows = result.get("mutations") or []
    check("анализ прошёл", result.get("ok"), "мутаций: %d, score %s%%" % (len(rows), result.get("mutation_score_pct")))
    check("мутации собраны", len(rows) >= 6, "%d шт" % len(rows))

    classification = witness.classify_mutants(code, tests_src, result)
    counts = classification["counts"]
    total = sum(counts.values())
    check(
        "классификация полная",
        total == len(rows),
        "killed %d / gap %d / equivalent %d, корпус %d, %d мс"
        % (counts["killed"], counts["gap"], counts["equivalent"], classification["corpus_size"], classification["duration_ms"]),
    )
    denominator = counts["killed"] + counts["gap"]
    expected_honest = int(round(100.0 * counts["killed"] / denominator)) if denominator else 0
    check(
        "честный mutation score без эквивалентных",
        classification["honest_mutation_pct"] == expected_honest,
        "%d%% (сырой %s%%)" % (classification["honest_mutation_pct"], result.get("mutation_score_pct")),
    )

    survived_ids = [row["id"] for row in rows if row.get("status") == "survived"]
    classes = classification["classes"]
    misplaced = [
        mutation_id
        for mutation_id in survived_ids
        if classes.get(mutation_id) == "gap" and mutation_id not in classification["witnesses"]
    ]
    check("gap только с найденным свидетелем", not misplaced, "без свидетеля: %s" % misplaced)

    plan = witness.build_relay_plan(code, tests_src, result, session_id, limit=4, classification=classification)
    tasks = plan["tasks"]
    check("решающие задания собраны", len(tasks) >= 2, "%s" % [(task["task_id"], task["type"], task["mutation_id"]) for task in tasks])
    check("все задания решающего типа", all(task["type"] in relay.DECISIVE_TYPES for task in tasks))
    check(
        "эквивалентные мутанты в задания не попали",
        all(classes.get(task["mutation_id"]) != "equivalent" for task in tasks),
    )
    check(
        "test_fix только на дырах в тестах",
        all(classes.get(task["mutation_id"]) == "gap" for task in tasks if task["type"] == "test_fix"),
    )
    check(
        "witness только с известным свидетелем",
        all(task["mutation_id"] in plan["_witnesses"] for task in tasks if task["type"] == "witness"),
    )

    public = {"tasks": tasks, "classification": plan["classification"], "targets": plan["targets"]}
    leaks = audit.find_in_payload(public)
    check("I2: в payload нет эталонов", not leaks, "утечки: %s" % leaks[:6])
    private_leak = [
        (task["task_id"], field)
        for task in tasks
        for field in relay._PRIVATE_MUTATION_FIELDS
        if field in task["mutation"]
    ]
    check("в задании нет кода мутанта и подсказок", not private_leak, "%s" % private_leak[:6])
    check("гейт ловит утечку (негативный контроль)", bool(audit.find_in_payload({"plan": plan})))

    if deep:
        corpus = witness.build_corpus(code, tests_src)
        for task in tasks:
            mutation_id = task["mutation_id"]
            mutant_code = plan["_mutants"][mutation_id]
            witness_row = plan["_witnesses"].get(mutation_id)
            label = "%s/%s/%s" % (task["task_id"], task["type"], mutation_id)
            if not witness_row:
                check("%s: свидетель известен" % label, False, "свидетеля нет")
                continue
            expression = witness_row["expression"]
            kind_original, literal_original = observed_literal(code, expression)
            kind_mutant, literal_mutant = observed_literal(mutant_code, expression)

            if task["type"] == "witness":
                good = relay.grade_task(
                    task,
                    {
                        "expression": expression,
                        "observed_original": literal_original,
                        "observed_mutant": literal_mutant,
                    },
                    code,
                    mutant_code,
                )
                check("%s: верный ответ даёт 100%%" % label, good["score"] == 1.0, "score %s | %s" % (good["score"], "; ".join(good["notes"])))
                lied = relay.grade_task(
                    task,
                    {"expression": expression, "observed_original": "999", "observed_mutant": "999"},
                    code,
                    mutant_code,
                )
                check(
                    "%s: вход без доказательств не даёт 100%%" % label,
                    lied["score"] == relay.WITNESS_FOUND_SCORE,
                    "score %s" % lied["score"],
                )
                blind = non_witness(code, mutant_code, corpus)
                if blind:
                    guessed = relay.grade_task(
                        task,
                        {"expression": blind, "observed_original": "1", "observed_mutant": "2"},
                        code,
                        mutant_code,
                    )
                    check("%s: угаданный вход отклонён" % label, guessed["score"] == 0.0, "score %s" % guessed["score"])
            else:
                source = killer_test(expression, kind_original, literal_original)
                good = relay.grade_task(task, {"test_source": source}, code, mutant_code)
                check(
                    "%s: тест-убийца существует и даёт 100%%" % label,
                    good["score"] == 1.0,
                    "score %s | %s" % (good["score"], "; ".join(good["notes"])),
                )
                check(
                    "%s: поведение мутанта не раскрывается" % label,
                    "tests" not in (good["_check"].get("mutant") or {}),
                )
                trivial = relay.grade_task(
                    task,
                    {"test_source": "def test_trivial():\n    assert True\n"},
                    code,
                    mutant_code,
                )
                check(
                    "%s: тривиальный тест не даёт 100%%" % label,
                    trivial["score"] == relay.TEST_VALID_SCORE,
                    "score %s" % trivial["score"],
                )
                broken = relay.grade_task(
                    task,
                    {"test_source": "def test_broken():\n    assert False\n"},
                    code,
                    mutant_code,
                )
                check("%s: тест, падающий на решении, отклонён" % label, broken["score"] == 0.0, "score %s" % broken["score"])

    report = audit.audit(
        public,
        tasks=tasks,
        warmup_weight=0.0,
        code_lines=len(code.splitlines()),
    )
    check("аудит инвариантов I1–I5", report["passed"], ", ".join("%s=%s" % (item["id"], "ok" if item["ok"] else "FAIL") for item in report["invariants"]))
    weak = [row["kind"] for row in report["ssr"] if row["kind"] in relay.DECISIVE_TYPES and row["ssr_static"] < audit.SSR_GATE]
    check("SSR на решающих шагах ≥ %.2f" % audit.SSR_GATE, not weak, "слабые: %s" % weak)
    return {"result": result, "classification": classification, "plan": plan, "audit": report}


def run_guards(code):
    section("Границы песочницы и валидация артефактов")
    cases = [
        ("вызов несуществующей функции", "nope('x')"),
        ("импорт в выражении", "__import__('os')"),
        ("чтение файла в аргументе", "parse_orders(open('/etc/passwd').read())"),
        ("путь в аргументе", "parse_orders('/etc/passwd')"),
        ("URL в аргументе", "parse_orders('http://example.com/x')"),
        ("не вызов, а выражение", "1 + 1"),
    ]
    for title, expression in cases:
        ok, error = relay.validate_call(code, expression)
        check("отклонено: %s" % title, not ok, error[:70])

    ok, _ = relay.validate_call(code, "parse_orders('Болт;10;5.5')")
    check("принят нормальный вызов", ok)

    bad_tests = [
        ("импорт os", "import os\n\n\ndef test_x():\n    assert True\n"),
        ("open в тесте", "def test_x():\n    open('/etc/passwd')\n"),
        ("дандер-атрибут", "def test_x():\n    assert (1).__class__ is int\n"),
        ("без тест-функции", "x = 1\n"),
        ("синтаксис", "def test_x(:\n    pass\n"),
    ]
    for title, source in bad_tests:
        ok, error = relay.validate_test_source(source)
        check("тест отклонён: %s" % title, not ok, error[:70])

    ok, _ = relay.validate_test_source("from solution import *\n\n\ndef test_ok():\n    assert True\n")
    check("принят нормальный тест", ok)

    spent = relay.experiment(code, "total_amount([])", used=relay.MAX_EXPERIMENTS)
    check("лимит экспериментов работает", not spent["ok"] and spent["remaining"] == 0)
    live = relay.experiment(code, "total_amount([])", used=0)
    check(
        "консоль экспериментов считает решение",
        live["ok"] and live["remaining"] == relay.MAX_EXPERIMENTS - 1,
        "value=%s remaining=%s" % (live["value"], live["remaining"]),
    )


def run_risk():
    section("Риск-индекс по процессу (без прокторинга)")
    honest = {
        "decisive": [
            {"task_id": "T1", "experiments": 5, "latency_ms": 148000, "typed_chars": 210, "paste_chars": 0, "blur_ms": 900, "revealed": True, "evidence_ok": True},
            {"task_id": "T2", "experiments": 3, "latency_ms": 92000, "typed_chars": 160, "paste_chars": 0, "blur_ms": 400, "revealed": True, "evidence_ok": True},
            {"task_id": "T3", "experiments": 8, "latency_ms": 205000, "typed_chars": 340, "paste_chars": 20, "blur_ms": 1500, "revealed": True, "evidence_ok": True},
        ]
    }
    relayed = {
        "decisive": [
            {"task_id": "T1", "experiments": 0, "latency_ms": 61000, "typed_chars": 8, "paste_chars": 140, "blur_ms": 22000, "revealed": False, "evidence_ok": False},
            {"task_id": "T2", "experiments": 0, "latency_ms": 59000, "typed_chars": 6, "paste_chars": 120, "blur_ms": 18000, "revealed": False, "evidence_ok": False},
            {"task_id": "T3", "experiments": 0, "latency_ms": 60500, "typed_chars": 9, "paste_chars": 160, "blur_ms": 25000, "revealed": False, "evidence_ok": False},
        ]
    }
    clean = audit.risk_index(honest)
    dirty = audit.risk_index(relayed)
    check("честная сессия — низкий риск", clean["level"] == "low", "score %d" % clean["score"])
    check(
        "сессия с признаками релея — высокий риск",
        dirty["level"] == "high" and dirty["score"] >= audit.RISK_HIGH,
        "score %d, сигналов %d" % (dirty["score"], len(dirty["signals"])),
    )
    check("риск не меняет балл", bool(dirty["disclaimer"]))


def run_cost():
    section("Стоимость релея против бюджета шага")
    for kind in relay.DECISIVE_TYPES:
        model = audit.relay_cost_model(kind)
        frame = audit.frame_analysis(kind)
        print(
            "  %-9s бюджет %3d с | A1 %5.1f с без ответа | A2 %6.1f с | ssr_static %.2f | ssr_tool %.2f"
            % (kind, model["budget_seconds"], model["a1_seconds"], model["a2_seconds"], frame["ssr_static"], frame["ssr_tool"])
        )
        check("%s: фото кадра не даёт ответа" % kind, not model["a1_yields_answer"])
        check("%s: опора защиты — запуск кода" % kind, model["binding_constraint"] == "execution")


def main():
    started = time.time()
    print("АРП гейт — проверка защиты от фотографии экрана")
    strong = run_fixture(
        "Заказы — сильные тесты кандидата",
        fixtures.ORDERS_CODE,
        fixtures.ORDERS_TESTS,
        "s-qa-orders",
    )
    weak = run_fixture(
        "Заказы — слабые тесты кандидата",
        fixtures.ORDERS_CODE,
        fixtures.ORDERS_WEAK_TESTS,
        "s-qa-orders-weak",
        deep=False,
    )
    section("Слабые тесты дают больше дыр")
    check(
        "дыр больше на слабом наборе",
        weak["classification"]["counts"]["gap"] >= strong["classification"]["counts"]["gap"],
        "gap: сильные %d → слабые %d"
        % (strong["classification"]["counts"]["gap"], weak["classification"]["counts"]["gap"]),
    )
    check(
        "честный score ниже на слабом наборе",
        weak["classification"]["honest_mutation_pct"] <= strong["classification"]["honest_mutation_pct"],
        "%d%% против %d%%"
        % (weak["classification"]["honest_mutation_pct"], strong["classification"]["honest_mutation_pct"]),
    )
    run_fixture(
        "Слова — вторая задача для проверки общности",
        fixtures.WORDS_CODE,
        fixtures.WORDS_TESTS,
        "s-qa-words",
    )
    run_guards(fixtures.ORDERS_CODE)
    run_risk()
    run_cost()

    passed = len([1 for _, ok, _ in CHECKS if ok])
    print("\nИтого: %d проверок, зелёных %d, падений %d, %.1f с"
          % (len(CHECKS), passed, len(FAILS), time.time() - started))
    if FAILS:
        print("Падения:")
        for name in FAILS:
            print("  - %s" % name)
        return 1
    print("Гейт зелёный: задания решаемы, в кадре ответа нет, обходы не проходят.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
