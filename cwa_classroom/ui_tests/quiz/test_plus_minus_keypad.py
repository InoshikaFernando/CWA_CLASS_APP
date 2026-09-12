"""Playwright UI test — the ± key on the maths answer keypad.

"Solve the equation, rounding to two decimal places: x² = 23" stores its answer
as ``x=±4.80``, but the keypad beside the answer box had no plus-minus key, so
a student could only reach ± through their OS's symbol picker — and the marked
quiz then listed three correct answers, every one of them needing a character
the student had no way to type.

This drives the real topic quiz: the student clicks the ± key, types "4.80",
and is graded correct — which needs both the new key and the plus-minus
comparison in maths.algebra_grading (a stored ``x=±4.80`` also accepts a typed
``+/-4.80`` and ``4.80 or -4.80``).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login

PLUS_MINUS_KEY = '.cwa-sym-panel button[aria-label="plus or minus"]'


@pytest.fixture
def plus_minus_question(db, level, topic):
    """A short-answer question whose correct answers are written with ±.

    All three rows from the reported screenshot, so the test grades against
    the bank exactly as it stands rather than a tidied-up version of it.
    """
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text=(
            "Solve the equation, rounding to two decimal places: x² = 23"
        ),
        question_type=Question.SHORT_ANSWER,
        difficulty=1,
        points=1,
    )
    for order, text in enumerate(["x=±4.80", "x=4.80 or x=-4.80", "±4.80"]):
        Answer.objects.create(
            question=q, answer_text=text, is_correct=True, order=order,
        )
    return q


class TestPlusMinusKeypadKey:

    def _open_quiz(self, page, live_server, enrolled_student, level, topic):
        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator("#question-card")).to_contain_text("x² = 23")

    @pytest.mark.django_db(transaction=True)
    def test_plus_minus_key_is_on_the_keypad(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, plus_minus_question,
    ):
        self._open_quiz(page, live_server, enrolled_student, level, topic)
        key = page.locator(PLUS_MINUS_KEY)
        expect(key).to_be_visible()
        expect(key).to_have_text("±")

    @pytest.mark.django_db(transaction=True)
    def test_plus_minus_key_types_the_answer_and_grades_correct(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, plus_minus_question,
    ):
        from maths.models import StudentAnswer

        self._open_quiz(page, live_server, enrolled_student, level, topic)

        # Build "±4.80" the way a student would: tap the key, then type.
        answer_box = page.locator("#text-answer-input")
        answer_box.click()
        page.locator(PLUS_MINUS_KEY).click()
        page.keyboard.type("4.80")
        expect(answer_box).to_have_value("±4.80")

        page.locator('button[onclick*="submitTextAnswer"]').click()

        expect(page.locator("#question-card")).to_contain_text(
            "Correct", timeout=10_000
        )
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=plus_minus_question,
            is_correct=True,
        ).exists(), 'the ± key did not produce an answer graded against "x=±4.80"'

    @pytest.mark.django_db(transaction=True)
    def test_the_ascii_spelling_is_graded_correct_without_the_key(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, plus_minus_question,
    ):
        """A student who never finds the key still types a correct answer.

        The key is the discoverable route to ±; it is not the only one that
        may work, or the fix would only help students who spot the button.
        """
        from maths.models import StudentAnswer

        self._open_quiz(page, live_server, enrolled_student, level, topic)

        answer_box = page.locator("#text-answer-input")
        answer_box.click()
        page.keyboard.type("+/-4.80")

        page.locator('button[onclick*="submitTextAnswer"]').click()

        expect(page.locator("#question-card")).to_contain_text(
            "Correct", timeout=10_000
        )
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=plus_minus_question,
            is_correct=True,
        ).exists(), '"+/-4.80" was not graded against the stored ± answers'

    @pytest.mark.django_db(transaction=True)
    def test_the_key_inserts_at_the_caret_rather_than_appending(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, plus_minus_question,
    ):
        """A student who types first and reaches for the key second."""
        self._open_quiz(page, live_server, enrolled_student, level, topic)

        answer_box = page.locator("#text-answer-input")
        answer_box.click()
        page.keyboard.type("x=4.80")
        # Put the caret back between "=" and "4".
        for _ in range(4):
            page.keyboard.press("ArrowLeft")
        page.locator(PLUS_MINUS_KEY).click()
        expect(answer_box).to_have_value("x=±4.80")
