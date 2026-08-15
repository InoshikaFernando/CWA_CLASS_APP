"""Playwright UI test — a multi-option answer grades in any order (CPP-374).

A student reported that a "which of these are correct?" question only accepted
one ordering: they typed ``"E,D"`` and were told the answer was ``"D and E"``.
There is no multi-select question type — such a question is authored as a typed
short answer whose correct text lists the option labels — so the grader compared
the two as strings and marked a right selection wrong.

This drives the real topic quiz: the student types the two labels in the
opposite order, with a comma, and must be graded correct.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


@pytest.fixture
def multi_answer_question(db, level, topic):
    """One short-answer question whose correct answer is two option labels."""
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text="Which of these are multiples of 3? (A-E)",
        question_type=Question.SHORT_ANSWER,
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=q, answer_text="D and E", is_correct=True, order=0)
    return q


class TestMultiAnswerOrderIndependence:

    @pytest.mark.django_db(transaction=True)
    def test_labels_typed_in_reverse_order_grade_correct(
        self, page: Page, live_server,
        enrolled_student, school, classroom, level, topic, multi_answer_question,
    ):
        from maths.models import StudentAnswer

        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("#question-card")).to_contain_text(
            "Which of these are multiples of 3?"
        )

        # The reported input: the same two options, the student's own order.
        page.locator("#text-answer-input").fill("E,D")
        page.locator('button[onclick*="submitTextAnswer"]').click()

        expect(page.locator("#question-card")).to_contain_text(
            "Correct", timeout=10_000
        )
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=multi_answer_question,
            is_correct=True,
        ).exists(), '"E,D" was not graded correct against the stored "D and E"'
