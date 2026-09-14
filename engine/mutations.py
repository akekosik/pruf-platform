"""
ПРУФ · engine.mutations

Детерминированный генератор мутаций по AST конкретного решения.

Принцип: каждая мутация — это точечная замена одного фрагмента исходного текста
(по точным координатам узла), поэтому весь остальной код сохраняется байт в байт:
комментарии, форматирование и номера строк не едут. Никаких языковых моделей:
один и тот же вход всегда даёт один и тот же набор мутаций — вердикт воспроизводим.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "pruf.mutations/1"

DEFAULT_LIMIT = 12
MAX_LIMIT = 15
MIN_USEFUL = 3

# ---------------------------------------------------------------- навыки

SKILLS: Dict[str, str] = {
    "boundary": "Границы и индексы",
    "logic": "Логика условий",
    "arithmetic": "Арифметика и накопление",
    "strings": "Работа со строками",
    "io": "Ввод-вывод и кодировки",
    "errors": "Обработка ошибок",
    "collections": "Коллекции и принадлежность",
    "flow": "Поток выполнения",
}


@dataclass(frozen=True)
class Operator:
    code: str
    kind: str          # короткое имя для интерфейса
    skill: str
    intent: str        # что проверяет
    consequence: str   # что сломается в поведении
    priority: int = 5

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "kind": self.kind,
            "skill": self.skill,
            "skill_title": SKILLS.get(self.skill, self.skill),
            "intent": self.intent,
            "consequence": self.consequence,
            "priority": self.priority,
        }


OPERATOR_LIST: Tuple[Operator, ...] = (
    Operator("CMP_BOUNDARY", "сдвиг границы", "boundary",
             "Понимает ли автор, включена ли граница в условие",
             "Значение ровно на границе попадёт не в ту ветку", 1),
    Operator("CMP_EQUALITY", "инверсия равенства", "logic",
             "Проверены ли обе ветки условия",
             "Ветки условия меняются местами", 2),
    Operator("CMP_MEMBERSHIP", "инверсия вхождения", "collections",
             "Проверен ли случай отсутствия элемента",
             "Отбор элементов инвертируется", 4),
    Operator("CMP_IDENTITY", "инверсия is", "logic",
             "Отличает ли автор None от пустого значения",
             "Проверка на None срабатывает наоборот", 4),
    Operator("BOOL_OP", "and ↔ or", "logic",
             "Понимает ли автор составное условие",
             "Условие срабатывает, когда верна только одна часть", 2),
    Operator("NOT_DROP", "снято отрицание", "logic",
             "Зачем нужна охранная проверка",
             "Охранное условие выворачивается наизнанку", 3),
    Operator("ARITH_OP", "подмена операции", "arithmetic",
             "Зафиксирован ли числовой результат",
             "Результат счёта становится другим числом", 2),
    Operator("DIV_KIND", "деление / ↔ //", "arithmetic",
             "Различает ли автор целое и вещественное деление",
             "Дробная часть теряется или появляется", 3),
    Operator("AUG_OP", "подмена накопления", "arithmetic",
             "Проверено ли накопление в цикле",
             "Итоговая сумма считается в другую сторону", 3),
    Operator("CONST_INT", "сдвиг константы", "arithmetic",
             "Зафиксированы ли точные значения в тестах",
             "Числовая константа смещается на единицу", 3),
    Operator("CONST_BOOL", "инверсия флага", "logic",
             "Проверены ли оба состояния флага",
             "Флаг переключается в противоположное значение", 4),
    Operator("CONST_STR_IO", "подмена режима/кодировки", "io",
             "Знает ли автор, зачем указана кодировка и режим файла",
             "Файл читается или пишется не в том виде", 5),
    Operator("CALL_DROP_METHOD", "убран вызов метода", "strings",
             "Понимает ли автор, зачем нужна нормализация",
             "Входные данные остаются неочищенными", 2),
    Operator("CALL_SWAP_METHOD", "подмена метода", "strings",
             "Различает ли автор близкие методы",
             "Обрабатывается другая сторона или другой регистр", 4),
    Operator("SLICE_SHIFT", "сдвиг среза", "boundary",
             "Проверены ли крайние элементы",
             "Из выборки уходит или добавляется один элемент", 3),
    Operator("RANGE_BOUND", "сдвиг range", "boundary",
             "Считает ли автор число итераций",
             "Цикл делает на один шаг меньше", 3),
    Operator("EXCEPT_SWALLOW", "проглочено исключение", "errors",
             "Есть ли тест на ошибочный сценарий",
             "Ошибка молча игнорируется", 1),
    Operator("RETURN_DROP", "потерян возврат", "flow",
             "Проверяется ли возвращаемое значение",
             "Функция возвращает None вместо результата", 2),
)

OPERATORS: Dict[str, Operator] = {op.code: op for op in OPERATOR_LIST}


def catalog() -> List[Dict[str, Any]]:
    """Каталог операторов — используется в документации и в API."""
    return [op.as_dict() for op in OPERATOR_LIST]


# ------------------------------------------------------------- структуры

@dataclass
class Mutation:
    id: str
    operator: str
    kind: str
    skill: str
    skill_title: str
    intent: str
    consequence: str
    line: int
    start_line: int
    end_line: int
    before: str
    after: str
    diff: str
    code: str = field(repr=False, default="")
    fingerprint: str = ""

    def as_dict(self, include_code: bool = False) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "operator": self.operator,
            "kind": self.kind,
            "skill": self.skill,
            "skill_title": self.skill_title,
            "intent": self.intent,
            "consequence": self.consequence,
            "line": self.line,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "before": self.before,
            "after": self.after,
            "diff": self.diff,
            "fingerprint": self.fingerprint,
        }
        if include_code:
            payload["code"] = self.code
        return payload


def code_fingerprint(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------- таблицы

_CMP_BOUNDARY = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
_CMP_EQUALITY = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_CMP_MEMBER = {ast.In: ast.NotIn, ast.NotIn: ast.In}
_CMP_IDENT = {ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div}
_DIVKIND = {ast.Div: ast.FloorDiv, ast.FloorDiv: ast.Div, ast.Mod: ast.FloorDiv}
_AUG = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div}

_DROPPABLE_METHODS = ("strip", "lstrip", "rstrip", "lower", "upper", "title", "casefold")
_SWAP_METHODS = {
    "lower": "upper", "upper": "lower",
    "lstrip": "rstrip", "rstrip": "lstrip",
    "startswith": "endswith", "endswith": "startswith",
    "find": "rfind", "rfind": "find",
    "split": "rsplit", "rsplit": "split",
    "append": "insert",
    "keys": "values", "values": "keys",
    "sort": "reverse",
}
_ENCODINGS = {"utf-8": "cp1251", "utf8": "cp1251", "cp1251": "utf-8", "windows-1251": "utf-8"}
_FILE_MODES = {"r": "rb", "rb": "r", "w": "a", "a": "w", "w+": "r+", "rt": "rb"}


# ------------------------------------------------------- работа с текстом

def _segment(source: str, span: Tuple[int, int, int, int]) -> str:
    """Точный фрагмент исходника по координатам AST (col_offset — в байтах UTF-8)."""
    start_line, start_col, end_line, end_col = span
    lines = source.split("\n")
    if start_line == end_line:
        raw = lines[start_line - 1].encode("utf-8")
        return raw[start_col:end_col].decode("utf-8", "replace")
    parts = [lines[start_line - 1].encode("utf-8")[start_col:].decode("utf-8", "replace")]
    parts.extend(lines[start_line:end_line - 1])
    parts.append(lines[end_line - 1].encode("utf-8")[:end_col].decode("utf-8", "replace"))
    return "\n".join(parts)


def _splice(source: str, span: Tuple[int, int, int, int], replacement: str) -> str:
    start_line, start_col, end_line, end_col = span
    lines = source.split("\n")
    head = lines[start_line - 1].encode("utf-8")[:start_col].decode("utf-8", "replace")
    tail = lines[end_line - 1].encode("utf-8")[end_col:].decode("utf-8", "replace")
    merged = (head + replacement + tail).split("\n")
    lines[start_line - 1:end_line] = merged
    return "\n".join(lines)


def _unparse(node: ast.AST) -> Optional[str]:
    try:
        return ast.unparse(node)
    except Exception:
        return None


_SIMPLE = (ast.Name, ast.Attribute, ast.Call, ast.Constant, ast.Subscript)


def _wrap(node: ast.AST) -> Optional[str]:
    """Безопасная подстановка выражения: сложные берём в скобки, чтобы не сломать приоритеты."""
    text = _unparse(node)
    if text is None:
        return None
    if isinstance(node, _SIMPLE):
        return text
    return "(%s)" % text


def _parent_map(tree: ast.AST) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _docstring_ids(tree: ast.AST) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                found.add(id(body[0].value))
    return found


def _span(node: ast.AST) -> Optional[Tuple[int, int, int, int]]:
    if not hasattr(node, "lineno") or getattr(node, "end_lineno", None) is None:
        return None
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _is_stringy(node: ast.AST) -> bool:
    """Пропускаем склейку строк: подмена + на - даст TypeError, а не проверку понимания."""
    for side in (getattr(node, "left", None), getattr(node, "right", None)):
        if isinstance(side, ast.Constant) and isinstance(side.value, str):
            return True
        if isinstance(side, ast.JoinedStr):
            return True
    return False


# -------------------------------------------------------------- сбор мест

def _collect_sites(code: str) -> List[Dict[str, Any]]:
    """Все места, где можно сделать осмысленную правку. Порядок детерминирован."""
    tree = ast.parse(code)
    parents = _parent_map(tree)
    docstrings = _docstring_ids(tree)
    sites: List[Dict[str, Any]] = []

    def add(operator: str, node: ast.AST, replacement: Optional[str],
            span: Optional[Tuple[int, int, int, int]] = None) -> None:
        if replacement is None:
            return
        region = span or _span(node)
        if region is None:
            return
        if _segment(code, region) == replacement:
            return
        sites.append({
            "operator": operator,
            "span": region,
            "replacement": replacement,
            "line": region[0],
            "col": region[1],
            "priority": OPERATORS[operator].priority,
        })

    for node in ast.walk(tree):
        parent = parents.get(id(node))

        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op_type = type(node.ops[0])
            for table, operator in (
                (_CMP_BOUNDARY, "CMP_BOUNDARY"),
                (_CMP_EQUALITY, "CMP_EQUALITY"),
                (_CMP_MEMBER, "CMP_MEMBERSHIP"),
                (_CMP_IDENT, "CMP_IDENTITY"),
            ):
                if op_type in table:
                    swapped = ast.Compare(left=node.left, ops=[table[op_type]()], comparators=node.comparators)
                    add(operator, node, _unparse(swapped))

        elif isinstance(node, ast.BoolOp) and len(node.values) >= 2 and not isinstance(parent, ast.BoolOp):
            new_op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            add("BOOL_OP", node, _unparse(ast.BoolOp(op=new_op, values=node.values)))

        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            add("NOT_DROP", node, _wrap(node.operand))

        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in _ARITH and not _is_stringy(node):
                swapped = ast.BinOp(left=node.left, op=_ARITH[op_type](), right=node.right)
                add("ARITH_OP", node, _unparse(swapped))
            if op_type in _DIVKIND:
                swapped = ast.BinOp(left=node.left, op=_DIVKIND[op_type](), right=node.right)
                add("DIV_KIND", node, _unparse(swapped))

        elif isinstance(node, ast.AugAssign) and type(node.op) in _AUG:
            swapped = ast.AugAssign(target=node.target, op=_AUG[type(node.op)](), value=node.value)
            add("AUG_OP", node, _unparse(swapped))

        elif isinstance(node, ast.Constant) and id(node) not in docstrings:
            value = node.value
            if isinstance(value, bool):
                add("CONST_BOOL", node, repr(not value))
            elif isinstance(value, int) and abs(value) < 1_000_000:
                add("CONST_INT", node, repr(value + 1))
            elif isinstance(value, str):
                low = value.lower()
                if low in _ENCODINGS:
                    add("CONST_STR_IO", node, repr(_ENCODINGS[low]))
                elif value in _FILE_MODES and isinstance(parent, ast.Call) \
                        and isinstance(parent.func, ast.Name) and parent.func.id == "open":
                    add("CONST_STR_IO", node, repr(_FILE_MODES[value]))

        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in _DROPPABLE_METHODS and not node.args and not node.keywords:
                    add("CALL_DROP_METHOD", node, _wrap(func.value))
                if func.attr in _SWAP_METHODS:
                    swapped_func = ast.Attribute(value=func.value, attr=_SWAP_METHODS[func.attr], ctx=ast.Load())
                    swapped = ast.Call(func=swapped_func, args=node.args, keywords=node.keywords)
                    add("CALL_SWAP_METHOD", node, _unparse(swapped))
            elif isinstance(func, ast.Name) and func.id == "range" and node.args and not node.keywords:
                args = list(node.args)
                last = args[-1]
                args[-1] = ast.BinOp(left=last, op=ast.Sub(), right=ast.Constant(value=1))
                swapped = ast.Call(func=func, args=args, keywords=[])
                add("RANGE_BOUND", node, _unparse(swapped))

        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            piece = node.slice
            new_slice = None
            if piece.lower is not None:
                new_slice = ast.Slice(
                    lower=ast.BinOp(left=piece.lower, op=ast.Add(), right=ast.Constant(value=1)),
                    upper=piece.upper, step=piece.step)
            elif piece.upper is not None:
                new_slice = ast.Slice(
                    lower=piece.lower,
                    upper=ast.BinOp(left=piece.upper, op=ast.Sub(), right=ast.Constant(value=1)),
                    step=piece.step)
            if new_slice is not None:
                swapped = ast.Subscript(value=node.value, slice=new_slice, ctx=ast.Load())
                add("SLICE_SHIFT", node, _unparse(swapped))

        elif isinstance(node, ast.ExceptHandler) and node.body:
            body = node.body
            if not (len(body) == 1 and isinstance(body[0], ast.Pass)):
                first, last = body[0], body[-1]
                region = (first.lineno, first.col_offset, last.end_lineno, last.end_col_offset)
                add("EXCEPT_SWALLOW", node, "pass", span=region)

        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                add("RETURN_DROP", node, "return None")

    sites.sort(key=lambda item: (item["line"], item["col"], item["priority"], item["operator"]))
    return sites


def count_sites(code: str) -> int:
    try:
        return len(_collect_sites(code))
    except SyntaxError:
        return 0


# ------------------------------------------------------------ генерация

def _build_mutation(code: str, site: Dict[str, Any]) -> Optional[Mutation]:
    span = site["span"]
    replacement = site["replacement"]
    try:
        mutated = _splice(code, span, replacement)
    except Exception:
        return None
    if mutated == code:
        return None
    try:
        compile(mutated, "<mutant>", "exec")
    except (SyntaxError, ValueError):
        return None

    original_lines = code.split("\n")
    mutated_lines = mutated.split("\n")
    start_line, _, end_line, _ = span
    added = replacement.count("\n")
    before = "\n".join(original_lines[start_line - 1:end_line]).rstrip()
    after = "\n".join(mutated_lines[start_line - 1:start_line + added]).rstrip()
    diff = "\n".join(
        ["- " + line for line in before.split("\n")] + ["+ " + line for line in after.split("\n")]
    )
    operator = OPERATORS[site["operator"]]
    return Mutation(
        id="M??",
        operator=operator.code,
        kind=operator.kind,
        skill=operator.skill,
        skill_title=SKILLS.get(operator.skill, operator.skill),
        intent=operator.intent,
        consequence=operator.consequence,
        line=start_line,
        start_line=start_line,
        end_line=start_line + added,
        before=before,
        after=after,
        diff=diff,
        code=mutated,
        fingerprint=code_fingerprint(mutated),
    )


def generate(code: str, limit: int = DEFAULT_LIMIT, diversify: bool = True) -> List[Mutation]:
    """Генерирует до `limit` разнообразных мутаций конкретного решения."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    sites = _collect_sites(code)
    if not sites:
        return []

    if diversify:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for site in sites:
            buckets.setdefault(site["operator"], []).append(site)
        order = sorted(buckets, key=lambda code_: (OPERATORS[code_].priority, code_))
        ordered: List[Dict[str, Any]] = []
        index = 0
        while True:
            progressed = False
            for operator_code in order:
                bucket = buckets[operator_code]
                if index < len(bucket):
                    ordered.append(bucket[index])
                    progressed = True
            index += 1
            if not progressed:
                break
    else:
        ordered = list(sites)

    seen: set = {code_fingerprint(code)}
    collected: List[Mutation] = []
    for site in ordered:
        if len(collected) >= limit:
            break
        mutation = _build_mutation(code, site)
        if mutation is None or mutation.fingerprint in seen:
            continue
        seen.add(mutation.fingerprint)
        collected.append(mutation)

    collected.sort(key=lambda item: (item.start_line, item.operator, item.after))
    for number, mutation in enumerate(collected, start=1):
        mutation.id = "M%02d" % number
    return collected


def generate_dicts(code: str, limit: int = DEFAULT_LIMIT, include_code: bool = False) -> List[Dict[str, Any]]:
    return [item.as_dict(include_code=include_code) for item in generate(code, limit=limit)]


def skill_histogram(items: List[Mutation]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item.skill] = counts.get(item.skill, 0) + 1
    return [
        {"skill": skill, "title": SKILLS.get(skill, skill), "count": count}
        for skill, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
