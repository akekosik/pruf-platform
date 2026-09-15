# -*- coding: utf-8 -*-
"""ПРУФ · сквозная проверка HTTP API поверх живого сервера.

    python3 -m engine.cli serve --port 8777 &
    python3 tools/qa_api.py --base http://127.0.0.1:8777

Список роутов берётся прямо из server/app.py, поэтому новый роут нельзя забыть
проверить: если он есть в коде, но не покрыт, отчёт об этом скажет.
Код возврата 0 — всё зелёное, 1 — есть падения.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CHECKS = []
COVERED = set()


def req(base, path, method="GET", payload=None, raw=False, timeout=90):
    url = base + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
    except Exception as error:
        return 0, {"error": str(error)}, b""
    if raw:
        return status, None, body
    try:
        return status, json.loads(body.decode("utf-8")), body
    except Exception:
        return status, None, body


def check(title, ok, detail=""):
    CHECKS.append((bool(ok), title, detail))
    print("  %s  %s" % ("ok  " if ok else "FAIL", title), flush=True)
    if detail and not ok:
        print("        → %s" % str(detail)[:400], flush=True)
    return bool(ok)


def section(title):
    print("\n── %s" % title, flush=True)


# Своё решение кандидата: мутироваться должен именно этот код, а не фикстура.
OWN_CODE = '''def normalize(raw):
    """Отбрасывает короткие строки и стрижёт пробелы."""
    rows = []
    for line in raw.strip().splitlines():
        item = line.strip()
        if len(item) < 2:
            continue
        rows.append(item.lower())
    return rows


def score(rows, bonus=10):
    total = 0
    for index, row in enumerate(rows):
        weight = len(row) * 2
        if index == 0:
            weight += bonus
        total += weight
    return round(total / max(len(rows), 1), 2)
'''

OWN_TESTS = '''from solution import normalize, score


def test_normalize_drops_short():
    assert normalize("  Bolt \\n a \\n Nut ") == ["bolt", "nut"]


def test_score_average():
    assert score(["aa", "bb"]) == 9.0
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8777")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    from server import app as server_app

    get_routes = sorted(server_app.GET_ROUTES)
    post_routes = sorted(server_app.POST_ROUTES)

    section("Статика и служебные файлы")
    for page in ("/", "/index.html", "/studio.html", "/session.html", "/employer.html",
                 "/candidate.html", "/docs.html", "/css/app.css", "/css/cabinet.css",
                 "/js/app.js", "/js/landing.js", "/js/gl.js", "/js/studio.js",
                 "/js/session.js", "/js/employer.js", "/js/candidate.js",
                 "/data/demo.json", "/favicon.ico"):
        status, _, body = req(base, page, raw=True)
        check("GET %s" % page, status == 200 and len(body) > 0, "status=%s" % status)
    status, _, _ = req(base, "/no-such-page-qa.html", raw=True)
    check("Несуществующая страница отдаёт 404", status == 404, "status=%s" % status)
    status, _, _ = req(base, "/../server/app.py", raw=True)
    check("Выход за пределы web/ закрыт", status in (403, 404), "status=%s" % status)

    section("GET-роуты API")
    for route in get_routes:
        status, data, _ = req(base, route)
        COVERED.add(route)
        check("GET %s" % route, status == 200 and isinstance(data, dict), "status=%s" % status)

    section("Ядро на своём коде (не фикстура)")
    status, data, _ = req(base, "/api/mutations", "POST", {"code": OWN_CODE, "limit": 12})
    COVERED.add("/api/mutations")
    rows = (data or {}).get("mutations") or []
    check("POST /api/mutations даёт мутации", status == 200 and len(rows) >= 9,
          "status=%s, мутаций=%s" % (status, len(rows)))
    check("У мутаций есть строка, оператор и diff",
          all(row.get("line") and row.get("operator") and row.get("diff") for row in rows), rows[:1])
    check("Мутации разнообразны (≥ 4 операторов)",
          len({row.get("operator") for row in rows}) >= 4, sorted({row.get("operator") for row in rows}))
    check("Мутации применены именно к моему коду",
          all(row.get("before") != row.get("after") for row in rows), rows[:1])

    status, data, _ = req(base, "/api/run", "POST", {"code": OWN_CODE, "tests": OWN_TESTS})
    COVERED.add("/api/run")
    report = (data or {}).get("report") or data or {}
    check("POST /api/run прогоняет мои тесты", status == 200 and report.get("passed") == 2 and report.get("ok"),
          "status=%s, report=%s" % (status, json.dumps(report, ensure_ascii=False)[:250]))

    status, data, _ = req(base, "/api/run", "POST",
                          {"code": "def normalize(raw):\n    return []\n", "tests": OWN_TESTS})
    report = (data or {}).get("report") or data or {}
    broke = (report.get("failed") or 0) + (report.get("errored") or 0)
    check("Сломанное решение не даёт зелёный прогон", broke > 0 and not report.get("ok"),
          json.dumps(report, ensure_ascii=False)[:250])

    status, data, _ = req(base, "/api/analyze", "POST",
                          {"code": OWN_CODE, "tests": OWN_TESTS, "limit": 12}, timeout=240)
    COVERED.add("/api/analyze")
    analysis = (data or {}).get("analysis") or data or {}
    summary = analysis.get("summary") or analysis
    total = summary.get("total") or summary.get("mutation_total") or 0
    killed = summary.get("killed")
    survived = summary.get("survived")
    check("POST /api/analyze считает mutation score",
          status == 200 and total >= 9 and killed is not None and survived is not None,
          json.dumps(summary, ensure_ascii=False)[:300])
    check("killed + survived = всего мутаций", (killed or 0) + (survived or 0) == total,
          "killed=%s survived=%s total=%s" % (killed, survived, total))
    check("Есть вердикт по набору тестов", bool(analysis.get("verdict")), analysis.get("verdict"))
    check("Выжившие мутации показаны как дыры в тестах",
          isinstance(analysis.get("gaps"), list), type(analysis.get("gaps")).__name__)

    status, data, _ = req(base, "/api/analyze", "POST",
                          {"code": "def broken(:\n    pass\n", "tests": OWN_TESTS})
    check("Синтаксическая ошибка объяснена, а не 500",
          status in (200, 400, 422) and not (data or {}).get("ok", False),
          "status=%s %s" % (status, json.dumps(data or {}, ensure_ascii=False)[:200]))

    section("Сессия защиты полным циклом")
    status, data, _ = req(base, "/api/session/start", "POST",
                          {"code": OWN_CODE, "tests": OWN_TESTS, "candidate": "QA-кандидат",
                           "task": "Своё решение из QA", "limit": 10}, timeout=300)
    COVERED.add("/api/session/start")
    session_view = (data or {}).get("session") or data or {}
    session_id = session_view.get("id")
    questions = session_view.get("questions") or []
    check("POST /api/session/start открывает сессию",
          status == 200 and bool(session_id) and len(questions) >= 6,
          "status=%s, id=%s, вопросов=%s" % (status, session_id, len(questions)))
    blob = json.dumps(session_view, ensure_ascii=False)
    check("Правильные ответы не уходят клиенту",
          '"correct"' not in blob and '"explanation"' not in blob and '"answer"' not in blob, blob[:200])
    check("Таймер сессии — 15 минут", session_view.get("seconds_total") == 900,
          session_view.get("seconds_total"))

    protocol_id = None
    if session_id:
        first = questions[0]
        status, data, _ = req(base, "/api/session/%s" % session_id)
        check("GET /api/session/{id} возвращает сессию", status == 200, "status=%s" % status)

        option = (first.get("options") or [{}])[0].get("id")
        status, data, _ = req(base, "/api/session/%s/answer" % session_id, "POST",
                              {"question_id": first.get("id"), "option_id": option, "seconds": 12})
        answer = (data or {}).get("answer") or data or {}
        check("POST answer принимает ответ и даёт разбор",
              status == 200 and answer.get("explanation") is not None and answer.get("correct") is not None,
              json.dumps(data or {}, ensure_ascii=False)[:250])
        check("В разборе есть правильный вариант и привязка к мутации",
              bool(answer.get("correct_options")) and bool(answer.get("mutation")),
              json.dumps(answer, ensure_ascii=False)[:250])

        status, repeat, _ = req(base, "/api/session/%s/answer" % session_id, "POST",
                                {"question_id": first.get("id"), "option_id": option, "seconds": 3})
        repeat_body = (repeat or {}).get("answer") or repeat or {}
        check("Повторный ответ не перезаписывает результат",
              status == 200 and repeat_body.get("repeat") is True,
              json.dumps(repeat or {}, ensure_ascii=False)[:200])

        status, bad, _ = req(base, "/api/session/%s/answer" % session_id, "POST",
                             {"question_id": "q-no-such", "option_id": "ZZZ"})
        check("Неизвестный вопрос отбивается без 500",
              status in (400, 404, 422) or not ((bad or {}).get("ok", False)),
              "status=%s %s" % (status, json.dumps(bad or {}, ensure_ascii=False)[:200]))

        for question in questions[1:]:
            options = question.get("options") or []
            if not options:
                continue
            req(base, "/api/session/%s/answer" % session_id, "POST",
                {"question_id": question.get("id"), "option_id": options[0].get("id"), "seconds": 9})

        status, data, _ = req(base, "/api/session/%s/finish" % session_id, "POST", {})
        report = (data or {}).get("protocol") or data or {}
        protocol_id = report.get("id")
        check("POST finish выдаёт протокол понимания", status == 200 and bool(protocol_id),
              json.dumps(data or {}, ensure_ascii=False)[:250])
        check("В протоколе есть карта навыков", bool(report.get("skills")), list(report)[:12])
        check("В протоколе есть отпечаток решения", bool(report.get("fingerprint")), list(report)[:12])

        status, _, _ = req(base, "/api/session/no-such-session")
        check("Неизвестная сессия — 404, а не 500", status == 404, "status=%s" % status)

    if protocol_id:
        status, data, _ = req(base, "/api/protocol/%s" % protocol_id)
        check("GET /api/protocol/{id}", status == 200 and isinstance(data, dict), "status=%s" % status)
        status, _, body = req(base, "/api/protocol/%s.pdf" % protocol_id, raw=True)
        check("GET /api/protocol/{id}.pdf отдаёт PDF", status == 200 and body[:4] == b"%PDF",
              "status=%s, начало=%r" % (status, body[:12]))
        status, data, _ = req(base, "/api/protocol/%s/send" % protocol_id, "POST",
                              {"email": "hr@example.com"})
        check("POST /api/protocol/{id}/send", status == 200 and (data or {}).get("ok") is not False,
              json.dumps(data or {}, ensure_ascii=False)[:200])

    section("Кабинеты и заявки")
    status, data, _ = req(base, "/api/candidates")
    rows = (data or {}).get("candidates") or []
    check("GET /api/candidates — пул кандидатов", status == 200 and len(rows) >= 6,
          "кандидатов=%s" % len(rows))
    for row in rows:
        candidate_id = row.get("id")
        status, bundle, _ = req(base, "/api/candidates/%s" % candidate_id)
        ok = status == 200 and isinstance(bundle, dict) and bool((bundle or {}).get("protocol"))
        check("GET /api/candidates/%s с готовым протоколом" % candidate_id, ok, "status=%s" % status)
        if ok:
            pid = ((bundle or {}).get("protocol") or {}).get("id")
            status, _, body = req(base, "/api/protocol/%s.pdf" % pid, raw=True)
            check("PDF протокола кандидата %s" % candidate_id,
                  status == 200 and body[:4] == b"%PDF", "status=%s" % status)
    status, _, _ = req(base, "/api/candidates/no-such-candidate")
    check("Неизвестный кандидат — 404", status == 404, "status=%s" % status)

    status, data, _ = req(base, "/api/leads", "POST",
                          {"name": "QA Проверка", "email": "qa@example.com",
                           "company": "ООО Пример", "plan": "employer", "message": "автопроверка"})
    COVERED.add("/api/leads")
    check("POST /api/leads сохраняет заявку", status == 200 and (data or {}).get("ok") is not False,
          json.dumps(data or {}, ensure_ascii=False)[:200])
    status, data, _ = req(base, "/api/leads", "POST", {"name": "", "email": ""})
    check("Пустая заявка отбивается с понятной ошибкой",
          status in (200, 400, 422) and not (data or {}).get("ok", False),
          json.dumps(data or {}, ensure_ascii=False)[:200])

    section("Покрытие роутов")
    missed = [route for route in post_routes if route not in COVERED]
    check("Все POST-роуты покрыты проверками", not missed, "не проверено: %s" % missed)

    failed = [item for item in CHECKS if not item[0]]
    print("\n" + "=" * 64)
    print("Проверок: %d · зелёных: %d · падений: %d" % (len(CHECKS), len(CHECKS) - len(failed), len(failed)))
    if failed:
        print("\nПадения:")
        for _, title, detail in failed:
            print("  · %s\n      %s" % (title, str(detail)[:300]))
    print("=" * 64)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
