"""
ПРУФ · engine.session

Сессия защиты понимания: 15 минут, 6–15 вопросов, все вопросы собраны из конкретных
строк конкретного решения. Вопрос нельзя переиспользовать в другой сессии: он привязан
к отпечатку кода, а варианты перетасованы детерминированно от sha256(отпечаток + id сессии).

Типы вопросов:
    danger        — какая из трёх правок пройдёт мимо тестов (самая опасная)
    gap           — заметят ли тесты эту правку
    first_failure — какой тест упадёт первым
    consequence   — что именно сломается в поведении
"""

from __future__ import annotations

import hashlib
import random
import time
from typing import Any, Dict, List, Optional

from . import analysis as analysis_mod
from . import mutations as mut

SCHEMA_VERSION = "pruf.session/1"

SESSION_SECONDS = 15 * 60
MIN_QUESTIONS = 6
MAX_QUESTIONS = 15
DEFAULT_QUESTIONS = 13
MAX_PER_MUTATION = 2

NO_TEST_OPTION = "Ни один тест не заметит правку"
CRASH_OPTION = "Прогон упадёт целиком: ошибка или таймаут"

QUESTION_WEIGHTS = {"danger": 1.2, "gap": 1.3, "first_failure": 1.0, "consequence": 1.0}
QUESTION_TITLES = {
    "danger": "Какая правка опасна?",
    "gap": "Заметят ли ваши тесты эту правку?",
    "first_failure": "Какой тест упадёт первым?",
    "consequence": "Что именно сломается?",
}
QUESTION_HINTS = {
    "danger": "Опасна та правка, которая меняет поведение и при этом оставляет тесты зелёными.",
    "gap": "Правка уже применена к вашему коду. Решите головой, не запуская тесты.",
    "first_failure": "Смотрите на то, какой тест касается изменённой строки.",
    "consequence": "Важно не название оператора, а последствие для пользователя.",
}

_LETTERS = "ABCDE"


def _rng(*material: Any) -> random.Random:
    digest = hashlib.sha256("|".join(str(part) for part in material).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _short_diff(row: Dict[str, Any]) -> str:
    before = (row.get("before") or "").strip()
    after = (row.get("after") or "").strip()
    return "- %s\n+ %s" % (before, after)


def _finalize(raw: List[Dict[str, Any]], rng: random.Random):
    ordered = raw[:]
    rng.shuffle(ordered)
    options: List[Dict[str, Any]] = []
    correct: List[str] = []
    for index, item in enumerate(ordered[:len(_LETTERS)]):
        option_id = _LETTERS[index]
        options.append({
            "id": option_id,
            "label": item["label"],
            "kind": item.get("kind", "text"),
            "ref": item.get("ref"),
        })
        if item.get("correct"):
            correct.append(option_id)
    return options, correct


def _mutation_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "operator": row["operator"],
        "kind": row["kind"],
        "skill": row["skill"],
        "skill_title": row["skill_title"],
        "line": row["line"],
        "before": row["before"],
        "after": row["after"],
        "diff": row["diff"],
    }


def _question(kind: str, row: Dict[str, Any], prompt: str, options, correct, explanation: str) -> Dict[str, Any]:
    return {
        "id": "Q?",
        "type": kind,
        "title": QUESTION_TITLES[kind],
        "hint": QUESTION_HINTS[kind],
        "prompt": prompt,
        "weight": QUESTION_WEIGHTS[kind],
        "skill": row["skill"],
        "skill_title": row["skill_title"],
        "mutation": _mutation_payload(row),
        "options": options,
        "correct": correct,
        "explanation": explanation,
    }


