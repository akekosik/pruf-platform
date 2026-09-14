"""
ПРУФ · server.app

HTTP-слой над движком: только стандартная библиотека Python, без фреймворков,
без внешних запросов и без LLM. Запуск: python3 -m engine.cli serve --port 8000

Роуты
    GET  /api/health                     состояние сервиса и версии схем
    GET  /api/catalog                    каталог операторов мутаций и навыков
    GET  /api/tasks                      демо-задачи с кодом и тестами
    GET  /api/economics                  юнит-экономика
    GET  /api/demo?task=orders           полный офлайн-цикл
    POST /api/mutations                  {code, limit} → мутации без прогона
    POST /api/run                        {code, tests} → прогон тестов в изоляторе
    POST /api/analyze                    {code, tests, limit} → мутационный анализ
    POST /api/session/start              {code, tests, meta} → сессия защиты
    GET  /api/session/{id}               текущее состояние сессии
    POST /api/session/{id}/answer        {question, option, seconds}
    POST /api/session/{id}/finish        завершить и собрать протокол
    GET  /api/protocol/{id}[.txt|.pdf]   протокол понимания
    POST /api/protocol/{id}/send         {email} → отправка работодателю (журнал)
    GET  /api/candidates                 пул кандидатов для кабинета
    GET  /api/candidates/{id}            протокол конкретного кандидата
    GET  /api/vacancies                  вакансии
    POST /api/leads                      {name, email, company, plan} → заявка
    GET  /api/leads                      список заявок
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine import __version__  # noqa: E402
from engine import analysis, economics, fixtures, mutations, protocol, sandbox, store  # noqa: E402
from engine import session as session_mod  # noqa: E402

WEB_ROOT = os.path.join(PROJECT_ROOT, "web")
MAX_BODY = 400_000
SERVER_NAME = "PRUF/%s" % __version__

_CACHE: dict = {}
_CACHE_LOCK = threading.RLock()


def _cached(key: str, builder):
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = builder()
    with _CACHE_LOCK:
        _CACHE[key] = value
    return value


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _require_code(payload: dict) -> str:
    code = payload.get("code") or ""
    if not code.strip():
        raise ApiError("Пустой код решения")
    if len(code.encode("utf-8")) > sandbox.MAX_CODE_BYTES:
        raise ApiError("Решение слишком большое для прототипа")
    return code


def _require_tests(payload: dict) -> str:
    tests = payload.get("tests") or ""
    if not tests.strip():
        raise ApiError("Нет тестов: без них нечем ловить мутации")
    return tests


def _limit(payload: dict) -> int:
    try:
        value = int(payload.get("limit") or mutations.DEFAULT_LIMIT)
    except (TypeError, ValueError):
        value = mutations.DEFAULT_LIMIT
    return max(3, min(value, mutations.MAX_LIMIT))


# --- обработчики API -------------------------------------------------------

def api_health(_payload: dict, _query: dict) -> dict:
    return {
        "ok": True,
        "service": "pruf",
        "version": __version__,
        "time": time.time(),
        "offline": True,
        "schemas": {
            "engine": getattr(sys.modules["engine"], "SCHEMA_VERSION", "pruf.engine/1"),
            "mutations": mutations.SCHEMA_VERSION,
            "sandbox": sandbox.SCHEMA_VERSION,
            "analysis": analysis.SCHEMA_VERSION,
            "session": session_mod.SCHEMA_VERSION,
            "protocol": protocol.SCHEMA_VERSION,
            "economics": economics.SCHEMA_VERSION,
            "store": store.SCHEMA_VERSION,
        },
        "operators": len(mutations.OPERATOR_LIST),
        "data_root": store.root(),
    }


def api_catalog(_payload: dict, _query: dict) -> dict:
    return {"operators": mutations.catalog(), "skills": mutations.SKILLS}


def api_tasks(_payload: dict, _query: dict) -> dict:
    return {"tasks": fixtures.tasks(), "vacancies": fixtures.VACANCIES}


def api_vacancies(_payload: dict, _query: dict) -> dict:
    return {"vacancies": fixtures.VACANCIES}


def api_economics(_payload: dict, _query: dict) -> dict:
    return economics.report()


def api_demo(_payload: dict, query: dict) -> dict:
    task_id = (query.get("task") or ["orders"])[0]
    variant = (query.get("tests") or ["full"])[0]
    key = "demo:%s:%s" % (task_id, variant)
    return _cached(key, lambda: fixtures.demo(task_id=task_id, tests_variant=variant))


def api_mutations(payload: dict, _query: dict) -> dict:
    return analysis.preview(_require_code(payload), limit=_limit(payload))


def api_run(payload: dict, _query: dict) -> dict:
    return sandbox.run_tests(_require_code(payload), _require_tests(payload))


def api_analyze(payload: dict, _query: dict) -> dict:
    return analysis.analyze(_require_code(payload), _require_tests(payload), limit=_limit(payload))


def api_session_start(payload: dict, _query: dict) -> dict:
    code = _require_code(payload)
    tests = _require_tests(payload)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    session = session_mod.build(
        code, tests,
        limit=_limit(payload),
        question_limit=int(payload.get("questions") or session_mod.DEFAULT_QUESTIONS),
        meta=meta,
    )
    if not session.get("ok"):
        raise ApiError(session.get("error") or "Не удалось собрать сессию", 422)
    store.save("sessions", session["id"], session)
    return session_mod.public_view(session)


def _load_session(session_id: str) -> dict:
    session = store.load("sessions", session_id)
    if session is None:
        raise ApiError("Сессия не найдена или уже удалена", 404)
    return session


def api_session_get(session_id: str) -> dict:
    return session_mod.public_view(_load_session(session_id))


def api_session_answer(session_id: str, payload: dict) -> dict:
    session = _load_session(session_id)
    question_id = payload.get("question") or payload.get("question_id")
    option_id = payload.get("option") or payload.get("option_id")
    if not question_id or not option_id:
        raise ApiError("Нужны question и option")
    outcome = session_mod.answer(session, question_id, option_id, seconds=payload.get("seconds"))
    store.save("sessions", session_id, session)
    return {"answer": outcome, "session": session_mod.public_view(session)}


def api_session_finish(session_id: str, payload: dict) -> dict:
    session = _load_session(session_id)
    session_mod.finish(session)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
    report = protocol.build(session, meta=meta)
    store.save("sessions", session_id, session)
    store.save("protocols", report["id"], report)
    return {"protocol": report, "session": session_mod.public_view(session)}


def _load_protocol(protocol_id: str) -> dict:
    report = store.load("protocols", protocol_id)
    if report is None:
        session = store.load("sessions", "s-" + protocol_id[2:]) if protocol_id.startswith("p-") else None
        if session is not None:
            report = protocol.build(session)
            store.save("protocols", report["id"], report)
    if report is None:
        raise ApiError("Протокол не найден", 404)
    return report


def api_protocol_send(protocol_id: str, payload: dict) -> dict:
    report = _load_protocol(protocol_id)
    email = (payload.get("email") or "").strip()
    if "@" not in email:
        raise ApiError("Нужен корректный e-mail получателя")
    entry = store.append("outbox", "protocols", {
        "protocol": protocol_id,
        "email": email,
        "control_pct": report.get("control_pct"),
        "note": payload.get("note", ""),
    })
    return {
        "ok": True,
        "delivered": False,
        "queued": True,
        "entry": entry,
        "message": "Протокол поставлен в очередь отправки. В прототипе почта не уходит: запись сохранена в data/outbox.",
    }


def api_candidates(_payload: dict, _query: dict) -> dict:
    rows = _cached("candidates", fixtures.candidates_overview)
    total = len(rows)
    passed = len([row for row in rows if row.get("passed")])
    average = round(sum(row.get("control_pct", 0) for row in rows) / total, 1) if total else 0.0
    return {
        "candidates": rows,
        "vacancies": fixtures.VACANCIES,
        "stats": {
            "total": total,
            "passed": passed,
            "rejected": total - passed,
            "average_control": average,
            "saved_hours": total * 2,
        },
    }


def api_candidate(candidate_id: str) -> dict:
    bundle = _cached("candidate:%s" % candidate_id, lambda: fixtures.candidate_bundle(candidate_id))
    if bundle is None:
        raise ApiError("Кандидат не найден", 404)
    return bundle


def api_leads_post(payload: dict, _query: dict) -> dict:
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    if not name:
        raise ApiError("Укажите имя")
    if "@" not in email:
        raise ApiError("Укажите корректный e-mail")
    entry = store.append("leads", "inbox", {
        "name": name,
        "email": email,
        "company": (payload.get("company") or "").strip(),
        "plan": payload.get("plan") or "Пилот",
        "comment": (payload.get("comment") or "").strip()[:600],
    })
    return {"ok": True, "lead": entry, "message": "Заявка сохранена локально в data/leads."}


def api_leads_get(_payload: dict, _query: dict) -> dict:
    items = store.read_items("leads", "inbox")
    return {"leads": items, "count": len(items)}


GET_ROUTES = {
    "/api/health": api_health,
    "/api/catalog": api_catalog,
    "/api/tasks": api_tasks,
    "/api/vacancies": api_vacancies,
    "/api/economics": api_economics,
    "/api/demo": api_demo,
    "/api/candidates": api_candidates,
    "/api/leads": api_leads_get,
}

POST_ROUTES = {
    "/api/mutations": api_mutations,
    "/api/run": api_run,
    "/api/analyze": api_analyze,
    "/api/session/start": api_session_start,
    "/api/leads": api_leads_post,
}


class Handler(BaseHTTPRequestHandler):
    server_version = SERVER_NAME
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # тише в консоли
        sys.stderr.write("[pruf] %s\n" % (fmt % args))

    # --- служебное ---------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message, "status": status}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("Слишком большой запрос", 413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("Ожидается корректный JSON")
        return data if isinstance(data, dict) else {"value": data}

    # --- статика -----------------------------------------------------
    def _static(self, path: str) -> None:
        relative = unquote(path.lstrip("/")) or "index.html"
        if relative.endswith("/"):
            relative += "index.html"
        target = os.path.normpath(os.path.join(WEB_ROOT, relative))
        if not target.startswith(WEB_ROOT):
            self._error("Запрещённый путь", 403)
            return
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.exists(target) and not os.path.splitext(target)[1]:
            target += ".html"
        if not os.path.isfile(target):
            self._send(404, "Страница не найдена".encode("utf-8"), "text/plain; charset=utf-8")
            return
        guessed = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed in {"application/javascript", "application/json"}:
            guessed += "; charset=utf-8"
        with open(target, "rb") as handle:
            self._send(200, handle.read(), guessed)

    # --- маршрутизация ----------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if not path.startswith("/api"):
                self._static(parsed.path)
                return
            query = parse_qs(parsed.query)
            handler = GET_ROUTES.get(path)
            if handler is not None:
                self._json(handler({}, query))
                return
            if path.startswith("/api/session/"):
                self._json(api_session_get(path.split("/")[3]))
                return
            if path.startswith("/api/candidates/"):
                self._json(api_candidate(path.split("/")[3]))
                return
            if path.startswith("/api/protocol/"):
                self._protocol(path.split("/")[3])
                return
            self._error("Неизвестный роут: %s" % path, 404)
        except ApiError as error:
            self._error(error.message, error.status)
        except Exception:  # pragma: no cover
            traceback.print_exc()
            self._error("Внутренняя ошибка сервера", 500)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            payload = self._body()
            query = parse_qs(parsed.query)
            handler = POST_ROUTES.get(path)
            if handler is not None:
                self._json(handler(payload, query))
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "session":
                if parts[3] == "answer":
                    self._json(api_session_answer(parts[2], payload))
                    return
                if parts[3] == "finish":
                    self._json(api_session_finish(parts[2], payload))
                    return
            if len(parts) == 4 and parts[1] == "protocol" and parts[3] == "send":
                self._json(api_protocol_send(parts[2], payload))
                return
            self._error("Неизвестный роут: %s" % path, 404)
        except ApiError as error:
            self._error(error.message, error.status)
        except Exception:  # pragma: no cover
            traceback.print_exc()
            self._error("Внутренняя ошибка сервера", 500)

    def _protocol(self, raw_id: str) -> None:
        if raw_id.endswith(".pdf"):
            report = _load_protocol(raw_id[:-4])
            blob = protocol.render_pdf(report)
            if blob is None:
                self._error("PDF недоступен: не установлен reportlab. Скачайте текстовую версию.", 503)
                return
            self._send(200, blob, "application/pdf", {
                "Content-Disposition": 'attachment; filename="%s.pdf"' % report["id"],
            })
            return
        if raw_id.endswith(".txt"):
            report = _load_protocol(raw_id[:-4])
            body = protocol.render_text(report).encode("utf-8")
            self._send(200, body, "text/plain; charset=utf-8", {
                "Content-Disposition": 'attachment; filename="%s.txt"' % report["id"],
            })
            return
        self._json(_load_protocol(raw_id))


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("ПРУФ %s · сайт и API: http://%s:%d" % (__version__, host, port))
    print("Данные: %s · остановка: Ctrl+C" % store.root())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve(port=int(os.environ.get("PRUF_PORT", "8000")))
