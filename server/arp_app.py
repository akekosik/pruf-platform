"""
ПРУФ · server/arp_app.py

HTTP-слой протокола АРП-2 «Оракул». Только stdlib, без зависимостей и без сети.
Порт 8788 (8777 занят прототипом v1, они живут рядом).

Запуск:
    python3 server/arp_app.py
    python3 server/arp_app.py --port 9000 --host 0.0.0.0
Затем открыть http://127.0.0.1:8788/verify.html

Инварианты этого слоя (они важнее удобства):
  1. Наружу уходит только `arp.public_view(session)`. Сама сессия с ключом `secret`
     никогда не сериализуется.
  2. Перед каждым ответом гоняется `arp.audit_public(session)`. Нашлась утечка — ответ
     не отдаётся, клиент получает 500 и список ключей в логе. Дыру лучше увидеть в
     логе, чем в кадре кандидата.
  3. Ядро не знает про HTTP: любая `arp.ArpError` превращается в JSON с её же статусом.
  4. Результаты шагов отдаются как `result` без переупаковки — слой не интерпретирует
     семантику протокола, чтобы одна правка ядра не требовала правки сервера.

Ручки:
  GET  /api/arp/health
  GET  /api/arp/session?id=...
  POST /api/arp/start          {candidate?, code?, tests?, seed?}
  POST /api/arp/run            {id}                 — прогон оригинала, бесплатно
  POST /api/arp/probe          {id, expr}           — один бит дифференциального оракула
  POST /api/arp/locate         {id, expr}
  POST /api/arp/identify       {id, hypothesis}
  POST /api/arp/trap/check     {id, tests}
  POST /api/arp/trap/submit    {id, tests}
  POST /api/arp/telemetry      {id, type, payload?}
  POST /api/arp/finish         {id}
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import arp  # noqa: E402

LOCK = threading.Lock()
SESSIONS = {}


class LeakError(Exception):
    """Аудит экрана нашёл запрещённый ключ в публичном виде."""

    def __init__(self, leaks):
        super().__init__("leaks: %s" % ", ".join(str(x) for x in leaks))
        self.leaks = leaks


def engine_fn(*names):
    """Первая существующая функция ядра из списка имён (устойчивость к правкам ядра)."""
    for name in names:
        fn = getattr(arp, name, None)
        if callable(fn):
            return fn
    return None


def get_session(sid):
    if not sid:
        raise arp.ArpError("unknown_session", "Не указан id сессии", 404)
    with LOCK:
        session = SESSIONS.get(sid)
    if session is not None:
        return session
    loader = engine_fn("load_session", "load", "get_session")
    if loader is not None:
        try:
            session = loader(sid)
        except Exception:
            session = None
        if session:
            with LOCK:
                SESSIONS[sid] = session
            return session
    raise arp.ArpError("unknown_session", "Сессия не найдена: %s" % sid, 404)


def public(session):
    """Публичный вид плюс обязательный аудит утечек."""
    tick = engine_fn("tick")
    if tick is not None:
        try:
            tick(session)
        except arp.ArpError:
            pass
    leaks = arp.audit_public(session)
    if leaks:
        raise LeakError(leaks)
    return arp.public_view(session)


def wrap(session, result):
    return {"id": session.get("id"), "result": result, "session": public(session)}


# --- ручки ------------------------------------------------------------------


def api_health(payload):
    return 200, {
        "ok": True,
        "schema": getattr(arp, "SCHEMA", "pruf.arp/2"),
        "version": getattr(arp, "VERSION", ""),
        "sessions": len(SESSIONS),
        "budgets": {
            "probes": getattr(arp, "PROBE_BUDGET", 7),
            "runs": getattr(arp, "RUN_BUDGET", 60),
            "seconds": getattr(arp, "SESSION_BUDGET_S", 900),
        },
    }


def api_start(payload):
    kwargs = {}
    for key in ("code", "tests", "candidate", "seed"):
        value = payload.get(key)
        if value not in (None, ""):
            kwargs[key] = value
    session = arp.start(**kwargs)
    sid = session.get("id")
    with LOCK:
        SESSIONS[sid] = session
    return 200, {"id": sid, "session": public(session)}


def api_session(payload):
    session = get_session(payload.get("id"))
    return 200, {"id": session.get("id"), "session": public(session)}


def api_run(payload):
    session = get_session(payload.get("id"))
    runner = engine_fn("run_original")
    if runner is None:
        return 501, {"error": "not_implemented", "message": "run_original недоступен в ядре"}
    return 200, wrap(session, runner(session))


def api_probe(payload):
    session = get_session(payload.get("id"))
    return 200, wrap(session, arp.probe(session, payload.get("expr", "")))


def api_locate(payload):
    session = get_session(payload.get("id"))
    return 200, wrap(session, arp.submit_locate(session, payload.get("expr", "")))


def api_identify(payload):
    session = get_session(payload.get("id"))
    hypothesis = payload.get("hypothesis") or payload.get("hypothesis_id") or ""
    return 200, wrap(session, arp.submit_identify(session, hypothesis))


def api_trap_check(payload):
    session = get_session(payload.get("id"))
    return 200, wrap(session, arp.check_trap(session, payload.get("tests", "")))


def api_trap_submit(payload):
    session = get_session(payload.get("id"))
    return 200, wrap(session, arp.submit_trap(session, payload.get("tests", "")))


def api_telemetry(payload):
    session = get_session(payload.get("id"))
    fn = engine_fn("telemetry")
    if fn is None:
        return 200, wrap(session, None)
    kind = payload.get("type", "render")
    try:
        result = fn(session, kind, payload.get("payload"))
    except TypeError:
        result = fn(session, kind)
    return 200, wrap(session, result)


def api_finish(payload):
    session = get_session(payload.get("id"))
    protocol = arp.finish(session)
    return 200, {"id": session.get("id"), "protocol": protocol, "session": public(session)}


GET_ROUTES = {
    "/api/arp/health": api_health,
    "/api/arp/session": api_session,
}

POST_ROUTES = {
    "/api/arp/start": api_start,
    "/api/arp/session": api_session,
    "/api/arp/run": api_run,
    "/api/arp/probe": api_probe,
    "/api/arp/locate": api_locate,
    "/api/arp/identify": api_identify,
    "/api/arp/trap/check": api_trap_check,
    "/api/arp/trap/submit": api_trap_submit,
    "/api/arp/telemetry": api_telemetry,
    "/api/arp/finish": api_finish,
}


# --- транспорт ---------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "pruf-arp/2"

    def log_message(self, fmt, *args):  # тише, чем стандартный шум
        sys.stderr.write("[arp] %s - %s\n" % (self.address_string(), fmt % args))

    # — ответы

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self.send_json(404, {"error": "not_found", "message": "Файл не найден"})
            return
        kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # — маршрутизация

    def resolve_static(self, path):
        if path in ("", "/"):
            for candidate in ("index.html", "verify.html"):
                full = os.path.join(WEB, candidate)
                if os.path.isfile(full):
                    return full
            return None
        parts = [p for p in path.split("/") if p not in ("", ".", "..")]
        full = os.path.normpath(os.path.join(WEB, *parts))
        if not full.startswith(WEB):
            return None
        return full if os.path.isfile(full) else None

    def dispatch(self, route, payload, table):
        handler = table.get(route)
        if handler is None:
            self.send_json(404, {"error": "unknown_route", "message": "Нет такой ручки: %s" % route})
            return
        try:
            status, data = handler(payload)
        except arp.ArpError as exc:
            self.send_json(getattr(exc, "status", 400) or 400, {
                "error": exc.reason,
                "message": str(exc),
            })
            return
        except LeakError as exc:
            self.log_message("УТЕЧКА В ПУБЛИЧНОМ ВИДЕ: %s", exc.leaks)
            self.send_json(500, {
                "error": "screen_leak",
                "message": "Аудит экрана нашёл утечку, ответ не отдан",
                "leaks": exc.leaks,
            })
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.send_json(500, {"error": "internal", "message": str(exc)})
            return
        self.send_json(status, data)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            self.dispatch(parsed.path.rstrip("/") or parsed.path, query, GET_ROUTES)
            return
        static = self.resolve_static(parsed.path)
        if static is None:
            self.send_json(404, {"error": "not_found", "message": "Нет такого файла"})
            return
        self.send_file(static)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "bad_json", "message": "Тело запроса не JSON"})
            return
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "bad_json", "message": "Ожидается объект JSON"})
            return
        self.dispatch(parsed.path.rstrip("/") or parsed.path, payload, POST_ROUTES)


def main(argv=None):
    parser = argparse.ArgumentParser(description="ПРУФ · сервер АРП-2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("ПРУФ · АРП-2 на http://%s:%d/verify.html" % (args.host, args.port))
    print("статика: %s" % WEB)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
