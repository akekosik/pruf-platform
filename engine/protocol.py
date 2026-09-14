"""
ПРУФ · engine.protocol

Протокол понимания: что человек контролирует, что шатко, что не контролирует.
Любая цифра выводится из ответов на конкретные мутации и пересчитывается по тем же входным данным:
спор разбирается пересчётом, а не мнением интервьюера.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "pruf.protocol/1"

SKILL_CONTROL = 0.80
SKILL_SHAKY = 0.50
PASS_CONTROL_PCT = 70

SKILL_VERDICTS = {
    "control": "Контролирует",
    "shaky": "Шатко",
    "weak": "Не контролирует",
}

FONT_CANDIDATES = (
    "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/msttcore/arial.ttf",
)


def _skill_verdict(score: float) -> str:
    if score >= SKILL_CONTROL:
        return "control"
    if score >= SKILL_SHAKY:
        return "shaky"
    return "weak"


def clock(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    total = int(max(0, seconds))
    return "%02d:%02d" % (total // 60, total % 60)


def grade(session: Dict[str, Any]) -> Dict[str, Any]:
    """Взвешенный процент контроля и разбивка по навыкам."""
    answers = session.get("answers") or {}
    questions = session.get("questions") or []

    weight_total = 0.0
    weight_correct = 0.0
    correct_count = 0
    per_skill: Dict[str, Dict[str, Any]] = {}

    for question in questions:
        answer = answers.get(question["id"])
        if not answer:
            continue
        weight = float(question.get("weight", 1.0))
        skill = question.get("skill", "other")
        entry = per_skill.setdefault(skill, {
            "skill": skill,
            "title": question.get("skill_title", skill),
            "weight_total": 0.0,
            "weight_correct": 0.0,
            "questions": 0,
            "correct": 0,
        })
        entry["weight_total"] += weight
        entry["questions"] += 1
        weight_total += weight
        if answer.get("correct"):
            entry["weight_correct"] += weight
            entry["correct"] += 1
            weight_correct += weight
            correct_count += 1

    skills: List[Dict[str, Any]] = []
    for entry in per_skill.values():
        score = entry["weight_correct"] / entry["weight_total"] if entry["weight_total"] else 0.0
        verdict = _skill_verdict(score)
        skills.append({
            "skill": entry["skill"],
            "title": entry["title"],
            "score": round(score, 4),
            "score_pct": int(round(score * 100)),
            "questions": entry["questions"],
            "correct": entry["correct"],
            "verdict": verdict,
            "verdict_label": SKILL_VERDICTS[verdict],
        })
    skills.sort(key=lambda item: (-item["score"], item["skill"]))

    control = weight_correct / weight_total if weight_total else 0.0
    control_pct = int(round(control * 100))
    return {
        "control": round(control, 4),
        "control_pct": control_pct,
        "weight_total": round(weight_total, 2),
        "weight_correct": round(weight_correct, 2),
        "answered": len(answers),
        "questions_total": len(questions),
        "correct": correct_count,
        "skills": skills,
        "passed": control_pct >= PASS_CONTROL_PCT,
    }


def _overall(control_pct: int, mutation_pct: int, answered: int) -> Dict[str, str]:
    if answered == 0:
        return {
            "level": "empty", "label": "Сессия не пройдена",
            "summary": "Ответов нет, выводов о понимании сделать нельзя.",
            "tests_note": "Мутационный счёт набора тестов — %d %%." % mutation_pct,
        }
    if control_pct >= 85:
        level, label = "good", "Понимание подтверждено"
        summary = "Автор разбирает свой код и видит последствия правок. Можно идти на техническое интервью."
    elif control_pct >= PASS_CONTROL_PCT:
        level, label = "medium", "Понимание подтверждено частично"
        summary = "Основная логика своя, но есть зоны, где автор не видит последствий правки."
    elif control_pct >= 45:
        level, label = "low", "Понимание не подтверждено"
        summary = "Большая часть правок осталась без объяснения — нужен живой разбор."
    else:
        level, label = "bad", "Код с большой вероятностью не свой"
        summary = "На своём же решении автор не различает опасные и безопасные правки."
    return {
        "level": level, "label": label, "summary": summary,
        "tests_note": "Мутационный счёт набора тестов — %d %%." % mutation_pct,
    }


def build(session: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Собирает протокол по завершённой (или частично пройденной) сессии."""
    scores = grade(session)
    summary = session.get("summary", {}) or {}
    answers = session.get("answers") or {}
    questions = session.get("questions") or []
    info = dict(session.get("meta") or {})
    info.update(meta or {})

    # Таймлайн сессии в порядке ответов
    timeline: List[Dict[str, Any]] = []
    for question in questions:
        answer = answers.get(question["id"])
        if not answer:
            continue
        timeline.append({
            "order": answer.get("order", len(timeline) + 1),
            "question": question["id"],
            "type": question["type"],
            "title": question["title"],
            "mutation": question["mutation"]["id"],
            "line": question["mutation"]["line"],
            "skill": question.get("skill_title", ""),
            "result": "разобрал" if answer.get("correct") else "не заметил",
            "correct": bool(answer.get("correct")),
            "seconds": answer.get("seconds"),
            "clock": clock(answer.get("seconds")),
        })
    timeline.sort(key=lambda item: item["order"])

    # Риски: выжившие мутации плюс слабые навыки
    risks: List[Dict[str, Any]] = []
    for gap in (session.get("gaps") or [])[:6]:
        risks.append({
            "kind": "дыра в тестах",
            "mutation": gap.get("id"),
            "line": gap.get("line"),
            "skill": gap.get("skill_title"),
            "text": gap.get("consequence"),
            "action": gap.get("suggestion"),
        })
    for skill in scores["skills"]:
        if skill["verdict"] == "weak":
            risks.append({
                "kind": "не контролирует навык",
                "mutation": None,
                "line": None,
                "skill": skill["title"],
                "text": "Верных ответов %d из %d по теме «%s»" % (skill["correct"], skill["questions"], skill["title"]),
                "action": "На интервью стоит разобрать эту тему вручную.",
            })

    # Цитаты мутаций: что именно человек не заметил
    quotes: List[Dict[str, Any]] = []
    for question in questions:
        answer = answers.get(question["id"])
        if not answer or answer.get("correct"):
            continue
        mutation = question["mutation"]
        quotes.append({
            "mutation": mutation["id"],
            "line": mutation["line"],
            "kind": mutation["kind"],
            "diff": mutation["diff"],
            "question": question["title"],
            "skill": question.get("skill_title", ""),
        })
        if len(quotes) >= 4:
            break

    duration = None
    if session.get("finished_at") and session.get("started_at"):
        duration = int(session["finished_at"] - session["started_at"])

    protocol = {
        "schema": SCHEMA_VERSION,
        "id": "p-" + str(session.get("id", "session")).replace("s-", ""),
        "session_id": session.get("id"),
        "created_at": time.time(),
        "fingerprint": session.get("fingerprint"),
        "candidate": {
            "name": info.get("candidate") or info.get("name") or "Кандидат без имени",
            "email": info.get("email", ""),
            "role": info.get("role", ""),
            "vacancy": info.get("vacancy", ""),
            "company": info.get("company", ""),
        },
        "task": {
            "title": info.get("task", "Своё решение"),
            "language": info.get("language", "Python"),
            "lines": summary.get("lines", 0),
            "sites": summary.get("sites", 0),
        },
        "control_pct": scores["control_pct"],
        "passed": scores["passed"],
        "pass_threshold_pct": PASS_CONTROL_PCT,
        "verdict": _overall(scores["control_pct"], summary.get("mutation_score_pct", 0), scores["answered"]),
        "mutation": {
            "total": summary.get("mutation_total", 0),
            "killed": summary.get("killed", 0),
            "survived": summary.get("survived", 0),
            "score_pct": summary.get("mutation_score_pct", 0),
            "verdict": summary.get("verdict", {}),
        },
        "questions": {
            "total": scores["questions_total"],
            "answered": scores["answered"],
            "correct": scores["correct"],
        },
        "skills": scores["skills"],
        "risks": risks,
        "quotes": quotes,
        "timeline": timeline,
        "duration_seconds": duration,
        "duration_clock": clock(duration) if duration is not None else "—",
        "engine": {"protocol": SCHEMA_VERSION, "session": session.get("schema")},
        "reproducible": "Отпечаток решения %s · те же входы дают те же мутации и тот же вердикт" % (
            session.get("fingerprint") or "—"),
    }
    return protocol


