"""Playwright UI tests — Cartesian-plane / read-graph question types end-to-end.

A student opens a homework with each new interactive type and is auto-marked:
- plot_points: tap lattice points to plot coordinates (with a visible read-out).
- plot_line: tap points that auto-connect into a polyline.
- identify_coords: type the coordinates of a plotted point.
- read_graph: type a value read off a graph, tolerance-graded.

Also: tapping a plotted point removes it (toggle), mobile tap targets work, and
the teacher PDF-preview exposes the structured-spec editors. Mirrors the fixtures
in test_draw_on_grid.py. CPP graph/Cartesian question-type family.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


POINTS_SPEC = {
    'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
    'mode': 'points',
    'target': {'points': [[3, -2], [1, 4]]},
    'allow_extra': False,
}

SEGMENTS_SPEC = {
    'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
    'mode': 'segments',
    'target': {'segments': [
        {'x1': -2, 'y1': 1, 'x2': 0, 'y2': 4},
        {'x1': 0, 'y1': 4, 'x2': 3, 'y2': 1},
    ]},
}

IDENTIFY_SPEC = {
    'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
    'mode': 'points',
    'given_points': [[-2, 4]],
    'target': {'points': [[-2, 4]]},
}

GRAPH_SPEC = {
    'title': 'Grand Prix Race',
    'x_axis': {'label': 'Time', 'unit': 'min', 'min': 0, 'max': 110, 'step': 10},
    'y_axis': {'label': 'Distance', 'unit': 'km', 'min': 0, 'max': 320, 'step': 65},
    'series': [{'points': [[20, 65], [40, 130], [60, 200], [80, 260], [100, 305]]}],
}


def _make_homework(classroom, teacher_user, topic, question, title):
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title=title, homework_type='topic', num_questions=1,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=question, order=0)
    return hw


@pytest.fixture
def plot_points_hw(db, classroom, teacher_user, topic, level):
    from maths.models import Question
    q = Question.objects.create(
        level=level, topic=topic, question_text='Plot (3, -2) and (1, 4).',
        question_type=Question.PLOT_POINTS, difficulty=1, points=1,
        plane_spec=POINTS_SPEC,
    )
    return _make_homework(classroom, teacher_user, topic, q, 'Plot Points E2E'), q


@pytest.fixture
def plot_line_hw(db, classroom, teacher_user, topic, level):
    from maths.models import Question
    q = Question.objects.create(
        level=level, topic=topic, question_text='Plot and join the points.',
        question_type=Question.PLOT_LINE, difficulty=1, points=1,
        plane_spec=SEGMENTS_SPEC,
    )
    return _make_homework(classroom, teacher_user, topic, q, 'Plot Line E2E'), q


@pytest.fixture
def identify_hw(db, classroom, teacher_user, topic, level):
    from maths.models import Question
    q = Question.objects.create(
        level=level, topic=topic, question_text='Write the coordinates of the point.',
        question_type=Question.IDENTIFY_COORDS, difficulty=1, points=1,
        plane_spec=IDENTIFY_SPEC,
    )
    return _make_homework(classroom, teacher_user, topic, q, 'Identify Coords E2E'), q


@pytest.fixture
def read_graph_hw(db, classroom, teacher_user, topic, level):
    from decimal import Decimal
    from maths.models import Question
    q = Question.objects.create(
        level=level, topic=topic, question_text='How far at 40 minutes?',
        question_type=Question.READ_GRAPH, difficulty=1, points=1,
        graph_spec=GRAPH_SPEC, numeric_answer=Decimal('130'),
        answer_tolerance=Decimal('5'), answer_unit='km',
    )
    return _make_homework(classroom, teacher_user, topic, q, 'Read Graph E2E'), q


def _dot(page, qid, gx, gy):
    return page.locator(f'[data-pl-dot="{qid}"][data-gx="{gx}"][data-gy="{gy}"]')


def _take(page, live_server, student, hw):
    do_login(page, live_server.url, student)
    page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
    page.wait_for_load_state("networkidle")


def _submit(page):
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
    page.wait_for_load_state("networkidle")


def _answer(hw, student, question):
    from homework.models import HomeworkStudentAnswer, HomeworkSubmission
    sub = HomeworkSubmission.objects.filter(homework=hw, student=student).first()
    assert sub is not None
    return HomeworkStudentAnswer.objects.get(submission=sub, question=question)


class TestPlotPoints:

    @pytest.mark.django_db(transaction=True)
    def test_plane_and_lattice_render(self, page, live_server, enrolled_student, plot_points_hw):
        hw, q = plot_points_hw
        _take(page, live_server, enrolled_student, hw)
        expect(page.locator(f'svg[data-pl-wrap="{q.pk}"]')).to_be_visible()
        expect(_dot(page, q.pk, 3, -2)).to_be_attached()

    @pytest.mark.django_db(transaction=True)
    def test_correct_points_marked_right_and_readout_updates(
        self, page, live_server, enrolled_student, plot_points_hw
    ):
        hw, q = plot_points_hw
        _take(page, live_server, enrolled_student, hw)
        _dot(page, q.pk, 3, -2).click()
        _dot(page, q.pk, 1, 4).click()
        # The visible read-out echoes the plotted coordinates (anti-silent-mistap).
        expect(page.locator(f'[data-pl-readout="{q.pk}"]')).to_contain_text("(3, -2)")
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_wrong_point_marked_wrong(self, page, live_server, enrolled_student, plot_points_hw):
        hw, q = plot_points_hw
        _take(page, live_server, enrolled_student, hw)
        _dot(page, q.pk, 3, -2).click()
        _dot(page, q.pk, 0, 0).click()      # wrong second point
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is False

    @pytest.mark.django_db(transaction=True)
    def test_tap_toggles_point_off(self, page, live_server, enrolled_student, plot_points_hw):
        hw, q = plot_points_hw
        _take(page, live_server, enrolled_student, hw)
        _dot(page, q.pk, 3, -2).click()
        _dot(page, q.pk, 1, 4).click()
        _dot(page, q.pk, 0, 0).click()      # add a stray point...
        _dot(page, q.pk, 0, 0).click()      # ...then tap again to remove it
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_mobile_tap_targets(self, page, live_server, enrolled_student, plot_points_hw):
        hw, q = plot_points_hw
        page.set_viewport_size({"width": 375, "height": 720})
        _take(page, live_server, enrolled_student, hw)
        _dot(page, q.pk, 3, -2).click()
        _dot(page, q.pk, 1, 4).click()
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True


class TestPlotLine:

    @pytest.mark.django_db(transaction=True)
    def test_points_auto_connect_correct(self, page, live_server, enrolled_student, plot_line_hw):
        hw, q = plot_line_hw
        _take(page, live_server, enrolled_student, hw)
        # Tap in order so consecutive points auto-connect into the target polyline.
        _dot(page, q.pk, -2, 1).click()
        _dot(page, q.pk, 0, 4).click()
        _dot(page, q.pk, 3, 1).click()
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True


class TestIdentifyCoords:

    @pytest.mark.django_db(transaction=True)
    def test_typed_coordinates_marked_right(self, page, live_server, enrolled_student, identify_hw):
        hw, q = identify_hw
        _take(page, live_server, enrolled_student, hw)
        page.locator(f'#answer_{q.pk}').fill("(-2, 4)")
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_wrong_coordinates_marked_wrong(self, page, live_server, enrolled_student, identify_hw):
        hw, q = identify_hw
        _take(page, live_server, enrolled_student, hw)
        page.locator(f'#answer_{q.pk}').fill("(2, -4)")
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is False


class TestReadGraph:

    @pytest.mark.django_db(transaction=True)
    def test_graph_renders_and_value_within_tolerance(
        self, page, live_server, enrolled_student, read_graph_hw
    ):
        hw, q = read_graph_hw
        _take(page, live_server, enrolled_student, hw)
        # The generated graph SVG renders (title text present).
        expect(page.get_by_text("Grand Prix Race")).to_be_visible()
        page.locator(f'#answer_{q.pk}').fill("132")     # within 130 ± 5
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is True

    @pytest.mark.django_db(transaction=True)
    def test_value_out_of_tolerance_marked_wrong(
        self, page, live_server, enrolled_student, read_graph_hw
    ):
        hw, q = read_graph_hw
        _take(page, live_server, enrolled_student, hw)
        page.locator(f'#answer_{q.pk}').fill("120")     # outside 130 ± 5
        _submit(page)
        assert _answer(hw, enrolled_student, q).is_correct is False


class TestTeacherPdfPreview:

    @pytest.mark.django_db(transaction=True)
    def test_preview_exposes_plane_and_graph_editors(
        self, page, live_server, teacher_user, classroom, school
    ):
        """The homework PDF preview shows the plane_spec / read_graph editors for
        the matching extracted types (teacher authoring surface)."""
        from homework.models import HomeworkUploadSession

        session = HomeworkUploadSession.objects.create(
            user=teacher_user, school=school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 7, 'subject': 'Mathematics', 'topic': 'Coordinates',
                'questions': [
                    {'question_text': 'Plot the points.', 'question_type': 'plot_points',
                     'plane_spec': POINTS_SPEC, 'validation_type': 'auto',
                     'difficulty': 1, 'points': 1, 'answers': []},
                    {'question_text': 'Read off the value.', 'question_type': 'read_graph',
                     'numeric_answer': 130, 'answer_tolerance': 5, 'answer_unit': 'km',
                     'validation_type': 'auto', 'difficulty': 1, 'points': 1, 'answers': []},
                ],
            },
        )
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("networkidle")
        # plot_points → plane_spec textarea; read_graph → numeric answer input.
        expect(page.locator('textarea[name="q_0_plane_spec"]')).to_be_visible()
        expect(page.locator('input[name="q_1_numeric_answer"]')).to_be_visible()
