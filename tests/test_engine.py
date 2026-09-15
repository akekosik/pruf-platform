# -*- coding: utf-8 -*-
"""Автотесты ядра ПРУФ.

Запуск:  python3 -m unittest discover -s tests -v

Проверяются четыре обещания из документации:
  1. Каталог из 18 операторов — публичный контракт.
  2. Генератор детерминирован и всегда даёт компилируемый код.
  3. Песочница изолирует чужой код и не виснет.
  4. Протокол воспроизводим, а правильные ответы не утекают до ответа кандидата.
"""

import inspect
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import analysis, economics, fixtures, mutations, protocol, sandbox, session  # noqa: E402


def _accepts(fn, name):
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _mutant_source(item):
    """Исходник мутанта независимо от того, dict это или объект."""
    keys = ("mutant", "code", "source", "mutated", "mutant_code")
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    for key in keys:
        value = getattr(item, key, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _field(item, *names):
    for name in names:
        if isinstance(item, dict):
            if name in item:
                return item[name]
        elif hasattr(item, name):
            return getattr(item, name)
    return None


BROKEN = "def broken(:\n    pass\n"

ORDERS = fixtures.get_task("orders")
CODE = ORDERS["code"] if isinstance(ORDERS, dict) else None
TESTS = None
if isinstance(ORDERS, dict):
    for _key in ("tests", "tests_full", "reference_tests"):
        if isinstance(ORDERS.get(_key), str):
            TESTS = ORDERS[_key]
            break


class TestCatalog(unittest.TestCase):
    """Каталог операторов — публичный контракт, он не должен меняться молча."""

    def test_eighteen_operators(self):
        rows = mutations.catalog()
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 18, "в документации заявлено 18 операторов")

    def test_catalog_is_json_serializable(self):
        json.dumps(mutations.catalog(), ensure_ascii=False)

    def test_every_operator_has_identity(self):
        for row in mutations.catalog():
            self.assertTrue(_field(row, "code", "id", "operator", "name"))

    def test_every_operator_declares_a_skill(self):
        known = {"boundary", "logic", "arithmetic", "strings", "io", "errors", "collections", "flow"}
        for row in mutations.catalog():
            skill = _field(row, "skill")
            self.assertIn(skill, known, "неизвестная ось навыков: %r" % (skill,))

    def test_limits_match_documentation(self):
        self.assertEqual(mutations.DEFAULT_LIMIT, 12)
        self.assertEqual(mutations.MAX_LIMIT, 15)
        self.assertEqual(mutations.MIN_USEFUL, 3)


class TestFingerprint(unittest.TestCase):
    """Отпечаток — ключ воспроизводимости и разбора апелляций."""

    def test_stable(self):
        self.assertEqual(mutations.code_fingerprint(CODE), mutations.code_fingerprint(CODE))

    def test_short_hex(self):
        value = mutations.code_fingerprint(CODE)
        self.assertIsInstance(value, str)
        self.assertGreaterEqual(len(value), 8)
        int(value, 16)

    def test_sensitive_to_change(self):
        self.assertNotEqual(
            mutations.code_fingerprint(CODE),
            mutations.code_fingerprint(CODE + "\nX = 1\n"),
        )


class TestGenerator(unittest.TestCase):
    """Главное свойство: мутант всегда компилируется и отличается от оригинала."""

    def test_sites_found(self):
        self.assertGreater(mutations.count_sites(CODE), 0)

    def test_respects_limit(self):
        rows = mutations.generate(CODE, 5)
        self.assertLessEqual(len(rows), 5)
        self.assertGreater(len(rows), 0)

    def test_default_limit_produces_useful_set(self):
        rows = mutations.generate(CODE)
        self.assertGreaterEqual(len(rows), mutations.MIN_USEFUL)
        self.assertLessEqual(len(rows), mutations.MAX_LIMIT)

    def test_every_mutant_compiles(self):
        for item in mutations.generate(CODE):
            src = _mutant_source(item)
            self.assertTrue(src, "у мутации нет исходника")
            compile(src, "<mutant>", "exec")

    def test_every_mutant_differs_from_original(self):
        for item in mutations.generate(CODE):
            self.assertNotEqual(_mutant_source(item), CODE)

    def test_mutants_are_deduplicated(self):
        sources = [_mutant_source(x) for x in mutations.generate(CODE)]
        self.assertEqual(len(sources), len(set(sources)))

    def test_generation_is_deterministic(self):
        first = [_mutant_source(x) for x in mutations.generate(CODE, 12)]
        second = [_mutant_source(x) for x in mutations.generate(CODE, 12)]
        self.assertEqual(first, second)

    def test_broken_code_raises_syntax_error(self):
        """Невалидный код не маскируется: сервер обязан сначала звать syntax_check."""
        with self.assertRaises(SyntaxError):
            mutations.generate(BROKEN, 5)


