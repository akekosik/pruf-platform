"""Роуты анти-релей протокола.

Подключаются к server.app без его правки: таблицы GET_ROUTES/POST_ROUTES — обычные
словари, и register() дописывает в них свои обработчики. id сессии передаётся в
теле запроса (POST) или в ?id= (GET), чтобы не трогать разбор путей.

Роуты
    POST /api/verify/start        {code, tests, limit, warmup, tasks, meta}
    GET  /api/verify?id=          текущее состояние сессии
    POST /api/verify/phase        {id, phase}
    POST /api/verify/warmup       {id, question, option, seconds}
    POST /api/verify/experiment   {id, expression}
    POST /api/verify/task         {id, task, expression|test_source, observed_*}
    POST /api/verify/telemetry    {id, task, paste_chars, typed_chars, blur_ms, latency_ms, revealed}
    POST /api/verify/finish       {id, meta}
    GET  /api/verify/audit?id=    аудит того же пайлоада, который видит браузер
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from engine import protocol, store, verify

from . import app as app_mod

ApiError = app_mod.ApiError

AUDIT_PUBLIC_KEYS = ("passed", "invariants", "ssr", "ssr_gate", "threat_model", "risk", "claim")


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _session_id(payload: Optional[Dict[str, Any]], query: Optional[Dict[str, Any]]) -> str:
    payload = payload or {}
    value = payload.get("session") or payload.get("id")
    if not value:
        for key in ("id", "session"):
            values = (query or {}).get(key) or []
            if values:
                value = values[0]
                break
    if not value:
        raise ApiError("Нужен id сессии")
    return str(value)


def _load(session_id: str) -> Dict[str, Any]:
    sess = store.load("sessions", session_id)
    if sess is None:
        raise ApiError("Сессия не найдена или уже удалена", 404)
    if not sess.get("relay"):
        raise ApiError("Сессия старого формата: начните новую проверку", 409)
    return sess


def _save(sess: Dict[str, Any]) -> Dict[str, Any]:
    store.save("sessions", sess["id"], sess)
    return sess


def api_verify_start(payload: dict, _query: dict) -> dict:
    code = app_mod._require_code(payload)
    tests = app_mod._require_tests(payload)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    sess = verify.build(
        code,
        tests,
        limit=app_mod._limit(payload),
        warmup_limit=_int(payload.get("warmup"), verify.WARMUP_QUESTIONS),
        decisive_limit=_int(payload.get("tasks"), verify.DECISIVE_LIMIT),
        meta=meta,
    )
    if not sess.get("ok"):
        raise ApiError(sess.get("error") or "Не удалось собрать сессию", 422)
    if not (sess.get("relay") or {}).get("tasks"):
        raise ApiError(
            "Ни одна правка этого решения не меняет поведение — решающие задания не построены. "
            "Возьмите задачу с более содержательной логикой или добавьте тестов.",
            422,
        )
    _save(sess)
    return verify.public_view(sess)


def api_verify_state(_payload: dict, query: dict) -> dict:
    return verify.public_view(_load(_session_id(None, query)))


def api_verify_audit(_payload: dict, query: dict) -> dict:
    sess = _load(_session_id(None, query))
    report = verify.audit_view(sess)
    return {
        "session": sess["id"],
        "audit": report,
        "payload_keys": sorted(verify.audit_payload(sess).keys()),
    }


def api_verify_phase(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    outcome = verify.set_phase(sess, str(payload.get("phase") or ""))
    if not outcome.get("ok"):
        raise ApiError(outcome.get("error") or "Фаза не переключена")
    _save(sess)
    return {"phase": outcome["phase"], "session": verify.public_view(sess)}


def api_verify_warmup(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    question_id = payload.get("question") or payload.get("question_id")
    option_id = payload.get("option") or payload.get("option_id")
    if not question_id or not option_id:
        raise ApiError("Нужны question и option")
    outcome = verify.answer_warmup(sess, str(question_id), str(option_id), seconds=payload.get("seconds"))
    if outcome.get("ok") is False:
        raise ApiError(outcome.get("error") or "Ответ не принят")
    _save(sess)
    return {"answer": outcome, "session": verify.public_view(sess)}


def api_verify_experiment(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    expression = str(payload.get("expression") or payload.get("expr") or "")
    if not expression.strip():
        raise ApiError("Пустое выражение: нужен вызов функции вашего решения")
    outcome = verify.run_experiment(sess, expression)
    _save(sess)
    state = (verify.public_view(sess).get("relay") or {})
    return {
        "run": outcome,
        "experiments": state.get("experiments") or [],
        "experiments_left": state.get("experiments_left"),
    }


def api_verify_task(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    task_id = str(payload.get("task") or payload.get("task_id") or "")
    if not task_id:
        raise ApiError("Нужен task")
    submission = payload.get("submission") if isinstance(payload.get("submission"), dict) else {
        "expression": payload.get("expression"),
        "observed_original": payload.get("observed_original"),
        "observed_mutant": payload.get("observed_mutant"),
        "test_source": payload.get("test_source"),
    }
    outcome = verify.submit_task(sess, task_id, submission)
    if not outcome.get("ok"):
        raise ApiError(outcome.get("error") or "Задание не принято", 409)
    _save(sess)
    outcome["session"] = verify.public_view(sess)
    return outcome


def api_verify_telemetry(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    outcome = verify.record_telemetry(sess, payload)
    if not outcome.get("ok"):
        raise ApiError(outcome.get("error") or "Телеметрия не принята")
    _save(sess)
    return outcome


def api_verify_finish(payload: dict, query: dict) -> dict:
    sess = _load(_session_id(payload, query))
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
    outcome = verify.finish(sess)
    report = protocol.build(sess, meta=meta)
    report["relay"] = outcome["score"]
    report["audit"] = {key: outcome["audit"].get(key) for key in AUDIT_PUBLIC_KEYS}
    _save(sess)
    store.save("protocols", report["id"], report)
    return {
        "protocol": report,
        "score": outcome["score"],
        "audit": outcome["audit"],
        "session": verify.public_view(sess),
    }


GET_ROUTES = {
    "/api/verify": api_verify_state,
    "/api/verify/audit": api_verify_audit,
}

POST_ROUTES = {
    "/api/verify/start": api_verify_start,
    "/api/verify/phase": api_verify_phase,
    "/api/verify/warmup": api_verify_warmup,
    "/api/verify/experiment": api_verify_experiment,
    "/api/verify/task": api_verify_task,
    "/api/verify/telemetry": api_verify_telemetry,
    "/api/verify/finish": api_verify_finish,
}


def register() -> Dict[str, int]:
    """Идемпотентная регистрация роутов в таблицах server.app."""
    app_mod.GET_ROUTES.update(GET_ROUTES)
    app_mod.POST_ROUTES.update(POST_ROUTES)
    return {"get": len(GET_ROUTES), "post": len(POST_ROUTES)}


register()