def build_questions(result: Dict[str, Any], session_id: str, question_limit: int = DEFAULT_QUESTIONS) -> List[Dict[str, Any]]:
    """Собирает вопросы из результата мутационного анализа."""
    question_limit = max(1, min(int(question_limit), MAX_QUESTIONS))
    rows: List[Dict[str, Any]] = result.get("mutations", [])
    fingerprint = result.get("fingerprint", "")
    tests = [test["name"] for test in result.get("tests", [])]
    survived = [row for row in rows if row.get("status") == "survived"]
    killed = [row for row in rows if row.get("status") == "killed"]

    buckets: Dict[str, List[Dict[str, Any]]] = {"danger": [], "gap": [], "first_failure": [], "consequence": []}

    # danger: одна выжившая правка против двух пойманных
    if len(killed) >= 2:
        for row in survived:
            rng = _rng(fingerprint, session_id, "danger", row["id"])
            picks = rng.sample(killed, 2)
            raw = [{"label": _short_diff(row), "kind": "diff", "correct": True, "ref": row["id"]}]
            raw += [{"label": _short_diff(other), "kind": "diff", "ref": other["id"]} for other in picks]
            options, correct = _finalize(raw, rng)
            buckets["danger"].append(_question(
                "danger", row,
                "Какая из трёх правок изменит поведение и при этом не уронит ни один ваш тест?",
                options, correct,
                "Правка %s (%s, строка %d) прошла все тесты. %s Остальные две правки тесты поймали."
                % (row["id"], row["kind"], row["line"], row["consequence"]),
            ))

    # gap: заметят ли тесты
    for row in rows:
        rng = _rng(fingerprint, session_id, "gap", row["id"])
        raw: List[Dict[str, Any]] = []
        if row.get("status") == "survived":
            raw.append({"label": NO_TEST_OPTION, "correct": True})
            for name in tests[:2]:
                raw.append({"label": "Упадёт тест %s" % name})
            if len(raw) < 3:
                raw.append({"label": CRASH_OPTION})
            explanation = "Прогон показал: после правки %s все тесты остались зелёными. %s" % (
                row["id"], row.get("suggestion", ""))
        elif row.get("first_failed"):
            raw.append({"label": "Упадёт тест %s" % row["first_failed"], "correct": True})
            others = [name for name in tests if name != row["first_failed"]][:2]
            for name in others:
                raw.append({"label": "Упадёт тест %s" % name})
            raw.append({"label": NO_TEST_OPTION})
            explanation = "Тест %s ловит эту правку: %s" % (row["first_failed"], row["consequence"])
        else:
            raw.append({"label": CRASH_OPTION, "correct": True})
            raw.append({"label": NO_TEST_OPTION})
            for name in tests[:1]:
                raw.append({"label": "Упадёт только тест %s" % name})
            explanation = "После правки %s прогон не дошƫл до ассертов — код упал или завис." % row["id"]
        options, correct = _finalize(raw, rng)
        buckets["gap"].append(_question(
            "gap", row,
            "Правка ниже уже внесена в ваш код (строка %d). Что покажет прогон ваших тестов?" % row["line"],
            options, correct, explanation,
        ))

    # first_failure: какой тест упадёт первым
    if len(tests) >= 2:
        for row in killed:
            if not row.get("first_failed"):
                continue
            rng = _rng(fingerprint, session_id, "first_failure", row["id"])
            raw = [{"label": row["first_failed"], "correct": True}]
            others = [name for name in tests if name != row["first_failed"]][:2]
            raw += [{"label": name} for name in others]
            raw.append({"label": NO_TEST_OPTION})
            options, correct = _finalize(raw, rng)
            buckets["first_failure"].append(_question(
                "first_failure", row,
                "Правка %s внесена в строку %d. Какой из ваших тестов упадёт первым?" % (row["id"], row["line"]),
                options, correct,
                "Первым упал %s. Всего правку заметили тесты: %s."
                % (row["first_failed"], ", ".join(row.get("killed_by") or [row["first_failed"]])),
            ))

    # consequence: что именно сломается
    all_consequences = sorted({operator.consequence for operator in mut.OPERATOR_LIST})
    for row in rows:
        rng = _rng(fingerprint, session_id, "consequence", row["id"])
        distractors = [text for text in all_consequences if text != row["consequence"]]
        if len(distractors) < 2:
            continue
        picks = rng.sample(distractors, 2)
        raw = [{"label": row["consequence"], "correct": True}] + [{"label": text} for text in picks]
        options, correct = _finalize(raw, rng)
        buckets["consequence"].append(_question(
            "consequence", row,
            "Что именно изменится в поведении программы после правки в строке %d?" % row["line"],
            options, correct,
            "Оператор %s (%s): %s" % (row["operator"], row["kind"], row["consequence"]),
        ))

    order = ["danger", "gap", "first_failure", "consequence"]
    questions: List[Dict[str, Any]] = []
    per_mutation: Dict[str, int] = {}
    index = 0
    while len(questions) < question_limit:
        progressed = False
        for kind in order:
            bucket = buckets[kind]
            if index >= len(bucket):
                continue
            progressed = True
            candidate = bucket[index]
            mutation_id = candidate["mutation"]["id"]
            if per_mutation.get(mutation_id, 0) >= MAX_PER_MUTATION:
                continue
            per_mutation[mutation_id] = per_mutation.get(mutation_id, 0) + 1
            questions.append(candidate)
            if len(questions) >= question_limit:
                break
        index += 1
        if not progressed:
            break

    for number, question in enumerate(questions, start=1):
        question["id"] = "Q%d" % number
    return questions