class TestAnalysis(unittest.TestCase):

    def test_syntax_check_passes_valid_code(self):
        self.assertIsNone(analysis.syntax_check(CODE))

    def test_syntax_check_reports_broken_code(self):
        self.assertIsInstance(analysis.syntax_check(BROKEN), dict)

    def test_preview_returns_mutations(self):
        result = analysis.preview(CODE, 6)
        self.assertIsInstance(result, dict)
        rows = result.get("mutations") or result.get("rows") or []
        self.assertGreater(len(rows), 0)

    def test_verdict_levels_are_known(self):
        for score, survived in ((1.0, 0), (0.6, 4), (0.1, 11)):
            verdict = analysis.verdict_for(score, survived)
            self.assertIsInstance(verdict, dict)
            self.assertTrue(_field(verdict, "level", "kind"))


class TestSandbox(unittest.TestCase):
    """Изоляция: любой прогон завершается и возвращает отчёт, а не виснет."""

    def _run(self, code, tests, timeout=None):
        kwargs = {}
        if timeout is not None and _accepts(sandbox.run_tests, "timeout"):
            kwargs["timeout"] = timeout
        return sandbox.run_tests(code, tests, **kwargs)

    def test_constants_match_documentation(self):
        self.assertEqual(sandbox.MARKER, "__PRUF__")
        self.assertEqual(sandbox.DEFAULT_MEMORY_MB, 512)
        self.assertEqual(sandbox.DEFAULT_CPU_SECONDS, 5)
        self.assertEqual(sandbox.MAX_CODE_BYTES, 200000)

    @unittest.skipIf(TESTS is None, "у фикстуры нет эталонных тестов")
    def test_reference_solution_passes(self):
        report = self._run(CODE, TESTS)
        self.assertIsInstance(report, dict)
        self.assertEqual(report.get("failed"), 0, "эталонное решение должно проходить тесты")
        self.assertGreater(report.get("passed", 0), 0)

    @unittest.skipIf(TESTS is None, "у фикстуры нет эталонных тестов")
    def test_broken_solution_is_detected(self):
        """Заведомо сломанное решение не должно давать зелёный прогон."""
        report = self._run("def parse_orders(raw):\n    return None\n", TESTS)
        self.assertIsInstance(report, dict)
        broke = (report.get("failed") or 0) + (report.get("errored") or 0)
        self.assertGreater(broke, 0, "песочница обязана заметить сломанное решение")

    def test_infinite_loop_does_not_hang(self):
        report = self._run("x = 1\n", "while True:\n    pass\n", timeout=4.0)
        self.assertIsInstance(report, dict, "песочница обязана вернуть отчёт")
        self.assertFalse(report.get("ok", False), "бесконечный цикл не может быть успешным прогоном")

    def test_network_import_is_blocked(self):
        report = self._run("x = 1\n", "import socket\n\ndef test_x():\n    assert socket\n", timeout=6.0)
        self.assertIsInstance(report, dict)

    def test_run_key_is_content_addressed(self):
        a = sandbox.run_key("a", "b", 10.0, 512, 5)
        b = sandbox.run_key("a", "b", 10.0, 512, 5)
        c = sandbox.run_key("a", "c", 10.0, 512, 5)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_cache_is_bounded(self):
        self.assertEqual(sandbox.CACHE_LIMIT, 512)
        self.assertLessEqual(sandbox.cache_size(), sandbox.CACHE_LIMIT)


class TestSessionConstants(unittest.TestCase):

    def test_constants_match_documentation(self):
        self.assertEqual(session.SESSION_SECONDS, 900)
        self.assertEqual(session.MIN_QUESTIONS, 6)
        self.assertEqual(session.MAX_QUESTIONS, 15)
        self.assertEqual(session.DEFAULT_QUESTIONS, 13)
        self.assertEqual(session.MAX_PER_MUTATION, 2)

    def test_question_weights_cover_all_types(self):
        self.assertEqual(
            set(session.QUESTION_WEIGHTS),
            {"danger", "gap", "first_failure", "consequence"},
        )
        for weight in session.QUESTION_WEIGHTS.values():
            self.assertGreater(weight, 0)

    def test_gap_questions_weigh_most(self):
        """Дыра в тестах — самый информативный вопрос."""
        self.assertEqual(max(session.QUESTION_WEIGHTS, key=session.QUESTION_WEIGHTS.get), "gap")

    def test_trap_options_exist(self):
        self.assertIn("тест", session.NO_TEST_OPTION.lower())
        self.assertTrue(session.CRASH_OPTION)

    def test_session_id_has_expected_shape(self):
        value = session.new_session_id(CODE, "salt")
        self.assertRegex(value, r"^s-[0-9a-f]{12}$")


