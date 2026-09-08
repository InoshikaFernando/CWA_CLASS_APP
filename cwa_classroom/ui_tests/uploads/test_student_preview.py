"""Playwright UI tests — "Preview as student" on the PDF review page (CPP-389).

The review page is an editing form, so a teacher could not find out what a
question would look like to a child, or whether the marker would accept a
sensible answer, without importing it and assigning it to a class. Parabola and
measurement questions went unuploaded for exactly that reason.

These drive the real page: open the preview, answer it the way a student would,
watch the real marker mark it, and confirm that looking at a question changed
neither the review form nor the question bank.

No AI call or worker is involved — the session is created directly.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login

_TABLE_SPEC = {
    "headers": ["Money value", "Decimal form"],
    "rows": [[{"given": "56c"}, {"answer": "0.56"}]],
    "tolerance": 0,
}


def _session(user, school, question):
    from homework.models import HomeworkUploadSession

    return HomeworkUploadSession.objects.create(
        user=user, school=school, pdf_filename="money.pdf",
        homework_title="Money values",
        status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
        extracted_data={
            "year_level": 4, "subject": "Mathematics", "topic": "Decimals",
            "questions": [question],
        },
        extracted_images={},
    )


def _short_answer_question():
    return {
        "question_text": "20c is how many hundredths of a dollar?",
        "question_type": "short_answer",
        "validation_type": "auto", "difficulty": 1, "points": 1,
        "explanation": "20 out of the 100 cents in a dollar.",
        "answers": [{"text": "twenty hundredths", "is_correct": True}],
        "include": True,
    }


def _open_preview(page, live_server, session):
    do_login(page, str(live_server), session.user)
    page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
    page.wait_for_load_state("domcontentloaded")
    page.locator('[data-preview-open="0"]').click()
    expect(page.locator("[data-preview-stage]")).to_be_visible(timeout=15_000)


class TestPreviewAsStudent:

    @pytest.mark.django_db(transaction=True)
    def test_the_question_and_how_it_marks_are_both_shown(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school, _short_answer_question())
        _open_preview(page, live_server, session)

        expect(page.locator("[data-preview-stage]")
               .get_by_text("20c is how many hundredths")).to_be_visible()
        # The one thing the review form could never say: what will be accepted.
        expect(page.get_by_text("Only one wording is accepted")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_a_trial_answer_is_marked_by_the_marker_the_student_gets(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school, _short_answer_question())
        _open_preview(page, live_server, session)

        stage = page.locator("[data-preview-stage]")
        stage.locator('[name^="answer_"]').fill("0.20")
        page.locator("[data-preview-check]").click()
        expect(page.locator('[data-preview-result="wrong"]')).to_be_visible(timeout=15_000)

        # ...and the wording the answer key does accept passes.
        page.locator("[data-preview-stage]").locator(
            '[name^="answer_"]').fill("Twenty Hundredths")
        page.locator("[data-preview-check]").click()
        expect(page.locator('[data-preview-result="correct"]')).to_be_visible(timeout=15_000)

    @pytest.mark.django_db(transaction=True)
    def test_the_preview_follows_edits_that_have_not_been_saved(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _session(teacher_user, school, _short_answer_question())
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.locator('textarea[name="q_0_text"]').fill("How many hundredths is 20c?")
        page.locator('input[name="q_0_answer_0_text"]').fill("0.20")
        page.locator('[data-preview-open="0"]').click()

        expect(page.locator("[data-preview-stage]")
               .get_by_text("How many hundredths is 20c?")).to_be_visible(timeout=15_000)
        page.locator("[data-preview-stage]").locator('[name^="answer_"]').fill("0.20")
        page.locator("[data-preview-check]").click()
        expect(page.locator('[data-preview-result="correct"]')).to_be_visible(timeout=15_000)

    @pytest.mark.django_db(transaction=True)
    def test_previewing_changes_neither_the_form_nor_the_question_bank(
        self, page: Page, live_server, school, teacher_user
    ):
        from homework.models import HomeworkUploadSession
        from maths.models import Question

        session = _session(teacher_user, school, _short_answer_question())
        before = Question.objects.count()
        _open_preview(page, live_server, session)

        page.locator("[data-preview-stage]").locator(
            '[name^="answer_"]').fill("twenty hundredths")
        page.locator("[data-preview-check]").click()
        expect(page.locator('[data-preview-result="correct"]')).to_be_visible(timeout=15_000)

        page.get_by_role("button", name="Close preview").click()
        expect(page.locator("[data-preview-stage]")).to_be_hidden()

        expect(page.locator('textarea[name="q_0_text"]')).to_have_value(
            "20c is how many hundredths of a dollar?")
        assert Question.objects.count() == before
        stored = HomeworkUploadSession.objects.get(pk=session.pk).extracted_data
        assert stored["questions"][0]["question_text"] == (
            "20c is how many hundredths of a dollar?")

    @pytest.mark.django_db(transaction=True)
    def test_an_interactive_question_is_previewed_as_its_real_widget(
        self, page: Page, live_server, school, teacher_user
    ):
        """A table must arrive as a table, not as a text box.

        This is also what proves the scripts inside the injected fragment run —
        the widget mounts and fills its hidden field, which is the only way the
        trial answer can be marked at all.
        """
        question = _short_answer_question()
        question.update(
            question_text="Complete the chart by writing the decimal form of 56c.",
            question_type="table_of_values", table_spec=_TABLE_SPEC, answers=[])
        session = _session(teacher_user, school, question)
        _open_preview(page, live_server, session)

        stage = page.locator("[data-preview-stage]")
        expect(stage.get_by_text("Money value")).to_be_visible()
        expect(page.get_by_text("every cell must be right")).to_be_visible()

        stage.locator('input[type="text"]').first.fill("0.56")
        page.locator("[data-preview-check]").click()
        expect(page.locator('[data-preview-result="correct"]')).to_be_visible(timeout=15_000)
