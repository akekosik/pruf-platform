"""Аудит анти-релей протокола: SSR, инварианты I1–I5, стоимость релея, риск-индекс.

Защита от «сфотографировал и спросил модель» не может быть обещанием в презентации.
Она должна быть метрикой, которая падает в CI, если интерфейс случайно начнёт
отдавать лишнее.

SSR (screenshot solve rate) — верхняя оценка доли заданий, решаемых из кадра:

    guess            = 1 / число вариантов (если варианты есть)
    derivable_static = 0, если ответ требует запуска кода
    ssr_static       = 1 − max(guess, coverage × derivable_static)
    ssr_tool         = 1 − coverage

Названия специально перевёрнутые: ssr = 1 означает «с кадра не решается
вообще», то есть чем больше, тем лучше. Порог для решающих шагов — SSR_GATE.

Инварианты, которые проверяются механически
    I1 no_enumerable_answer  у решающего задания нет списка вариантов;
    I2 no_answer_in_payload  в клиентском payload нет эталонов, свидетелей,
                             кода мутанта и приватных ключей;
    I3 requires_execution    каждое решающее задание требует запуска кода;
    I4 frame_split           одного кадра недостаточно: ssr_static ≥ SSR_GATE;
    I5 warmup_has_no_weight  разминка с вариантами не влияет на вердикт.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from . import relay

SCHEMA_VERSION = "pruf.audit/1"

SSR_GATE = 0.90

# Сколько информации несёт кадр для каждого типа шага.
#   options            число вариантов ответа на экране (0 = свободный артефакт);
#   coverage           доля нужных для ответа данных, видимая в кадре;
#   execution_required нужен ли фактический запуск кода;
#   frames             сколько разных кадров придётся собрать атакующему.
FRAME_PROFILE = {
    "warmup": {"options": 4, "coverage": 1.00, "execution_required": False, "frames": 1},
    "witness": {"options": 0, "coverage": 0.34, "execution_required": True, "frames": 3},
    "test_fix": {"options": 0, "coverage": 0.34, "execution_required": True, "frames": 3},
}

# Стоимость одного цикла релея в секундах (замеры на живом телефоне).
RELAY_COST = {"capture": 6.0, "upload": 5.0, "model": 12.0, "readback": 9.0}
# Перенабрать или выровнять строку кода с фотографии — около 4,5 с на строку.
TRANSCRIBE_COST_PER_LINE = 4.5
# Сверх этого: собрать мутанта, прогнать и сверить значения.
EXEC_OVERHEAD = {"witness": 36.5, "test_fix": 68.5}

RISK_HIGH = 55
RISK_MEDIUM = 25

# Поведенческие сигналы. Это НЕ прокторинг: нет камеры, нет экрана, нет
# биометрии. Смотрим только на процесс работы в самом инструменте.
# Сигналы не влияют на балл — они только помечают сессию к пересмотру.
RISK_SIGNALS = {
    "answer_without_experiment": {
        "weight": 34,
        "title": "Верный ответ без единого прогона",
        "why": "Различающий вход практически невозможно назвать, не запустив код",
    },
    "evidence_mismatch": {
        "weight": 24,
        "title": "Заявленные значения не совпали с прогоном",
        "why": "Артефакт угадан или подсказан, но не наблюдался",
    },
    "paste_dominant": {
        "weight": 18,
        "title": "Ответ преимущественно вставлен из буфера",
        "why": "Большая часть символов появилась одним блоком",
    },
    "focus_gap_before_answer": {
        "weight": 16,
        "title": "Длительный уход из окна перед ответом",
        "why": "Сам по себе не нарушение, но в совокупности с другими — сигнал",
    },
    "flat_latency": {
        "weight": 12,
        "title": "Одинаковое время на разных по сложности шагах",
        "why": "Работа руками даёт разброс по времени, конвейер — нет",
    },
    "no_reveal": {
        "weight": 8,
        "title": "Кандидат ни разу не раскрыл дифф",
        "why": "Ответ дан про правку, которую не смотрели",
    },
}

# Ключи, которые не должны покидать сервер ни при каких условиях.
BANNED_PAYLOAD_KEYS = (
    "correct",
    "correct_index",
    "correct_answer",
    "reference",
    "reference_answer",
    "expected",
    "expected_value",
    "witness",
    "witnesses",
    "witness_expression",
    "mutant_code",
    "mutant_output",
    "mutant_value",
    "kill_input",
    "observed_original",
    "observed_mutant",
)


def _cv(values: List[float]) -> float:
    """Коэффициент вариации — мера разброса, независимая от масштаба."""
    clean = [float(value) for value in values if value]
    if len(clean) < 2:
        return 1.0
    mean = sum(clean) / len(clean)
    if mean <= 0:
        return 1.0
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return (variance ** 0.5) / mean


def frame_analysis(kind: str, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """SSR для одного типа шага."""
    base = dict(FRAME_PROFILE.get(kind) or FRAME_PROFILE["warmup"])
    base.update(profile or {})
    options = int(base.get("options") or 0)
    coverage = float(base.get("coverage") or 0.0)
    derivable_static = 0.0 if base.get("execution_required") else 1.0
    guess = (1.0 / options) if options else 0.0
    ssr_static = 1.0 - max(guess, coverage * derivable_static)
    ssr_tool = 1.0 - coverage
    return {
        "kind": kind,
        "options": options,
        "coverage": round(coverage, 4),
        "execution_required": bool(base.get("execution_required")),
        "frames": int(base.get("frames") or 1),
        "guess": round(guess, 4),
        "ssr_static": round(max(0.0, min(1.0, ssr_static)), 4),
        "ssr_tool": round(max(0.0, min(1.0, ssr_tool)), 4),
    }


def relay_cost_model(task_type: str, code_lines: int = 26) -> Dict[str, Any]:
    """Сколько секунд стоит релей при двух сценариях атаки.

    A1 — только фотография кадра. Цикл дешёвый, но ответа не даёт: при ssr_static
    ≥ SSR_GATE в кадре просто нет нужных данных.

    A2 — второй компьютер с запуском кода. Здесь мы честны: сам бюджет времени
    атаку не закрывает. Закрывает то, что атакующему придётся восстановить
    решение строка за строкой, собрать мутанта и прогнать его — то есть
    выполнить ту же инженерную работу, которую мы и измеряем.
    """
    cycle = round(sum(RELAY_COST.values()), 2)
    transcribe = round(TRANSCRIBE_COST_PER_LINE * max(0, int(code_lines)), 2)
    overhead = float(EXEC_OVERHEAD.get(task_type, 40.0))
    budget = int(relay.STEP_BUDGET.get(task_type, 240))
    a2 = round(cycle + transcribe + overhead, 2)
    return {
        "task_type": task_type,
        "budget_seconds": budget,
        "cycle_seconds": cycle,
        "a1_seconds": cycle,
        "a1_yields_answer": False,
        "a2_seconds": a2,
        "a2_fits_budget": a2 <= budget,
        "transcribe_seconds": transcribe,
        "exec_overhead_seconds": overhead,
        "binding_constraint": "execution",
        "note": (
            "A1 дешёвый, но бесполезный: в кадре нет ответа. A2 укладывается в бюджет, "
            "поэтому опора защиты — не таймер, а обязательность запуска кода."
        ),
    }


def find_in_payload(payload: Any, keys: Tuple[str, ...] = BANNED_PAYLOAD_KEYS) -> List[str]:
    """Пути до запрещённых или приватных ключей в отдаваемом наружу объекте."""
    hits: List[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                where = "%s.%s" % (path, key) if path else str(key)
                if isinstance(key, str) and (key in keys or key.startswith("_")):
                    hits.append(where)
                walk(value, where)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, "%s[%d]" % (path, index))

    walk(payload, "")
    return hits


def risk_index(telemetry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Индекс риска по телеметрии процесса.

    Ожидаемый вход:
        {"decisive": [{"task_id": "T1", "experiments": 3, "latency_ms": 90000,
                       "paste_chars": 40, "typed_chars": 300, "blur_ms": 1200,
                       "revealed": true, "evidence_ok": true, "scored": true}]}
    """
    items = list((telemetry or {}).get("decisive") or [])
    fired: List[Dict[str, Any]] = []

    def fire(signal: str, detail: str) -> None:
        meta = RISK_SIGNALS[signal]
        fired.append(
            {
                "id": signal,
                "weight": meta["weight"],
                "title": meta["title"],
                "why": meta["why"],
                "detail": detail,
            }
        )

    scored = [item for item in items if item.get("scored", True)]
    blind = [item for item in scored if not int(item.get("experiments") or 0)]
    if blind:
        fire(
            "answer_without_experiment",
            "шаги без прогонов: %s" % ", ".join(str(item.get("task_id")) for item in blind),
        )
    mismatched = [item for item in items if item.get("evidence_ok") is False]
    if mismatched:
        fire("evidence_mismatch", "шагов с расхождением: %d" % len(mismatched))
    paste_chars = sum(int(item.get("paste_chars") or 0) for item in items)
    typed_chars = sum(int(item.get("typed_chars") or 0) for item in items)
    if paste_chars >= 40 and (paste_chars / float(paste_chars + typed_chars or 1)) > 0.6:
        fire("paste_dominant", "из буфера %d из %d символов" % (paste_chars, paste_chars + typed_chars))
    blur = max([int(item.get("blur_ms") or 0) for item in items] or [0])
    if blur >= 8000:
        fire("focus_gap_before_answer", "максимальный уход из окна %.1f с" % (blur / 1000.0))
    latencies = [float(item.get("latency_ms") or 0) for item in items]
    if len(latencies) >= 3:
        variation = _cv(latencies)
        if variation < 0.15:
            fire("flat_latency", "коэффициент вариации %.2f" % variation)
    if items and not any(item.get("revealed") for item in items):
        fire("no_reveal", "дифф не раскрывался ни разу")

    score = min(100, sum(int(signal["weight"]) for signal in fired))
    if score >= RISK_HIGH:
        level, title = "high", "Требует пересмотра человеком"
    elif score >= RISK_MEDIUM:
        level, title = "medium", "Есть на что посмотреть"
    else:
        level, title = "low", "Процесс выглядит естественно"
    return {
        "schema": SCHEMA_VERSION,
        "score": score,
        "level": level,
        "title": title,
        "signals": fired,
        "steps": len(items),
        "disclaimer": (
            "Риск-индекс не меняет балл и не является обвинением. Он только решает, "
            "показать ли сессию человеку."
        ),
    }


