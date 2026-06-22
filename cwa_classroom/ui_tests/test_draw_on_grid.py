"""Playwright UI test — draw_on_grid click-to-draw end-to-end (CPP-339).

A student opens a homework with a "draw all lines of symmetry" question,
clicks two grid dots to lay the symmetry line, submits, and the submission is
marked correct. Drawing an extra line is marked wrong. Mirrors the fixtures in
test_homework_e2e_maths.py. Epic CPP-330.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


GRID_SPEC = {
    'grid': {'cols': 9, 'rows': 9},
    'shape': {'type': 'polygon', 'points': [[2, 3], [6, 3], [6, 5], [2, 5]]},
    'mode': 'segments',
    'target': {'segments': [{'x1': 4, 'y1': 0, 'x2': 4, 'y2': 8}]},
    'allow_extra': False,
}


@pytest.fixture
def grid_question(db, level, topic):
    from maths.models import Question

    return Question.objects.create(
        level=level, topic=topic,
        question_text='Draw all lines of symmetry.',
        question_type=Question.DRAW_ON_GRID,
        difficulty=1, points=1,
        grid_spec=GRID_SPEC,
    )


@pytest.fixture
def grid_homework_ready(db, classroom, teacher_user, topic, grid_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title='Symmetry E2E', homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=grid_question, order=0)
    return hw


def _dot(page, gx, gy):
    return page.locator(f'circle[data-gx="{gx}"][data-gy="{gy}"]')


class TestDrawOnGridTake:

    @pytest.mark.django_db(transaction=True)
    def test_student_sees_grid_and_dots(
        self, page: Page, live_server, enrolled_student, grid_homework_ready, grid_question
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{grid_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")
        expect(page.locator(f'svg[data-dog-wrap="{grid_question.pk}"]')).to_be_visible()
        expect(_dot(page, 4, 0)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_student_draws_correct_symmetry_line(
        self, page: Page, live_server, enrolled_student, grid_homework_ready, grid_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{grid_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Click the two endpoints of the vertical line of symmetry.
        _dot(page, 4, 0).click()
        _dot(page, 4, 8).click()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=grid_homework_ready, student=enrolled_student
        ).first()
        assert sub is not None
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=grid_question)
        assert ans.is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_extra_line_marked_wrong(
        self, page: Page, live_server, enrolled_student, grid_homework_ready, grid_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{grid_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Correct line plus an extra (wrong) line → "draw ALL" means exact set.
        _dot(page, 4, 0).click()
        _dot(page, 4, 8).click()
        _dot(page, 0, 0).click()
        _dot(page, 8, 8).click()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=grid_homework_ready, student=enrolled_student
        ).first()
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=grid_question)
        assert ans.is_correct is False
