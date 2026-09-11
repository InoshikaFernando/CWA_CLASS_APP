"""A ``plot_line`` target has to be something a child can actually tap out.

The widget draws ONE unbranched stroke, optionally closed back onto its start.
``segment_chain`` decides whether a set of sides is that, and two callers lean
on the answer:

* ``validate_plane_spec`` refuses a target that is not — a star, a T, two
  separate pieces, the same side twice. Before this, such a target validated
  happily and then failed every attempt in silence, because grading is a set
  comparison with nothing to say about the impossible.
* ``Question.plane_data`` reports ``closed`` so the take page offers closing on
  the questions that want a ring and ONLY those.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.geometry_grading import grade_plane, segment_chain, validate_plane_spec
from maths.models import Question


def sides(*quads):
    return [{'x1': a, 'y1': b, 'x2': c, 'y2': d} for a, b, c, d in quads]


BOUNDS = {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5}
OPEN_PATH = sides((-2, 1, 0, 4), (0, 4, 3, 1))
TRIANGLE = sides((-2, 1, 0, 4), (0, 4, 3, 1), (3, 1, -2, 1))


class SegmentChainTests(TestCase):

    def test_an_open_path_is_ordered_and_reported_open(self):
        self.assertEqual(segment_chain(OPEN_PATH),
                         ([(-2, 1), (0, 4), (3, 1)], False))

    def test_a_ring_is_reported_closed_without_repeating_the_join(self):
        vertices, closed = segment_chain(TRIANGLE)
        self.assertTrue(closed)
        # The closing vertex is NOT repeated: these are the points to tap, and
        # the widget keeps each one once.
        self.assertEqual(vertices, [(-2, 1), (0, 4), (3, 1)])

    def test_the_order_sides_are_listed_in_does_not_matter(self):
        # An author writing the spec by hand, or an AI import, has no reason to
        # list the sides in walking order.
        shuffled = sides((3, 1, -2, 1), (-2, 1, 0, 4), (0, 4, 3, 1))
        self.assertEqual(segment_chain(shuffled), segment_chain(TRIANGLE))

    def test_a_side_drawn_the_other_way_round_is_the_same_side(self):
        self.assertEqual(segment_chain(sides((0, 4, -2, 1), (0, 4, 3, 1)))[1], False)

    def test_one_side_on_its_own_is_a_path(self):
        self.assertEqual(segment_chain(sides((0, 0, 1, 1))),
                         ([(0, 0), (1, 1)], False))

    def test_a_branch_is_not_drawable(self):
        # A T: the stroke would have to split. No tap order produces it.
        self.assertIsNone(
            segment_chain(sides((0, 0, 1, 0), (1, 0, 2, 0), (1, 0, 1, 1))))

    def test_two_separate_strokes_are_not_drawable(self):
        self.assertIsNone(segment_chain(sides((0, 0, 1, 0), (4, 4, 5, 4))))

    def test_the_same_side_listed_twice_is_not_drawable(self):
        self.assertIsNone(segment_chain(sides((0, 0, 1, 0), (1, 0, 0, 0))))

    def test_rubbish_is_none_rather_than_an_exception(self):
        for bad in ([], None, [{'x1': 0}], [{'x1': 'a', 'y1': 0, 'x2': 1, 'y2': 1}],
                    sides((2, 2, 2, 2))):
            self.assertIsNone(segment_chain(bad), bad)


class PlaneSpecValidationTests(TestCase):

    def _spec(self, segments):
        return {'bounds': BOUNDS, 'mode': 'segments',
                'target': {'segments': segments}}

    def test_an_open_path_validates(self):
        validate_plane_spec(self._spec(OPEN_PATH))       # does not raise

    def test_a_closed_shape_validates(self):
        # It used to as well — the difference is that now it is also drawable.
        validate_plane_spec(self._spec(TRIANGLE))

    def test_an_undrawable_target_is_refused_with_a_reason(self):
        undrawable = sides((0, 0, 1, 0), (1, 0, 2, 0), (1, 0, 1, 1))
        with self.assertRaises(ValueError) as caught:
            validate_plane_spec(self._spec(undrawable))
        self.assertIn('tapping points in order', str(caught.exception))

    def test_two_separate_pieces_are_refused(self):
        with self.assertRaises(ValueError):
            validate_plane_spec(self._spec(sides((0, 0, 1, 0), (4, 4, 5, 4))))

    def test_points_mode_is_untouched_by_the_new_check(self):
        validate_plane_spec({'bounds': BOUNDS, 'mode': 'points',
                             'target': {'points': [[1, 1], [2, 2]]}})


class ClosedShapeGradingTests(TestCase):
    """The closing side is an ordinary side to the grader."""

    def _spec(self, segments):
        return {'bounds': BOUNDS, 'mode': 'segments',
                'target': {'segments': segments}}

    def test_a_ring_drawn_by_a_student_is_marked_right(self):
        # What the widget now serialises when the shape is closed.
        drawn = {'segments': sides((-2, 1, 0, 4), (0, 4, 3, 1), (3, 1, -2, 1))}
        self.assertTrue(grade_plane(self._spec(TRIANGLE), drawn))

    def test_the_same_ring_started_anywhere_is_still_right(self):
        drawn = {'segments': sides((0, 4, 3, 1), (3, 1, -2, 1), (-2, 1, 0, 4))}
        self.assertTrue(grade_plane(self._spec(TRIANGLE), drawn))

    def test_leaving_the_shape_open_is_marked_wrong(self):
        self.assertFalse(
            grade_plane(self._spec(TRIANGLE), {'segments': OPEN_PATH}))

    def test_closing_a_shape_that_should_be_open_is_marked_wrong(self):
        self.assertFalse(
            grade_plane(self._spec(OPEN_PATH), {'segments': TRIANGLE}))


class PlaneDataClosedFlagTests(TestCase):
    """What the take page is told about closing."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=987, defaults={'display_name': 'plane fixture'})

    def _question(self, segments):
        return Question.objects.create(
            level=self.level, question_text='Draw it.',
            question_type=Question.PLOT_LINE, difficulty=1, points=1,
            plane_spec={'bounds': BOUNDS, 'mode': 'segments',
                        'target': {'segments': segments}},
        )

    def test_a_ring_question_offers_closing(self):
        self.assertTrue(self._question(TRIANGLE).plane_data['closed'])

    def test_an_open_path_question_does_not(self):
        # The whole point of gating it: a stray tap on the first point must not
        # add a side the question never asked for.
        self.assertFalse(self._question(OPEN_PATH).plane_data['closed'])

    def test_a_plot_points_question_does_not(self):
        q = Question.objects.create(
            level=self.level, question_text='Plot them.',
            question_type=Question.PLOT_POINTS, difficulty=1, points=1,
            plane_spec={'bounds': BOUNDS, 'mode': 'points',
                        'target': {'points': [[1, 1], [2, 2]]}},
        )
        self.assertFalse(q.plane_data['closed'])
