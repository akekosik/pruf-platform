"""Сессия верификации v2: разминка без веса + решающие артефактные задания.

Старая сессия (engine/session.py) собирала вопросы с вариантами ответа. Это удобно
для объяснения формата и безнадёжно против фотографии экрана: четыре варианта в
кадре — значит, кадр содержит ответ.

Поэтому сессия разделена на две части:

    разминка   вопросы с вариантами, вес 0 — нарочно решаемые, нужны только чтобы
                человек понял, что вообще происходит;
    решающая   артефактные задания (найти вход-свидетель, написать тест-убийцу),
                только она идёт в вердикт.

Всё, что нельзя показывать клиенту, лежит в ключах с подчёркиванием (_mutants,
_witnesses, _checks, _client) и вырезается рекурсивно в public_view. Так утечка
становится структурно невозможной, а не вопросом аккуратности.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import analysis as analysis_mod
from . import audit as audit_mod
from . import mutations as mut
from . import relay
from . import session as session_mod
from . import witness

SCHEMA_VERSION = "pruf.verify/1"

# Вес разминки ровно нуль — это инвариант I5, а не настройка.
WARMUP_WEIGHT = 0.0
WARMUP_QUESTIONS = 4
DECISIVE_LIMIT = 4

PHASES = ("brief", "warmup", "experiment", "decisive", "done")

PUBLIC_CLASSIFICATION_KEYS = ("counts", "titles", "honest_mutation_pct", "corpus_size", "note")
CLIENT_TELEMETRY_KEYS = ("paste_chars", "typed_chars", "blur_ms", "latency_ms", "revealed")

CLAIM = "В кадре нет ответа: его нет даже в данных, которые получает браузер"


def _scrub(node: Any) -> Any:
    """Рекурсивно удаляет приватные ключи (начинаются с подчёркивания)."""
    if isinstance(node, dict):
        return {
            key: _scrub(value)
            for key, value in node.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return node


def build(
    code: str,
    tests_src: str,
    session_id: Optional[str] = None,
    limit: int = mut.DEFAULT_LIMIT,
    warmup_limit: int = WARMUP_QUESTIONS,
    decisive_limit: int = DECISIVE_LIMIT,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Собирает сессию: анализ → классификация мутантов → решающие задания."""
    started = time.time()
    result = analysis_mod.analyze(code, tests_src, limit=limit, include_code=True)
    if not result.get("ok"):
        return {
            "schema": SCHEMA_VERSION,
            "ok": False,
            "id": session_id or "",
            "error": result.get("error") or "Анализ не выполнен",
            "stage": result.get("stage"),
            "analysis": result,
        }
    sess = session_mod.build(
        code,
        tests_src,
        session_id=session_id,
        limit=limit,
        question_limit=max(1, int(warmup_limit)),
        result=result,
        meta=meta,
    )
    if not sess.get("ok"):
        return sess

    classification = witness.classify_mutants(code, tests_src, result)
    plan = witness.build_relay_plan(
        code,
        tests_src,
        result,
        sess["id"],
        limit=max(1, int(decisive_limit)),
        classification=classification,
    )
    source = plan.get("classification") or classification
    public_classification = {
        key: source.get(key) for key in PUBLIC_CLASSIFICATION_KEYS if key in source
    }

    sess["verify_schema"] = SCHEMA_VERSION
    sess["mode"] = "relay"
    sess["phase"] = "brief"
    sess["relay"] = {
        "schema": SCHEMA_VERSION,
        "tasks": plan.get("tasks") or [],
        "targets": plan.get("targets") or [],
        "classification": public_classification,
        "grades": {},
        "log": [],
        "experiments": [],
        "experiments_used": 0,
        "experiments_cursor": 0,
        "experiments_budget": relay.MAX_EXPERIMENTS,
        "telemetry": {"decisive": []},
        "weights": dict(relay.TASK_WEIGHTS),
        "step_budget": dict(relay.STEP_BUDGET),
        "warmup_weight": WARMUP_WEIGHT,
        "pass_control_pct": relay.PASS_CONTROL_PCT,
        "pass_partial_pct": relay.PASS_PARTIAL_PCT,
        "claim": CLAIM,
        "build_ms": int((time.time() - started) * 1000),
    }
    sess["_mutants"] = plan.get("_mutants") or {}
    sess["_witnesses"] = plan.get("_witnesses") or {}
    sess["_checks"] = {}
    sess["_client"] = {}
    return sess


