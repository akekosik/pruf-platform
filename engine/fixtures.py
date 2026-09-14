"""
ПРУФ · engine.fixtures

Демо-данные: три задачи с решениями и тестами, пул кандидатов для кабинета работодателя
и детерминированное автопрохождение сессии.

Важно: протоколы демо-кандидатов не нарисованы руками — они считаются тем же движком,
что обслуживает реальных кандидатов: AST → мутации → изолятор → сессия → протокол.
Отличается только источник ответов: вместо человека — заданная доля верных ответов.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from . import analysis as analysis_mod
from . import protocol as protocol_mod
from . import session as session_mod

SCHEMA_VERSION = "pruf.fixtures/1"

ORDERS_CODE = '''def parse_orders(raw):
    """Разбирает строки заказов вида: имя;количество;цена."""
    orders = []
    for line in raw.strip().splitlines():
        parts = line.split(";")
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        try:
            qty = int(parts[1])
            price = float(parts[2])
        except ValueError:
            raise ValueError("некорректная строка: " + line)
        orders.append({"name": name, "qty": qty, "price": price})
    return orders


def total_amount(orders, limit=1000.0):
    """Сумма заказов, каждый заказ ограничен сверху значением limit."""
    total = 0.0
    for order in orders:
        amount = order["qty"] * order["price"]
        if amount > limit:
            amount = limit
        total += amount
    return round(total, 2)
'''

ORDERS_TESTS = '''from solution import parse_orders, total_amount


def test_parse_basic():
    rows = parse_orders("Болт;10;5.5\\nГайка;2;3.0")
    assert len(rows) == 2
    assert rows[0]["name"] == "Болт"
    assert rows[0]["qty"] == 10


def test_total_simple():
    rows = [{"name": "a", "qty": 2, "price": 10.0}]
    assert total_amount(rows) == 20.0


def test_limit_applied():
    rows = [{"name": "a", "qty": 100, "price": 50.0}]
    assert total_amount(rows, limit=1000.0) == 1000.0


def test_skips_short_lines():
    rows = parse_orders("Болт;10;5.5\\nсломанная строка")
    assert len(rows) == 1
'''

ORDERS_WEAK_TESTS = '''from solution import parse_orders, total_amount


def test_parse_runs():
    rows = parse_orders("Болт;10;5.5")
    assert rows


def test_total_is_number():
    rows = [{"name": "a", "qty": 2, "price": 10.0}]
    assert total_amount(rows) >= 0
'''

WORDS_CODE = '''def normalize(text):
    """Приводит текст к нижнему регистру и убирает лишние пробелы."""
    return " ".join(text.lower().split())


def word_counts(text, min_length=3):
    """Считает слова длиной не меньше min_length."""
    counts = {}
    for word in normalize(text).split(" "):
        cleaned = word.strip(".,!?:;()")
        if len(cleaned) < min_length:
            continue
        counts[cleaned] = counts.get(cleaned, 0) + 1
    return counts


def top_words(text, size=3):
    """Возвращает size самых частых слов."""
    counts = word_counts(text)
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word for word, _ in ordered[:size]]
'''

WORDS_TESTS = '''from solution import normalize, word_counts, top_words


def test_normalize_collapses_spaces():
    assert normalize("  Привет   МИР ") == "привет мир"


def test_counts_skip_short():
    counts = word_counts("да да нет кода кода кода")
    assert counts == {"нет": 1, "кода": 3}


def test_top_words_order():
    assert top_words("кода кода тест тест тест байт", size=2) == ["тест", "кода"]
'''

WORDS_WEAK_TESTS = '''from solution import normalize, top_words


def test_normalize_runs():
    assert normalize("Привет МИР")


def test_top_words_returns_list():
    assert isinstance(top_words("кода кода тест"), list)
'''

PHONE_CODE = '''def clean_phone(raw):
    """Оставляет только цифры номера и приводит его к виду 7XXXXXXXXXX."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def is_valid(raw):
    """Номер корректен, если в нём 11 цифр и он начинается с 7."""
    digits = clean_phone(raw)
    return len(digits) == 11 and digits.startswith("7")


def unique_valid(rows):
    """Уникальные корректные номера в порядке появления."""
    seen = []
    for row in rows:
        digits = clean_phone(row)
        if not is_valid(row):
            continue
        if digits in seen:
            continue
        seen.append(digits)
    return seen
'''

PHONE_TESTS = '''from solution import clean_phone, is_valid, unique_valid


def test_clean_converts_eight():
    assert clean_phone("8 (912) 345-67-89") == "79123456789"


def test_valid_and_invalid():
    assert is_valid("+7 912 345 67 89") is True
    assert is_valid("12345") is False