def new_session_id(code: str, salt: Optional[str] = None) -> str:
    material = "%s|%s|%s" % (mut.code_fingerprint(code), salt or "", time.time())
    return "s-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def build(
    code: str,
    tests_src: str,
    session_id: Optional[str] = None,
    limit: int = mut.DEFAULT_LIMIT,
    question_limit: int = DEFAULT_QUESTIONS,
    result: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Готовит сессию защиты. Если анализ уже сделан, передайте его в result."""
    session_id = session_id or new_session_id(code)
    result = result or analysis_mod.analyze(code, tests_src, limit=limit)
    if not result.get("ok"):
        return {
            "schema": SCHEMA_VERSION,
            "ok": False,
            "id": session_id,
            "error": result.get("error", "анализ не выполнен"),
            "stage": result.get("stage"),
            "analysis": result,
        }

    questions = build_questions(result, session_id, question_limit=question_limit)
    now = time.time()
    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "id": session_id,
        "status": "active",
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "seconds_total": SESSION_SECONDS,
        "fingerprint": result.get("fingerprint"),
        "meta": meta or {},
        "code": code,
        "tests": tests_src,
        "summary": {
            "mutation_total": result.get("mutation_total", 0),
            "killed": result.get("killed", 0),
            "survived": result.get("survived", 0),
            "mutation_score_pct": result.get("mutation_score_pct", 0),
            "verdict": result.get("verdict", {}),
            "lines": result.get("lines", 0),
            "sites": result.get("sites", 0),
        },
        "baseline": result.get("baseline", {}),
        "skills": result.get("skills", []),
        "gaps": result.get("gaps", []),
        "tests_report": result.get("tests", []),
        "questions": questions,
        "answers": {},
    }


def remaining_seconds(session: Dict[str, Any]) -> int:
    started = session.get("started_at") or time.time()
    left = int(session.get("seconds_total", SESSION_SECONDS) - (time.time() - started))
    return max(0, left)


def public_view(session: Dict[str, Any]) -> Dict[str, Any]:
    """Вид для клиента: правильные ответы и разборы не уходят до ответа."""
    if not session.get("ok", True):
        return dict(session)
    answers = session.get("answers", {})
    questions = []
    for question in session.get("questions", []):
        item = {key: value for key, value in question.items() if key not in {"correct", "explanation"}}
        answer = answers.get(question["id"])
        if answer:
            item["answer"] = answer
            item["correct"] = question["correct"]
            item["explanation"] = question["explanation"]
        questions.append(item)
    view = {key: value for key, value in session.items() if key not in {"questions", "tests", "code"}}
    view["questions"] = questions
    view["code"] = session.get("code", "")
    view["tests"] = session.get("tests", "")
    view["answered"] = len(answers)
    view["questions_total"] = len(session.get("questions", []))
    view["remaining_seconds"] = remaining_seconds(session)
    return view


def answer(session: Dict[str, Any], question_id: str, option_id: str, seconds: Optional[float] = None) -> Dict[str, Any]:
    """Ответ на вопрос. Ответить можно один раз — второй попытки нет."""
    found = None
    for question in session.get("questions", []):
        if question["id"] == question_id:
            found = question
            break
    if found is None:
        return {"ok": False, "error": "Вопрос %s не найден в этой сессии" % question_id}

    answers = session.setdefault("answers", {})
    if question_id in answers:
        stored = answers[question_id]
        return {
            "ok": True, "repeat": True, "correct": stored["correct"],
            "correct_options": found["correct"], "explanation": found["explanation"],
            "mutation": found["mutation"],
            "progress": {"answered": len(answers), "total": len(session.get("questions", []))},
            "status": session.get("status"),
        }

    valid = {option["id"] for option in found["options"]}
    if option_id not in valid:
        return {"ok": False, "error": "Вариант %s не относится к вопросу %s" % (option_id, question_id)}

    is_correct = option_id in found["correct"]
    answers[question_id] = {
        "option_id": option_id,
        "correct": is_correct,
        "seconds": round(float(seconds), 1) if seconds is not None else None,
        "at": time.time(),
        "order": len(answers) + 1,
    }

    total = len(session.get("questions", []))
    if len(answers) >= total:
        session["status"] = "finished"
        session["finished_at"] = time.time()

    return {
        "ok": True,
        "correct": is_correct,
        "correct_options": found["correct"],
        "explanation": found["explanation"],
        "mutation": found["mutation"],
        "suggestion": next(
            (gap.get("suggestion") for gap in session.get("gaps", []) if gap.get("id") == found["mutation"]["id"]),
            None,
        ),
        "progress": {"answered": len(answers), "total": total},
        "status": session.get("status"),
    }


def finish(session: Dict[str, Any]) -> Dict[str, Any]:
    if session.get("status") != "finished":
        session["status"] = "finished"
        session["finished_at"] = time.time()
    return session