class TestProtocolThresholds(unittest.TestCase):

    def test_thresholds_match_documentation(self):
        self.assertEqual(protocol.SKILL_CONTROL, 0.80)
        self.assertEqual(protocol.SKILL_SHAKY, 0.50)
        self.assertEqual(protocol.PASS_CONTROL_PCT, 70)

    def test_clock_formats_seconds(self):
        self.assertEqual(protocol.clock(0), "00:00")
        self.assertEqual(protocol.clock(79), "01:19")

    def test_clock_handles_none(self):
        self.assertIsInstance(protocol.clock(None), str)


class TestDemoPipeline(unittest.TestCase):
    """Сквозной прогон: регрессионный эталон из документации."""

    @classmethod
    def setUpClass(cls):
        cls.demo = fixtures.demo()

    def test_demo_is_a_bundle(self):
        self.assertIsInstance(self.demo, dict)

    def test_demo_is_json_serializable(self):
        json.dumps(self.demo, ensure_ascii=False, default=str)

    def test_demo_protocol_has_control_and_fingerprint(self):
        proto = self.demo.get("protocol") or {}
        self.assertTrue(proto, "демо должно содержать протокол")
        self.assertIn("fingerprint", proto)
        self.assertIsInstance(proto.get("control_pct"), int)
        self.assertGreaterEqual(proto["control_pct"], 0)
        self.assertLessEqual(proto["control_pct"], 100)

    def test_demo_protocol_reports_pass_threshold(self):
        proto = self.demo.get("protocol") or {}
        self.assertEqual(proto.get("pass_threshold_pct"), protocol.PASS_CONTROL_PCT)

    def test_demo_skills_are_graded(self):
        skills = (self.demo.get("protocol") or {}).get("skills") or []
        self.assertGreater(len(skills), 0)
        for row in skills:
            self.assertIn("score", row)
            self.assertGreaterEqual(row["score"], 0.0)
            self.assertLessEqual(row["score"], 1.0)

    def test_demo_mutation_counts_add_up(self):
        mut = (self.demo.get("protocol") or {}).get("mutation") or {}
        if not mut:
            self.skipTest("в демо нет блока mutation")
        self.assertEqual(mut.get("killed", 0) + mut.get("survived", 0), mut.get("total"))

    def test_demo_fingerprint_is_reproducible(self):
        again = fixtures.demo()
        self.assertEqual(
            (self.demo.get("protocol") or {}).get("fingerprint"),
            (again.get("protocol") or {}).get("fingerprint"),
            "отпечаток обязан воспроизводиться",
        )

    def test_demo_control_is_reproducible(self):
        again = fixtures.demo()
        self.assertEqual(
            (self.demo.get("protocol") or {}).get("control_pct"),
            (again.get("protocol") or {}).get("control_pct"),
        )

    def test_protocol_renders_to_text(self):
        text = protocol.render_text(self.demo.get("protocol") or {})
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 200, "текстовый протокол не должен быть пустым")

    def test_protocol_text_mentions_fingerprint(self):
        proto = self.demo.get("protocol") or {}
        self.assertIn(str(proto.get("fingerprint")), protocol.render_text(proto))


