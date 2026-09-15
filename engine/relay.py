"""АРП — анти-релей протокол ПРУФ.

Закрываемая атака: кандидат фотографирует экран, отдаёт фото внешней модели и
переписывает ответ. Прокторингом это не лечится (камера, биометрия, согласия),
да и ловит она поведение, а не понимание.

Модель угроз
    A1 «фото экрана»          снимается полностью: в кадре нет информации,
                              достаточной для ответа;
    A2 «второй компьютер»     не запрещается, а удорожается: ответ требует
                              прогонов кода, релей не укладывается в бюджет шага;
    A3 «живой инженер рядом»  вне зоны действия любого софта — объявляется честно.

Семь правил, из которых собран протокол
    1. Execution dependency  ответ невозможно вывести из текста, нужен запуск кода.
    2. Artifact-not-option   ответ — артефакт (вход или тест), а не выбор варианта.
    3. Evidence binding      вместе с артефактом заявляются наблюдаемые значения.
    4. Session entropy       набор заданий детерминирован сессией, не задачей.
    5. History dependency    решающие задания опираются на эксперименты в сессии.
    6. Latency budget        на шаг есть бюджет времени, цикл релея его съедает.
    7. Process telemetry     фиксируется процесс работы, а не картинка человека.

Главное утверждение, на котором держится защита:

    Информация(фотография экрана) ⊆ Информация(клиентский payload)

Фотография не может содержать больше того, что браузер получил с сервера.
Значит достаточно доказать, что в payload нет ответа — и атака A1 закрыта без
единой камеры. Формальные инварианты I1–I5 и их проверка живут в engine/audit.py.

Что здесь есть
    callable_targets / validate_call / eval_call  безопасный вызов решения;
    witness_check                                 проверка различающего входа;
    validate_test_source / test_fix_check         проверка теста-убийцы;
    build_tasks                                   сборка решающих заданий;
    experiment                                    консоль экспериментов кандидата;
    grade_task / score_tasks                      оценка с привязкой к доказательствам.
"""

from __future__ import annotations

import ast
import hashlib
import json
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from . import sandbox

SCHEMA_VERSION = "pruf.relay/1"

# Разминочные типы вопросов достались от Стапеля: это выбор из вариантов, их
# можно решить с фотографии, поэтому они не влияют на итог (инвариант I5).
WARMUP_TYPES = ("danger", "gap", "first_failure", "consequence")

# Решающие типы. Оба требуют запуска кода и не имеют перечислимого множества
# ответов, поэтому именно они определяют вердикт.
DECISIVE_TYPES = ("witness", "test_fix")

TASK_WEIGHTS = {"witness": 2.0, "test_fix": 2.4}
STEP_BUDGET = {"witness": 210, "test_fix": 300}

MAX_EXPERIMENTS = 40
EVAL_TIMEOUT = 6.0
MAX_ARTIFACT_BYTES = 8000
VALUE_MARKER = "@@PRUF_VALUE@@"

# Баллы внутри одного задания: найти вход — 0.6, подтвердить значения — 0.4.
# Так «угадал направление» и «действительно прогнал код» различаются в оценке.
WITNESS_FOUND_SCORE = 0.6
WITNESS_EVIDENCE_SCORE = 0.4
TEST_VALID_SCORE = 0.3

PASS_CONTROL_PCT = 70
PASS_PARTIAL_PCT = 40

TASK_PROMPTS = {
    "witness": (
        "Приведите вход, на котором ваше решение и показанная правка ведут себя "
        "по-разному, и укажите оба наблюдаемых значения."
    ),
    "test_fix": (
        "Напишите тест, который проходит на вашем решении и падает на показанной "
        "правке. Ваш текущий набор тестов эту правку не замечает."
    ),
}

TASK_TITLES = {
    "witness": "Различающий вход",
    "test_fix": "Тест-убийца",
}

# Разрешённые импорты в тесте кандидата. Список узкий сознательно: тест — это
# артефакт проверки, а не площадка для доступа к системе.
ALLOWED_TEST_IMPORTS = {
    "solution",
    "math",
    "json",
    "re",
    "copy",
    "string",
    "itertools",
    "statistics",
    "decimal",
    "fractions",
    "datetime",
}

