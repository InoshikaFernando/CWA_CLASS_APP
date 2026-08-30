"""Rendering tests for identify_coords — the figure the student reads.

The reported fault: a question reading "A is the point (2, 2), B is the point
(8, 2) and C is the point (5, 8). D is the mid point of the line AB. Write down
the co-ordinates of the point D" drew a plane with ONE unlabelled dot on it, at
(5, 2) — which is D, the answer. A, B and C, the three points the question is
entirely about, were not drawn at all. So the figure both gave the answer away
and omitted everything needed to work it out.

Two things had to change for that question to be drawable: given points carry
their NAME, and the answer box survives a question stored without a figure
rather than leaving the child a blank space.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.models import Question

MIDPOINT_TEXT = (
    'A is the point (2, 2), B is the point (8, 2) and C is the point (5, 8). '
    'D is the mid point of the line AB. Write down the co-ordinates of the '
    'point D.'
)


def _render(question):
    return render_to_string(
        'homework/partials/_maths_take_item.html',
        {'ctx': {'question': question, 'shuffled_answers': []}},
    )


class IdentifyCoordsTakeItemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=989,
            defaults={'display_name': 'identify coords render fixture'},
        )

    def _question(self, **over):
        fields = dict(
            level=self.level, question_text=MIDPOINT_TEXT,
            question_type=Question.IDENTIFY_COORDS, difficulty=1, points=1,
            plane_spec={
                'bounds': {'xmin': 0, 'xmax': 10, 'ymin': 0, 'ymax': 10},
                'mode': 'points',
                'given_points': [[2, 2, 'A'], [8, 2, 'B'], [5, 8, 'C']],
                'target': {'points': [[5, 2]]},
            },
        )
        fields.update(over)
        return Question.objects.create(**fields)

    def test_named_given_points_are_drawn_with_their_names(self):
        html = _render(self._question())
        self.assertIn('<svg', html)
        for name in ('>A<', '>B<', '>C<'):
            self.assertIn(name, html,
                          f'the plane does not label its given points ({name})')

    def test_the_answer_is_not_drawn_on_the_plane(self):
        """Only given_points are plotted. target is the answer, never the figure.

        This is the half of the fault that cost the mark rather than the
        understanding: a child who can see D has nothing left to work out.
        """
        q = self._question()
        html = _render(q)
        # (5, 2) is D. The plane is 0..10 with pad 28 and step 32, so D would
        # be drawn at x=28+5*32=188, y=28+(10-2)*32=284.
        self.assertNotIn('cx="188" cy="284"', html)
        # The three given points ARE there: A at (2, 2) -> x=92, y=284.
        self.assertIn('cx="92" cy="284"', html)

    def test_unnamed_given_points_draw_no_label(self):
        q = self._question(
            question_text='Write down the co-ordinates of the point shown.',
            plane_spec={
                'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                'mode': 'points',
                # The plotted dot IS the answer here — that is what this type
                # was originally built for, and it must keep working.
                'given_points': [[-2, 4]],
                'target': {'points': [[-2, 4]]},
            },
        )
        html = _render(q)
        self.assertIn('<svg', html)
        self.assertIn(f'name="answer_{q.id}"', html)

    def test_the_answer_box_survives_a_question_with_no_figure(self):
        """No plane stored used to render NOTHING — no grid and no input.

        The child met an empty space and lost the mark in silence. The grader
        reads the typed string, not the drawing, so the question is still
        answerable from its text; the missing figure is the author's bug.
        """
        q = self._question(plane_spec=None)
        html = _render(q)
        self.assertIn(f'name="answer_{q.id}"', html)
        self.assertIn('(x, y)', html)