def audit(
    payload: Any,
    tasks: Optional[List[Dict[str, Any]]] = None,
    telemetry: Optional[Dict[str, Any]] = None,
    warmup_weight: float = 0.0,
    code_lines: int = 26,
) -> Dict[str, Any]:
    """Полный аудит: инварианты, SSR, стоимость релея, модель угроз.

    payload — ровно то, что клиент получает с сервера. Фотография не может
    содержать больше, чем payload, поэтому аудит payload есть верхняя оценка
    того, что вообще можно увидеть в кадре.
    """
    started = time.time()
    tasks = list(tasks or [])
    decisive = [task for task in tasks if task.get("type") in relay.DECISIVE_TYPES]

    enumerable = [
        task.get("task_id")
        for task in decisive
        if task.get("options") or task.get("choices") or not task.get("artifact")
    ]
    leaks = find_in_payload(payload)
    no_execution = [task.get("task_id") for task in decisive if not task.get("requires_execution")]

    ssr_rows = [frame_analysis(kind) for kind in ("warmup",) + tuple(relay.DECISIVE_TYPES)]
    weak_frames = [
        row["kind"]
        for row in ssr_rows
        if row["kind"] in relay.DECISIVE_TYPES and row["ssr_static"] < SSR_GATE
    ]

    invariants = [
        {
            "id": "I1",
            "key": "no_enumerable_answer",
            "title": "У решающего задания нет перебираемого ответа",
            "ok": not enumerable,
            "detail": "варианты найдены у: %s" % ", ".join(map(str, enumerable)) if enumerable else "все шаги требуют артефакта",
        },
        {
            "id": "I2",
            "key": "no_answer_in_payload",
            "title": "В клиентском payload нет эталонов и свидетелей",
            "ok": not leaks,
            "detail": "утечки: %s" % ", ".join(leaks[:8]) if leaks else "запрещённых ключей нет",
        },
        {
            "id": "I3",
            "key": "requires_execution",
            "title": "Ответ невозможен без запуска кода",
            "ok": bool(decisive) and not no_execution,
            "detail": "без запуска: %s" % ", ".join(map(str, no_execution)) if no_execution else "решающих шагов: %d" % len(decisive),
        },
        {
            "id": "I4",
            "key": "frame_split",
            "title": "Одного кадра недостаточно",
            "ok": not weak_frames,
            "detail": "слабые шаги: %s" % ", ".join(weak_frames) if weak_frames else "ssr_static ≥ %.2f на всех решающих шагах" % SSR_GATE,
        },
        {
            "id": "I5",
            "key": "warmup_has_no_weight",
            "title": "Разминка не влияет на вердикт",
            "ok": float(warmup_weight) == 0.0,
            "detail": "вес разминки = %s" % warmup_weight,
        },
    ]

    threat_model = [
        {
            "id": "A1",
            "title": "Фотография экрана в любую нейросеть",
            "status": "снято",
            "why": (
                "В кадре есть только дифф и форма для артефакта. Чтобы назвать различающий "
                "вход и два наблюдаемых значения, нужно запустить код — фотография этого "
                "не даёт."
            ),
            "cost": relay_cost_model("witness", code_lines),
        },
        {
            "id": "A2",
            "title": "Второй компьютер с запуском кода",
            "status": "удорожается",
            "why": (
                "Атакующему придётся восстановить решение строка за строкой, собрать "
                "мутанта и прогнать его, то есть сделать ту же работу, которую мы и "
                "проверяем. Процесс при этом виден в телеметрии."
            ),
            "cost": relay_cost_model("test_fix", code_lines),
        },
        {
            "id": "A3",
            "title": "Знакомый инженер рядом",
            "status": "вне зоны действия",
            "why": (
                "Ни один софт этого не закрывает, и мы не делаем вид, что закрываем. "
                "Протокол понимания — фильтр перед техсобесом, а не замена ему."
            ),
            "cost": None,
        },
    ]

    passed = all(item["ok"] for item in invariants)
    return {
        "schema": SCHEMA_VERSION,
        "passed": passed,
        "invariants": invariants,
        "ssr": ssr_rows,
        "ssr_gate": SSR_GATE,
        "threat_model": threat_model,
        "risk": risk_index(telemetry) if telemetry is not None else None,
        "cla