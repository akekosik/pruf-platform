"""
ПРУФ · engine.economics

Юнит-экономика новой модели (платит работодатель) и сравнение с вузовской моделью Стапеля.
Все цифры считаются из одного набора параметров, чтобы питч и документация не расходились.
"""

from __future__ import annotations

from typing import Any, Dict, List

SCHEMA_VERSION = "pruf.economics/1"

PARAMS: Dict[str, float] = {
    "price_verification": 1500.0,      # ₽ за одну верификацию кандидата
    "price_subscription_year": 150000.0,  # ₽ годовая подписка компании (90–250 тыс.)
    "price_onprem_year": 650000.0,     # ₽ on-premise для закрытого контура (400–900 тыс.)
    "variable_cost_session": 4.0,      # ₽ процессорное время + хранение с запасом
    "fixed_costs_year": 1200000.0,     # ₽ постоянные затраты (уровень гранта)
    "sessions_per_company_year": 200.0,
    "senior_hour_cost": 2500.0,        # ₽ час senior-инженера на разбор тестового
    "senior_hours_per_candidate": 2.0,
}

STAPEL_MODEL: Dict[str, float] = {
    "price_per_student_year": 190.0,
    "pilot_students": 300.0,
    "pilot_result": -9272.0,
    "year1_result": -403086.0,
    "breakeven_students": 3745.0,
}


def unit(params: Dict[str, float] = None) -> Dict[str, Any]:
    """Юнит-экономика одной верификации."""
    values = dict(PARAMS)
    values.update(params or {})
    price = values["price_verification"]
    variable = values["variable_cost_session"]
    margin = price - variable
    manual = values["senior_hour_cost"] * values["senior_hours_per_candidate"]
    return {
        "price": price,
        "variable_cost": variable,
        "margin": margin,
        "margin_pct": round(margin / price * 100, 2) if price else 0.0,
        "manual_alternative": manual,
        "client_saving": manual - price,
        "client_saving_pct": round((manual - price) / manual * 100, 2) if manual else 0.0,
    }


def breakeven(params: Dict[str, float] = None) -> Dict[str, Any]:
    """Сколько верификаций и компаний нужно для нуля."""
    values = dict(PARAMS)
    values.update(params or {})
    figures = unit(values)
    margin = figures["margin"]
    sessions = values["fixed_costs_year"] / margin if margin > 0 else float("inf")
    per_company = values["sessions_per_company_year"]
    return {
        "fixed_costs_year": values["fixed_costs_year"],
        "margin_per_session": margin,
        "sessions_needed": int(sessions) + 1,
        "companies_needed": round(sessions / per_company, 1) if per_company else None,
        "sessions_per_company_year": per_company,
        "comment": "Безубыточность — порядка 800–900 верификаций в год, это 3–5 активных компаний.",
    }


def scenario(name: str, verifications: int, subscriptions: int = 0, onprem: int = 0,
             params: Dict[str, float] = None) -> Dict[str, Any]:
    """Сценарий выручки и результата за период."""
    values = dict(PARAMS)
    values.update(params or {})
    revenue = (
        verifications * values["price_verification"]
        + subscriptions * values["price_subscription_year"]
        + onprem * values["price_onprem_year"]
    )
    variable = verifications * values["variable_cost_session"]
    fixed = values["fixed_costs_year"]
    return {
        "name": name,
        "verifications": verifications,
        "subscriptions": subscriptions,
        "onprem": onprem,
        "revenue": round(revenue, 2),
        "variable_costs": round(variable, 2),
        "fixed_costs": fixed,
        "result": round(revenue - variable - fixed, 2),
        "result_without_fixed": round(revenue - variable, 2),
    }


def scenarios(params: Dict[str, float] = None) -> List[Dict[str, Any]]:
    return [
        scenario("Пилот: 2 компании, 60 верификаций", 60, 0, 0, params),
        scenario("Год 1: 5 компаний по подписке", 600, 5, 0, params),
        scenario("Год 1 + закрытый контур", 600, 5, 1, params),
        scenario("Год 2: 12 компаний + 2 on-premise", 1800, 12, 2, params),
    ]


def compare_with_stapel() -> Dict[str, Any]:
    """Почему плательщик поменялся: две модели рядом."""
    new_break = breakeven()
    return {
        "stapel": {
            "payer": "Кафедра вуза",
            "price": "190 ₽ за студента в год",
            "pilot_result": STAPEL_MODEL["pilot_result"],
            "year1_result": STAPEL_MODEL["year1_result"],
            "breakeven": "%d студентов (2–3 вуза)" % STAPEL_MODEL["breakeven_students"],
            "sales_cycle": "Учебный год и дольше, через закупку",
        },
        "pruf": {
            "payer": "ИТ-компания 50–500 человек",
            "price": "1 500 ₽ за верификацию",
            "breakeven": "%d верификаций (%s компаний)" % (
                new_break["sessions_needed"], new_break["companies_needed"]),
            "sales_cycle": "Пилот за две недели, без закупочных процедур",
            "universities": "0 ₽ — канал и данные, а не выручка",
        },
    }


def report(params: Dict[str, float] = None) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "params": {**PARAMS, **(params or {})},
        "unit": unit(params),
        "breakeven": breakeven(params),
        "scenarios": scenarios(params),
        "comparison": compare_with_stapel(),
        "prices": {
            "verification": "1 200–1 800 ₽ за сессию",
            "subscription": "90 000–250 000 ₽ в год",
            "onprem": "400 000–900 000 ₽ в год",
            "education": "0 ₽",
        },
    }
