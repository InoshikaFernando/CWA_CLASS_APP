"""Unit tests for the ``sketch_graph`` question type.

"Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex,
x-axis and y-axis intercepts and equation of the axis of symmetry" is a whole
family of Year 10-11 quadratics questions. The app cannot take a hand-drawn
curve, so before this type existed every one of them was routed to the teacher
as an un-gradeable drawing. It is not one: the marks are for the FEATURES the
stem names, and the student can type those.

Covered here: what a usable spec is, how the typed features are marked (whole
numbers, decimals, fractions, either order, part by part), and that the answers
never reach the student's screen.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from classroom.models import Level

from maths.geometry_grading import (
    DEFAULT_SKETCH_TOLERANCE,
    describe_sketch_answer,
    describe_sketch_spec,
    grade_sketch,
    grade_sketch_parts,
    parse_axis_of_symmetry,
    parse_sketch_points,
    sketch_feature_expected,
    sketch_number,
    validate_sketch_spec,
)
from maths.models import Question
from maths.svg_geometry import sketch_answer_svg, sketch_curve_polylines, sketch_curve_y


# y = x² + x − 2 — question 11 of the paper this type was built from.
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


def payload(**features):
    return {'features': features}


ALL_RIGHT = payload(
    vertex='(-0.5, -2.25)',
    x_intercept='(-2, 0), (1, 0)',
    y_intercept='(0, -2)',
    axis_of_symmetry='x = -0.5',
)


# ---------------------------------------------------------------------------
# Parsing the forms a student writes an answer in
# ---------------------------------------------------------------------------
class TestNumberParsing:

    @pytest.mark.parametrize('text,want', [
        ('3', '3'), ('-0.5', '-0.5'), ('+4', '4'),
        ('-1/2', '-0.5'), ('9/4', '2.25'),
        ('-2 1/4', '-2.25'),        # a mixed number is 2¼, never 21/4
        ('2 1/4', '2.25'),
        ('−0.5', '-0.5'),      # the unicode minus a PDF pastes in
    ])
    def test_reads_the_forms_a_student_writes(self, text, want):
        assert sketch_number(text) == Decimal(want)

    @pytest.mark.parametrize('text', ['', 'x', '1/0', '1..2', None, '3cm'])
    def test_unparseable_is_none_not_a_guess(self, text):
        assert sketch_number(text) is None

    def test_points_parse_in_every_punctuation(self):
        for text in ['(-2, 0), (1, 0)', '(-2,0) (1,0)', '-2,0; 1,0']:
            assert parse_sketch_points(text) == [
                (Decimal('-2'), Decimal('0')), (Decimal('1'), Decimal('0'))]

    def test_fractional_coordinates_parse(self):
        assert parse_sketch_points('(-1/2, -2 1/4)') == [
            (Decimal('-0.5'), Decimal('-2.25'))]

    @pytest.mark.parametrize('text', ['x = -0.5', 'x=-1/2', '-0.5', 'X : -0.5'])
    def test_axis_of_symmetry_accepts_the_equation_or_the_value(self, text):
        assert parse_axis_of_symmetry(text) == Decimal('-0.5')


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------
class TestValidateSketchSpec:

    def test_a_real_spec_validates(self):
        validate_sketch_spec(SPEC)  # does not raise

    def test_curve_is_optional(self):
        spec = {k: v for k, v in SPEC.items() if k != 'curve'}
        validate_sketch_spec(spec)

    @pytest.mark.parametrize('spec,fragment', [
        ('not a dict', 'JSON object'),
        ({'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8}}, 'features'),
        ({'bounds': {'xmin': 6, 'xmax': -6, 'ymin': -4, 'ymax': 8},
          'features': [{'kind': 'vertex', 'points': [[0, 0]]}]}, 'bounds'),
        ({'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
          'features': [{'kind': 'nonsense', 'points': [[0, 0]]}]}, 'kind'),
        ({'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
          'features': [{'kind': 'axis_of_symmetry'}]}, 'value'),
    ])
    def test_a_spec_that_cannot_be_answered_is_rejected(self, spec, fragment):
        with pytest.raises(ValueError) as exc:
            validate_sketch_spec(spec)
        assert fragment in str(exc.value)

    def test_a_feature_outside_the_grid_is_rejected(self):
        """A vertex the plane cannot show is a mis-read, and the student would
        be marked against it."""
        spec = dict(SPEC, features=[{'kind': 'vertex', 'points': [[-40, 0]]}])
        with pytest.raises(ValueError, match='outside the plane bounds'):
            validate_sketch_spec(spec)

    def test_an_intercept_off_its_own_axis_is_rejected(self):
        spec = dict(SPEC, features=[{'kind': 'y_intercept', 'points': [[3, -2]]}])
        with pytest.raises(ValueError, match='x = 0'):
            validate_sketch_spec(spec)
        spec = dict(SPEC, features=[{'kind': 'x_intercept', 'points': [[3, 5]]}])
        with pytest.raises(ValueError, match='y = 0'):
            validate_sketch_spec(spec)

    def test_the_same_feature_twice_is_rejected(self):
        spec = dict(SPEC, features=[
            {'kind': 'vertex', 'points': [[0, 0]]},
            {'kind': 'vertex', 'points': [[1, 1]]},
        ])
        with pytest.raises(ValueError, match='twice'):
            validate_sketch_spec(spec)

    def test_a_plane_too_big_to_draw_is_rejected(self):
        spec = dict(SPEC, bounds={'xmin': -100, 'xmax': 100, 'ymin': -4, 'ymax': 8})
        with pytest.raises(ValueError, match='span'):
            validate_sketch_spec(spec)

    def test_a_quadratic_with_no_x_squared_term_is_rejected(self):
        spec = dict(SPEC, curve={'type': 'quadratic', 'a': 0, 'b': 1, 'c': -2})
        with pytest.raises(ValueError, match='must not be zero'):
            validate_sketch_spec(spec)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
class TestGradeSketch:

    def test_every_feature_right_is_correct(self):
        assert grade_sketch(SPEC, ALL_RIGHT) is True

    def test_the_payload_may_arrive_as_a_json_string(self):
        import json
        assert grade_sketch(SPEC, json.dumps(ALL_RIGHT)) is True

    def test_the_intercepts_may_be_written_either_way_round(self):
        assert grade_sketch(SPEC, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], x_intercept='(1, 0), (-2, 0)'))) is True

    def test_fractions_are_accepted_for_the_same_value(self):
        """The vertex of these quadratics is a quarter or a half far more often
        than a whole number, so a correct fraction must not be marked wrong."""
        assert grade_sketch(SPEC, payload(
            vertex='(-1/2, -2 1/4)',
            x_intercept='(-2, 0), (1, 0)',
            y_intercept='(0, -2)',
            axis_of_symmetry='x = -1/2',
        )) is True

    def test_only_one_of_two_intercepts_is_wrong(self):
        grade = grade_sketch_parts(SPEC, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], x_intercept='(1, 0)')))
        assert grade.is_correct is False
        assert grade.correct == 3

    def test_three_features_of_four_earns_three_quarters(self):
        grade = grade_sketch_parts(SPEC, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], vertex='(0, 0)')))
        assert grade.is_correct is False
        assert grade.correct == 3
        assert grade.total == 4
        assert grade.fraction == 0.75
        assert grade.noun == 'feature'

    def test_a_wrong_feature_is_named_with_what_was_wanted(self):
        grade = grade_sketch_parts(SPEC, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], vertex='(0, 0)')))
        wrong = grade.wrong_parts[0]
        assert wrong.label == 'Vertex (turning point)'
        assert wrong.typed == '(0, 0)'
        assert wrong.expected == '(-0.5, -2.25)'

    def test_a_feature_left_empty_is_one_wrong_part_not_a_wrecked_answer(self):
        grade = grade_sketch_parts(SPEC, payload(
            vertex='(-0.5, -2.25)',
            x_intercept='(-2, 0), (1, 0)',
            y_intercept='(0, -2)',
        ))
        assert grade.correct == 3
        assert grade.wrong_parts[0].typed == ''

    def test_tolerance_defaults_small_and_is_honoured(self):
        assert DEFAULT_SKETCH_TOLERANCE == Decimal('0.01')
        assert grade_sketch(SPEC, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], vertex='(-0.5, -2.3)'))) is False
        loose = dict(SPEC, tolerance=0.1)
        assert grade_sketch(loose, dict(ALL_RIGHT, features=dict(
            ALL_RIGHT['features'], vertex='(-0.5, -2.3)'))) is True

    @pytest.mark.parametrize('bad', [
        'not json', {'cells': {}}, {'features': 'nope'}, None, 42,
    ])
    def test_a_malformed_payload_is_wrong_never_an_error(self, bad):
        assert grade_sketch(SPEC, bad) is False

    def test_a_malformed_spec_grades_nothing_rather_than_correct(self):
        assert grade_sketch_parts({'features': []}, ALL_RIGHT) is None
        assert grade_sketch({'features': []}, ALL_RIGHT) is False


class TestDescribeSketch:

    def test_the_expected_value_reads_the_way_the_question_asks(self):
        assert sketch_feature_expected(SPEC['features'][0]) == '(-0.5, -2.25)'
        assert sketch_feature_expected(SPEC['features'][1]) == '(-2, 0), (1, 0)'
        assert sketch_feature_expected(SPEC['features'][3]) == 'x = -0.5'

    def test_a_stored_payload_is_shown_readably_not_as_json(self):
        shown = describe_sketch_answer(ALL_RIGHT, SPEC)
        assert shown.startswith('Vertex (turning point): (-0.5, -2.25)')
        assert 'Equation of the axis of symmetry: x = -0.5' in shown
        assert '{' not in shown

    def test_a_missed_feature_shows_as_a_dash(self):
        assert '—' in describe_sketch_answer(payload(vertex='(0, 0)'), SPEC)

    def test_the_correct_answer_can_be_read_off_the_spec(self):
        shown = describe_sketch_spec(SPEC)
        assert 'x-axis intercept(s): (-2, 0), (1, 0)' in shown

    def test_a_payload_that_is_not_a_sketch_comes_back_unchanged(self):
        assert describe_sketch_answer('42', SPEC) == '42'


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
@pytest.fixture
def level(db):
    level, _ = Level.objects.get_or_create(
        level_number=993, defaults={'display_name': 'sketch_graph fixture'})
    return level


@pytest.mark.django_db
class TestSketchQuestionModel:

    def _question(self, level, **kwargs):
        fields = dict(
            level=level,
            question_text=('Sketch the graph of y = x² + x - 2 showing the '
                           'coordinates of the vertex, x-axis and y-axis '
                           'intercepts and equation of the axis of symmetry.'),
            question_type=Question.SKETCH_GRAPH, sketch_spec=SPEC,
        )
        fields.update(kwargs)
        return Question(**fields)

    def test_the_type_is_offered_and_stores_its_spec(self, level):
        assert ('sketch_graph', 'Sketch a Graph (state vertex / intercepts / '
                'axis of symmetry)') in Question.QUESTION_TYPES
        q = self._question(level)
        q.full_clean(exclude=['school', 'department', 'classroom', 'topic'])
        q.save()
        assert Question.objects.get(pk=q.pk).sketch_spec == SPEC

    def test_a_sketch_without_a_spec_is_rejected(self, level):
        q = self._question(level, sketch_spec=None)
        with pytest.raises(ValidationError) as exc:
            q.clean()
        assert 'sketch_spec' in exc.value.message_dict

    def test_a_malformed_spec_is_rejected_by_clean(self, level):
        q = self._question(level, sketch_spec={'features': []})
        with pytest.raises(ValidationError) as exc:
            q.clean()
        assert 'sketch_spec' in exc.value.message_dict

    def test_it_grades_through_the_model_part_by_part(self, level):
        import json
        q = self._question(level)
        q.save()
        grade = q.grade_text_answer_parts(json.dumps(ALL_RIGHT))
        assert grade is not None and grade.is_correct

    def test_the_correct_answer_is_readable_without_answer_rows(self, level):
        q = self._question(level)
        q.save()
        assert q.answers.count() == 0
        assert 'Vertex (turning point): (-0.5, -2.25)' in q.correct_answer_display()


@pytest.mark.django_db
class TestSketchRenderData:

    def _question(self, level, spec=None):
        return Question.objects.create(
            level=level, question_text='Sketch it.',
            question_type=Question.SKETCH_GRAPH, sketch_spec=spec or SPEC,
        )

    def test_the_take_data_carries_a_blank_plane_and_a_box_per_feature(self, level):
        data = self._question(level).sketch_data
        assert [f['kind'] for f in data['features']] == [
            'vertex', 'x_intercept', 'y_intercept', 'axis_of_symmetry']
        assert '<line' in data['svg']
        assert data['equation'] == 'y = x^2 + x - 2'

    def test_the_blank_plane_holds_none_of_the_answers(self, level):
        """The student's figure is the same axes the worksheet printed —
        drawing the curve on it would hand them the answer."""
        data = self._question(level).sketch_data
        assert '-2.25' not in data['svg']
        assert all('expected' not in f for f in data['features'])

    def test_the_answer_figure_draws_the_curve_and_names_the_features(self, level):
        data = self._question(level).sketch_data
        assert '<path' in data['answer_svg']            # the parabola
        assert 'stroke-dasharray' in data['answer_svg']  # the axis of symmetry
        assert '(-0.5, -2.25)' in data['answer_svg']
        assert [f['expected'] for f in data['answer_features']][0] == '(-0.5, -2.25)'

    def test_another_question_type_has_no_sketch_data(self, level):
        q = Question.objects.create(
            level=level, question_text='2 + 2?',
            question_type=Question.SHORT_ANSWER)
        assert q.sketch_data is None


class TestSketchCurve:

    def test_the_curve_is_evaluated_from_its_coefficients(self):
        assert sketch_curve_y(SPEC['curve'], 1) == 0
        assert sketch_curve_y(SPEC['curve'], 0) == -2
        assert sketch_curve_y({'type': 'linear', 'm': 2, 'c': 1}, 3) == 7
        assert sketch_curve_y({'type': 'cubic'}, 1) is None

    def test_the_arms_that_leave_the_grid_are_separate_strokes(self):
        """A parabola whose arms rise off the top of the grid must not be joined
        by a false line drawn straight across the figure."""
        narrow = dict(SPEC, bounds={'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 2})
        assert len(sketch_curve_polylines(narrow)) == 1
        # Flip it: only the two arms are on-grid, the vertex is below.
        clipped = dict(SPEC, bounds={'xmin': -6, 'xmax': 6, 'ymin': 1, 'ymax': 8})
        assert len(sketch_curve_polylines(clipped)) == 2

    def test_no_curve_means_no_stroke_but_still_a_figure(self):
        spec = {k: v for k, v in SPEC.items() if k != 'curve'}
        assert sketch_curve_polylines(spec) == []
        assert '<line' in sketch_answer_svg(spec)

    def test_an_undrawable_spec_renders_nothing_rather_than_raising(self):
        assert sketch_answer_svg({'features': []}) == ''
        assert sketch_curve_polylines('nope') == []
