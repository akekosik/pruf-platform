#!/usr/bin/env python3
"""ПРУФ · починка двух дефектов ядра. Идемпотентно.

Запуск на любой свежей копии репозитория:
    python3 tools/patch_engine.py

Скрипт сохранён в репозитории как журнал двух найденных дефектов: если код
ядра когда-нибудь откатят, один запуск возвращает обе правки на место.

Дефект 1 — engine/session.py, public_view.
    Ответ кандидата хранится ВНУТРИ словаря вопроса под ключом "answer",
    а в нём лежит "correct". Фильтр {"correct", "explanation"} прятал только
    верхний уровень, поэтому правильный ответ утекал клиенту до ответа.
    Цена дефекта: вся механика «защиту нельзя списать» обходится через DevTools.

Дефект 2 — engine/sandbox.py, run_tests.
    Если решение не импортируется или падает по таймауту, отчёт приходил
    с пустым tests и errored = 0: сломанное решение выглядело как «ноль
    ошибок». Теперь пустой прогон всегда содержит явную стадию-провал
    «<загрузка решения>», errored >= 1 и ok = False.

Проверка после запуска:
    python3 -m unittest discover -s tests   # 65 тестов, OK
    python3 -m engine.cli demo              # отпечаток 392829790817d1b8
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

SESSION_OLD = '        item = {key: value for key, value in question.items() if key not in {"correct", "explanation"}}'
SESSION_NEW = (
    '        item = {\n'
    '            key: value\n'
    '            for key, value in question.items()\n'
    '            # "answer" прячем тоже: внутри него лежит "correct" этого же вопроса\n'
    '            if key not in {"correct", "explanation", "answer"}\n'
    '        }'
)

HELPERS = '''LOAD_STAGE_NAME = "<загрузка решения>"


def _ensure_visible_failure(report: Dict[str, Any]) -> Dict[str, Any]:
    """Пустой прогон — это провал, а не «ноль ошибок»."""
    if report.get("tests"):
        return report
    message = report.get("import_error") or ""
    if not message and report.get("timeout"):
        message = "Прогон остановлен по таймауту"
    if not message:
        message = "Тесты не были запущены: прогон не дал ни одного результата"
    report["tests"] = [
        {"name": LOAD_STAGE_NAME, "status": "errored", "message": message, "duration_ms": 0}
    ]
    report["errored"] = max(int(report.get("errored") or 0), 1)
    report["ok"] = False
    return report


'''

WRAPPER = '''

def run_tests(
    code: str,
    tests_src: str,
    timeout: float = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Прогон тестов. Гарантия: отчёт никогда не бывает пустым и молчаливым."""
    report = _run_tests_raw(code, tests_src, timeout, memory_mb, cpu_seconds, use_cache)
    return _ensure_visible_failure(report)
'''

done = []


def patch_session():
    path = ROOT / "engine" / "session.py"
    src = path.read_text(encoding="utf-8")
    if '"correct", "explanation", "answer"' in src:
        done.append("session.py: уже пропатчен")
        return True
    if SESSION_OLD not in src:
        print("session.py: не нашёл строку фильтра public_view", file=sys.stderr)
        return False
    path.write_text(src.replace(SESSION_OLD, SESSION_NEW, 1), encoding="utf-8")
    done.append("session.py: public_view больше не отдаёт answer/correct до ответа")
    return True


def patch_sandbox():
    path = ROOT / "engine" / "sandbox.py"
    src = path.read_text(encoding="utf-8")
    if "_ensure_visible_failure" in src:
        done.append("sandbox.py: уже пропатчен")
        return True
    if "def _empty_report(" not in src or "def run_tests(" not in src:
        print("sandbox.py: не нашёл _empty_report/run_tests", file=sys.stderr)
        return False
    src = src.replace("def _empty_report(", HELPERS + "def _empty_report(", 1)
    src = src.replace("def run_tests(", "def _run_tests_raw(", 1)
    src = src.rstrip("\n") + "\n" + WRAPPER
    path.write_text(src, encoding="utf-8")
    done.append("sandbox.py: пустой прогон теперь виден как провал загрузки решения")
    return True


ok = patch_session() and patch_sandbox()
for line in done:
    print("  • " + line)
print("patch_engine: " + ("ок" if ok else "ОШИБКА"))
sys.exit(0 if ok else 1)
