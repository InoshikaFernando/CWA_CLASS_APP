"""Playwright UI test — shape_select tap-to-colour end-to-end.

A student opens a homework with a "colour all the triangles" question, taps the
triangle shapes, submits, and the submission is marked correct. Colouring an
extra (non-triangle) shape is marked wrong. Mirrors the fixtures in
test_draw_on_grid.py.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# Fixed scene: s0/s2/s4 are the triangles to find; s1/s3 are distractors.
SHAPE_SPEC = {
    'target_type': 'triangle',
    'viewbox': [680, 400],
    'shapes': [
        {'id': 's0', 'type': 'triangle', 'cx': 80, 'cy': 80, 'size': 34, 'rot': 0},
        {'id': 's1', 'type': 'circle', 'cx': 240, 'cy': 80, 'size': 30, 'rot': 0},
        {'id': 's2', 'type': 'triangle', 'cx': 400, 'cy': 80, 'size': 32, 'rot': 10},
        {'id': 's3', 'type': 'square', 'cx': 560, 'cy': 80, 'size': 30, 'rot': 0},
        {'id': 's4', 'type': 'triangle', 'cx': 240, 'cy': 240, 'size': 34, 'rot': -8},
    ],
}


@pytest.fixture
def shape_question(db, level, topic):
    from maths.models import Question

    return Question.objects.create(
        level=level, topic=topic,
        question_text='Colour all the triangles.',
        question_type=Question.SHAPE_SELECT,
        difficulty=1, points=1,
        shape_spec=SHAPE_SPEC,
    )


@pytest.fixture
def shape_homework_ready(db, classroom, teacher_user, topic, shape_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title='Shapes E2E', homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=shape_question, order=0)
    return hw


def _shape(page, sid):
    return page.locator(f'[data-shape-id="{sid}"]')


class TestShapeSelectTake:

    @pytest.mark.django_db(transaction=True)
    def test_student_sees_shapes(
        self, page: Page, live_server, enrolled_student, shape_homework_ready, shape_question
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{shape_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")
        expect(page.locator(f'svg[data-ss-wrap="{shape_question.pk}"]')).to_be_visible()
        expect(_shape(page, 's0')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_student_colours_all_triangles_correct(
        self, page: Page, live_server, enrolled_student, shape_homework_ready, shape_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{shape_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        for sid in ('s0', 's2', 's4'):
            _shape(page, sid).click()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=shape_homework_ready, student=enrolled_student
        ).first()
        assert sub is not None
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=shape_question)
        assert ans.is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_extra_shape_marked_wrong(
        self, page: Page, live_server, enrolled_student, shape_homework_ready, shape_question
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{shape_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # All three triangles plus a circle → "colour ALL the triangles" means
        # exactly the triangle set, so the extra shape makes it wrong.
        for sid in ('s0', 's2', 's4', 's1'):
            _shape(page, sid).click()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=shape_homework_ready, student=enrolled_student
        ).first()
        ans = HomeworkStudentAnswer.objects.get(submission=sub, question=shape_question)
        assert ans.is_correct is False
