"""
ПРУФ · tools/smoke_arp.py

Смоук-прогон протокола АРП-2 «Оракул»: проверяет три аксиомы на живом ядре.
Без сети, без LLM, без внешних зависимостей.

Запуск: python3 tools/smoke_arp.py
Код возврата 0 — все проверки зелёные.

Что именно проверяется:
  A1 (в кадре нет ответа) — screen_digest побайтово одинаков при разных скрытых правках;
  A2 (ответ добывается взаимодействием) — зонд отдаёт ровно один бит, пул валидируется;
  A3 (ответ без доказательства не считается) — порог улик и ОБЭ.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import arp  # noqa: E402

CHECKS = []


def check(name, condition, detail=""):
    ok = bool(condition)
    CHECKS.append((name, ok, detail))
    print("%s %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "  <- %s" % detail))
    return ok


def session_for(seed):
    return arp.start(seed=seed, persist=False)


def bits_of(session, hid):
    for item in session["secret"]["hypotheses"]:
        if item["id"] == hid:
            return list(item["pool_bits"])
    raise KeyError(hid)


def solution_expr(code, expr):
    """Зонд -> код теста: подставляет префикс solution. перед вызовами."""
    out = expr
    for name in sorted(arp.public_names(code), key=len, reverse=True):
        out = out.replace(name + "(", "solution." + name + "(")
    return out


def differentiating_index(session, want_value=True, min_group=1):
    """Индекс пула, на котором скрытая правка проявляется и подпись пригодна для теста.

    min_group — сколько гипотез должно давать на этом входе бит 1: при min_group=2
    после локализации совместимыми остаются минимум две гипотезы.
    """
    secret = session["secret"]
    bits = bits_of(session, secret["active"])
    for index, bit in enumerate(bits):
        if not bit:
            continue
        signature = secret["base_signatures"][index]
        if want_value and not signature.startswith("V:"):
            continue
        if len(signature) > 110:
            continue
        group = sum(1 for item in secret["hypotheses"] if item["pool_bits"][index] == 1)
        if group < min_group:
            continue
        return index
    return None


def greedy_probe_to_unique(session, limit=6):
    """Зонды, которые действительно сужают совместимое множество до одной гипотезы."""
    secret = session["secret"]
    pool = secret["pool"]
    active = secret["active"]
    used = {row["expr"] for row in secret["evidence"]}
    for _ in range(limit):
        alive = arp.consistent_set(session)
        if len(alive) <= 1:
            return alive
        best, best_gain = None, -1
        for index, expr in enumerate(pool):
            if expr in used:
                continue
            mine = bits_of(session, active)[index]
            gain = sum(1 for hid in alive if hid != active and bits_of(session, hid)[index] != mine)
            if gain > best_gain:
                best, best_gain = expr, gain
        if best is None or best_gain <= 0:
            return alive
        arp.probe(session, best)
        used.add(best)
    return arp.consistent_set(session)


def spare_probe(session):
    """Любой ещё не использованный зонд пула — чтобы добрать публичный порог улик."""
    secret = session["secret"]
    used = {row["expr"] for row in secret["evidence"]}
    for expr in secret["pool"]:
        if expr not in used:
            arp.probe(session, expr)
            return True
    return False


def identify_active(session):
    """Идентификация с добором зондов до публичного порога.

    Публичный порог равен log2(k) и одинаков для всех гипотез — иначе он сам стал бы
    битом информации о скрытой правке (A1). Точная граница инстанса бывает меньше,
    поэтому доказанный ответ иногда готов раньше порога: добираем зондами.
    """
    for _ in range(4):
        try:
            return arp.submit_identify(session, session["secret"]["active"])
        except arp.ArpError as exc:
            if exc.reason != "not_enough_evidence" or not spare_probe(session):
                raise
    return arp.submit_identify(session, session["secret"]["active"])


def trap_for(session, index):
    """Ловушка: тест проходит на оригинале и падает на скрытой правке."""
    secret = session["secret"]
    expr = solution_expr(session["code"], secret["pool"][index])
    expected = secret["base_signatures"][index][2:]
    return "import solution\n\n\ndef test_hidden_edit():\n    assert repr(%s) == %r\n" % (expr, expected)


def obe_session():
    """Сценарий ОБЭ: зонды, не отделяющие active от партнёра (детерминированный подбор).

    Для каждой гипотезы p != active собираем индексы пула, где биты p и active совпадают,
    требуем не меньше порога таких индексов и хотя бы один с битом 1 (им закрывается
    локализация). Тогда порог улик пройден, а совместимых гипотез осталось больше одной.
    """
    for attempt in range(12):
        session = session_for("obe-%d" % attempt)
        secret = session["secret"]
        active = secret["active"]
        mine = bits_of(session, active)
        floor = session["min_probes"]
        for item in secret["hypotheses"]:
            if item["id"] == active:
                continue
            shared = [i for i in range(len(mine)) if item["pool_bits"][i] == mine[i]]
            ones = [i for i in shared if mine[i] == 1]
            if len(shared) >= floor and ones:
                order = [ones[0]] + [i for i in shared if i != ones[0]]
                return session, item["id"], order[:floor]
    return None, None, None


def main():
    print("ПРУФ · смоук АРП-2 «Оракул»")
    print("-" * 64)

    # --- 1. сборка сессии -------------------------------------------------
    main_session = session_for("smoke-main")
    total = main_session["hypotheses_total"]
    check("1.1 гипотез не меньше минимума", total >= arp.HYPOTHESES_MIN, total)
    check("1.2 пул зондов пригоден", len(main_session["secret"]["pool"]) >= 2,
          len(main_session["secret"]["pool"]))
    check("1.3 порог улик = log2(k)", main_session["min_probes"] == int(math.ceil(math.log2(total))),
          main_session["min_probes"])
    check("1.4 baseline зелёный", main_session["baseline"]["passed"] >= 3, main_session["baseline"])
    check("1.5 все гипотезы попарно различимы",
          len({tuple(i["pool_bits"]) for i in main_session["secret"]["hypotheses"]}) == total)

    # --- 2. A1: в кадре нет ответа ---------------------------------------
    digests, actives = set(), set()
    for number in range(10):
        probe_session = session_for("a1-%d" % number)
        digests.add(arp.screen_digest(probe_session))
        actives.add(probe_session["secret"]["active"])
    check("2.1 разные скрытые правки по сидам", len(actives) >= 2, sorted(actives))
    check("2.2 экран побайтово одинаков (A1)", len(digests) == 1, digests)
    check("2.3 утечек в публичном виде нет", arp.audit_public(main_session) == [],
          arp.audit_public(main_session))
    public = arp.public_view(main_session)
    check("2.4 фаза A скрывает список гипотез", public["hypotheses"] == [] and public["phase"] == "A")
    check("2.5 в публичном виде нет ключа secret", "secret" not in public)

    # --- 3. A2: валидация зондов -----------------------------------------
    for bad, label in (
        ("__import__('os')", "3.1 импорт отклонён"),
        ("parse_line('a;1;2').keys()", "3.2 обращение к атрибуту отклонено"),
        ("1 + 1", "3.3 зонд без вызова отклонён"),
        ("open('/etc/passwd')", "3.4 стороннее имя отклонено"),
    ):
        try:
            arp.probe(main_session, bad)
            check(label, False, "зонд прошёл")
        except arp.ArpError as exc:
            check(label, exc.status == 422, exc.reason)
    check("3.5 отклонённые зонды не тратят бюджет", len(main_session["probes"]) == 0)

    # --- 4. A3: ответ без улик не принимается ----------------------------
    locate_index = differentiating_index(main_session, min_group=2)
    check("4.1 найден вход с проявлением правки", locate_index is not None, locate_index)
    located = arp.submit_locate(main_session, main_session["secret"]["pool"][locate_index])
    check("4.2 локализация принята", located["accepted"] and located["score"] == 1.0, located)
    check("4.3 фаза B открывает список гипотез",
          len(arp.public_view(main_session)["hypotheses"]) == total)
    try:
        arp.submit_identify(main_session, main_session["secret"]["active"])
        check("4.4 порог улик держит (A3)", False, "ответ принят без улик")
    except arp.ArpError as exc:
        check("4.4 порог улик держит (A3)", exc.reason == "not_enough_evidence" and exc.status == 409,
              exc.reason)
    check("4.5 отказ по порогу не тратит попытку",
          arp._step(main_session, "identify")["attempts"] == 0)

    # --- 5. честный путь -------------------------------------------------
    alive = greedy_probe_to_unique(main_session)
    check("5.1 зонды сузили множество до одной гипотезы", len(alive) == 1, alive)
    exact_bound = arp.instance_bound(main_session["secret"]["hypotheses"], main_session["secret"]["active"])
    check("5.2 зондов не меньше точной границы инстанса",
          len(main_session["probes"]) >= exact_bound, (len(main_session["probes"]), exact_bound))
    identified = identify_active(main_session)
    check("5.3 идентификация с доказательством", identified["accepted"] and identified["score"] == 1.0,
          identified)
    trap_index = differentiating_index(main_session)
    trapped = arp.submit_trap(main_session, trap_for(main_session, trap_index))
    check("5.4 ловушка поймала скрытую правку", trapped["accepted"] and trapped["score"] == 1.0, trapped)
    protocol = arp.finish(main_session)
    check("5.5 вердикт «контролирует»", protocol["verdict"] == "control", protocol["verdict"])
    check("5.6 протокол подтверждён", protocol["confirmed"] and protocol["score"] >= 0.8, protocol["score"])
    check("5.7 в протоколе обе границы",
          protocol["evidence"]["bound_worst_case"] == main_session["min_probes"]
          and protocol["evidence"]["bound_instance"] >= 1, protocol["evidence"])
    check("5.8 аудит экрана чистый", protocol["screen_audit"]["clean"], protocol["screen_audit"])
    check("5.9 совместимых гипотез осталось одна", protocol["evidence"]["consistent_left"] == 1,
          protocol["evidence"]["consistent_left"])
    try:
        arp.finish(main_session)
        check("5.10 закрытая сессия не переоткрывается", False, "finish прошёл дважды")
    except arp.ArpError as exc:
        check("5.10 закрытая сессия не переоткрывается", exc.reason == "session_finished", exc.reason)

    # --- 6. ОБЭ: метка угадана, улик нет --------------------------------
    obe, partner, order = obe_session()
    if not check("6.1 сценарий ОБЭ построен", obe is not None, "не нашлось партнёрской гипотезы"):
        return summary()
    pool = obe["secret"]["pool"]
    arp.submit_locate(obe, pool[order[0]])
    for index in order[1:]:
        arp.probe(obe, pool[index])
    check("6.2 порог улик по числу зондов пройден",
          len(obe["probes"]) >= obe["min_probes"], len(obe["probes"]))
    left = arp.consistent_set(obe)
    check("6.3 совместимых гипотез больше одной", len(left) > 1, left)
    check("6.4 партнёр остался совместим", partner in left, (partner, left))
    obe_result = arp.submit_identify(obe, obe["secret"]["active"])
    check("6.5 ОБЭ: верная метка без улик не зачтена",
          obe_result["accepted"] is False and obe_result["score"] == 0.0, obe_result)
    check("6.6 флаг ОБЭ выставлен", "ОБЭ" in obe_result["flags"], obe_result["flags"])
    obe_protocol = arp.finish(obe)
    check("6.7 ОБЭ поднимает индекс делегирования", obe_protocol["delegation"]["index"] >= 30,
          obe_protocol["delegation"])
    check("6.8 вердикт ниже порога подтверждения", not obe_protocol["confirmed"], obe_protocol["score"])

    # --- 7. ловушка, падающая на оригинале ------------------------------
    trap_session = session_for("trap-bad")
    arp.submit_locate(trap_session, trap_session["secret"]["pool"][differentiating_index(trap_session)])
    try:
        arp.check_trap(trap_session, "import solution\n\n\ndef test_bad():\n    assert False\n")
        check("7.1 ловушка на оригинале обязана проходить", False, "принята падающая ловушка")
    except arp.ArpError as exc:
        check("7.1 ловушка на оригинале обязана проходить",
              exc.reason == "trap_fails_on_original", exc.reason)
    try:
        arp.validate_trap("x = 1")
        check("7.2 ловушка без теста отклонена", False, "принята")
    except arp.ArpError as exc:
        check("7.2 ловушка без теста отклонена", exc.reason == "trap_no_tests", exc.reason)

    # --- 8. бюджеты и воспроизводимость ---------------------------------
    budget_session = session_for("budget")
    budget_session["probes"] = [{"n": i + 1, "expr": "x", "bit": 0, "at": 0.0}
                                for i in range(arp.PROBE_BUDGET)]
    try:
        arp.probe(budget_session, budget_session["secret"]["pool"][0])
        check("8.1 бюджет зондов ограничен", False, "зонд прошёл сверх бюджета")
    except arp.ArpError as exc:
        check("8.1 бюджет зондов ограничен", exc.reason == "probe_budget", exc.reason)
    first = session_for("repro")
    second = session_for("repro")
    check("8.2 тот же сид -> та же скрытая правка",
          first["secret"]["active"] == second["secret"]["active"],
          (first["secret"]["active"], second["secret"]["active"]))
    check("8.3 тот же сид -> тот же пул", first["secret"]["pool"] == second["secret"]["pool"])
    cost = arp.relay_cost(total)
    check("8.4 стоимость релея считается",
          cost["cycles"] == main_session["min_probes"] + 2 and cost["seconds"] < arp.SESSION_BUDGET_S,
          cost)
    return summary()


def summary():
    failed = [name for name, ok, _ in CHECKS if not ok]
    print("-" * 64)
    print("проверок: %d, успешно: %d, провалено: %d"
          % (len(CHECKS), len(CHECKS) - len(failed), len(failed)))
    for name in failed:
        print("  провал: %s" % name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
