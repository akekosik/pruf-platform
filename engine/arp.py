"""
ПРУФ · engine.arp

АРП-2 «Оракул» — протокол защиты от релея через фотографию экрана.

Три аксиомы (подробно в docs/anti-relay.md):
  A1. В кадре нет ответа: скрытая правка не отображается никогда, экран
      побайтово одинаков при разных скрытых правках.
  A2. Ответ добывается взаимодействием: единственный источник информации —
      дифференциальный оракул, отдающий ровно один бит за зонд.
  A3. Ответ без доказательства не считается: метка засчитывается только если
      собранные биты оставляют ровно одну совместимую гипотезу.

Никаких языковых моделей: один и тот же код и сид дают один и тот же вердикт.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import math
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import mutations as mutations_mod
from . import sandbox

SCHEMA_VERSION = "pruf.arp/2"
PROTOCOL = "АРП-2"
PROTOCOL_TITLE = "АРП-2 «Оракул»"
PROTOCOL_SCHEMA = "pruf.arp.protocol/1"
COLLECTION = "arp_sessions"

PROBE_BUDGET = 7
RUN_BUDGET = 60
SESSION_BUDGET_S = 900
THRESHOLD_CONTROL = 0.80
THRESHOLD_SHAKY = 0.50
CONFIRMED_AT = 0.70
MAX_EXPR_CHARS = 400
MAX_EXPR_NODES = 180
MAX_TRAP_BYTES = 8000
POOL_LIMIT = 10
HYPOTHESES_TARGET = 8
HYPOTHESES_MIN = 4
PROBE_TIMEOUT = 8.0
REPR_CAP = 120
MAX_IDENTIFY_ATTEMPTS = 2
MAX_TRAP_ATTEMPTS = 3
TELEMETRY_LIMIT = 500

VALUE_MARK = "<<PRUF:V>>"
ERROR_MARK = "<<PRUF:E>>"

VERDICTS = {
    "control": "Контролирует свой код",
    "shaky": "Контроль шаткий",
    "none": "Не контролирует",
}

STEP_DEFS: Tuple[Dict[str, Any], ...] = (
    {
        "type": "locate",
        "title": "Локализация",
        "weight": 0.25,
        "budget_seconds": 240,
        "goal": "Найдите вход, на котором скрытая правка проявляется",
        "hint": "Прогоны по вашему коду бесплатны. Зонд сравнивает ваш код со скрытой правкой и возвращает один бит.",
    },
    {
        "type": "identify",
        "title": "Идентификация",
        "weight": 0.40,
        "budget_seconds": 300,
        "goal": "Назовите, какая именно правка загружена",
        "hint": "Ответ засчитывается только если ваши зонды оставляют ровно одну совместимую гипотезу.",
    },
    {
        "type": "trap",
        "title": "Ловушка",
        "weight": 0.35,
        "budget_seconds": 360,
        "goal": "Напишите тест, который проходит на вашем коде и падает на скрытой правке",
        "hint": "Это и есть доказательство: ловушка ловит именно загруженную правку.",
    },
)

_LOCATE_SCORE = {1: 1.0, 2: 0.9, 3: 0.75, 4: 0.6, 5: 0.5}

FORBIDDEN_KEYS = (
    "secret", "active", "probe_bits", "signature_cache", "pool",
    "base_signatures", "correct", "answer", "mutant", "pool_bits",
)
PUBLIC_STEP_KEYS = (
    "type", "title", "goal", "hint", "weight", "budget_seconds",
    "status", "score", "attempts", "message", "flags", "detail",
)
_VOLATILE = ("id", "candidate", "created_at", "deadline_at", "seconds_left")

TELEMETRY_TYPES = ("render", "focus_lost", "focus_back", "paste", "copy", "typing", "idle")


# --------------------------------------------------------------- ошибки

class ArpError(Exception):
    """Ошибка протокола с машинной причиной и человеческим сообщением."""

    def __init__(self, reason: str, message: str, status: int = 400, detail: Any = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": self.reason, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class ProbeRejected(ArpError):
    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__("probe_rejected", message, 422, detail)


# ------------------------------------------------------------ математика

def entropy_bits(count: int) -> float:
    return round(math.log2(count), 3) if count and count > 0 else 0.0


def min_probes(count: int) -> int:
    return int(math.ceil(math.log2(count))) if count and count > 1 else 0


def worst_case_bound(hypotheses: Sequence[Dict[str, Any]]) -> int:
    return min_probes(len(hypotheses))


def instance_bound(hypotheses: Sequence[Dict[str, Any]], active: str) -> int:
    """Точная граница инстанса: минимальный набор зондов пула, отделяющий active от всех."""
    table = {item["id"]: tuple(item.get("pool_bits") or ()) for item in hypotheses}
    target = table.get(active)
    if not target:
        return 0
    others = [bits for hid, bits in table.items() if hid != active]
    if not others:
        return 0
    width = len(target)
    for size in range(1, width + 1):
        for combo in itertools.combinations(range(width), size):
            if all(any(bits[i] != target[i] for i in combo) for bits in others):
                return size
    return width


def probe_gain(hypotheses: Sequence[Dict[str, Any]], alive: Sequence[str], index: int) -> int:
    ones = 0
    for item in hypotheses:
        if item["id"] in alive and item["pool_bits"][index]:
            ones += 1
    return min(ones, len(alive) - ones)


def math_note(count: int) -> str:
    return (
        "На экране %d гипотез — это %.3f бита неопределённости. Весь публичный экран можно отдать любой модели: "
        "вердикт всё равно требует не менее %d обращений к оракулу — в кадре нет ни одного бита ответа."
        % (count, entropy_bits(count), min_probes(count))
    )


def relay_cost(count: int) -> Dict[str, Any]:
    cycles = min_probes(count) + 2
    seconds = cycles * 40
    return {
        "cycles": cycles,
        "seconds_per_cycle": 40,
        "seconds": seconds,
        "budget_seconds": SESSION_BUDGET_S,
        "note": "стоимость релея: %d циклов ≈ %d с при бюджете %d с" % (cycles, seconds, SESSION_BUDGET_S),
    }


def verdict_for(score: float) -> str:
    if score >= THRESHOLD_CONTROL:
        return "control"
    if score >= THRESHOLD_SHAKY:
        return "shaky"
    return "none"


def code_fingerprint(code: str) -> str:
    return mutations_mod.code_fingerprint(code)


# --------------------------------------------------------- разбор решения

def public_names(code: str) -> List[str]:
    tree = ast.parse(code)
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            names.append(node.name)
    return names


def allowed_names(code: str) -> set:
    tree = ast.parse(code)
    names: set = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
    return names


def _arity(code: str) -> Dict[str, Tuple[int, int]]:
    tree = ast.parse(code)
    info: Dict[str, Tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            total = len(node.args.args)
            required = total - len(node.args.defaults)
            info[node.name] = (max(0, required), total)
    return info


_ALLOWED_NODES = (
    ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List,
    ast.Dict, ast.Set, ast.keyword, ast.Starred, ast.BinOp, ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
)


def validate_expression(expr: str, code: str) -> str:
    """Зонд — это вызов функций решения. Всё остальное отклоняется до запуска."""
    text = (expr or "").strip()
    if not text:
        raise ProbeRejected("Зонд пустой: напишите вызов функции вашего решения")
    if len(text) > MAX_EXPR_CHARS:
        raise ProbeRejected("Зонд длиннее %d символов" % MAX_EXPR_CHARS)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ProbeRejected("Зонд не разбирается как выражение: %s" % exc.msg)
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_EXPR_NODES:
        raise ProbeRejected("Зонд слишком сложный: разбейте его на части")
    allowed = allowed_names(code)
    callable_names = set(public_names(code))
    has_call = False
    for node in nodes:
        if isinstance(node, ast.Attribute):
            raise ProbeRejected("Обращение к атрибутам в зонде запрещено")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ProbeRejected("Служебные имена недоступны")
            if node.id not in allowed:
                raise ProbeRejected("Имя %s недоступно: зонд вызывает только ваши функции" % node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in callable_names:
            has_call = True
        if not isinstance(node, _ALLOWED_NODES):
            raise ProbeRejected("В зонде разрешены только вызовы ваших функций и литералы")
    if not has_call:
        raise ProbeRejected("Зонд должен вызывать функцию решения")
    return text


def validate_trap(tests_src: str) -> str:
    text = (tests_src or "").strip()
    if not text:
        raise ArpError("trap_empty", "Ловушка пустая: напишите тест", 422)
    if len(text.encode("utf-8")) > MAX_TRAP_BYTES:
        raise ArpError("trap_too_large", "Ловушка больше %d байт" % MAX_TRAP_BYTES, 422)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ArpError("trap_syntax", "Ловушка не компилируется: %s" % exc.msg, 422)
    found = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
    ]
    if not found:
        raise ArpError("trap_no_tests", "В ловушке нет функции, имя которой начинается с test", 422)
    return text


# ------------------------------------------------------------- оракул

def multi_source(exprs: Sequence[str]) -> str:
    """Тестовый файл, который считает подписи сразу нескольких зондов."""
    lines = [
        "import solution",
        "EXPRS = %r" % (list(exprs),),
        "MARK_V = %r" % VALUE_MARK,
        "MARK_E = %r" % ERROR_MARK,
        "",
        "def test_probe():",
        "    scope = dict(vars(solution))",
        "    for index, expr in enumerate(EXPRS):",
        "        try:",
        "            value = eval(expr, dict(scope))",
        "        except Exception as exc:",
        "            print(str(index) + '|' + MARK_E + type(exc).__name__)",
        "        else:",
        "            print(str(index) + '|' + MARK_V + repr(value)[:%d])" % REPR_CAP,
        "",
    ]
    return "\n".join(lines)


def _parse_multi(report: Dict[str, Any], count: int) -> List[str]:
    if report.get("timeout"):
        return ["T:timeout"] * count
    if report.get("import_error"):
        return ["I:%s" % str(report["import_error"])[:80]] * count
    signatures = ["?:нет ответа"] * count
    for line in (report.get("stdout") or "").splitlines():
        head, sep, rest = line.partition("|")
        if not sep or not head.isdigit():
            continue
        index = int(head)
        if index >= count:
            continue
        if rest.startswith(VALUE_MARK):
            signatures[index] = "V:" + rest[len(VALUE_MARK):]
        elif rest.startswith(ERROR_MARK):
            signatures[index] = "E:" + rest[len(ERROR_MARK):]
    return signatures


def _usable(signature: str) -> bool:
    return bool(signature) and (signature.startswith("V:") or signature.startswith("E:"))


def describe_signature(signature: str) -> str:
    if not signature:
        return "нет ответа"
    if signature.startswith("V:"):
        return "значение %s" % signature[2:]
    if signature.startswith("E:"):
        return "исключение %s" % signature[2:]
    if signature.startswith("T:"):
        return "не уложился во время"
    if signature.startswith("I:"):
        return "ошибка импорта: %s" % signature[2:]
    return "нет ответа"


def _signatures_batched(code: str, exprs: Sequence[str], chunk: int = 8) -> List[str]:
    out: List[str] = []
    items = list(exprs)
    for start_at in range(0, len(items), chunk):
        batch = items[start_at:start_at + chunk]
        report = sandbox.run_tests(code, multi_source(batch), timeout=PROBE_TIMEOUT)
        out.extend(_parse_multi(report, len(batch)))
    return out


_LITERALS = (
    '"Болт;3;12.5"', '10', '"Гайка;10;4.0"', '3', '"Болт;3;12.5\\nГайка;2;4.0"', '0',
    '"Шайба;9;1.5"', '9', '"Винт;11;2.0"', '11', '""', '1', '[1, 2, 3]', '"abc"',
    '" abc "', '"ABC"', '[]', '2', '-1', '0.5', '100.0', 'True', 'False',
)


def probe_pool(code: str) -> List[str]:
    """Кандидаты в зонды: вызовы публичных функций и их композиции, по кругу между функциями."""
    info = _arity(code)
    if not info:
        return []
    names = sorted(info)
    unary = [name for name in names if info[name][0] <= 1 <= info[name][1]]
    buckets: Dict[str, List[str]] = {}

    def add(owner: str, expr: str) -> None:
        items = buckets.setdefault(owner, [])
        if expr not in items:
            items.append(expr)

    for name in names:
        required, total = info[name]
        if required == 0:
            add(name, "%s()" % name)
        if required <= 1 <= total:
            for literal in _LITERALS:
                add(name, "%s(%s)" % (name, literal))
        if required <= 2 <= total:
            for literal in _LITERALS[:6]:
                add(name, "%s(%s, %s)" % (name, literal, literal))
    for outer in unary:
        for inner in unary:
            if outer == inner:
                continue
            for literal in _LITERALS[:8]:
                add("%s/%s" % (outer, inner), "%s(%s(%s))" % (outer, inner, literal))

    order = sorted(buckets)
    out: List[str] = []
    index = 0
    while True:
        progressed = False
        for owner in order:
            items = buckets[owner]
            if index < len(items):
                out.append(items[index])
                progressed = True
        index += 1
        if not progressed:
            break
    return out[:96]


def claim_text(mutation: Any) -> str:
    return "%s — %s" % (mutation.kind, mutation.consequence)


def build_hypotheses(code: str) -> Dict[str, Any]:
    """Строит множество попарно различимых гипотез и пул зондов для них."""
    mutants = mutations_mod.generate(code, limit=mutations_mod.MAX_LIMIT)
    if len(mutants) < HYPOTHESES_MIN:
        raise ArpError(
            "no_mutations",
            "Для этого решения удалось построить только %d правок, нужно минимум %d" % (len(mutants), HYPOTHESES_MIN),
            422,
        )
    candidates = probe_pool(code)
    if not candidates:
        raise ArpError("no_probe_pool", "Не удалось собрать пул зондов: в решении нет публичных функций", 422)

    base_all = _signatures_batched(code, candidates)
    pool: List[str] = []
    base_signatures: List[str] = []
    seen: set = set()
    for expr, signature in zip(candidates, base_all):
        if not _usable(signature) or signature in seen:
            continue
        seen.add(signature)
        pool.append(expr)
        base_signatures.append(signature)
        if len(pool) >= POOL_LIMIT:
            break
    if len(pool) < 2:
        raise ArpError("pool_unusable", "Пул зондов беден: решение не даёт различимых наблюдений", 422)

    reports = sandbox.run_many(
        [(item.id, item.code) for item in mutants], multi_source(pool), timeout=PROBE_TIMEOUT
    )
    hypotheses: List[Dict[str, Any]] = []
    patterns: set = set()
    dropped: List[str] = []
    for mutation in mutants:
        signatures = _parse_multi(reports.get(mutation.id, {}), len(pool))
        bits = tuple(0 if signatures[i] == base_signatures[i] else 1 for i in range(len(pool)))
        if not any(bits):
            dropped.append(mutation.id)
            continue
        if bits in patterns:
            dropped.append(mutation.id)
            continue
        patterns.add(bits)
        hypotheses.append({
            "id": mutation.id,
            "claim": claim_text(mutation),
            "kind": mutation.kind,
            "skill": mutation.skill,
            "skill_title": mutation.skill_title,
            "consequence": mutation.consequence,
            "operator": mutation.operator,
            "line": mutation.line,
            "diff": mutation.diff,
            "code": mutation.code,
            "pool_bits": list(bits),
        })
        if len(hypotheses) >= HYPOTHESES_TARGET:
            break
    if len(hypotheses) < HYPOTHESES_MIN:
        raise ArpError(
            "too_few_hypotheses",
            "Различимых гипотез получилось %d, нужно минимум %d — задача не годится для АРП-2"
            % (len(hypotheses), HYPOTHESES_MIN),
            422,
        )
    return {"hypotheses": hypotheses, "pool": pool, "base_signatures": base_signatures, "dropped": dropped}


# ------------------------------------------------------------ хранилище

def _store():
    from . import store  # локальный импорт: смоук-прогон работает без хранилища
    return store


def _save(session: Dict[str, Any]) -> None:
    if not session.get("persist"):
        return
    _store().save(COLLECTION, session["id"], session)


def load(session_id: str) -> Dict[str, Any]:
    session = _store().load(COLLECTION, session_id)
    if not session:
        raise ArpError("unknown_session", "Сессия не найдена", 404)
    return session


# --------------------------------------------------------------- сессия

def start(
    code: Optional[str] = None,
    tests: Optional[str] = None,
    title: Optional[str] = None,
    candidate: Optional[str] = None,
    seed: Optional[str] = None,
    persist: bool = True,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    demo = demo_task()
    code = (code or demo["code"]).replace("\r\n", "\n")
    tests = (tests or demo["tests"]).replace("\r\n", "\n")
    title = title or demo["title"]
    moment = float(now if now is not None else time.time())

    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise ArpError("solution_syntax", "Решение не разбирается: %s" % exc.msg, 422)

    baseline = sandbox.run_tests(code, tests, timeout=PROBE_TIMEOUT)
    if not baseline.get("ok"):
        raise ArpError(
            "baseline_failed",
            "Ваши тесты не проходят на вашем же решении — сначала нужен зелёный прогон",
            422,
            detail={
                "passed": baseline.get("passed", 0),
                "failed": baseline.get("failed", 0),
                "errored": baseline.get("errored", 0),
                "import_error": baseline.get("import_error"),
            },
        )

    built = build_hypotheses(code)
    hypotheses = built["hypotheses"]
    fingerprint = code_fingerprint(code)
    seed_value = seed or uuid.uuid4().hex[:12]
    rng = random.Random("%s|%s" % (fingerprint, seed_value))
    active = rng.choice([item["id"] for item in hypotheses])

    steps = []
    for index, definition in enumerate(STEP_DEFS):
        step = dict(definition)
        step.update({
            "status": "open" if index == 0 else "locked",
            "score": None,
            "attempts": 0,
            "message": "",
            "flags": [],
            "detail": None,
        })
        steps.append(step)

    session: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "protocol_title": PROTOCOL_TITLE,
        "id": "a-" + uuid.uuid4().hex[:10],
        "title": title,
        "candidate": candidate or "",
        "created_at": moment,
        "deadline_at": moment + SESSION_BUDGET_S,
        "finished_at": None,
        "status": "live",
        "code": code,
        "tests": tests,
        "fingerprint": fingerprint,
        "seed": seed_value,
        "baseline": {"passed": baseline.get("passed", 0), "duration_ms": baseline.get("duration_ms", 0)},
        "steps": steps,
        "probes": [],
        "runs": [],
        "telemetry": [],
        "phase_b": False,
        "hypotheses_total": len(hypotheses),
        "screen_entropy_bits": entropy_bits(len(hypotheses)),
        "min_probes": min_probes(len(hypotheses)),
        "persist": bool(persist),
        "protocol_result": None,
        "secret": {
            "active": active,
            "hypotheses": hypotheses,
            "pool": built["pool"],
            "base_signatures": built["base_signatures"],
            "dropped": built["dropped"],
            "evidence": [],
            "signature_cache": {},
        },
    }
    _save(session)
    return session


def tick(session: Dict[str, Any], now: Optional[float] = None) -> int:
    moment = float(now if now is not None else time.time())
    left = int(max(0, session["deadline_at"] - moment))
    if left <= 0 and session["status"] == "live":
        session["status"] = "expired"
    return left


def _require_live(session: Dict[str, Any]) -> None:
    if session.get("status") == "finished":
        raise ArpError("session_finished", "Сессия уже закрыта", 409)


def _step(session: Dict[str, Any], kind: str) -> Dict[str, Any]:
    for step in session["steps"]:
        if step["type"] == kind:
            return step
    raise ArpError("unknown_step", "Шаг %s не найден" % kind, 404)


def _require_step(session: Dict[str, Any], kind: str) -> Dict[str, Any]:
    _require_live(session)
    step = _step(session, kind)
    if step["status"] == "locked":
        raise ArpError("step_locked", "Шаг «%s» ещё не открыт" % step["title"], 409)
    if step["status"] == "done":
        raise ArpError("step_closed", "Шаг «%s» уже закрыт" % step["title"], 409)
    return step


def _open_next(session: Dict[str, Any], kind: str) -> None:
    types = [step["type"] for step in session["steps"]]
    index = types.index(kind)
    if index + 1 < len(session["steps"]):
        following = session["steps"][index + 1]
        if following["status"] == "locked":
            following["status"] = "open"
    if kind == "locate":
        session["phase_b"] = True


def _close_step(session: Dict[str, Any], step: Dict[str, Any], score: float, message: str,
                flags: Optional[List[str]] = None, detail: Any = None) -> None:
    step["status"] = "done"
    step["score"] = round(float(score), 3)
    step["message"] = message
    if flags:
        step["flags"] = list(flags)
    if detail is not None:
        step["detail"] = detail
    _open_next(session, step["type"])


def _hypothesis(session: Dict[str, Any], hypothesis_id: str) -> Dict[str, Any]:
    for item in session["secret"]["hypotheses"]:
        if item["id"] == hypothesis_id:
            return item
    raise ArpError("unknown_hypothesis", "Такой гипотезы в списке нет", 422)


def consistent_set(session: Dict[str, Any]) -> List[str]:
    """Гипотезы, совместимые со всеми собранными битами."""
    evidence = session["secret"]["evidence"]
    alive = []
    for item in session["secret"]["hypotheses"]:
        hid = item["id"]
        if all(row["pattern"].get(hid) == row["bit"] for row in evidence):
            alive.append(hid)
    return alive


# ------------------------------------------------------- публичный вид

def public_view(session: Dict[str, Any]) -> Dict[str, Any]:
    """Всё, что разрешено показать на экране. Ни одного бита про скрытую правку."""
    total = session["hypotheses_total"]
    view: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "protocol_title": PROTOCOL_TITLE,
        "id": session["id"],
        "title": session["title"],
        "candidate": session["candidate"],
        "created_at": session["created_at"],
        "deadline_at": session["deadline_at"],
        "seconds_left": int(max(0, session["deadline_at"] - time.time())),
        "status": session["status"],
        "code": session["code"],
        "tests": session["tests"],
        "fingerprint": session["fingerprint"],
        "baseline": dict(session["baseline"]),
        "phase": "B" if session["phase_b"] else "A",
        "hypotheses_total": total,
        "hypotheses": [],
        "screen_entropy_bits": session["screen_entropy_bits"],
        "min_probes_required": session["min_probes"],
        "probe_budget": PROBE_BUDGET,
        "probes_used": len(session["probes"]),
        "run_budget": RUN_BUDGET,
        "runs_used": len(session["runs"]),
        "probe_log": [
            {"n": item["n"], "expr": item["expr"], "differs": item["bit"] == 1}
            for item in session["probes"]
        ],
        "runs": [dict(item) for item in session["runs"][-5:]],
        "steps": [{key: step.get(key) for key in PUBLIC_STEP_KEYS} for step in session["steps"]],
        "math_note": math_note(total),
        "relay_cost": relay_cost(total),
        "protocol_result": session.get("protocol_result"),
    }
    if session["phase_b"]:
        view["hypotheses"] = [
            {
                "id": item["id"],
                "claim": item["claim"],
                "kind": item["kind"],
                "skill_title": item["skill_title"],
            }
            for item in session["secret"]["hypotheses"]
        ]
    return view


def normalized_public(session: Dict[str, Any]) -> Dict[str, Any]:
    view = public_view(session)
    for key in _VOLATILE:
        view.pop(key, None)
    return view


def screen_digest(session: Dict[str, Any]) -> str:
    blob = json.dumps(normalized_public(session), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def audit_public(session: Dict[str, Any]) -> List[str]:
    """Ищет утечки в публичном виде: запрещённые ключи и исходник скрытого мутанта."""
    view = public_view(session)
    view.pop("protocol_result", None)
    findings: List[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                where = "%s.%s" % (path, key) if path else str(key)
                if key in FORBIDDEN_KEYS:
                    findings.append(where)
                walk(value, where)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, "%s[%d]" % (path, index))

    walk(view, "")
    blob = json.dumps(view, ensure_ascii=False)
    active = _hypothesis(session, session["secret"]["active"])
    for line in active["diff"].splitlines():
        if not line.startswith("+"):
            continue
        text = line[1:].strip()
        if len(text) >= 12 and text in blob:
            findings.append("mutant_source:%s" % active["id"])
            break
    return sorted(set(findings))


# ---------------------------------------------------------- оракул: API

def _signatures_for(session: Dict[str, Any], variant_code: str, exprs: Sequence[str]) -> List[str]:
    cache = session["secret"]["signature_cache"]
    prefix = code_fingerprint(variant_code)
    missing = [expr for expr in exprs if ("%s|%s" % (prefix, expr)) not in cache]
    if missing:
        signatures = _signatures_batched(variant_code, missing)
        for expr, signature in zip(missing, signatures):
            cache["%s|%s" % (prefix, expr)] = signature
    return [cache["%s|%s" % (prefix, expr)] for expr in exprs]


def run_original(session: Dict[str, Any], expr: str) -> Dict[str, Any]:
    """Прогон по собственному коду: ноль бит про скрытую правку, поэтому бесплатен."""
    _require_live(session)
    text = validate_expression(expr, session["code"])
    if len(session["runs"]) >= RUN_BUDGET:
        raise ArpError("run_budget", "Бюджет прогонов по оригиналу исчерпан", 409)
    signature = _signatures_for(session, session["code"], [text])[0]
    if not _usable(signature):
        raise ProbeRejected("Зонд не выполняется на вашем решении: %s" % describe_signature(signature))
    entry = {
        "n": len(session["runs"]) + 1,
        "expr": text,
        "result": describe_signature(signature),
        "at": time.time(),
    }
    session["runs"].append(entry)
    _save(session)
    return {
        "expr": text,
        "result": entry["result"],
        "runs_left": RUN_BUDGET - len(session["runs"]),
        "probes_used": len(session["probes"]),
    }


def _pattern_for(session: Dict[str, Any], expr: str, base: str) -> Dict[str, int]:
    """Бит различия для каждой гипотезы — нужен, чтобы сужать совместимое множество."""
    cache = session["secret"]["signature_cache"]
    pattern: Dict[str, int] = {}
    todo = []
    for item in session["secret"]["hypotheses"]:
        key = "%s|%s" % (code_fingerprint(item["code"]), expr)
        cached = cache.get(key)
        if cached is None:
            todo.append((item["id"], item["code"], key))
        else:
            pattern[item["id"]] = 0 if cached == base else 1
    if todo:
        reports = sandbox.run_many(
            [(hid, hcode) for hid, hcode, _ in todo], multi_source([expr]), timeout=PROBE_TIMEOUT
        )
        for hid, _hcode, key in todo:
            signature = _parse_multi(reports.get(hid, {}), 1)[0]
            cache[key] = signature
            pattern[hid] = 0 if signature == base else 1
    return pattern


def probe(session: Dict[str, Any], expr: str) -> Dict[str, Any]:
    """Одно обращение к дифференциальному оракулу. Возвращает ровно один бит."""
    _require_live(session)
    text = validate_expression(expr, session["code"])
    if len(session["probes"]) >= PROBE_BUDGET:
        raise ArpError(
            "probe_budget",
            "Бюджет зондов исчерпан: %d из %d" % (len(session["probes"]), PROBE_BUDGET),
            409,
        )
    base = _signatures_for(session, session["code"], [text])[0]
    if not _usable(base):
        raise ProbeRejected("Зонд не выполняется на вашем решении: %s" % describe_signature(base))
    pattern = _pattern_for(session, text, base)
    bit = int(pattern.get(session["secret"]["active"], 0))
    entry = {"n": len(session["probes"]) + 1, "expr": text, "bit": bit, "at": time.time()}
    session["probes"].append(entry)
    session["secret"]["evidence"].append({"expr": text, "bit": bit, "pattern": pattern})
    _save(session)
    return {
        "n": entry["n"],
        "expr": text,
        "differs": bit == 1,
        "probes_left": PROBE_BUDGET - len(session["probes"]),
        "message": (
            "Поведение отличается от оригинала на этом входе"
            if bit else "На этом входе поведение совпадает с оригиналом"
        ),
    }


# ------------------------------------------------------------- шаги

def submit_locate(session: Dict[str, Any], expr: str) -> Dict[str, Any]:
    step = _require_step(session, "locate")
    result = probe(session, expr)
    step["attempts"] += 1
    if not result["differs"]:
        return {
            "accepted": False,
            "score": None,
            "message": "На этом входе поведение совпадает с оригиналом — правка здесь не проявляется",
            "probes_used": len(session["probes"]),
            "probes_left": result["probes_left"],
        }
    score = _LOCATE_SCORE.get(len(session["probes"]), 0.45)
    _close_step(session, step, score, "Вход найден: на нём скрытая правка проявляется")
    _save(session)
    return {
        "accepted": True,
        "score": step["score"],
        "message": step["message"],
        "probes_used": len(session["probes"]),
        "hypotheses": [
            {"id": item["id"], "claim": item["claim"], "kind": item["kind"], "skill_title": item["skill_title"]}
            for item in session["secret"]["hypotheses"]
        ],
    }


def submit_identify(session: Dict[str, Any], hypothesis_id: str) -> Dict[str, Any]:
    step = _require_step(session, "identify")
    secret = session["secret"]
    ids = [item["id"] for item in secret["hypotheses"]]
    if hypothesis_id not in ids:
        raise ArpError("unknown_hypothesis", "Такой гипотезы в списке нет", 422)

    floor = session["min_probes"]
    used = len(session["probes"])
    if used < floor:
        # Порог улик: аксиома A3 держится политикой, а не только арифметикой.
        raise ArpError(
            "not_enough_evidence",
            "Нужно не менее %d зондов, чтобы называть гипотезу: сделано %d" % (floor, used),
            409,
        )

    step["attempts"] += 1
    alive = consistent_set(session)
    correct = hypothesis_id == secret["active"]

    if correct and len(alive) == 1 and alive[0] == secret["active"]:
        _close_step(session, step, 1.0, "Гипотеза названа и доказана: зонды оставляют ровно одну совместимую")
        _save(session)
        return {"accepted": True, "score": step["score"], "message": step["message"],
                "consistent_left": len(alive), "flags": step["flags"]}

    if correct:
        _close_step(
            session, step, 0.0,
            "Ответ без эвиденции: метка угадана, но зонды оставляют %d совместимых гипотез" % len(alive),
            flags=["ОБЭ"],
        )
        _save(session)
        return {"accepted": False, "score": step["score"], "message": step["message"],
                "consistent_left": len(alive), "flags": step["flags"]}

    if step["attempts"] < MAX_IDENTIFY_ATTEMPTS:
        _save(session)
        raise ArpError(
            "wrong_hypothesis",
            "Не эта правка. Осталась %d попытка — соберите ещё биты" % (MAX_IDENTIFY_ATTEMPTS - step["attempts"]),
            409,
        )
    _close_step(session, step, 0.0, "Гипотеза не определена: попытки исчерпаны")
    _save(session)
    return {"accepted": False, "score": step["score"], "message": step["message"],
            "consistent_left": len(alive), "flags": step["flags"]}


def check_trap(session: Dict[str, Any], tests_src: str) -> Dict[str, Any]:
    """Прогоняет ловушку на оригинале и на всех гипотезах: разрешающая сила теста."""
    text = validate_trap(tests_src)
    on_original = sandbox.run_tests(session["code"], text, timeout=PROBE_TIMEOUT)
    if not on_original.get("ok"):
        message = on_original.get("import_error") or "тест не проходит"
        for item in on_original.get("tests") or []:
            if item.get("status") != "passed":
                message = "%s: %s" % (item.get("name"), item.get("message"))
                break
        raise ArpError("trap_fails_on_original", "Тест падает уже на вашем коде: %s" % message, 409)

    hypotheses = session["secret"]["hypotheses"]
    reports = sandbox.run_many([(item["id"], item["code"]) for item in hypotheses], text, timeout=PROBE_TIMEOUT)
    killed = [item["id"] for item in hypotheses if not (reports.get(item["id"], {}) or {}).get("ok")]
    active = session["secret"]["active"]
    return {
        "killed": killed,
        "kills_active": active in killed,
        "power": round(len(killed) / float(len(hypotheses)), 3),
        "exact": active in killed and len(killed) == 1,
    }


def submit_trap(session: Dict[str, Any], tests_src: str) -> Dict[str, Any]:
    step = _require_step(session, "trap")
    report = check_trap(session, tests_src)
    step["attempts"] += 1

    if report["kills_active"]:
        _close_step(
            session, step, 1.0,
            "Ловушка сработала: тест прошёл на оригинале и упал на скрытой правке",
            detail={"power": report["power"], "exact": report["exact"]},
        )
        _save(session)
        return {"accepted": True, "score": step["score"], "message": step["message"],
                "power": report["power"], "exact": report["exact"]}

    if step["attempts"] < MAX_TRAP_ATTEMPTS:
        _save(session)
        raise ArpError(
            "trap_missed",
            "Тест проходит и на оригинале, и на скрытой правке — ловушка не сработала",
            409,
            detail={"power": report["power"]},
        )
    score = 0.25 if report["killed"] else 0.0
    _close_step(
        session, step, score,
        "Ловушка не поймала загруженную правку",
        detail={"power": report["power"]},
    )
    _save(session)
    return {"accepted": False, "score": step["score"], "message": step["message"], "power": report["power"]}


# --------------------------------------------------------- телеметрия

def telemetry(session: Dict[str, Any], kind: str, now: Optional[float] = None) -> Dict[str, Any]:
    if kind not in TELEMETRY_TYPES:
        raise ArpError("unknown_telemetry", "Неизвестный тип события: %s" % kind, 422)
    events = session["telemetry"]
    if len(events) < TELEMETRY_LIMIT:
        events.append({"kind": kind, "at": float(now if now is not None else time.time())})
    _save(session)
    return {"accepted": True, "events": len(events)}


def delegation_index(session: Dict[str, Any]) -> Dict[str, Any]:
    """Совещательный индекс делегирования. Не влияет на вердикт."""
    events = session["telemetry"]
    reasons: List[str] = []
    score = 0

    first_probe = session["probes"][0]["at"] if session["probes"] else None
    rendered = next((item["at"] for item in events if item["kind"] == "render"), session["created_at"])
    if first_probe is not None:
        delay = first_probe - rendered
        if delay > 90:
            score += 25
            reasons.append("до первого зонда прошло больше 90 с")
        elif delay > 45:
            score += 12
            reasons.append("до первого зонда прошло больше 45 с")

    pastes = sum(1 for item in events if item["kind"] == "paste")
    if pastes:
        score += min(30, pastes * 10)
        reasons.append("вставок из буфера: %d" % pastes)

    lost = sum(1 for item in events if item["kind"] == "focus_lost")
    if lost >= 3:
        score += 15
        reasons.append("уходов со страницы: %d" % lost)
    elif lost:
        score += 6
        reasons.append("уходов со страницы: %d" % lost)

    identify = _step(session, "identify")
    if "ОБЭ" in (identify.get("flags") or []):
        score += 30
        reasons.append("ответ без эвиденции")

    blind = sum(1 for item in session["probes"] if item["bit"] == 0)
    if blind >= 3:
        score += 10
        reasons.append("зондов без различия: %d" % blind)

    score = max(0, min(100, score))
    label = "высокий" if score >= 55 else ("средний" if score >= 25 else "низкий")
    return {"index": score, "label": label, "reasons": reasons}


# ------------------------------------------------------------ протокол

def finish(session: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    _require_live(session)
    moment = float(now if now is not None else time.time())
    secret = session["secret"]
    hypotheses = secret["hypotheses"]
    active = _hypothesis(session, secret["active"])

    score = 0.0
    for step in session["steps"]:
        score += float(step["weight"]) * float(step["score"] or 0.0)
    score = round(score, 3)
    verdict = verdict_for(score)
    alive = consistent_set(session)

    protocol = {
        "schema": PROTOCOL_SCHEMA,
        "score": score,
        "percent": int(round(score * 100)),
        "verdict": verdict,
        "verdict_title": VERDICTS[verdict],
        "confirmed": score >= CONFIRMED_AT,
        "duration_s": int(max(0, moment - session["created_at"])),
        "steps": [{key: step.get(key) for key in PUBLIC_STEP_KEYS} for step in session["steps"]],
        "evidence": {
            "hypotheses": len(hypotheses),
            "screen_entropy_bits": session["screen_entropy_bits"],
            "min_probes_required": session["min_probes"],
            "bound_instance": instance_bound(hypotheses, secret["active"]),
            "bound_worst_case": worst_case_bound(hypotheses),
            "probes_used": len(session["probes"]),
            "runs_on_original": len(session["runs"]),
            "consistent_left": len(alive),
            "entropy_left_bits": entropy_bits(len(alive)),
            "rows": [
                {"n": item["n"], "expr": item["expr"], "differs": item["bit"] == 1}
                for item in session["probes"]
            ],
        },
        "delegation": delegation_index(session),
        "reveal": {
            "hypothesis": active["id"],
            "claim": active["claim"],
            "skill": active["skill_title"],
            "consequence": active["consequence"],
            "diff": active["diff"],
        },
        "reproducibility": {
            "seed": session["seed"],
            "code_fingerprint": session["fingerprint"],