BANNED_TEST_NAMES = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "exit",
    "quit",
}

# Строки, похожие на путь, URL или домашний каталог, в аргументы не пропускаем.
_PATHY = re.compile(r"(^\s*[/~])|(^\s*\.\.)|(^[a-zA-Z]:\\)|(://)")

# Зонд, которым измеряется поведение функции. Печатает одну строку с маркером,
# чтобы результат нельзя было спутать с выводом самого решения.
# ВАЖНО: _norm здесь и _jsonable ниже должны нормализовать значения одинаково,
# иначе сравнение заявленного значения с наблюдаемым начнёт врать.
_PROBE_TEMPLATE = '''import json
from solution import *  # noqa: F401,F403


def _norm(value, depth=0):
    if depth > 6:
        return repr(value)
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_norm(item, depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(repr(_norm(item, depth + 1)) for item in value)
    if isinstance(value, dict):
        return {repr(_norm(key, depth + 1)): _norm(item, depth + 1) for key, item in value.items()}
    return repr(value)


def test_probe():
    try:
        payload = {"kind": "value", "value": _norm(%(expression)s)}
    except BaseException as exc:  # noqa: BLE001 - поведение мутанта ловим целиком
        payload = {"kind": "exception", "value": type(exc).__name__, "message": str(exc)[:200]}
    print(%(marker)r + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=repr))
'''


def _rng(*parts: Any) -> random.Random:
    """Детерминированный генератор: одна и та же сессия даёт один и тот же набор.

    Воспроизводимость — продуктовое требование: спор по результату разбирается
    повторным прогоном, а не словами.
    """
    seed = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return random.Random(int(seed[:16], 16))


# --- разбор решения ---------------------------------------------------------


def callable_targets(code: str) -> List[Dict[str, Any]]:
    """Публичные функции верхнего уровня — то, что кандидат может вызывать."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []
    targets: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = [arg.arg for arg in node.args.args]
            targets.append(
                {
                    "name": node.name,
                    "args": args,
                    "signature": "%s(%s)" % (node.name, ", ".join(args)),
                    "line": node.lineno,
                }
            )
    return targets


def _literal_only(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False
    return True


def _has_pathy(value: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, str):
        return bool(_PATHY.search(value))
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_has_pathy(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return any(_has_pathy(key, depth + 1) or _has_pathy(item, depth + 1) for key, item in value.items())
    return False


def validate_call(code: str, expression: str) -> Tuple[bool, str]:
    """Пускаем только вызов функции решения с литеральными аргументами.

    Это не про недоверие к кандидату, а про то, что выражение исполняется в
    песочнице: чем уже форма, тем меньше поверхность атаки и тем понятнее ошибки.
    """
    if not expression or not expression.strip():
        return False, "Пустое выражение"
    if len(expression.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        return False, "Выражение длиннее %d байт" % MAX_ARTIFACT_BYTES
    try:
        parsed = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        return False, "Это не выражение Python: %s" % (exc.msg or "ошибка синтаксиса")
    call = parsed.body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return False, "Нужен вызов функции решения, например parse_orders('Болт;10;5.5')"
    targets = {item["name"] for item in callable_targets(code)}
    if not targets:
        return False, "В решении нет функций верхнего уровня"
    if call.func.id not in targets:
        return False, "Функции %s нет в решении. Доступны: %s" % (call.func.id, ", ".join(sorted(targets)))
    for node in list(call.args) + [keyword.value for keyword in call.keywords]:
        if not _literal_only(node):
            return False, "Аргументы должны быть литералами: строки, числа, списки, словари"
        if _has_pathy(ast.literal_eval(node)):
            return False, "Строки, похожие на путь или URL, в аргументы не принимаются"
    return True, ""


def eval_call(code: str, expression: str, timeout: float = EVAL_TIMEOUT) -> Dict[str, Any]:
    """Выполняет вызов в песочнице и возвращает нормализованное наблюдение."""
    ok, error = validate_call(code, expression)
    if not ok:
        return {"ok": False, "error": error, "kind": "rejected", "value": None}
    probe = _PROBE_TEMPLATE % {"expression": expression.strip(), "marker": VALUE_MARKER}
    report = sandbox.run_tests(code, probe, timeout=timeout)
    payload: Optional[Dict[str, Any]] = None
    for line in (report.get("stdout") or "").splitlines():
        if VALUE_MARKER in line:
            try:
                payload = json.loads(line.split(VALUE_MARKER, 1)[1].strip())
            except json.JSONDecodeError:
                payload = None
    if payload is None:
        reason = "Решение не запустилось"
        if report.get("timeout"):
            reason = "Прогон не уложился в %s с" % timeout
        elif report.get("import_error"):
            reason = "Ошибка импорта решения: %s" % str(report.get("import_error"))[:200]
        return {"ok": False, "error": reason, "kind": "no_output", "value": None}
    return {
        "ok": True,
        "kind": payload.get("kind"),
        "value": payload.get("value"),
        "message": payload.get("message"),
        "duration_ms": report.get("duration_ms"),
        "cached": bool(report.get("cached")),
    }


# --- сравнение наблюдений ---------------------------------------------------


def normalize_value(value: Any, depth: int = 0) -> Any:
    """Приводит значение к сравнимому виду (числа с плавающей точкой округляются)."""
    if depth > 8:
        return repr(value)
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (list, tuple)):
        return [normalize_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(item, depth + 1) for key, item in value.items()}
    return repr(value)


def _jsonable(value: Any, depth: int = 0) -> Any:
    """Повторяет нормализацию зонда для значений, введённых кандидатом руками."""
    if depth > 6:
        return repr(value)
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(repr(_jsonable(item, depth + 1)) for item in value)
    if isinstance(value, dict):
        return {repr(_jsonable(key, depth + 1)): _jsonable(item, depth + 1) for key, item in value.items()}
    return repr(value)


def values_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Совпадают ли два наблюдения (вид результата и само значение)."""
    if not (left.get("ok") and right.get("ok")):
        return False
    if left.get("kind") != right.get("kind"):
        return False
    return normalize_value(left.get("value")) == normalize_value(right.get("value"))


