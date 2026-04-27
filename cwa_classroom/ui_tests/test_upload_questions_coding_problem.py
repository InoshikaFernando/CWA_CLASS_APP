"""
Playwright UI tests for the /upload-questions/ page — Coding Problems.

Covers ``CodingProblemParser`` (classroom/upload_services.py):

  - Switching to 'coding_problem' shows purple context note
  - Valid upload creates CodingProblem + ProblemTestCase rows
  - Re-upload updates problem and REPLACES test cases (not duplicates)
  - Missing language → error
  - Missing description → per-problem error
  - Invalid category → per-problem error with valid-options hint
  - Empty problems array → error
  - forbidden_code_patterns list is persisted
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _write_json(tmp_path: Path, payload: dict, name: str = "problems.json") -> Path:
    fp = tmp_path / name
    fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fp


def _goto_upload(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/upload-questions/")
    page.wait_for_load_state("networkidle")


def _submit(page: Page, upload_path: Path) -> None:
    page.locator("select[name='subject']").select_option("coding_problem")
    page.locator("input[name='upload_file']").set_input_files(str(upload_path))
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Upload", re.I)).click()
    page.wait_for_load_state("networkidle")


def _valid_problem_payload(
    title: str = "Reverse a String",
    language: str = "python",
    category: str = "algorithm",
    test_cases: list | None = None,
) -> dict:
    return {
        "subject": "coding_problem",
        "language": language,
        "problems": [
            {
                "title": title,
                "difficulty": 1,
                "category": category,
                "description": "Read a line and print it reversed.",
                "starter_code": "s = input()\n# reverse it\n",
                "constraints": "",
                "time_limit_seconds": 5,
                "memory_limit_mb": 256,
                "forbidden_code_patterns": [],
                "test_cases": test_cases if test_cases is not None else [
                    {"input": "hello", "expected": "olleh",
                     "visible": True, "boundary": False, "description": "Basic"},
                    {"input": "a", "expected": "a",
                     "visible": False, "boundary": True, "description": "Single char"},
                ],
            },
        ],
    }


class TestUploadQuestionsCodingProblem:

    @pytest.mark.django_db(transaction=True)
    def test_switching_to_coding_problem_shows_context_note(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)
        page.locator("select[name='subject']").select_option("coding_problem")
        expect(
            page.get_by_text(re.compile(r"algorithm challenges", re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_valid_upload_creates_problem_and_test_cases(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        from coding.models import CodingProblem, ProblemTestCase

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(tmp_path, _valid_problem_payload())
        _submit(page, fp)

        prob = CodingProblem.objects.filter(title="Reverse a String").first()
        assert prob is not None
        assert ProblemTestCase.objects.filter(problem=prob).count() == 2

    @pytest.mark.django_db(transaction=True)
    def test_reupload_replaces_test_cases(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        from coding.models import CodingProblem, ProblemTestCase

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp1 = _write_json(tmp_path, _valid_problem_payload(), name="v1.json")
        _submit(page, fp1)
        prob = CodingProblem.objects.get(title="Reverse a String")
        assert ProblemTestCase.objects.filter(problem=prob).count() == 2

        # Re-upload with 3 test cases (including one brand new)
        new_cases = [
            {"input": "abc", "expected": "cba", "visible": True, "boundary": False, "description": "New"},
            {"input": "", "expected": "", "visible": False, "boundary": True, "description": "Empty"},
            {"input": "x", "expected": "x", "visible": False, "boundary": True, "description": "One"},
        ]
        fp2 = _write_json(
            tmp_path, _valid_problem_payload(test_cases=new_cases), name="v2.json"
        )
        _goto_upload(page, live_server.url)
        _submit(page, fp2)

        prob.refresh_from_db()
        # Exactly the new 3 — old 2 replaced
        cases = list(ProblemTestCase.objects.filter(problem=prob).values_list("input_data", flat=True))
        assert sorted(cases) == sorted(["abc", "", "x"])

    @pytest.mark.django_db(transaction=True)
    def test_missing_language_reports_error(
        self, page: Page, live_server, teacher_user, classroom, tmp_path
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        bad = _valid_problem_payload()
        bad.pop("language")
        fp = _write_json(tmp_path, bad, name="nolang.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'Missing "language"', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_missing_description_reports_per_problem_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_problem_payload()
        payload["problems"][0]["description"] = ""
        fp = _write_json(tmp_path, payload, name="nodesc.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'missing "description"', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_invalid_category_reports_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(
            tmp_path, _valid_problem_payload(category="not_a_category"), name="bad_cat.json"
        )
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'invalid category "not_a_category"', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_empty_problems_array_reports_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_problem_payload()
        payload["problems"] = []
        fp = _write_json(tmp_path, payload, name="empty.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'"problems" array is empty', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_forbidden_code_patterns_persisted(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        from coding.models import CodingProblem

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_problem_payload(title="No sort allowed")
        payload["problems"][0]["forbidden_code_patterns"] = ["sorted(", ".sort("]
        fp = _write_json(tmp_path, payload, name="forbid.json")
        _submit(page, fp)

        prob = CodingProblem.objects.get(title="No sort allowed")
        assert prob.forbidden_code_patterns == ["sorted(", ".sort("]