def _task(state: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for task in state.get("tasks") or []:
        if task.get("task_id") == task_id:
            return task
    return None


def public_view(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Ровно то, что уходит в браузер. Фотография не может содержать больше этого."""
    if not sess.get("ok", True):
        return _scrub(dict(sess))
    view = _scrub(session_mod.public_view(sess))
    state = sess.get("relay") or {}
    grades = state.get("grades") or {}
    tasks: List[Dict[str, Any]] = []
    for task in state.get("tasks") or []:
        item = _scrub(dict(task))
        grade = grades.get(task.get("task_id"))
        if grade:
            item["grade"] = _scrub(dict(grade))
            item["status"] = "done"
        else:
            item["status"] = "open"
        tasks.append(item)
    used = int(state.get("experiments_used") or 0)
    budget = int(state.get("experiments_budget") or relay.MAX_EXPERIMENTS)
    view["mode"] = sess.get("mode") or "relay"
    view["phase"] = sess.get("phase") or "brief"
    view["verify_schema"] = SCHEMA_VERSION
    view["warmup_weight"] = WARMUP_WEIGHT
    view["decisive_total"] = len(tasks)
    view["decisive_done"] = len(grades)
    view["relay"] = {
        "schema": state.get("schema") or SCHEMA_VERSION,
        "tasks": tasks,
        "targets": state.get("targets") or [],
        "classification": state.get("classification") or {},
        "experiments": state.get("experiments") or [],
        "experiments_used": used,
        "experiments_left": max(0, budget - used),
        "experiments_budget": budget,
        "weights": state.get("weights") or {},
        "step_budget": state.get("step_budget") or {},
        "pass_control_pct": state.get("pass_control_pct"),
        "pass_partial_pct": state.get("pass_partial_pct"),
        "claim": state.get("claim") or CLAIM,
        "log": state.get("log") or [],
        "score": state.get("score"),
        "audit": state.get("audit"),
    }
    return view


def set_phase(sess: Dict[str, Any], phase: str) -> Dict[str, Any]:
    if phase not in PHASES:
        return {"ok": False, "error": "Неизвестная фаза %s" % phase}
    if sess.get("phase") == "done":
        return {"ok": False, "error": "Сессия завершена"}
    sess["phase"] = phase
    return {"ok": True, "phase": phase}


def answer_warmup(
    sess: Dict[str, Any],
    question_id: str,
    option_id: str,
    seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Ответ на разминочный вопрос. На вердикт не влияет никогда."""
    if sess.get("phase") == "done":
        return {"ok": False, "error": "Сессия завершена"}
    outcome = session_mod.answer(sess, question_id, option_id, seconds=seconds)
    state = sess.setdefault("relay", {})
    state.setdefault("log", []).append(
        {
            "at": time.time(),
            "kind": "warmup",
            "question": question_id,
            "ok": bool(outcome.get("ok", True)),
        }
    )
    if sess.get("phase") == "brief":
        sess["phase"] = "warmup"
    if isinstance(outcome, dict):
        outcome["weight"] = WARMUP_WEIGHT
        outcome["counts_towards_verdict"] = False
        outcome["note"] = "Разминка не влияет на вердикт — это инвариант I5"
    return outcome


def run_experiment(sess: Dict[str, Any], expression: str) -> Dict[str, Any]:
    """Консоль экспериментов: прогоняет ТОЛЬКО решение кандидата, никогда мутанта."""
    if sess.get("phase") == "done":
        return {"ok": False, "error": "Сессия завершена", "remaining": 0}
    state = sess.setdefault("relay", {})
    used = int(state.get("experiments_used") or 0)
    budget = int(state.get("experiments_budget") or relay.MAX_EXPERIMENTS)
    outcome = relay.experiment(sess.get("code") or "", expression, used=used, budget=budget)
    consumed = bool(outcome.get("ok")) or outcome.get("kind") == "exception"
    if consumed:
        used += 1
        state["experiments_used"] = used
    state.setdefault("experiments", []).append(
        {
            "n": used,
            "at": time.time(),
            "expression": outcome.get("expression") or str(expression)[:200],
            "ok": bool(outcome.get("ok")),
            "kind": outcome.get("kind"),
            "value": outcome.get("value"),
            "message": outcome.get("message"),
            "error": outcome.get("error"),
            "counted": consumed,
        }
    )
    if len(state["experiments"]) > 200:
        state["experiments"] = state["experiments"][-200:]
    if sess.get("phase") in ("brief", "warmup"):
        sess["phase"] = "experiment"
    outcome["used"] = used
    outcome["remaining"] = max(0, budget - used)
    return outcome


def record_telemetry(sess: Dict[str, Any], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Телеметрия процесса: ни камеры, ни экрана, ни биометрии."""
    payload = payload or {}
    task_id = str(payload.get("task") or payload.get("task_id") or "")
    if not task_id:
        return {"ok": False, "error": "Нужен task"}
    bucket = sess.setdefault("_client", {}).setdefault(task_id, {})
    for key in CLIENT_TELEMETRY_KEYS:
        if key not in payload:
            continue
        if key == "revealed":
            bucket[key] = bool(payload[key]) or bool(bucket.get(key))
            continue
        try:
            bucket[key] = max(int(bucket.get(key) or 0), int(payload[key] or 0))
        except (TypeError, ValueError):
            continue
    return {"ok": True, "task": task_id}


def _evidence_ok(task: Dict[str, Any], check: Dict[str, Any]) -> Optional[bool]:
    check = check or {}
    if task.get("type") == "witness":
        if not check.get("ok") or not check.get("differs"):
            return False
        evidence = check.get("evidence") or {}
        return bool(evidence.get("original_claim_ok") and evidence.get("mutant_claim_ok"))
    if task.get("type") == "test_fix":
        return bool(check.get("ok")) and bool(check.get("kills"))
    return None


def submit_task(sess: Dict[str, Any], task_id: str, submission: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Сдача решающего задания. Одна попытка на задание."""
    if sess.get("phase") == "done":
        return {"ok": False, "error": "Сессия завершена"}
    state = sess.setdefault("relay", {})
    task = _task(state, task_id)
    if task is None:
        return {"ok": False, "error": "Задание %s не найдено в этой сессии" % task_id}
    if task_id in (state.get("grades") or {}):
        return {"ok": False, "error": "Задание уже сдано — второй попытки нет"}
    mutant_code = (sess.get("_mutants") or {}).get(task.get("mutation_id"))
    if not mutant_code:
        return {"ok": False, "error": "Код правки для задания не найден"}

    sess["phase"] = "decisive"
    grade = relay.grade_task(task, submission or {}, sess.get("code") or "", mutant_code)
    check = grade.get("_check") or {}
    public_grade = _scrub(dict(grade))
    sess.setdefault("_checks", {})[task_id] = check
    state.setdefault("grades", {})[task_id] = public_grade

    cursor = int(state.get("experiments_cursor") or 0)
    used = int(state.get("experiments_used") or 0)
    client = (sess.get("_client") or {}).get(task_id) or {}
    row = {
        "task_id": task_id,
        "experiments": max(0, used - cursor),
        "latency_ms": int(client.get("latency_ms") or 0),
        "paste_chars": int(client.get("paste_chars") or 0),
        "typed_chars": int(client.get("typed_chars") or 0),
        "blur_ms": int(client.get("blur_ms") or 0),
        "revealed": bool(client.get("revealed")),
        "evidence_ok": _evidence_ok(task, check),
        "scored": True,
    }
    state["experiments_cursor"] = used
    state.setdefault("telemetry", {}).setdefault("decisive", []).append(row)
    state.setdefault("log", []).append(
        {
            "at": time.time(),
            "kind": task.get("type"),
            "task": task_id,
            "score": public_grade.get("score"),
        }
    )
    total = len(state.get("tasks") or [])
    done = len(state.get("grades") or {})
    return {
        "ok": True,
        "grade": public_grade,
        "decisive_done": done,
        "decisive_total": total,
        "all_done": done >= total,
        "telemetry": row,
    }


def audit_payload(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Пайлоад для аудита без разборов разминки.

    Разминка нарочно решается из кадра и после ответа показывает разбор — её вес нуль
    (I5), поэтому в границу SSR она не входит. Всё остальное аудитируется как есть.
    """
    view = public_view(sess)
    questions = []
    for question in view.get("questions") or []:
        questions.append(
            {
                key: value
                for key, value in question.items()
                if key not in ("correct", "explanation", "answer")
            }
        )
    payload = dict(view)
    payload["questions"] = questions
    return payload


def audit_view(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Аудит реального клиентского пайлоада этой сессии."""
    state = sess.get("relay") or {}
    return audit_mod.audit(
        audit_payload(sess),
        tasks=state.get("tasks") or [],
        telemetry=state.get("telemetry") or {"decisive": []},
        warmup_weight=WARMUP_WEIGHT,
        code_lines=len((sess.get("code") or "").splitlines()),
    )


def finish(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Завершает сессию: взвешенный итог решающей стадии плюс аудит."""
    state = sess.setdefault("relay", {})
    tasks = state.get("tasks") or []
    grades = list((state.get("grades") or {}).values())
    scored = relay.score_tasks(tasks, grades)
    state["score"] = scored
    sess["phase"] = "done"
    session_mod.finish(sess)
    report = audit_view(sess)
    state["audit"] = report
    return {"score": scored, "audit": report}
