"""
ПРУФ · engine.protocol

Протокол понимания: что человек контролирует, что шатко, что не контролирует.
Никаких «баллов за старание»: любая цифра выводится из ответов на конкретные мутации
и пересчитывается по тем же входным данным.
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
    "shaky": "Шатко́",
    "weak": "Не контролирует",
    "unknown": "Не проверялось",
}

FONT_CANDIDATES = (
    "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/msttcore/arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _skill_verdict(score: float) -> str:
    if score >= SKILL_CONTROL:
        return "control"
    if score >= SKILL_SHAKY:
        return "shaky"
    return "weak"


def _clock(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def grade(session: Dict[str, Any]) -> Dict[str, Any]:
    """Взвешенные баллы по навыкам и общий процент контроля."""
    answers = session.get("answers", {}) or {}
    questions = session.get("questions", []) or []

    weight_total = 0.0
    weight_correct = 0.0
    per_skill: Dict[str, Dict[str, Any]] = {}
    correct_count = 0

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
    return {
        "control": round(control, 4),
        "control_pct": int(round(control * 100)),
        "weight_total": round(weight_total, 2),
        "weight_correct": round(weight_correct, 2),
        "answered": len(answers),
        "questions_total": len(questions),
        "correct": correct_count,
        "skills": skills,
        "passed": int(round(control * 100)) >= PASS_CONTROL_PCT,
    }


def _overall_verdict(control_pct: int, mutation_pct: int) -> Dict[str, str]:
    if control_pct >= 85:
        level, label = "good", "Понимание подтверждено"
        summary = "Кандидат разбирает свой код и видит следствия правок. Можно идти на техническое интервью."
    elif control_pct >= PASS_CONTROL_PCT:
        level, label = "medium", "Понимание подтверждено частично"
        summary = "Основная логика своя, но есть зоны, где кандидат не видит последствий правки."
    elif control_pct >= 45:
        level, label = "low", "Понимание не подтверждено"
        summary = "Кандидат не объясняет поведение своего кода на большей части правок."
    else:
        level, label = "bad", "Код с большой вероятностью не свой"
        summary = "На своём же решении кандидат не различает опасные и безопасные правки."
    return {
        "level": level,
        "label": label,
        "summary": summary,
        "tests_note": "Мутационный счёт набора тестов — %d %%." % mutation_pct,
    }


def build(session: Dict[str,