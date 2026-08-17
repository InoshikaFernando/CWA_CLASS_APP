"""Playwright UI tests — "Pages to extract" on the PDF upload screens.

Covers the two things a teacher actually experiences: the field is there and
explains itself on every PDF upload form, a mistyped range comes back as an
error on the same screen (rather than a background job that dies minutes later),
and a partial extraction says on the preview which pages were left out.

No AI call or worker is involved — the upload POST is checked for its validation
behaviour, and the preview is driven from a session created directly.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _pdf_bytes(page_count: int) -> bytes:
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f"Question on page {index + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _upload_paths() -> list[tuple[str, str]]:
    """(label, path) for every PDF upload screen that offers page selection."""
    return [
        ("worksheets", "/worksheets/upload/"),
        ("homework", "/homework/pdf/upload/"),
    ]


class TestPageSelectionField:

    @pytest.mark.django_db(transaction=True)
    def test_every_pdf_upload_form_offers_the_field(
        self, page: Page, live_server, school, teacher_user
    ):
        do_login(page, str(live_server), teacher_user)

        for label, path in _upload_paths():
            page.goto(f"{live_server}{path}")
            page.wait_for_load_state("domcontentloaded")

            field = page.locator('input[name="page_selection"]')
            expect(field, f"{label}: page_selection input").to_be_visible()
            # It must be optional — an upload that ignores it still works.
            expect(field).not_to_have_attribute("required", "")
            expect(page.get_by_text("Pages to extract").first).to_be_visible()
            # And it must explain the syntax, not just accept it.
            expect(page.get_by_text("print dialog").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_field_accepts_a_typed_range(
        self, page: Page, live_server, school, teacher_user
    ):
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        field = page.locator('input[name="page_selection"]')
        field.fill("2-7, 9")
        expect(field).to_have_value("2-7, 9")

    @pytest.mark.django_db(transaction=True)
    def test_a_range_past_the_end_is_refused_on_the_upload_screen(
        self, page: Page, live_server, school, teacher_user
    ):
        """The teacher sees the mistake immediately, not as a failed job later."""
        from worksheets.models import WorksheetUploadSession

        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        page.set_input_files(
            'input[name="pdf_file"]',
            files=[{
                "name": "paper.pdf",
                "mimeType": "application/pdf",
                "buffer": _pdf_bytes(4),
            }],
        )
        page.fill('input[name="page_selection"]', "9-12")
        page.click("#upload-btn")

        # Bounced back with the reason (shown both as a toast and inline), and
        # nothing was enqueued.
        page.wait_for_url("**/worksheets/upload/", timeout=15_000)
        expect(page.get_by_text("only has 4 pages").first).to_be_visible()
        assert not WorksheetUploadSession.objects.exists()

    @pytest.mark.django_db(transaction=True)
    def test_field_renders_on_mobile(
        self, page: Page, live_server, school, teacher_user
    ):
        do_login(page, str(live_server), teacher_user)
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator('input[name="page_selection"]')).to_be_visible()


class TestPageSelectionPreviewNotice:

    @pytest.mark.django_db(transaction=True)
    def test_preview_states_which_pages_were_left_out(
        self, page: Page, live_server, school, teacher_user, level, topic
    ):
        from worksheets.models import WorksheetUploadSession
        from worksheets.page_selection import selection_summary

        session = WorksheetUploadSession.objects.create(
            user=teacher_user,
            school=school,
            pdf_filename="paper.pdf",
            worksheet_name="paper",
            page_selection="2-4",
            page_count=3,
            status=WorksheetUploadSession.STATUS_READY,
            extracted_data={
                "year_level": level.level_number,
                "subject": "Mathematics",
                "questions": [{
                    "include": True,
                    "question_text": "What is 2 + 2?",
                    "question_type": "short_answer",
                    "difficulty": 1,
                    "points": 1,
                    "year_level": level.level_number,
                    "topic": "",
                    "subject": "Mathematics",
                    "answers": [],
                }],
                "page_selection": selection_summary("2-4", [2, 3, 4], 6),
            },
        )
        do_login(page, str(live_server), teacher_user)

        page.goto(f"{live_server}/worksheets/upload/{session.pk}/preview/")
        page.wait_for_load_state("domcontentloaded")

        notice = page.get_by_text("Extracted page", exact=False).first
        expect(notice).to_be_visible()
        # Both halves must be named: what was read, and what wasn't.
        expect(page.get_by_text("1, 5, 6", exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_no_notice_when_the_whole_pdf_was_extracted(
        self, page: Page, live_server, school, teacher_user, level, topic
    ):
        from worksheets.models import WorksheetUploadSession
        from worksheets.page_selection import selection_summary

        session = WorksheetUploadSession.objects.create(
            user=teacher_user,
            school=school,
            pdf_filename="paper.pdf",
            worksheet_name="paper",
            page_count=2,
            status=WorksheetUploadSession.STATUS_READY,
            extracted_data={
                "year_level": level.level_number,
                "subject": "Mathematics",
                "questions": [{
                    "include": True,
                    "question_text": "What is 2 + 2?",
                    "question_type": "short_answer",
                    "difficulty": 1,
                    "points": 1,
                    "year_level": level.level_number,
                    "topic": "",
                    "subject": "Mathematics",
                    "answers": [],
                }],
                "page_selection": selection_summary("", [1, 2], 2),
            },
        )
        do_login(page, str(live_server), teacher_user)

        page.goto(f"{live_server}/worksheets/upload/{session.pk}/preview/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("Extracted page", exact=False)).to_have_count(0)