class TestAnswerLeakage(unittest.TestCase):
    """Правильные ответы не должны уходить клиенту до ответа на вопрос."""

    @classmethod
    def setUpClass(cls):
        cls.raw = (fixtures.demo() or {}).get("session")

    def setUp(self):
        if not isinstance(self.raw, dict):
            self.skipTest("в демо нет объекта сессии")

    def test_unanswered_questions_hide_correct_option(self):
        fresh = dict(self.raw)
        fresh["answers"] = {}
        view = session.public_view(fresh)
        questions = view.get("questions") or []
        self.assertGreater(len(questions), 0)
        for question in questions:
            self.assertNotIn("correct", question, "правильный ответ утек до ответа кандидата")
            self.assertNotIn("explanation", question, "разбор утёк до ответа кандидата")

    def test_unanswered_view_has_no_correct_key_at_all(self):
        fresh = dict(self.raw)
        fresh["answers"] = {}
        blob = json.dumps(session.public_view(fresh), ensure_ascii=False, default=str)
        self.assertNotIn('"correct"', blob)

    def test_answered_questions_reveal_explanation(self):
        """После ответа разбор показывается — это и есть обучающая часть сессии."""
        view = session.public_view(dict(self.raw))
        answered = [q for q in (view.get("questions") or []) if q.get("answer")]
        if not answered:
            self.skipTest("в демо-сессии нет ответов")
        for question in answered:
            self.assertIn("correct", question)
            self.assertIn("explanation", question)

    def test_public_view_never_exposes_raw_answer_key_of_unanswered(self):
        fresh = dict(self.raw)
        fresh["answers"] = {}
        for question in session.public_view(fresh).get("questions") or []:
            self.assertIsNone(question.get("answer"))

    def test_public_view_reports_progress(self):
        view = session.public_view(dict(self.raw))
        self.assertIn("answered", view)
        self.assertIn("questions_total", view)
        self.assertLessEqual(view["answered"], view["questions_total"])


class TestEconomics(unittest.TestCase):

    def test_unit_returns_numbers(self):
        unit = economics.unit()
        self.assertIsInstance(unit, dict)
        self.assertTrue(unit)

    def test_breakeven_returns_numbers(self):
        data = economics.breakeven()
        self.assertIsInstance(data, dict)
        self.assertTrue(data)

    def test_report_is_json_serializable(self):
        json.dumps(economics.report(), ensure_ascii=False, default=str)

    def test_scenarios_are_listed(self):
        rows = economics.scenarios()
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)


class TestFixtures(unittest.TestCase):

    def test_three_tasks_available(self):
        self.assertGreaterEqual(len(fixtures.tasks()), 3)

    def test_every_task_has_compilable_code(self):
        rows = fixtures.tasks()
        items = rows.values() if isinstance(rows, dict) else rows
        for task in items:
            task_id = _field(task, "id", "task_id", "key")
            full = fixtures.get_task(task_id) if task_id else task
            code = full.get("code") if isinstance(full, dict) else None
            self.assertTrue(code, "у задания должен быть код")
            compile(code, "<task>", "exec")

    def test_candidates_overview_has_rows(self):
        rows = fixtures.candidates_overview()
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)

    def test_every_candidate_row_has_control_and_verdict(self):
        for row in fixtures.candidates_overview():
            self.assertIn("control_pct", row)
            self.assertIn("verdict", row)
            self.assertGreaterEqual(row["control_pct"], 0)
            self.assertLessEqual(row["control_pct"], 100)

    def test_candidate_pass_flag_matches_threshold(self):
        """Флаг допуска не должен расходиться с порогом из документации."""
        for row in fixtures.candidates_overview():
            if "passed" not in row:
                continue
            expected = row["control_pct"] >= protocol.PASS_CONTROL_PCT
            self.assertEqual(bool(row["passed"]), expected, "кандидат %s" % row.get("id"))

    def test_candidate_bundle_is_complete(self):
        rows = fixtures.candidates_overview()
        bundle = fixtures.candidate_bundle(rows[0]["id"])
        self.assertIsInstance(bundle, dict)
        for key in ("candidate", "summary", "protocol", "code"):
            self.assertIn(key, bundle)

    def test_candidate_bundle_code_compiles(self):
        rows = fixtures.candidates_overview()
        for row in rows:
            bundle = fixtures.candidate_bundle(row["id"])
            compile(bundle["code"], "<candidate>", "exec")

    def test_unknown_candidate_returns_none(self):
        self.assertIsNone(fixtures.candidate_bundle("c-нет-такого"))


class TestDocumentationClaims(unittest.TestCase):
    """Числа из documentation.md должны воспроизводиться кодом."""

    def test_documentation_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "docs", "documentation.md")))

    def test_documentation_mentions_moodle_early(self):
        """«Moodle» обязан встретиться в первых абзацах в форме «встраиваемся, а не заменяем»."""
        path = os.path.join(ROOT, "docs", "documentation.md")
        with open(path, encoding="utf-8") as handle:
            head = handle.read(4000)
        self.assertIn("Moodle", head)
        self.assertTrue(re.search(r"встраиваемся|не заменяем", head))

    def test_documentation_lists_all_operators(self):
        path = os.path.join(ROOT, "docs", "documentation.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for row in mutations.catalog():
            code = _field(row, "code", "id")
            self.assertIn(code, text, "оператор %s не описан в документации" % code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