def claim_matches(claim: Any, observed: Dict[str, Any]) -> bool:
    """Привязка доказательства: совпало ли заявленное значение с прогоном.

    Кандидат пишет значение руками, поэтому сравнение терпимо к форме записи:
    сначала пробуем прочитать как литерал Python, потом сравниваем как текст
    без пробелов. Для исключений достаточно упомянуть его тип.
    """
    if claim is None:
        return False
    text = str(claim).strip()
    if not text:
        return False
    if observed.get("kind") == "exception":
        return str(observed.get("value") or "").lower() in text.lower()
    target = normalize_value(observed.get("value"))
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        rendered = json.dumps(target, ensure_ascii=False, sort_keys=True)
        compact = re.sub(r"\s+", "", text)
        return compact in (re.sub(r"\s+", "", rendered), re.sub(r"\s+", "", str(target)))
    return normalize_value(_jsonable(parsed)) == target


# --- проверка артефактов ----------------------------------------------------


def witness_check(
    code: str,
    mutant_code: str,
    expression: str,
    claims: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Различает ли предъявленный вход решение и правку.

    Возвращает наблюдаемые значения — это серверные данные. Наружу они уходить
    не должны: иначе задание можно решить, отправив любой вход и прочитав ответ.
    """
    original = eval_call(code, expression)
    if not original.get("ok"):
        return {"ok": False, "differs": False, "reason": original.get("error"), "original": original}
    mutant = eval_call(mutant_code, expression)
    if not mutant.get("ok"):
        return {
            "ok": False,
            "differs": False,
            "reason": "Правка на этом входе не дала наблюдаемого результата",
            "original": original,
            "mutant": mutant,
        }
    out: Dict[str, Any] = {
        "ok": True,
        "differs": not values_match(original, mutant),
        "original": original,
        "mutant": mutant,
    }
    if claims is not None:
        out["evidence"] = {
            "original_claim_ok": claim_matches(claims.get("original"), original),
            "mutant_claim_ok": claim_matches(claims.get("mutant"), mutant),
        }
    return out


def validate_test_source(source: str) -> Tuple[bool, str]:
    """Тест кандидата: только проверка поведения, без доступа к системе."""
    if not source or not source.strip():
        return False, "Пустой тест"
    if len(source.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        return False, "Тест длиннее %d байт" % MAX_ARTIFACT_BYTES
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, "Синтаксис: %s (строка %s)" % (exc.msg or "ошибка", exc.lineno)
    has_test = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            has_test = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_TEST_IMPORTS:
                    return False, "Импорт %s в тесте не разрешён" % alias.name
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_TEST_IMPORTS:
                return False, "Импорт из %s в тесте не разрешён" % (node.module or "?")
        elif isinstance(node, ast.Name) and node.id in BANNED_TEST_NAMES:
            return False, "Имя %s в тесте недоступно" % node.id
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False, "Доступ к %s запрещён" % node.attr
    if not has_test:
        return False, "Нужна функция, имя которой начинается с test"
    return True, ""


def _trim_run(report: Dict[str, Any], with_messages: bool) -> Dict[str, Any]:
    """Сжимает отчёт прогона.

    with_messages=False для прогона по мутанту: сообщения ассертов раскрывают
    поведение правки, а это ровно тот ответ, который кандидат должен вывести сам.
    Иначе тривиальный тест превратился бы в зонд по мутанту.
    """
    trimmed: Dict[str, Any] = {
        "ok": bool(report.get("ok")),
        "passed": int(report.get("passed") or 0),
        "failed": int(report.get("failed") or 0),
        "errored": int(report.get("errored") or 0),
        "timeout": bool(report.get("timeout")),
        "duration_ms": report.get("duration_ms"),
    }
    if with_messages:
        trimmed["tests"] = [
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "message": str(item.get("message") or "")[:300],
            }
            for item in (report.get("tests") or [])[:12]
        ]
        if report.get("import_error"):
            trimmed["import_error"] = str(report.get("import_error"))[:300]
    return trimmed


def test_fix_check(
    code: str,
    mutant_code: str,
    test_source: str,
    timeout: float = EVAL_TIMEOUT,
) -> Dict[str, Any]:
    """Тест-убийца: зелёный на решении, красный на правке."""
    ok, error = validate_test_source(test_source)
    if not ok:
        return {"ok": False, "error": error, "green_on_original": False, "red_on_mutant": False, "kills": False}
    original = sandbox.run_tests(code, test_source, timeout=timeout)
    mutant = sandbox.run_tests(mutant_code, test_source, timeout=timeout)
    green = (
        bool(original.get("ok"))
        and int(original.get("passed") or 0) >= 1
        and int(original.get("failed") or 0) == 0
        and int(original.get("errored") or 0) == 0
    )
    red = (int(mutant.get("failed") or 0) + int(mutant.get("errored") or 0)) >= 1
    return {
        "ok": True,
        "green_on_original": green,
        "red_on_mutant": red,
        "kills": bool(green and red),
        "original": _trim_run(original, with_messages=True),
        "mutant": _trim_run(mutant, with_messages=False),
    }


# --- сборка заданий ---------------------------------------------------------

# Поля мутации, которые не покидают сервер: исходник правки и все готовые
# объяснения. Именно они превратили бы фотографию экрана в готовый ответ.
_PRIVATE_MUTATION_FIELDS = (
    "code",
    "consequence",
    "intent",
    "suggestion",
    "killed_by",
    "first_failed",
    "run",
    "status",
)


def _public_mutation(row: Dict[str, Any]) -> Dict[str, Any]:
    """Публичная часть мутации: что изменилось и где, без объяснений и итога."""
    return {
        key: value
        for key, value in row.items()
        if key not in _PRIVATE_MUTATION_FIELDS and not key.startswith("_")
    }


def _rows_of(result: Any) -> List[Dict[str, Any]]:
    """Достаёт строки мутаций из отчёта анализа или из готового списка."""
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("mutations", "rows", "results", "items", "lines"):
            value = result.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def mutant_codes(result: Any) -> Dict[str, str]:
    """Карта id мутации → исходник мутанта (хранится только на сервере)."""
    return {row.get("id"): row.get("code") or "" for row in _rows_of(result) if row.get("id")}


def task_for(
    kind: str,
    row: Dict[str, Any],
    index: int,
    targets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Одно решающее задание в публичном виде."""
    mutation = _public_mutation(row)
    task: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "task_id": "T%d" % index,
        "type": kind,
        "title": TASK_TITLES[kind],
        "prompt": TASK_PROMPTS[kind],
        "weight": TASK_WEIGHTS[kind],
        "budget_seconds": STEP_BUDGET[kind],
        "requires_execution": True,
        "mutation_id": row.get("id"),
        "mutation": mutation,
        "skill": row.get("skill"),
        "skill_title": row.get("skill_title"),
        "line": row.get("line"),
    }
    if kind == "witness":
        task["artifact"] = {
            "kind": "expression",
            "label": "Вызов функции решения",
            "placeholder": (targets[0]["signature"] if targets else "function(argument)"),
            "targets": [item["signature"] for item in (targets or [])],
        }
        task["fields"] = [
            {"key": "observed_original", "label": "Что вернёт ваше решение"},
            {"key": "observed_mutant", "label": "Что вернёт правка"},
        ]
        task["hint"] = (
            "Значение своего решения можно проверить в консоли экспериментов. "
            "Поведение правки консоль не показывает — его нужно вывести самому."
        )
    else:
        task["artifact"] = {
            "kind": "python",
            "label": "Тест, который поймает правку",
            "template": "from solution import *\n\n\ndef test_kills_mutant():\n    assert ...\n",
        }
        task["fields"] = []
        task["hint"] = (
            "Тест должен быть зелёным на вашем решении и красным на правке. "
            "Сколько тестов правка прошла — покажем; чем именно она отличается — нет."
        )
    return task


