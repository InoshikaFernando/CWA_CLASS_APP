"""Playwright UI tests — CPP-327 async worksheet PDF upload UX.

Exercises the processing page + HTMX polling without a real worker or AI call:
the session is created directly and its status flipped to simulate the worker
finishing (or failing). Verifies the spinner, the auto-advance to preview, and
the failure/retry state — desktop and mobile.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _make_session(teacher_user, school, status, **extra):
    from worksheets.models import WorksheetUploadSession

    return WorksheetUploadSession.objects.create(
        user=teacher_user,
        school=school,
        pdf_filename="ws.pdf",
        worksheet_name="ws",
        status=status,
        **extra,
    )


def _ready_data(level):
    return {
        "year_level": level.level_number,
        "subject": "Mathematics",
        "questions": [
            {
                "include": True,
                "question_text": "What is 2 + 2?",
                "question_type": "short_answer",
                "difficulty": 1,
                "points": 1,
                "year_level": level.level_number,
                "topic": "",
                "subject": "Mathematics",
                "answers": [],
            }
        ],
    }


class TestWorksheetAsyncUploadUX:

    @pytest.mark.django_db(transaction=True)
    def test_processing_page_advances_to_preview_when_ready(
        self, page: Page, live_server, school, teacher_user, level, topic
    ):
        from worksheets.models import WorksheetUploadSession

        session = _make_session(teacher_user, school, WorksheetUploadSession.STATUS_PROCESSING)
        do_login(page, str(live_server), teacher_user)

        page.goto(f"{live_server}/worksheets/upload/{session.pk}/processing/")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_text("Extracting questions")).to_be_visible()

        # Simulate the background worker finishing.
        WorksheetUploadSession.objects.filter(pk=session.pk).update(
            status=WorksheetUploadSession.STATUS_READY,
            extracted_data=_ready_data(level),
        )

        # The page polls every 3s; the status partial sends an HX-Redirect to preview.
        page.wait_for_url(
            re.compile(rf"/worksheets/upload/{session.pk}/preview/"), timeout=15_000
        )

    @pytest.mark.django_db(transaction=True)
    def test_processing_page_shows_failure_with_retry(
        self, page: Page, live_server, school, teacher_user
    ):
        from worksheets.models import WorksheetUploadSession

        session = _make_session(
            teacher_user, school, WorksheetUploadSession.STATUS_FAILED,
            error_message="Could not read PDF",
        )
        do_login(page, str(live_server), teacher_user)

        page.goto(f"{live_server}/worksheets/upload/{session.pk}/processing/")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_text("Processing failed")).to_be_visible()
        expect(page.get_by_role("link", name="Try again")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_processing_page_renders_on_mobile(
        self, page: Page, live_server, school, teacher_user
    ):
        from worksheets.models import WorksheetUploadSession

        session = _make_session(teacher_user, school, WorksheetUploadSession.STATUS_PROCESSING)
        do_login(page, str(live_server), teacher_user)
        page.set_viewport_size({"width": 375, "height": 667})

        page.goto(f"{live_server}/worksheets/upload/{session.pk}/processing/")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_text("Extracting questions")).to_be_visible()