def render_text(protocol: Dict[str, Any]) -> str:
    """Текстовая версия протокола — для CLI и для вложения в письмо."""
    lines = [
        "ПРОТОКОЛ ПОНИМАНИЯ · ПРУФ",
        "=" * 46,
        "Кандидат: %s" % protocol["candidate"]["name"],
        "Задача: %s (%s)" % (protocol["task"]["title"], protocol["task"]["language"]),
        "Вердикт: %s — %s" % (protocol["verdict"]["label"], protocol["verdict"]["summary"]),
        "Контроль: %d %% (порог %d %%)" % (protocol["control_pct"], protocol["pass_threshold_pct"]),
        "Мутации: %d всего, поймано %d, выжило %d (счёт %d %%)" % (
            protocol["mutation"]["total"], protocol["mutation"]["killed"],
            protocol["mutation"]["survived"], protocol["mutation"]["score_pct"]),
        "Вопросы: %d из %d, верно %d" % (
            protocol["questions"]["answered"], protocol["questions"]["total"], protocol["questions"]["correct"]),
        "",
        "Карта навыков:",
    ]
    for skill in protocol["skills"]:
        lines.append("  %-28s %3d %%  %s" % (skill["title"], skill["score_pct"], skill["verdict_label"]))
    if protocol["risks"]:
        lines += ["", "Риски:"]
        for risk in protocol["risks"]:
            place = " (строка %s)" % risk["line"] if risk.get("line") else ""
            lines.append("  [%s]%s %s" % (risk["kind"], place, risk["text"]))
            if risk.get("action"):
                lines.append("      → %s" % risk["action"])
    if protocol["timeline"]:
        lines += ["", "Таймлайн сессии:"]
        for item in protocol["timeline"]:
            lines.append("  %s %s · %s · %s" % (item["question"], item["mutation"], item["result"], item["clock"]))
    lines += ["", protocol["reproducible"]]
    return "\n".join(lines)


