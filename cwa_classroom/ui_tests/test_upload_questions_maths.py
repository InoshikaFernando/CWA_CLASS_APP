"""
Playwright UI tests for the /upload-questions/ page — Mathematics subject.

Covers the Mathematics branch of ``UploadQuestionsView`` and
``MathsQuestionParser`` (classroom/upload_services.py):

  - Page renders with Mathematics preselected
  - JSON upload success (questions inserted + answers created)
  - JSON upload updates an existing question (same text + topic + level)
  - ZIP upload with an image saves both questions and image bytes
  - Missing "topic" field reports a validation error
  - Invalid question_type reports a per-question error
  - Teachers must pick a classroom; submitting without one re-renders with error
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp_json(tmp_path: Path, payload: dict, name: str = "questions.json") -> Path:
    """Dump payload as pretty-printed JSON and return the written path."""
    fp = tmp_path / name
    fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fp


def _write_temp_zip(
    tmp_path: Path, payload: dict, images: dict[str, bytes], name: str = "bundle.zip"
) -> Path:
    """Write a ZIP with questions.json plus in-memory image bytes."""
    fp = tmp_path / name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("questions.json", json.dumps(payload))
        for img_name, data in images.items():
            zf.writestr(img_name, data)
    fp.write_bytes(buf.getvalue())
    return fp


def _goto_upload(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/upload-questions/")
    page.wait_for_load_state("networkidle")


def _submit(page: Page, subject: str, upload_path: Path, classroom_id: int | None = None) -> None:
    """Fill the upload form and submit — waits for the results panel."""
    page.locator("select[name='subject']").select_option(subject)
    if classroom_id is not None:
        page.locator("select[name='classroom']").select_option(str(classroom_id))
    page.locator("input[name='upload_file']").set_input_files(str(upload_path))
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Upload", re.I)).click()
    page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

def _valid_maths_payload(topic_name: str = "Fractions UI") -> dict:
    return {
        "strand": "Number",
        "topic": topic_name,
        "year_level": 7,
        "questions": [
            {
                "question_text": "What is 1/2 + 1/4?",
                "question_type": "multiple_choice",
                "difficulty": 1,
                "points": 1,
                "explanation": "Find a common denominator.",
                "answers": [
                    {"text": "3/4", "is_correct": True},
                    {"text": "1/2", "is_correct": False},
                    {"text": "2/6", "is_correct": False},
                    {"text": "1/4", "is_correct": False},
                ],
            },
            {
                "question_text": "What is 2/5 + 1/5?",
                "question_type": "multiple_choice",
                "difficulty": 1,
                "points": 1,
                "answers": [
                    {"text": "3/5", "is_correct": True},
                    {"text": "2/10", "is_correct": False},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUploadQuestionsMaths:

    @pytest.mark.django_db(transaction=True)
    def test_page_renders_with_mathematics_preselected(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)
        expect(page.get_by_role("heading", name="Upload Questions")).to_be_visible()
        selected = page.locator("select[name='subject']").input_value()
        assert selected == "mathematics"

    @pytest.mark.django_db(transaction=True)
    def test_json_upload_inserts_questions_and_answers(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path
    ):
        from maths.models import Question

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_temp_json(tmp_path, _valid_maths_payload())
        _submit(page, "mathematics", fp, classroom_id=classroom.pk)

        # UI shows the success banner with inserted count
        expect(page.get_by_text("Upload Results").first).to_be_visible()
        # Check persisted rows
        qs = Question.objects.filter(classroom=classroom)
        assert qs.count() == 2
        for q in qs:
            assert q.answers.count() >= 2

    @pytest.mark.django_db(transaction=True)
    def test_reupload_updates_existing_question(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path
    ):
        from maths.models import Answer, Question

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_maths_payload()
        fp = _write_temp_json(tmp_path, payload, name="v1.json")
        _submit(page, "mathematics", fp, classroom_id=classroom.pk)
        first_count = Question.objects.filter(classroom=classroom).count()
        assert first_count == 2

        # Same content (same text + topic + level) → updated, not duplicated
        fp2 = _write_temp_json(tmp_path, payload, name="v2.json")
        _goto_upload(page, live_server.url)
        _submit(page, "mathematics", fp2, classroom_id=classroom.pk)
        assert Question.objects.filter(classroom=classroom).count() == first_count
        # Answers were wiped and recreated → order is stable; count unchanged
        q = Question.objects.filter(classroom=classroom, question_text__startswith="What is 1/2").first()
        assert q is not None
        assert Answer.objects.filter(question=q).count() == 4

    @pytest.mark.django_db(transaction=True)
    def test_zip_upload_saves_image(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path, settings
    ):
        from maths.models import Question

        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        # 1×1 transparent PNG
        png_bytes = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
            "890000000D49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
        )
        payload = _valid_maths_payload()
        payload["questions"][0]["image"] = "chart.png"
        fp = _write_temp_zip(tmp_path, payload, {"chart.png": png_bytes})
        _submit(page, "mathematics", fp, classroom_id=classroom.pk)

        q = Question.objects.filter(classroom=classroom, image__icontains="chart.png").first()
        assert q is not None, "Question with image field should exist"
        assert "questions/year7/" in q.image.name

    @pytest.mark.django_db(transaction=True)
    def test_missing_topic_field_reports_error(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        bad = _valid_maths_payload()
        bad.pop("topic")
        fp = _write_temp_json(tmp_path, bad, name="bad.json")
        _submit(page, "mathematics", fp, classroom_id=classroom.pk)

        expect(page.get_by_text(re.compile(r'Missing "topic"', re.I))).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_invalid_question_type_reports_per_question_error(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path
    ):
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        payload = _valid_maths_payload()
        payload["questions"][0]["question_type"] = "totally_fake_type"
        fp = _write_temp_json(tmp_path, payload, name="bad_type.json")
        _submit(page, "mathematics", fp, classroom_id=classroom.pk)

        expect(page.get_by_text(re.compile(r'unknown question_type', re.I))).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_teacher_must_select_classroom(
        self, page: Page, live_server, teacher_user, classroom, level, tmp_path
    ):
        """Regular teachers get an error if they submit without picking a classroom."""
        do_login(page, live_server.url, teacher_user)
        _goto_upload(page, live_server.url)

        fp = _write_temp_json(tmp_path, _valid_maths_payload())
        page.locator("select[name='subject']").select_option("mathematics")
        page.locator("input[name='upload_file']").set_input_files(str(fp))
        # Browsers won't submit while a required <select> is unfilled, so drop the
        # `required` attribute and click submit. The server redirects back with a
        # messages.error toast; toast auto-dismisses after 4s, so assert on the
        # rendered HTML rather than racing with visibility.
        page.evaluate(
            "document.querySelector(\"select[name='classroom']\").removeAttribute('required')"
        )
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Upload", re.I)).click()
        page.wait_for_load_state("domcontentloaded")
        assert "Please select a valid classroom" in page.content()
