"""Поиск свидетеля и честная классификация мутантов.

Зачем модуль существует — из реальной пробы на демо-задаче

Дымовой тест АРП прошёл зелёным, а потом прямая проба показала неприятное:
из 5 «выживших» мутантов демо-задачи ни один не различался собственным
корпусом тестов кандидата, а минимум три из них семантически эквивалентны
оригиналу:

    split(";") → rsplit(";")            без maxsplit это одно и то же;
    raw.strip().splitlines() → raw.splitlines()
                                       пустые строки всё равно отбрасываются;
    if amount > limit → >=             в ветке присваивается то же значение.

Значит задание «напишите тест, который поймает эту правку» на таком мутанте
нерешаемо в принципе. Нерешаемое задание — хуже, чем отсутствие задания:
оно наказывает сильного инженера за то, что он прав.

Поэтому сервер САМ ищет свидетеля (вход, на котором поведение расходится)
до того, как выдать задание. Три класса исхода:

    killed      тесты кандидата правку заметили;
    gap         не заметили, но поведение реально меняется — дыра в тестах;
    equivalent  поведение не меняется — не ставится в минус вообще.

Из этого сразу два следствия:

1. Честный mutation score считается по знаменателю killed + gap. Стандартный
   мутационный анализ этого не делает и занижает оценку хороших наборов тестов.
2. Свидетель остаётся на сервере (инвариант I2). Он нужен для двух вещей:
   гарантии решаемости и разбора спора после сессии.
"""

from __future__ import annotations

import ast
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from . import relay

SCHEMA_VERSION = "pruf.witness/1"

MAX_PROBES = 48
CLASSIFY_PROBES = 32
MAX_EXPRESSION_BYTES = 2000

MUTANT_CLASSES = {
    "killed": "Замечена вашими тестами",
    "gap": "Не замечена, но поведение реально меняется — дыра в тестах",
    "equivalent": "Поведение не меняется — не ставится в минус",
}


# --- извлечение вызовов из тестов кандидата -----------------------


def _literal_env(tree: ast.AST) -> Dict[str, Any]:
    """Локальные литеральные присваивания вида rows = [...] внутри тестов."""
    env: Dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                env[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                continue
    return env


def _static_value(node: ast.AST, env: Dict[str, Any]) -> Tuple[Any, bool]:
    try:
        return ast.literal_eval(node), True
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        pass
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id], True
    return None, False


def _render_call(name: str, args: List[Any], kwargs: Dict[str, Any]) -> str:
    parts = [repr(value) for value in args]
    parts.extend("%s=%r" % (key, value) for key, value in kwargs.items())
    return "%s(%s)" % (name, ", ".join(parts))