def build_tasks(
    result: Any,
    session_id: str,
    limit: int = 4,
    targets: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Решающие задания из отчёта анализа.

    Правка, которую тесты не заметили, идёт в test_fix: дыра в тестах уже
    доказана. Правка, которую тесты заметили, идёт в witness: различающий вход
    точно существует, его нашли сами тесты кандидата.

    Порядок перемешивается детерминированно по session_id — два кандидата с
    одинаковым решением получают разные наборы (правило 4, session entropy).
    """
    rows = _rows_of(result)
    survived = [row for row in rows if row.get("status") == "survived"]
    killed = [row for row in rows if row.get("status") == "killed"]
    rng = _rng(session_id, len(rows))
    rng.shuffle(survived)
    rng.shuffle(killed)

    plan: List[Tuple[str, Dict[str, Any]]] = []
    plan.extend(("test_fix", row) for row in survived[:2])
    plan.extend(("witness", row) for row in killed)
    plan.extend(("test_fix", row) for row in survived[2:])
    return [task_for(kind, row, index, targets) for index, (kind, row) in enumerate(plan[:limit], start=1)]


# --- консоль экспериментов --------------------------------------------------


def experiment(
    code: str,
    expression: str,
    used: int = 0,
    budget: int = MAX_EXPERIMENTS,
) -> Dict[str, Any]:
    """Прогон своего решения на своём входе.

    Консоль работает только с решением кандидата и никогда с мутантом: иначе
    задание сводилось бы к перебору входов без всякого понимания.
    """
    if used >= budget:
        return {"ok": False, "error": "Лимит экспериментов в сессии исчерпан", "remaining": 0, "used": used}
    started = time.time()
    outcome = eval_call(code, expression)
    return {
        "ok": bool(outcome.get("ok")),
        "error": outcome.get("error"),
        "kind": outcome.get("kind"),
        "value": outcome.get("value"),
        "message": outcome.get("message"),
        "expression": expression.strip(),
        "used": used + 1,
        "remaining": max(0, budget - used - 1),
        "wall_ms": int((time.time() - started) * 1000),
    }


# --- оценка -----------------------------------------------------------------


def grade_task(
    task: Dict[str, Any],
    submission: Optional[Dict[str, Any]],
    code: str,
    mutant_code: str,
) -> Dict[str, Any]:
    """Оценивает одно решающее задание. Служебные данные кладёт под ключ _check."""
    submission = submission or {}
    kind = task.get("type")
    notes: List[str] = []
    score = 0.0
    check: Dict[str, Any] = {}

    if kind == "witness":
        expression = str(submission.get("expression") or "")
        check = witness_check(
            code,
            mutant_code,
            expression,
            claims={
                "original": submission.get("observed_original"),
                "mutant": submission.get("observed_mutant"),
            },
        )
        if not check.get("ok"):
            notes.append(check.get("reason") or "Выражение не выполнилось")
        elif not check.get("differs"):
            notes.append("На этом входе решение и правка ведут себя одинаково — правка тут не проявляется")
        else:
            score += WITNESS_FOUND_SCORE
            notes.append("Вход действительно различает решение и правку")
            evidence = check.get("evidence") or {}
            if evidence.get("original_claim_ok") and evidence.get("mutant_claim_ok"):
                score += WITNESS_EVIDENCE_SCORE
                notes.append("Заявленные значения совпали с прогоном")
            elif evidence.get("original_claim_ok"):
                notes.append("Значение решения совпало, значение правки — нет")
            else:
                notes.append("Вход найден, но заявленные значения с прогоном не совпали")
    elif kind == "test_fix":
        check = test_fix_check(code, mutant_code, str(submission.get("test_source") or ""))
        if not check.get("ok"):
            notes.append(check.get("error") or "Тест не принят")
        elif check.get("kills"):
            score = 1.0
            notes.append("Тест зелёный на решении и красный на правке")
        elif check.get("green_on_original"):
            score = TEST_VALID_SCORE
            notes.append("Тест валиден, но правку не замечает — это и есть дыра в наборе тестов")
        else:
            notes.append("Тест падает на вашем же решении — сначала он должен быть зелёным")
    else:
        notes.append("Тип задания %s не оценивается" % kind)

    return {
        "task_id": task.get("task_id"),
        "type": kind,
        "mutation_id": task.get("mutation_id"),
        "skill": task.get("skill"),
        "score": round(score, 3),
        "passed": score >= 0.95,
        "partial": 0.0 < score < 0.95,
        "notes": notes,
        "_check": check,
    }


def score_tasks(tasks: List[Dict[str, Any]], grades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Взвешенный итог решающей стадии. Разминка в знаменатель не входит (I5)."""
    by_id = {grade.get("task_id"): grade for grade in grades}
    total = 0.0
    earned = 0.0
    answered = 0
    rows: List[Dict[str, Any]] = []
    skills: Dict[str, Dict[str, float]] = {}
    for task in tasks:
        weight = float(task.get("weight") or 1.0)
        grade = by_id.get(task.get("task_id"))
        value = float(grade.get("score") or 0.0) if grade else 0.0
        total += weight
        earned += weight * value
        if grade:
            answered += 1
        skill = task.get("skill") or "other"
        bucket = skills.setdefault(skill, {"earned": 0.0, "total": 0.0})
        bucket["earned"] += weight * value
        bucket["total"] += weight
        rows.append(
            {
                "task_id": task.get("task_id"),
                "type": task.get("type"),
                "weight": weight,
                "score": round(value, 3),
                "skill": skill,
                "skill_title": task.get("skill_title"),
                "notes": (grade or {}).get("notes") or [],
            }
        )
    pct = int(round(100.0 * earned / total)) if total else 0
    if pct >= PASS_CONTROL_PCT:
        verdict, title = "control", "Контролирует свой код"
    elif pct >= PASS_PARTIAL_PCT:
        verdict, title = "partial", "Понимание частичное"
    else:
        verdict, title = "not_confirmed", "Понимание не подтверждено"
    return {
        "schema": SCHEMA_VERSION,
        "earned": round(earned, 3),
        "total": round(total, 3),
        "pct": pct,
        "verdict": verdict,
        "verdict_title": title,
        "answered": answered,
        "tasks": len(tasks),
        "rows": rows,
        "skills": {
            name: {
                "pct": int(round(100.0 * bucket["earned"] / bucket["total"])) if bucket["total"] else 0,
                "weight": round(bucket["total"], 3),
            }
            for name, bucket in sorted(skills.items())
        },
    }
