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

            # The posted field is hidden — the teacher drives it through the
            # All / Range / Custom picker — so assert it EXISTS, not that it shows.
            field = page.locator('input[name="page_selection"]')
            assert field.count() == 1, f"{label}: expected one page_selection input"
            # Default is every page, so an upload that ignores the control is
            # identical to one from before the control existed.
            expect(field).to_have_value("")

            expect(page.get_by_text("Pages to extract").first,
                   f"{label}: heading").to_be_visible()
            for mode in ("All pages", "Range", "Custom"):
                expect(page.get_by_text(mode, exact=True).first,
                       f"{label}: {mode} option").to_be_visible()
            # And it must say what will happen, not just accept input.
            expect(page.get_by_text("Every page of the PDF will be read.").first
                   ).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_range_mode_builds_the_spec(
        self, page: Page, live_server, school, teacher_user
    ):
        """"Pages 5 to 20" must post as the spec string "5-20"."""
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_text("Range", exact=True).first.click()
        page.fill("#page-selection-from", "5")
        page.fill("#page-selection-to", "20")

        expect(page.locator('input[name="page_selection"]')).to_have_value("5-20")
        expect(page.get_by_text("Only page(s) 5-20 will be read.").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_range_with_no_end_reads_to_the_last_page(
        self, page: Page, live_server, school, teacher_user
    ):
        """Leaving "to" blank is how a teacher skips only a cover sheet."""
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_text("Range", exact=True).first.click()
        page.fill("#page-selection-from", "2")

        expect(page.locator('input[name="page_selection"]')).to_have_value("2-")

    @pytest.mark.django_db(transaction=True)
    def test_custom_mode_passes_the_list_through(
        self, page: Page, live_server, school, teacher_user
    ):
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_text("Custom", exact=True).first.click()
        page.fill("#page-selection-custom", "5, 6, 8, 9-11")

        expect(page.locator('input[name="page_selection"]')
               ).to_have_value("5, 6, 8, 9-11")

    @pytest.mark.django_db(transaction=True)
    def test_switching_back_to_all_clears_the_selection(
        self, page: Page, live_server, school, teacher_user
    ):
        """A teacher who changes their mind must not silently keep excluding pages."""
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_text("Range", exact=True).first.click()
        page.fill("#page-selection-from", "5")
        page.fill("#page-selection-to", "20")
        expect(page.locator('input[name="page_selection"]')).to_have_value("5-20")

        page.get_by_text("All pages", exact=True).first.click()
        expect(page.locator('input[name="page_selection"]')).to_have_value("")

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
        page.get_by_text("Custom", exact=True).first.click()
        page.fill("#page-selection-custom", "9-12")
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

        expect(page.get_by_text("Pages to extract").first).to_be_visible()
        for mode in ("All pages", "Range", "Custom"):
            expect(page.get_by_text(mode, exact=True).first).to_be_visible()


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