def test_unique_keeps_order():
    rows = ["8 912 345 67 89", "+7 912 345 67 89", "+7 495 000 00 00"]
    assert unique_valid(rows) == ["79123456789", "74950000000"]
'''

PHONE_WEAK_TESTS = '''from solution import clean_phone, unique_valid


def test_clean_returns_digits():
    assert clean_phone("8 (912) 345-67-89").isdigit()


def test_unique_runs():
    assert unique_valid(["8 912 345 67 89"])
'''

TASKS: List[Dict[str, Any]] = [
    {
        "id": "orders",
        "title": "Разбор заказов из текстового файла",
        "level": "junior",
        "language": "Python",
        "minutes": 40,
        "statement": "Разобрать строки вида «имя;количество;цена», посчитать сумму с ограничением на заказ.",
        "skills": ["Границы и индексы", "Обработка ошибок", "Арифметика и накопление"],
        "code": ORDERS_CODE,
        "tests": ORDERS_TESTS,
        "weak_tests": ORDERS_WEAK_TESTS,
    },
    {
        "id": "words",
        "title": "Частотный анализ текста",
        "level": "junior",
        "language": "Python",
        "minutes": 35,
        "statement": "Нормализовать текст, посчитать слова не короче заданной длины и выдать топ-N.",
        "skills": ["Работа со строками", "Коллекции и принадлежность", "Границы и индексы"],
        "code": WORDS_CODE,
        "tests": WORDS_TESTS,
        "weak_tests": WORDS_WEAK_TESTS,
    },
    {
        "id": "phones",
        "title": "Нормализация телефонных номеров",
        "level": "middle",
        "language": "Python",
        "minutes": 30,
        "statement": "Очистить номера от лишних символов, привести к формату 7XXXXXXXXXX и отбросить дубли.",
        "skills": ["Работа со строками", "Логика условий", "Коллекции и принадлежность"],
        "code": PHONE_CODE,
        "tests": PHONE_TESTS,
        "weak_tests": PHONE_WEAK_TESTS,
    },
]

VACANCIES: List[Dict[str, Any]] = [
    {"id": "py-dev", "title": "Python-разработчик", "team": "Платёжный шлюз", "task": "orders"},
    {"id": "backend-senior", "title": "Backend Senior", "team": "Ядро продукта", "task": "phones"},
    {"id": "qa-auto", "title": "QA Automation", "team": "Качество", "task": "words"},
]

CANDIDATES: List[Dict[str, Any]] = [
    {"id": "c-01", "name": "Анна Коробкова", "role": "Python-разработчик", "vacancy": "py-dev",
     "task": "orders", "tests": "full", "ratio": 0.92, "submitted": "2026-09-11", "source": "hh.ru"},
    {"id": "c-02", "name": "Дмитрий Савельев", "role": "Python-разработчик", "vacancy": "py-dev",
     "task": "orders", "tests": "weak", "ratio": 0.35, "submitted": "2026-09-11", "source": "телеграм-канал"},
    {"id": "c-03", "name": "Камиль Гарифуллин", "role": "Backend Senior", "vacancy": "backend-senior",
     "task": "phones", "tests": "full", "ratio": 0.78, "submitted": "2026-09-12", "source": "рекомендация"},
    {"id": "c-04", "name": "Ольга Нечаева", "role": "Backend Senior", "vacancy": "backend-senior",
     "task": "phones", "tests": "weak", "ratio": 0.55, "submitted": "2026-09-12", "source": "hh.ru"},
    {"id": "c-05", "name": "Руслан Шайхутдинов", "role": "QA Automation", "vacancy": "qa-auto",
     "task": "words", "tests": "full", "ratio": 0.66, "submitted": "2026-09-13", "source": "вуз-канал"},
    {"id": "c-06", "name": "Елена Баранова", "role": "QA Automation", "vacancy": "qa-auto",
     "task": "words", "tests": "weak", "ratio": 0.2, "submitted": "2026-09-13", "source": "стажировка"},
]


def tasks(include_code: bool = True) -> List[Dict[str, Any]]:
    rows = []
    for task in TASKS:
        row = {key: value for key, value in task.items() if include_code or key not in {"code", "tests", "weak_tests"}}
        rows.append(row)
    return rows


def get_task(task_id: str) -> Dict[str, Any]:
    for task in TASKS:
        if task["id"] == task_id:
            return task
    return TASKS[0]


def get_vacancy(vacancy_id: str) -> Optional[Dict[str, Any]]:
    for vacancy in VACANCIES:
        if vacancy["id"] == vacancy_id:
            return vacancy
    return None


def get_candidate(candidate_id: str) -> Optional[Dict[str, Any]]:
    for candidate in CANDIDATES:
        if candidate["id"] == candidate_id:
            return candidate
    return None


def _rng(*material: Any) -> random.Random:
    digest = hashlib.sha256("|".join(str(part) for part in material).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def auto_answer(session: Dict[str, Any], ratio: float = 1.0, seed: str = "demo") -> Dict[str, Any]:
    """Детерминированно отвечает на все вопросы с заданной долей верных ответов."""
    for question in session.get("questions", []):
        rng = _rng(seed, session.get("id"), question["id"])
        correct_ids = set(question.get("correct") or [])
        option_ids = [option["id"] for option in question.get("options", [])]
        if not option_ids:
            continue
        if rng.random() < ratio and correct_ids:
            choice = sorted(correct_ids)[0]
        else:
            wrong = [option for option in option_ids if option not in correct_ids]
            choice = rng.choice(wrong) if wrong else option_ids[0]
        session_mod.answer(session, question["id"], choice, seconds=25 + rng.randrange(0, 70))
    return session_mod.finish(session)


def demo(task_id: str = "orders", ratio: float = 0.7, question_limit: int = session_mod.DEFAULT_QUESTIONS,
         tests_variant: str = "full") -> Dict[str, Any]:
    """Полный офлайн-цикл: анализ → сессия → автоответы → протокол."""
    task = get_task(task_id)
    tests_src = task["weak_tests"] if tests_variant == "weak" else task["tests"]
    result = analysis_mod.analyze(task["code"], tests_src)
    session = session_mod.build(
        task["code"], tests_src,
        session_id="demo-%s-%s" % (task["id"], tests_variant),
        question_limit=question_limit,
        result=result,
        meta={"task": task["title"], "candidate": "Демо-кандидат", "language": task["language"]},
    )
    if not session.get("ok"):
        return {"schema": SCHEMA_VERSION, "ok": False, "error": session.get("error"), "analysis": result}
    auto_answer(session, ratio=ratio, seed="demo-%s" % task["id"])
    report = protocol_mod.build(session, meta={"task": task["title"]})
    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "task": {key: task[key] for key in ("id", "title", "level", "language", "statement", "skills")},
        "code": task["code"],
        "tests": tests_src,
        "analysis": result,
        "session": session_mod.public_view(session),
        "protocol": report,
    }


def candidate_bundle(candidate_id: str) -> Optional[Dict[str, Any]]:
    """Реальный протокол демо-кандидата: всё считается движком, а не задано руками."""
    candidate = get_candidate(candidate_id)
    if candidate is None:
        return None
    task = get_task(candidate["task"])
    tests_src = task["weak_tests"] if candidate["tests"] == "weak" else task["tests"]
    vacancy = get_vacancy(candidate["vacancy"]) or {}
    result = analysis_mod.analyze(task["code"], tests_src)
    session = session_mod.build(
        task["code"], tests_src,
        session_id="cand-%s" % candidate["id"],
        result=result,
        meta={
            "candidate": candidate["name"],
            "role": candidate["role"],
            "vacancy": vacancy.get("title", candidate["vacancy"]),
            "task": task["title"],
            "language": task["language"],
        },
    )
    if not session.get("ok"):
        return None
    auto_answer(session, ratio=candidate["ratio"], seed="cand-%s" % candidate["id"])
    report = protocol_mod.build(session)
    status = "Протокол готов" if report["passed"] else "Нужен разбор"
    return {
        "candidate": {
            **{key: candidate[key] for key in ("id", "name", "role", "submitted", "source")},
            "vacancy": vacancy.get("title", candidate["vacancy"]),
            "vacancy_id": candidate["vacancy"],
            "task": task["title"],
            "task_id": task["id"],
            "tests_variant": candidate["tests"],
            "status": status,
        },
        "summary": {
            "control_pct": report["control_pct"],
            "passed": report["passed"],
            "mutation_score_pct": report["mutation"]["score_pct"],
            "mutation_total": report["mutation"]["total"],
            "survived": report["mutation"]["survived"],
            "verdict": report["verdict"]["label"],
            "level": report["verdict"]["level"],
            "risks": len(report["risks"]),
            "duration_clock": report["duration_clock"],
        },
        "protocol": report,
        "analysis": {
            "mutation_total": result["mutation_total"],
            "killed": result["killed"],
            "survived": result["survived"],
            "gaps": result["gaps"],
            "tests": result["tests"],
            "useless_tests": result["useless_tests"],
        },
        "code": task["code"],
        "tests": tests_src,
    }


def candidates_overview() -> List[Dict[str, Any]]:
    """Сводка для кабинета работодателя."""
    rows = []
    for candidate in CANDIDATES:
        bundle = candidate_bundle(candidate["id"])
        if bundle is None:
            continue
        rows.append({**bundle["candidate"], **bundle["summary"]})
    return rows
