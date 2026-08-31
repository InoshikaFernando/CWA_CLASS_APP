"""Playwright UI test — sketch-a-graph question end-to-end.

A student opens a homework containing "Sketch the graph of y = x² + x − 2
showing the coordinates of the vertex, x-axis and y-axis intercepts and equation
of the axis of symmetry", sees the blank plane the worksheet printed plus one
box per feature the stem names, types them, submits, and the answer is marked
feature by feature: correct only when every feature is right, but worth the
share that are.

The JS half matters as much as the grading half. The boxes are collected into a
hidden field by static/js/sketch_graph.js, mounted through the shared
maths_mounts.js registry. If that never mounts, the hidden field stays empty and
every student is marked wrong — which no server-side test would catch. Mirrors
test_fill_blank_question.py.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login

QUESTION_TEXT = (
    'Sketch the graph of y = x^2 + x - 2 showing the coordinates of the vertex, '
    'x-axis and y-axis intercepts and equation of the axis of symmetry.'
)

SPEC = {
    'equation': 'y = x^2 + x - 2',
    'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
    'curve': {'type': 'quadratic', 'a': 1, 'b': 1, 'c': -2},
    'features': [
        {'kind': 'vertex', 'points': [[-0.5, -2.25]]},
        {'kind': 'x_intercept', 'points': [[-2, 0], [1, 0]]},
        {'kind': 'y_intercept', 'points': [[0, -2]]},
        {'kind': 'axis_of_symmetry', 'value': -0.5},
    ],
}


@pytest.fixture
def sketch_question(db, level, topic):
    from maths.models import Question

    return Question.objects.create(
        level=level, topic=topic,
        question_text=QUESTION_TEXT,
        question_type=Question.SKETCH_GRAPH,
        difficulty=2, points=4, sketch_spec=SPEC,
    )


@pytest.fixture
def sketch_homework_ready(db, classroom, teacher_user, topic, sketch_question):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title='Sketch Graph E2E', homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=sketch_question, order=0)
    return hw


def _open_take(page, live_server, student, homework):
    do_login(page, live_server.url, student)
    page.goto(f"{live_server.url}/homework/{homework.pk}/take/")
    page.wait_for_load_state("networkidle")


def _submit(page):
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
    page.wait_for_load_state("networkidle")


def _answer(homework, student, question):
    from homework.models import HomeworkStudentAnswer, HomeworkSubmission

    sub = HomeworkSubmission.objects.filter(
        homework=homework, student=student).first()
    assert sub is not None
    return HomeworkStudentAnswer.objects.get(submission=sub, question=question)


def _fill(page, **features):
    for kind, value in features.items():
        page.locator(f"[data-sk-feature][data-kind='{kind}']").fill(value)


class TestSketchGraphQuestionTake:

    @pytest.mark.django_db(transaction=True)
    def test_the_blank_plane_and_a_box_per_feature_render(
        self, page: Page, live_server, enrolled_student, sketch_homework_ready
    ):
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        stage = page.locator("[data-sk-stage]")
        expect(stage).to_be_visible()
        expect(stage.locator("svg")).to_have_count(1)          # the axes
        expect(stage.locator("[data-sk-feature]")).to_have_count(4)
        expect(stage).to_contain_text("Vertex (turning point)")
        expect(stage).to_contain_text("Equation of the axis of symmetry")

    @pytest.mark.django_db(transaction=True)
    def test_the_widget_mounts_through_the_shared_registry(
        self, page: Page, live_server, enrolled_student, sketch_homework_ready
    ):
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)
        expect(page.locator("[data-sk-stage][data-sk-mounted='1']")).to_have_count(1)

    @pytest.mark.django_db(transaction=True)
    def test_the_answers_never_reach_the_page(
        self, page: Page, live_server, enrolled_student, sketch_homework_ready
    ):
        """The plane is drawn blank on purpose: drawing the curve, or printing
        the vertex, hands the student the answer.

        Scoped to the widget rather than the whole document: the page chrome is
        full of SVG icons whose path data contains any short number you care to
        look for.
        """
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        stage = page.locator("[data-sk-stage]").inner_html()
        assert "-2.25" not in stage
        assert "x = -0.5" not in stage
        assert "stroke-dasharray" not in stage   # no axis of symmetry drawn

    @pytest.mark.django_db(transaction=True)
    def test_typing_syncs_the_features_into_the_hidden_field(
        self, page: Page, live_server, enrolled_student, sketch_homework_ready
    ):
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        _fill(page, vertex="(-0.5, -2.25)", axis_of_symmetry="x = -0.5")

        payload = json.loads(page.locator("[data-sk-hidden]").input_value())
        assert payload == {"features": {"vertex": "(-0.5, -2.25)",
                                        "axis_of_symmetry": "x = -0.5"}}

    @pytest.mark.django_db(transaction=True)
    def test_every_feature_right_is_marked_correct(
        self, page: Page, live_server, enrolled_student,
        sketch_homework_ready, sketch_question
    ):
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        _fill(page,
              vertex="(-0.5, -2.25)",
              x_intercept="(1, 0), (-2, 0)",   # either order is the same answer
              y_intercept="(0, -2)",
              axis_of_symmetry="x = -1/2")     # the fraction is the same value
        _submit(page)

        ans = _answer(sketch_homework_ready, enrolled_student, sketch_question)
        assert ans.is_correct is True
        assert ans.points_earned == sketch_question.points

    @pytest.mark.django_db(transaction=True)
    def test_one_wrong_feature_keeps_the_other_three_marks(
        self, page: Page, live_server, enrolled_student,
        sketch_homework_ready, sketch_question
    ):
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        _fill(page,
              vertex="(0, 0)",
              x_intercept="(-2, 0), (1, 0)",
              y_intercept="(0, -2)",
              axis_of_symmetry="x = -0.5")
        _submit(page)

        ans = _answer(sketch_homework_ready, enrolled_student, sketch_question)
        assert ans.is_correct is False
        assert ans.points_earned == 3.0
        assert ans.answer_data["parts_correct"] == 3
        assert ans.answer_data["parts_total"] == 4

    @pytest.mark.django_db(transaction=True)
    def test_the_result_page_shows_the_sketch_that_was_wanted(
        self, page: Page, live_server, enrolled_student, sketch_homework_ready
    ):
        """A student who got it wrong is shown the graph, not a blank where the
        correct answer belongs — these questions store no answer rows."""
        _open_take(page, live_server, enrolled_student, sketch_homework_ready)

        _fill(page, vertex="(0, 0)")
        _submit(page)

        body = page.content()
        assert "Vertex (turning point): (-0.5, -2.25)" in body
        assert "stroke-dasharray" in body   # the axis of symmetry on the figure
