"""
ПРУФ · engine.sandbox

Изолированный прогон тестов над решением или его мутантом.

Каждый прогон — отдельный процесс python -I -S во временном каталоге:
без сети, с ограничениями по CPU, памяти и размеру файлов, с таймаутом по часам родителя.
Внешних зависимостей нет: работает в закрытом контуре без интернета.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Sequence, Tuple

SCHEMA_VERSION = "pruf.sandbox/1"
RUN_SCHEMA = "pruf.sandbox.run/1"
MARKER = "__PRUF__"

DEFAULT_TIMEOUT = 10.0
DEFAULT_MEMORY_MB = 512
DEFAULT_CPU_SECONDS = 5
MAX_CODE_BYTES = 200_000
CACHE_LIMIT = 512

_CACHE: Dict[str, Dict[str, Any]] = {}


class SandboxError(RuntimeError):
    pass


HARNESS = r'''
import builtins, contextlib, io, json, os, sys, time, traceback

BLOCKED = {
    "socket", "ssl", "http", "urllib", "requests", "subprocess", "multiprocessing",
    "ctypes", "pickle", "shutil", "asyncio", "selectors", "xmlrpc", "ftplib",
    "smtplib", "webbrowser", "pty", "tty", "pdb",
}

_real_import = builtins.__import__


def _guarded_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root in BLOCKED:
        raise ImportError("модуль %s заблокирован песочницей ПРУФ" % name)
    return _real_import(name, *args, **kwargs)


builtins.__import__ = _guarded_import

for _attr in ("system", "popen", "execv", "execvp", "fork", "kill", "spawnv"):
    if hasattr(os, _attr):
        try:
            setattr(os, _attr, None)
        except Exception:
            pass

try:
    import resource
    cpu = int(os.environ.get("PRUF_CPU", "5"))
    mem = int(os.environ.get("PRUF_MEM_MB", "512")) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except Exception:
        pass
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

report = {
    "schema": "pruf.sandbox.run/1",
    "ok": False,
    "tests": [],
    "passed": 0,
    "failed": 0,
    "errored": 0,
    "import_error": None,
    "timeout": False,
    "stdout": "",
}


def emit():
    sys.stdout.flush()
    print("__PRUF__" + json.dumps(report, ensure_ascii=False))
    sys.stdout.flush()


def short(text, size=400):
    text = (text or "").strip().replace("\r", "")
    return text if len(text) <= size else text[:size] + "…"


buffer = io.StringIO()
started = time.time()

try:
    with contextlib.redirect_stdout(buffer):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pruf_tests", os.path.join(HERE, "tests.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["pruf_tests"] = module
        spec.loader.exec_module(module)
except BaseException as exc:
    report["import_error"] = short("%s: %s" % (type(exc).__name__, exc))
    report["stdout"] = short(buffer.getvalue(), 2000)
    emit()
    raise SystemExit(0)

cases = []
for name in dir(module):
    if not name.startswith("test"):
        continue
    value = getattr(module, name)
    if callable(value) and hasattr(value, "__code__"):
        cases.append((value.__code__.co_firstlineno, name, value))
cases.sort()

for _, name, func in cases:
    entry = {"name": name, "status": "passed", "message": "", "duration_ms": 0}
    case_started = time.time()
    try:
        with contextlib.redirect_stdout(buffer):
            func()
    except AssertionError as exc:
        entry["status"] = "failed"
        entry["message"] = short(str(exc) or "assert не выполнился")
        report["failed"] += 1
    except BaseException as exc:
        entry["status"] = "errored"
        entry["message"] = short("%s: %s" % (type(exc).__name__, exc))
        entry["traceback"] = short(traceback.format_exc(), 800)
        report["errored"] += 1
    else:
        report["passed"] += 1
    entry["duration_ms"] = int((time.time() - case_started) * 1000)
    report["tests"].append(entry)

report["ok"] = report["failed"] == 0 and report["errored"] == 0 and bool(report["tests"])
report["duration_ms"] = int((time.time() - started) * 1000)
report["stdout"] = short(buffer.getvalue(), 2000)
emit()
'''


def run_key(code: str, tests_src: str, timeout: float, memory_mb: int, cpu_seconds: int) -> str:
    material = "\u0000".join([code, tests_src, str(timeout), str(memory_mb), str(cpu_seconds)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _empty_report(reason: str, message: str, duration_ms: int = 0) -> Dict[str, Any]:
    return {
        "schema": RUN_SCHEMA,
        "ok": False,
        "tests": [],
        "passed": 0,
        "failed": 0,
        "errored": 0,
        "import_error": message,
        "timeout": reason == "timeout",
        "stdout": "",
        "duration_ms": duration_ms,
        "reason": reason,
    }


def run_tests(
    code: str,
    tests_src: str,
    timeout: float = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Запускает тесты над решением и возвращает отчёт прогона."""
    if len(code.encode("utf-8")) > MAX_CODE_BYTES or len(tests_src.encode("utf-8")) > MAX_CODE_BYTES:
        return _empty_report("too_large", "Файл больше %d КБ — песочница такое не берёт" % (MAX_CODE_BYTES // 1024))

    key = run_key(code, tests_src, timeout, memory_mb, cpu_seconds)
    if use_cache and key in _CACHE:
        cached = dict(_CACHE[key])
        cached["cached"] = True
        return cached

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="pruf_") as workdir:
        paths = {
            "solution.py": code,
            "tests.py": tests_src,
            "harness.py": HARNESS,
        }
        for name, content in paths.items():
            with open(os.path.join(workdir, name), "w", encoding="utf-8") as handle:
                handle.write(content)

        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": workdir,
            "TMPDIR": workdir,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PRUF_CPU": str(cpu_seconds),
            "PRUF_MEM_MB": str(memory_mb),
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", os.path.join(workdir, "harness.py")],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _empty_report(
                "timeout",
                "Прогон превысил %.0f с и был остановлен песочницей" % timeout,
                int((time.time() - started) * 1000),
            )

    report: Optional[Dict[str, Any]] = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith(MARKER):
            try:
                report = json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                report = None

    if report is None:
        stderr = (proc.stderr or "").strip().splitlines()
        message = stderr[-1] if stderr else "процесс завершился без отчёта"
        report = _empty_report("crash", message[:400], int((time.time() - started) * 1000))
    report.setdefault("duration_ms", int((time.time() - started) * 1000))
    report["wall_ms"] = int((time.time() - started) * 1000)
    report["cached"] = False
    report["exit_code"] = proc.returncode

    if use_cache:
        if len(_CACHE) >= CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = report
    return report


def run_many(
    variants: Sequence[Tuple[str, str]],
    tests_src: str,
    workers: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Dict[str, Any]]:
    """Прогоняет несколько вариантов кода (id, code) параллельно."""
    results: Dict[str, Dict[str, Any]] = {}
    if not variants:
        return results
    workers = max(1, min(int(workers), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(run_tests, code, tests_src, timeout): variant_id
            for variant_id, code in variants
        }
        for future in futures:
            variant_id = futures[future]
            try:
                results[variant_id] = future.result()
            except Exception as exc:  # pragma: no cover
                results[variant_id] = _empty_report("crash", str(exc)[:200])
    return results


def clear_cache() -> None:
    _CACHE.clear()


def cache_size() -> int:
    return len(_CACHE)
