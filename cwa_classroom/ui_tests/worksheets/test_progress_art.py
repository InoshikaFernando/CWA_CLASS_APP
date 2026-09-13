"""Playwright UI test — the progress-art picture across a worksheet session.

A worksheet is answered one question per page, and the session view already
resumes at the first unanswered question. So the interesting claim here is the
one a student would actually notice: the drawing carries over from one page to
the next, and from one sitting to the next, without ever restarting.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


_VISIBLE_STROKES = """
() => Array.from(document.querySelectorAll('[data-progress-art] path.pa-stroke'))
        .filter(p => p.style.visibility !== 'hidden').length
"""

_PICTURE_KEY = """
() => JSON.parse(document.querySelector(
    '[data-progress-art] script[type="application/json"]').textContent).key
"""


@pytest.fixture
def art_assignment(db, school, teacher_user, classroom, level, topic):
    """A three-question multiple-choice worksheet assigned to the class."""
    from maths.models import Answer, Question
    from worksheets.models import Worksheet, WorksheetAssignment, WorksheetQuestion

    worksheet = Worksheet.objects.create(
        school=school,
        name="Progress Art Worksheet",
        original_filename="art.pdf",
        created_by=teacher_user,
        level=level,
    )
    questions = []
    for i in range(3):
        q = Question.objects.create(
            level=level, topic=topic,
            question_text=f"What is {i} + 10?",
            question_type="multiple_choice",
            difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text=str(i + 10), is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text=str(i + 20), is_correct=False, order=2)
        WorksheetQuestion.objects.create(
            worksheet=worksheet, question=q, order=i + 1,
            subject_slug="mathematics", content_id=q.id,
        )
        questions.append(q)
    worksheet.refresh_question_count()

    assignment = WorksheetAssignment.objects.create(
        worksheet=worksheet, classroom=classroom, is_active=True,
    )
    return assignment, questions


def _answer_current_question(page, question):
    """Pick the correct option and submit it through the HTMX form."""
    correct = question.answers.get(is_correct=True)
    page.locator(f"input[type='radio'][value='{correct.pk}']").check()
    with page.expect_response(lambda r: "/answer/" in r.url and r.status == 200):
        page.locator("form[hx-post] button[type='submit']").click()


class TestWorksheetProgressArt:

    @pytest.mark.django_db(transaction=True)
    def test_the_drawing_carries_across_questions_and_sittings(
        self, page: Page, live_server, enrolled_student, art_assignment
    ):
        from worksheets.models import WorksheetSubmission

        assignment, questions = art_assignment
        session_url = (
            f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/"
        )

        do_login(page, live_server.url, enrolled_student)
        page.goto(session_url)
        page.wait_for_load_state("networkidle")

        panel = page.locator("[data-progress-art]")
        expect(panel).to_be_visible()
        expect(panel.locator("[data-pa-count]")).to_have_text("0 of 3")
        assert page.evaluate(_VISIBLE_STROKES) == 1     # the opening dot only
        first_key = page.evaluate(_PICTURE_KEY)

        # The choice is pinned on the submission the session view just created,
        # which is what lets it survive a gap of days.
        submission = WorksheetSubmission.objects.get(
            assignment=assignment, student=enrolled_student)
        assert submission.art_picture_key == first_key

        _answer_current_question(page, questions[0])

        # Next question — a full page load, the drawing must carry over.
        page.goto(session_url)
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-progress-art] [data-pa-count]")).to_have_text("1 of 3")
        assert page.evaluate(_VISIBLE_STROKES) > 1
        assert page.evaluate(_PICTURE_KEY) == first_key

        _answer_current_question(page, questions[1])

        # Come back "the next day" — a fresh page, same picture, same progress.
        page.goto(session_url)
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-progress-art] [data-pa-count]")).to_have_text("2 of 3")
        assert page.evaluate(_PICTURE_KEY) == first_key

    @pytest.mark.django_db(transaction=True)
    def test_the_worksheets_year_level_bands_the_picture(
        self, page: Page, live_server, enrolled_student, art_assignment, level
    ):
        """The `level` fixture is a senior year, so a junior-only subject (a
        balloon, a kite) must never be what a student of that year is given."""
        from classroom import progress_art

        assignment, _ = art_assignment
        assert level.level_number >= 5, "fixture assumption"

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/")
        page.wait_for_load_state("networkidle")

        picture = progress_art.get(page.evaluate(_PICTURE_KEY))
        assert picture is not None
        assert picture.band != progress_art.BAND_JUNIOR