def literal_calls(code: str, tests_src: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Вызовы функций решения с литеральными аргументами, найденные в тестах.

    Это стартовая точка корпуса: входы, которые автор решения сам счёл
    осмысленными, поэтому почти всегда валидны и быстро исполняются.
    """
    targets = {item["name"] for item in relay.callable_targets(code)}
    if not targets:
        return []
    try:
        tree = ast.parse(tests_src or "")
    except SyntaxError:
        return []
    env = _literal_env(tree)
    found: List[Dict[str, Any]] = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in targets:
            continue
        args: List[Any] = []
        kwargs: Dict[str, Any] = {}
        ok = True
        for argument in node.args:
            value, good = _static_value(argument, env)
            if not good:
                ok = False
                break
            args.append(value)
        if ok:
            for keyword in node.keywords:
                if keyword.arg is None:
                    ok = False
                    break
                value, good = _static_value(keyword.value, env)
                if not good:
                    ok = False
                    break
                kwargs[keyword.arg] = value
        if not ok:
            continue
        expression = _render_call(node.func.id, args, kwargs)
        if expression in seen or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES:
            continue
        seen.add(expression)
        found.append({"name": node.func.id, "args": args, "kwargs": kwargs, "expression": expression})
        if len(found) >= limit:
            break
    return found


# --- варианты аргументов -------------------------------------------------


def _variants(value: Any, depth: int = 0) -> List[Any]:
    """Соседние входы вокруг заданного.

    Набор подобран под каталог из 18 операторов мутаций: границы, пустота,
    пробелы по краям, нечисловые данные в числовом поле, один элемент вместо
    многих. Именно на таких входах ловятся CALL_DROP_METHOD, CMP_BOUNDARY,
    SLICE_SHIFT и EXCEPT_SWALLOW.
    """
    if depth > 1:
        return []
    out: List[Any] = []
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, str):
        head = value.split("\n", 1)[0]
        out.extend(
            [
                " " + value,
                value + " ",
                value.strip(),
                value + "\n",
                "\n" + value,
                "",
                value + ";",
                head,
                re.sub(r"\d", "x", value, count=1),
            ]
        )
    elif isinstance(value, (int, float)):
        out.extend([0, 1, -1, value + 1, value - 1, value * 2, 1000.0])
    elif isinstance(value, (list, tuple)):
        items = list(value)
        out.extend([[], items[:1], items + items])
        if items:
            for candidate in _variants(items[0], depth + 1)[:4]:
                out.append([candidate] + items[1:])
    elif isinstance(value, dict):
        for key, item in list(value.items())[:3]:
            for candidate in _variants(item, depth + 1)[:3]:
                clone = dict(value)
                clone[key] = candidate
                out.append(clone)
    deduped: List[Any] = []
    seen = set()
    for candidate in out:
        marker = repr(candidate)
        if marker in seen or marker == repr(value):
            continue
        seen.add(marker)
        deduped.append(candidate)
    return deduped


def build_corpus(code: str, tests_src: str, limit: int = MAX_PROBES) -> List[str]:
    """Корпус зондирующих выражений: сначала входы из тестов, потом варианты.

    Порядок детерминирован: один и тот же код всегда даёт один и тот же
    корпус, иначе вердикт перестанет быть воспроизводимым.
    """
    calls = literal_calls(code, tests_src)
    corpus: List[str] = []
    seen = set()

    def add(expression: str) -> None:
        if expression in seen:
            return
        if len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES:
            return
        ok, _ = relay.validate_call(code, expression)
        if not ok:
            return
        seen.add(expression)
        corpus.append(expression)

    for call in calls:
        add(call["expression"])
    for call in calls:
        if len(corpus) >= limit:
            break
        args = call["args"]
        kwargs = call["kwargs"]
        for index in range(len(args)):
            for candidate in _variants(args[index]):
                if len(corpus) >= limit:
                    break
                mutated = list(args)
                mutated[index] = candidate
                add(_render_call(call["name"], mutated, kwargs))
        for key in list(kwargs):
            for candidate in _variants(kwargs[key]):
                if len(corpus) >= limit:
                    break
                clone = dict(kwargs)
                clone[key] = candidate
                add(_render_call(call["name"], args, clone))
    return corpus[:limit]


# --- поиск свидетеля ----------------------------------------------------


def find_witness(
    code: str,
    mutant_code: str,
    corpus: List[str],
    base_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    max_probes: int = MAX_PROBES,
) -> Optional[Dict[str, Any]]:
    """Первое выражение корпуса, на котором решение и мутант расходятся."""
    if base_cache is None:
        base_cache = {}
    probes = 0
    for expression in corpus[:max_probes]:
        original = base_cache.get(expression)
        if original is None:
            original = relay.eval_call(code, expression)
            base_cache[expression] = original
        probes += 1
        if not original.get("ok"):
            continue
        mutant = relay.eval_call(mutant_code, expression)
        if not mutant.get("ok"):
            continue
        if not relay.values_match(original, mutant):
            return {"expression": expression, "probes": probes}
    return None


def classify_mutants(
    code: str,
    tests_src: str,
    result: Any,
    corpus: Optional[List[str]] = None,
    max_probes: int = CLASSIFY_PROBES,
) -> Dict[str, Any]:
    """Разносит мутанты по трём классам и считает честный mutation score."""
    started = time.time()
    rows = relay._rows_of(result)
    codes = relay.mutant_codes(result)
    if corpus is None:
        corpus = build_corpus(code, tests_src)
    base_cache: Dict[str, Dict[str, Any]] = {}
    classes: Dict[str, str] = {}
    witnesses: Dict[str, Dict[str, Any]] = {}
    counts = {"killed": 0, "gap": 0, "equivalent": 0}

    for row in rows:
        mutation_id = row.get("id")
        mutant_code = codes.get(mutation_id) or ""
        if not mutation_id or not mutant_code:
            continue
        found = find_witness(code, mutant_code, corpus, base_cache, max_probes)
        if found:
            witnesses[mutation_id] = found
        if row.get("status") == "killed":
            classes[mutation_id] = "killed"
        elif found:
            classes[mutation_id] = "gap"
        else:
            classes[mutation_id] = "equivalent"
        counts[classes[mutation_id]] += 1

    denominator = counts["killed"] + counts["gap"]
    honest = int(round(100.0 * counts["killed"] / denominator)) if denominator else 0
    return {
        "schema": SCHEMA_VERSION,
        "counts": counts,
        "classes": classes,
        "titles": MUTANT_CLASSES,
        "witnesses": witnesses,
        "corpus_size": len(corpus),
        "honest_mutation_pct": honest,
        "duration_ms": int((time.time() - started) * 1000),
        "note": (
            "Знаменатель честного mutation score — только убиваемые мутанты "
            "(killed + gap). Семантически эквивалентные правки в оценку не входят."
        ),
    }


# --- план сессии -------------------------------------------------------


def build_relay_plan(
    code: str,
    tests_src: str,
    result: Any,
    session_id: str,
    limit: int = 4,
    classification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Публичные задания + приватные эталоны для сервера.

    Гарантии плана:
      * в test_fix попадают только мутанты класса gap — у них точно есть
        различающий вход, значит тест-убийца существует;
      * в witness попадают только мутанты с найденным свидетелем;
      * equivalent не используется нигде и не влияет на вердикт.
    """
    if classification is None:
        classification = classify_mutants(code, tests_src, result)
    rows = {row.get("id"): row for row in relay._rows_of(result) if row.get("id")}
    codes = relay.mutant_codes(result)
    classes = classification.get("classes") or {}
    witnesses = classification.get("witnesses") or {}
    targets = relay.callable_targets(code)

    gap_ids = sorted(mutation_id for mutation_id, cls in classes.items() if cls == "gap")
    killed_ids = sorted(
        mutation_id
        for mutation_id, cls in classes.items()
        if cls == "killed" and mutation_id in witnesses
    )
    rng = relay._rng(session_id, len(rows), "plan")
    rng.shuffle(gap_ids)
    rng.shuffle(killed_ids)

    plan: List[Tuple[str, str]] = []
    plan.extend(("test_fix", mutation_id) for mutation_id in gap_ids[:2])
    plan.extend(("witness", mutation_id) for mutation_id in killed_ids[:2])
    plan.extend(("test_fix", mutation_id) for mutation_id in gap_ids[2:])
    plan.extend(("witness", mutation_id) for mutation_id in killed_ids[2:])

    tasks: List[Dict[str, Any]] = []
    used_mutants: Dict[str, str] = {}
    used_witnesses: Dict[str, Dict[str, Any]] = {}
    for index, (kind, mutation_id) in enumerate(plan[:limit], start=1):
        row = rows.get(mutation_id)
        if not row:
            continue
        tasks.append(relay.task_for(kind, row, index, targets))
        used_mutants[mutation_id] = codes.get(mutation_id) or ""
        if mutation_id in witnesses:
            used_witnesses[mutation_id] = witnesses[mutation_id]

    return {
        "schema": SCHEMA_VERSION,
        "tasks": tasks,
        "targets": [item["signature"] for item in targets],
        "classification": {
            "counts": classification.get("counts"),
            "titles": MUTANT_CLASSES,
            "honest_mutation_pct": classification.get("honest_mutation_pct"),
            "corpus_size": classification.get("corpus_size"),
            "note": classification.get("note"),
        },
        "_mutants": used_mutants,
        "_witnesses": used_witnesses,
    }