def _find_font() -> Optional[str]:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def render_pdf(protocol: Dict[str, Any], path: str) -> Optional[str]:
    """PDF протокола. Возвращает None, если reportlab или шрифт с кириллицей недоступны."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas as pdf_canvas
    except Exception:
        return None

    font_path = _find_font()
    if not font_path:
        return None
    try:
        pdfmetrics.registerFont(TTFont("PrufSans", font_path))
    except Exception:
        return None

    width, height = A4
    doc = pdf_canvas.Canvas(path, pagesize=A4)
    doc.setTitle("Протокол понимания · ПРУФ")
    cursor = height - 25 * mm

    def write(text: str, size: int = 10, gap: float = 6.0, color=(0.1, 0.1, 0.12)) -> None:
        nonlocal cursor
        if cursor < 25 * mm:
            doc.showPage()
            cursor = height - 25 * mm
        doc.setFont("PrufSans", size)
        doc.setFillColorRGB(*color)
        doc.drawString(20 * mm, cursor, text[:110])
        cursor -= gap * mm

    write("ПРОТОКОЛ ПОНИМАНИЯ · ПРУФ", 18, 9)
    write("Кандидат: %s" % protocol["candidate"]["name"], 12, 6)
    if protocol["candidate"].get("vacancy"):
        write("Вакансия: %s" % protocol["candidate"]["vacancy"], 10, 6)
    write("Задача: %s (%s)" % (protocol["task"]["title"], protocol["task"]["language"]), 10, 8)
    write("Вердикт: %s" % protocol["verdict"]["label"], 14, 7)
    write(protocol["verdict"]["summary"], 10, 8, (0.35, 0.35, 0.4))
    write("Контроль: %d %%   ·   порог %d %%   ·   мутационный счёт %d %%" % (
        protocol["control_pct"], protocol["pass_threshold_pct"], protocol["mutation"]["score_pct"]), 11, 8)
    write("Мутации: %d всего, поймано %d, выжило %d" % (
        protocol["mutation"]["total"], protocol["mutation"]["killed"], protocol["mutation"]["survived"]), 10, 9)

    write("Карта навыков", 13, 7)
    for skill in protocol["skills"]:
        write("  %s — %d %% · %s" % (skill["title"], skill["score_pct"], skill["verdict_label"]), 10, 5.5)

    if protocol["risks"]:
        cursor -= 3 * mm
        write("Риски и что делать", 13, 7)
        for risk in protocol["risks"]:
            place = " (строка %s)" % risk["line"] if risk.get("line") else ""
            write("  [%s]%s %s" % (risk["kind"], place, risk["text"]), 10, 5.5)
            if risk.get("action"):
                write("      → %s" % risk["action"], 9, 5.5, (0.35, 0.35, 0.4))

    if protocol["timeline"]:
        cursor -= 3 * mm
        write("Таймлайн сессии", 13, 7)
        for item in protocol["timeline"]:
            write("  %s · %s · %s · %s" % (item["question"], item["mutation"], item["result"], item["clock"]), 9, 5)

    cursor -= 4 * mm
    write(protocol["reproducible"], 8, 5, (0.45, 0.45, 0.5))
    write("Сессия %s · без прокторинга, без камеры, без вызовов языковых моделей" % protocol["session_id"],
          8, 5, (0.45, 0.45, 0.5))

    doc.showPage()
    doc.save()
    return path
