"""Playwright UI test — long-multiplication partial-product layout (CPP-354).

A column_operation × question with a genuine multi-digit multiplier (23 × 64)
gives the student a scratch working row per non-zero multiplier digit, while a
single-significant-digit multiplier (23 × 4) keeps the simple single-answer-row
layout. The partial rows are scratch only — grading still uses the final answer.
Mirrors the fixtures in test_measure_question.py / test_homework_e2e_maths.py.
Epic CPP-2.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


def _column_question(level, topic, operands, operator):
    from maths.models import Question

    return Question.objects.create(
        level=level,
        topic=topic,
        question_text="Work it out.",
        question_type=Question.COLUMN_OPERATION,
        operands=operands,
        operator=operator,
        difficulty=1,
        points=1,
    )


def _homework_with(classroom, teacher_user, topic, question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Long multiplication E2E",
        homework_type="topic",
        num_questions=1,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=question, order=0)
    return hw


@pytest.fixture
def long_mult_homework(db, classroom, teacher_user, topic, level):
    q = _column_question(level, topic, [23, 64], '*')
    return _homework_with(classroom, teacher_user, topic, q), q


@pytest.fixture
def single_digit_homework(db, classroom, teacher_user, topic, level):
    q = _column_question(level, topic, [23, 4], '*')
    return _homework_with(classroom, teacher_user, topic, q), q


class TestLongMultiplicationTake:

    @pytest.mark.django_db(transaction=True)
    def test_long_multiplication_renders_partial_rows(
        self, page: Page, live_server, enrolled_student, long_mult_homework
    ):
        hw, q = long_mult_homework
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        # 23 × 64 → 2 partial working rows = 4 + 3 = 7 amber scratch boxes,
        # plus the 4 blue final-answer cells (1472).
        expect(page.locator(f"input[data-ca-partial='{q.pk}']")).to_have_count(7)
        expect(page.locator(f"input[data-ca-answer='{q.pk}']")).to_have_count(4)

    @pytest.mark.django_db(transaction=True)
    def test_single_digit_multiplier_has_no_partial_rows(
        self, page: Page, live_server, enrolled_student, single_digit_homework
    ):
        hw, q = single_digit_homework
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        # 23 × 4 keeps the simple layout: no partial rows, 2 answer cells (92).
        expect(page.locator(f"input[data-ca-partial='{q.pk}']")).to_have_count(0)
        expect(page.locator(f"input[data-ca-answer='{q.pk}']")).to_have_count(2)

    @pytest.mark.django_db(transaction=True)
    def test_final_answer_still_graded_with_partial_boxes_present(
        self, page: Page, live_server, enrolled_student, long_mult_homework
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        hw, q = long_mult_homework
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Scribble in a couple of partial scratch boxes — they must NOT affect
        # grading.
        partials = page.locator(f"input[data-ca-partial='{q.pk}']")
        partials.nth(0).fill("9")
        partials.nth(1).fill("2")

        # Type the final answer 1472 across the four blue answer cells; the
        # answer-sync JS rolls them into the hidden field.
        answer_cells = page.locator(f"input[data-ca-answer='{q.pk}']")
        for i, digit in enumerate("1472"):
            answer_cells.nth(i).fill(digit)

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=hw, student=enrolled_student
        ).first()
        assert sub is not None
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=q)
        assert ans.is_correct is True
        assert ans.text_answer == "1472"
