"""
Playwright UI tests — the shared coding window on the worksheet session page.

The session used to build its own CodeMirror and stack the output panel UNDER
the editor, so a coding question looked different here than in the compilers,
the homework page or the builder's preview. It renders
coding/partials/_code_window.html now, like everything else.

The submit path is the risk worth guarding: this form posts over htmx, which
serialises the form itself rather than firing a native submit. CodeMirror only
writes its text back to the textarea on a native submit, so without an explicit
flush the answer would post as whatever the textarea held at page load — with
no error anywhere.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def coding_worksheet_assignment(db, school, teacher_user, classroom, coding_topic_level):
    """A one-question coding worksheet, assigned to the student's class."""
    from coding.models import CodingExercise
    from worksheets.models import Worksheet, WorksheetAssignment, WorksheetQuestion

    exercise = CodingExercise.objects.create(
        topic_level=coding_topic_level,
        title="Print a greeting",
        description="Print the word hello.",
        starter_code='# Write your solution here\n',
        expected_output="hello",
        question_type=CodingExercise.WRITE_CODE,
        is_active=True,
    )
    worksheet = Worksheet.objects.create(
        school=school,
        name="Coding Worksheet",
        original_filename="",
        created_by=teacher_user,
        question_count=1,
    )
    WorksheetQuestion.objects.create(
        worksheet=worksheet,
        coding_exercise=exercise,
        order=1,
        subject_slug="coding",
        content_id=exercise.pk,
    )
    assignment = WorksheetAssignment.objects.create(
        worksheet=worksheet, classroom=classroom, is_active=True,
    )
    return assignment, exercise


class TestWorksheetSessionCodingWindow:

    @pytest.mark.django_db(transaction=True)
    def test_session_renders_the_shared_window_side_by_side(
        self, page: Page, live_server, enrolled_student, coding_worksheet_assignment,
    ):
        assignment, exercise = coding_worksheet_assignment
        page.set_viewport_size({"width": 1440, "height": 1000})
        do_login(page, live_server.url, enrolled_student)

        page.goto(f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/")
        page.wait_for_load_state("networkidle")

        window = page.locator("[data-code-window]").first
        expect(window).to_be_visible()
        expect(window.locator(".CodeMirror")).to_contain_text("Write your solution")
        expect(window.locator(".cw-stdout")).to_be_visible()

        editor_box = window.locator(".cw-chrome").bounding_box()
        console_box = window.locator(".cw-output-wrap").bounding_box()
        assert editor_box and console_box
        assert console_box["x"] > editor_box["x"] + editor_box["width"] - 10, (
            "console should sit beside the editor, not under it"
        )

    @pytest.mark.django_db(transaction=True)
    def test_expected_output_is_shown_once(
        self, page: Page, live_server, enrolled_student, coding_worksheet_assignment,
    ):
        """The window prints it beside the console; the page must not repeat it."""
        assignment, exercise = coding_worksheet_assignment
        do_login(page, live_server.url, enrolled_student)

        page.goto(f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("Expected output", exact=False)).to_have_count(1)

    @pytest.mark.django_db(transaction=True)
    def test_typed_code_is_posted_by_the_htmx_submit(
        self, page: Page, live_server, enrolled_student, coding_worksheet_assignment,
    ):
        """htmx serialises the form without a native submit — see module docstring."""
        from worksheets.models import WorksheetStudentAnswer

        assignment, exercise = coding_worksheet_assignment
        do_login(page, live_server.url, enrolled_student)

        page.goto(f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/")
        page.wait_for_load_state("networkidle")

        editor = page.locator("[data-code-window] .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.type('print("hello")')

        with page.expect_response(lambda r: "/answer/" in r.url and r.status == 200):
            page.locator("form[hx-post] button[type='submit']").click()

        answer = WorksheetStudentAnswer.objects.filter(
            subject_slug="coding", content_id=exercise.pk,
        ).first()
        assert answer is not None, "no answer row was created"
        stored = (answer.answer_data or {}).get("code", "")
        assert 'print("hello")' in stored, (
            f"typed code did not reach the server: {stored!r}"
        )
