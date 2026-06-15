"""Playwright UI test — measure question end-to-end (CPP-334).

A student opens a homework containing a `measure` question, sees the
generated figure + a numeric box, types a value within tolerance, submits,
and the submission is marked correct. Mirrors the fixtures in
test_homework_e2e_maths.py. Epic CPP-330.
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


@pytest.fixture
def measure_question(db, level, topic):
    from maths.models import Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text="Measure angle a.",
        question_type=Question.MEASURE,
        difficulty=1,
        points=1,
        numeric_answer=Decimal("135"),
        answer_tolerance=Decimal("2"),
        answer_unit="°",
    )
    return q


@pytest.fixture
def measure_homework_ready(db, classroom, teacher_user, topic, measure_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Measure E2E",
        homework_type="topic",
        num_questions=1,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=measure_question, order=0)
    return hw


class TestMeasureQuestionTake:

    @pytest.mark.django_db(transaction=True)
    def test_student_sees_figure_and_numeric_box(
        self, page: Page, live_server, enrolled_student, measure_homework_ready, measure_question
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{measure_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Generated figure renders, and a numeric answer box exists (not radios).
        expect(page.locator(".measure-figure svg")).to_be_visible()
        expect(page.locator(f"input[name='answer_{measure_question.pk}']")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_student_answer_within_tolerance_marked_correct(
        self, page: Page, live_server, enrolled_student, measure_homework_ready, measure_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{measure_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # 134 is within 135 ± 2 → correct.
        page.locator(f"input[name='answer_{measure_question.pk}']").fill("134")
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=measure_homework_ready, student=enrolled_student
        ).first()
        assert sub is not None
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=measure_question)
        assert ans.is_correct is True
        assert ans.text_answer == "134"

    @pytest.mark.django_db(transaction=True)
    def test_student_answer_outside_tolerance_marked_wrong(
        self, page: Page, live_server, enrolled_student, measure_homework_ready, measure_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{measure_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # 120 is outside 135 ± 2 → wrong.
        page.locator(f"input[name='answer_{measure_question.pk}']").fill("120")
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=measure_homework_ready, student=enrolled_student
        ).first()
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=measure_question)
        assert ans.is_correct is False

    @pytest.mark.django_db(transaction=True)
    def test_interactive_protractor_overlay_mounts(
        self, page: Page, live_server, enrolled_student, measure_homework_ready, measure_question
    ):
        """measure_tool.js overlays a draggable/rotatable protractor on a
        degree-unit measure figure (the on-screen measuring instrument)."""
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{measure_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Degree unit → protractor stage; the script mounts the instrument SVG.
        stage = page.locator(".measure-stage[data-measure-tool='protractor']")
        expect(stage).to_be_visible()
        expect(stage.locator(".measure-instrument svg")).to_be_visible()
        # The rotate knob (for swinging the protractor) is present exactly once.
        expect(stage.locator("[data-role='rotate']")).to_have_count(1)
        # The figure to measure is still rendered, inside the same stage.
        expect(stage.locator(".measure-figure svg")).to_be_visible()
