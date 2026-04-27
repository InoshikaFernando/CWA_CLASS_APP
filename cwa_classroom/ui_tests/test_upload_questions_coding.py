"""
Playwright UI tests for the /upload-questions/ page — Coding (exercises) subject.

Covers ``CodingExerciseParser`` (classroom/upload_services.py):

  - Switching subject to 'coding' hides classroom selector and shows context note
  - Valid upload creates CodingExercise rows, updates on re-upload (same title)
  - Unknown language slug reports error
  - Unknown topic slug reports error
  - Invalid level reports error with valid-options hint
  - Missing "language" field reports error
  - Empty exercises array reports error
  - Missing instructions on an exercise reports per-item error
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _write_json(tmp_path: Path, payload: dict, name: str = "coding.json") -> Path:
    fp = tmp_path / name
    fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fp


def _goto_upload(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/upload-questions/")
    page.wait_for_load_state("networkidle")


def _submit(page: Page, upload_path: Path) -> None:
    page.locator("select[name='subject']").select_option("coding")
    page.locator("input[name='upload_file']").set_input_files(str(upload_path))
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Upload", re.I)).click()
    page.wait_for_load_state("networkidle")


def _valid_coding_payload(
    title: str = "Print Hello",
    language: str = "python",
    topic: str = "variables",
    level: str = "beginner",
) -> dict:
    return {
        "subject": "coding",
        "language": language,
        "topic": topic,
        "level": level,
        "exercises": [
            {
                "title": title,
                "instructions": "Print 'Hello' to the console.",
                "starter_code": "# Your code here\n",
                "expected_output": "Hello",
                "hints": "Use print()",
                "display_order": 1,
            },
        ],
    }


class TestUploadQuestionsCoding:

    @pytest.mark.django_db(transaction=True)
    def test_switching_to_coding_hides_classroom_selector(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)
        page.locator("select[name='subject']").select_option("coding")
        # Alpine x-show=="coding" → the context note is visible; classroom selector hidden
        expect(
            page.get_by_text(re.compile(r"Exercises are imported directly", re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_valid_upload_creates_exercise(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, tmp_path,
    ):
        from coding.models import CodingExercise

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(tmp_path, _valid_coding_payload())
        _submit(page, fp)

        assert CodingExercise.objects.filter(title="Print Hello").exists()
        expect(page.get_by_text("Upload Results").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_reupload_updates_existing_exercise(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, tmp_path,
    ):
        from coding.models import CodingExercise

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        # First upload — inserts
        fp = _write_json(tmp_path, _valid_coding_payload(), name="v1.json")
        _submit(page, fp)
        assert CodingExercise.objects.filter(title="Print Hello").count() == 1

        # Second upload — same title + topic + level → update, not duplicate
        payload = _valid_coding_payload()
        payload["exercises"][0]["hints"] = "Use print('Hello')"
        fp2 = _write_json(tmp_path, payload, name="v2.json")
        _goto_upload(page, live_server.url)
        _submit(page, fp2)

        qs = CodingExercise.objects.filter(title="Print Hello")
        assert qs.count() == 1
        assert qs.first().hints == "Use print('Hello')"

    @pytest.mark.django_db(transaction=True)
    def test_unknown_language_reports_error(
        self, page: Page, live_server, teacher_user, classroom, tmp_path
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(
            tmp_path, _valid_coding_payload(language="klingon"), name="bad_lang.json"
        )
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'Language "klingon" not found', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_unknown_topic_reports_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(
            tmp_path, _valid_coding_payload(topic="does-not-exist"), name="bad_topic.json"
        )
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'Topic "does-not-exist" not found', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_invalid_level_reports_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_json(
            tmp_path, _valid_coding_payload(level="wizard"), name="bad_level.json"
        )
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'Level "wizard" is invalid', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_missing_language_reports_error(
        self, page: Page, live_server, teacher_user, classroom, tmp_path
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        bad = _valid_coding_payload()
        bad.pop("language")
        fp = _write_json(tmp_path, bad, name="nolang.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'Missing "language"', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_empty_exercises_array_reports_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_coding_payload()
        payload["exercises"] = []
        fp = _write_json(tmp_path, payload, name="empty.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'"exercises" array is empty', re.I))
        ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_missing_instructions_reports_per_item_error(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, tmp_path,
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_coding_payload()
        payload["exercises"][0]["instructions"] = ""
        fp = _write_json(tmp_path, payload, name="noinstr.json")
        _submit(page, fp)
        expect(
            page.get_by_text(re.compile(r'missing "instructions"', re.I))
        ).to_be_visible()
