"""Playwright UI test — the ÷ key on the maths answer keypad.

"Write an algebraic expression for a number divided by 4." stores its answer
as ``n ÷ 4``, but the keypad beside the answer box had no division key, so a
student could only reach the ÷ character through their OS's symbol picker.

This drives the real topic quiz: the student types "n", clicks the ÷ key, types
"4", and is graded correct — which needs both the new key and the division fold
in maths.algebra_grading (a stored "n ÷ 4" also accepts a typed "n/4").
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def division_question(db, level, topic):
    """A short-answer question whose correct answer is written with ÷."""
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text="Write an algebraic expression for a number divided by 4.",
        question_type=Question.SHORT_ANSWER,
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=q, answer_text="n ÷ 4", is_correct=True, order=0)
    return q


class TestDivisionKeypadKey:

    def _open_quiz(self, page, live_server, enrolled_student, level, topic):
        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator("#question-card")).to_contain_text("divided by 4")

    @pytest.mark.django_db(transaction=True)
    def test_division_key_is_on_the_keypad(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, division_question,
    ):
        self._open_quiz(page, live_server, enrolled_student, level, topic)
        key = page.locator('.cwa-sym-panel button[aria-label="divided by"]')
        expect(key).to_be_visible()
        expect(key).to_have_text("÷")

    @pytest.mark.django_db(transaction=True)
    def test_division_key_types_the_answer_and_grades_correct(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, division_question,
    ):
        from maths.models import StudentAnswer

        self._open_quiz(page, live_server, enrolled_student, level, topic)

        # Build "n÷4" the way a student would: type, tap the key, type.
        answer_box = page.locator("#text-answer-input")
        answer_box.click()
        page.keyboard.type("n")
        page.locator('.cwa-sym-panel button[aria-label="divided by"]').click()
        page.keyboard.type("4")
        expect(answer_box).to_have_value("n÷4")

        page.locator('button[onclick*="submitTextAnswer"]').click()

        expect(page.locator("#question-card")).to_contain_text(
            "Correct", timeout=10_000
        )
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=division_question,
            is_correct=True,
        ).exists(), 'the ÷ key did not produce an answer graded against "n ÷ 4"'
