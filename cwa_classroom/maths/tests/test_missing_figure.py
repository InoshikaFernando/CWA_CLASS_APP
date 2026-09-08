"""The MISSING-FIGURE check: questions whose picture never reaches the page.

CPP-406. A student taking homework met "Measure X" with nothing above it and
asked how they were supposed to know what X was. The question was well-formed by
every check the bank had — right type, right numeric answer, right tolerance —
and completely unanswerable, because a length ``measure`` question generates no
figure of its own and this one had no image either.

Covers the three things that had to change:

* ``Question.renders_a_figure`` — one answer to "is there anything to look at",
  read by the take templates and the audit alike;
* ``verify_question_figure`` — finds the rest of them in the bank, by TYPE
  (a measure question with nothing to measure) and by WORDING ("the diagram
  below", "measure X");
* the take partial — says the figure is missing instead of laying a ruler over
  empty space.

Logic tests only. To find the questions actually affected in production, run

    python manage.py verify_question_answers --check MISSING-FIGURE
"""
from decimal import Decimal
from unittest.mock import PropertyMock, patch

from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level
from maths.answer_verification import (
    MISSING_FIGURE,
    verify_question,
    verify_question_figure,
)
from maths.models import Answer, Question


class RendersAFigureTests(TestCase):
    """What the student can actually see, decided in one place."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=971, defaults={'display_name': 'figure fixture'})

    def _q(self, **over):
        fields = dict(
            level=self.level, question_text='Measure X',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('6.5'), answer_tolerance=Decimal('0.2'),
            answer_unit='cm',
        )
        fields.update(over)
        return Question(**fields)

    def test_angle_measure_draws_its_own_figure(self):
        self.assertTrue(self._q(answer_unit='°').renders_a_figure)

    def test_length_measure_draws_nothing(self):
        # Only angles are drawable true-to-scale on an unknown screen, so a
        # length measure has nothing of its own to show.
        self.assertFalse(self._q().renders_a_figure)

    def test_an_uploaded_image_is_a_figure(self):
        self.assertTrue(self._q(image='questions/year7/measure/x.png')
                        .renders_a_figure)

    def test_plain_question_types_have_no_generated_figure(self):
        q = self._q(question_type=Question.MULTIPLE_CHOICE,
                    question_text='What is 2 + 2?')
        self.assertFalse(q.renders_a_figure)

    def test_spec_backed_type_draws_from_its_spec(self):
        q = self._q(
            question_type=Question.NUMBER_LINE, question_text='Mark 3.',
            answer_unit='', numeric_answer=None, answer_tolerance=None,
            number_line_spec={'min': 0, 'max': 10, 'step': 1,
                              'mode': 'mark', 'marks': [3]},
        )
        self.assertTrue(q.renders_a_figure)


class MeasureWithNoFigureTests(TestCase):
    """The reported defect, by question TYPE rather than by wording."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=972, defaults={'display_name': 'measure figure fixture'})

    def _measure(self, **over):
        fields = dict(
            level=self.level, question_text='Measure X',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('6.5'), answer_tolerance=Decimal('0.2'),
            answer_unit='cm',
        )
        fields.update(over)
        return Question.objects.create(**fields)

    def test_length_measure_without_an_image_is_flagged(self):
        issues = verify_question_figure(self._measure())
        self.assertEqual([i.code for i in issues], [MISSING_FIGURE])
        self.assertIn('measure', issues[0].detail)

    def test_length_measure_with_an_image_is_clean(self):
        q = self._measure(image='questions/year7/measure/ruler.png')
        self.assertEqual(verify_question_figure(q), [])

    def test_angle_measure_is_clean(self):
        # It generates its own figure from numeric_answer.
        q = self._measure(answer_unit='°', numeric_answer=Decimal('135'))
        self.assertEqual(verify_question_figure(q), [])

    def test_read_graph_without_a_graph_is_flagged(self):
        q = self._measure(question_type=Question.READ_GRAPH, answer_unit='cm',
                          question_text='Read off the value at x = 3.')
        self.assertEqual([i.code for i in verify_question_figure(q)],
                         [MISSING_FIGURE])

    def test_the_option_checks_still_pass_it(self):
        """The proof that this needed a new check at all.

        Every existing check is about answer options, and a measure question is
        not allowed to have any — so the bank reported this question as
        perfectly healthy right up until a child hit it.
        """
        issues, _verified = verify_question(self._measure())
        self.assertEqual(issues, [])

    def test_a_missing_spec_is_left_to_no_correct(self):
        """One fault, one finding.

        A self-graded type with its spec missing is already reported as
        NO-CORRECT naming the absent field. Reporting "and no figure" as well
        would send a reviewer to the same single fix twice.
        """
        q = self._measure(question_type=Question.DRAW_ON_GRID,
                          question_text='Draw the line of symmetry.',
                          numeric_answer=None, answer_tolerance=None,
                          answer_unit='')
        self.assertEqual(verify_question_figure(q), [])
        issues, _ = verify_question(q)
        self.assertIn('grid_spec', issues[0].detail)


class UnrenderableSpecTests(TestCase):
    """One bad row must not end a walk of nineteen thousand questions."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=976, defaults={'display_name': 'bad spec fixture'})

    def test_a_figure_that_cannot_be_built_is_reported_not_raised(self):
        """The audit walks the whole bank; a raise there stops everything.

        Every render property is defensive today — each returns None rather
        than throwing on a spec it cannot use — but a bulk-imported spec never
        went through ``clean()``, and the cost of one of those ten properties
        regressing is a nightly cron that stops recording, silently. The guard
        is cheap; this is what it does when it earns its keep.
        """
        q = Question.objects.create(
            level=self.level, question_text='Plot the points.',
            question_type=Question.PLOT_POINTS, difficulty=1, points=1,
            plane_spec={'xmin': 0, 'xmax': 5, 'ymin': 0, 'ymax': 5,
                        'points': [[1, 2]]})

        with patch.object(Question, 'plane_data',
                          new_callable=PropertyMock) as plane_data:
            plane_data.side_effect = ValueError('malformed plane_spec')
            issues = verify_question_figure(q)

        self.assertEqual([i.code for i in issues], [MISSING_FIGURE])
        self.assertIn('cannot be built', issues[0].detail)
        self.assertIn('malformed plane_spec', issues[0].detail)


class FigureWordingTests(TestCase):
    """Questions of any type whose stem points at a picture that is not there."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=973, defaults={'display_name': 'wording fixture'})

    def _choice(self, text, *, image=''):
        q = Question.objects.create(
            level=self.level, question_text=text, image=image,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='4', is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='6', is_correct=False, order=1)
        return q

    def test_deictic_reference_without_an_image_is_flagged(self):
        for text in ('What is the perimeter of this shape?',
                     'How many faces does the diagram below show?',
                     'Read the value shown on the number line.',
                     'Which angle is largest, as shown?'):
            with self.subTest(text):
                issues = verify_question_figure(self._choice(text))
                self.assertEqual([i.code for i in issues], [MISSING_FIGURE])

    def test_bare_label_reference_is_flagged(self):
        # The CPP-406 wording, on a type that generates nothing of its own.
        for text in ('Measure X', 'Measure AB and write down the length.'):
            with self.subTest(text):
                self.assertEqual(
                    [i.code for i in verify_question_figure(self._choice(text))],
                    [MISSING_FIGURE])

    def test_the_same_wording_with_an_image_is_clean(self):
        q = self._choice('What is the perimeter of this shape?',
                         image='questions/year7/measurement/shape.png')
        self.assertEqual(verify_question_figure(q), [])

    def test_text_only_questions_are_left_alone(self):
        """Under-report rather than cry wolf.

        MISSING-FIGURE is blocking — it fails the audit run — so a pattern that
        fires on questions spelled out in words would bury the real backlog.
        """
        for text in ('A rectangle has a perimeter of 20cm and a length of 6cm. '
                     'What is its width?',
                     'Measure a line of 5 cm with your ruler.',
                     'What is 9/10 - 3/5?',
                     'Estimate the mass of a pet cat.'):
            with self.subTest(text):
                self.assertEqual(verify_question_figure(self._choice(text)), [])

    def test_a_printed_sequence_is_not_a_missing_figure(self):
        """The stem prints the pattern, so nothing is missing from the page.

        166 of the weekly audit's 248 flags were MISSING-FIGURE and most were
        this: "pattern" is a figure word, but a number-pattern question puts
        the sequence in its own text. Nearly all of Year 1-4 Number Patterns
        and Skip Counting was flagged for a picture it never wanted, which
        buries the questions that really are unanswerable.
        """
        for text in (
                'Look at the pattern 0, 2, 4, 6, 8. Complete the sentence: '
                'This pattern is going up by ______.',
                'Work out the number pattern rule and complete the pattern: '
                '65, __, 75, 80',
                'Continue the pattern of counting by 5s: 55, 60, 65, 70, ___',
                'What is the missing letter in the pattern: B, F, J, ____, '
                'R, V, Z?',
                'What is the missing term in the pattern: Q, 9, Q, 9, Q, 9, '
                '____, 9, Q, 9?'):
            with self.subTest(text):
                self.assertEqual(verify_question_figure(self._choice(text)), [])

    def test_a_pattern_with_nothing_printed_is_still_flagged(self):
        """The exemption is for a sequence on the page, not for the word."""
        for text in ('Continue the pattern.',
                     'Draw the next step of this pattern.',
                     'Complete the pattern shown below: 2, 4, 6, ___'):
            with self.subTest(text):
                self.assertEqual(
                    [i.code for i in verify_question_figure(self._choice(text))],
                    [MISSING_FIGURE])

    def test_a_second_figure_word_is_not_excused_by_the_sequence(self):
        """Only the pattern reference is answered by a printed sequence."""
        q = self._choice('Copy the pattern in the diagram: 1, 2, 3, ___')
        self.assertEqual([i.code for i in verify_question_figure(q)],
                         [MISSING_FIGURE])

    def test_an_option_list_is_not_a_sequence(self):
        """"A, B, C, D" is a list of pictures to choose between.

        Bare letters with no number and no blank are what a multiple choice
        looks like, so they must not excuse the missing picture.
        """
        q = self._choice('Which of these shapes is a kite? A, B, C, D')
        self.assertEqual([i.code for i in verify_question_figure(q)],
                         [MISSING_FIGURE])

    def test_scaffolding_types_are_exempt(self):
        # "the grid" here is the column-arithmetic layout, transcribed into
        # the structured fields — never a picture.
        q = Question.objects.create(
            level=self.level, question_text='Work out 24 x 3 using the grid.',
            question_type=Question.COLUMN_OPERATION, difficulty=1, points=1,
            operands=[24, 3], operator='x')
        self.assertEqual(verify_question_figure(q), [])


class MeasureTakePartialTests(TestCase):
    """What the child sees when the figure is missing."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=974, defaults={'display_name': 'measure take fixture'})

    def _render(self, q):
        return render_to_string(
            'homework/partials/_maths_take_item.html',
            {'ctx': {'question': q, 'shuffled_answers': []}})

    def test_missing_figure_says_so_instead_of_showing_a_ruler(self):
        q = Question.objects.create(
            level=self.level, question_text='Measure X',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('6.5'), answer_tolerance=Decimal('0.2'),
            answer_unit='cm')
        html = self._render(q)

        self.assertIn('missing the figure', html)
        # No instrument over empty space, and no hint telling the child to
        # drag one — that is what made the page unreadable.
        self.assertNotIn('data-measure-tool', html)
        self.assertNotIn('Drag the ruler', html)
        # The answer box still renders: a student who can work the value out
        # another way is not blocked by the author's mistake.
        self.assertIn(f'name="answer_{q.id}"', html)

    def test_a_question_with_a_figure_still_gets_the_instrument(self):
        q = Question.objects.create(
            level=self.level, question_text='Measure angle a.',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('135'), answer_tolerance=Decimal('2'),
            answer_unit='°')
        html = self._render(q)

        self.assertIn('data-measure-tool', html)
        self.assertNotIn('missing the figure', html)


class AuditSurfacesTests(TestCase):
    """The check is only worth having if it reaches the people who fix things.

    Three surfaces read it: the CLI audit (which fails a run), the nightly
    health snapshot (the trend the super-admin dashboard draws), and the live
    Question Check page. A check wired into none of them would find CPP-406's
    siblings and tell nobody.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=975, defaults={'display_name': 'audit fixture'})
        Question.objects.create(
            level=cls.level, question_text='Measure X',
            question_type=Question.MEASURE, difficulty=1, points=1,
            numeric_answer=Decimal('6.5'), answer_tolerance=Decimal('0.2'),
            answer_unit='cm')

    def test_the_cli_audit_fails_the_run(self):
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_question_answers', '--level', 975,
                         '--check', MISSING_FIGURE, '--quiet')
        self.assertEqual(ctx.exception.code, 1)

    def test_the_health_snapshot_counts_it_as_blocking(self):
        from maths.models import QuestionHealthSnapshot

        call_command('record_question_health', '--level', 975, '--quiet')

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.issue_counts.get(MISSING_FIGURE), 1)
        self.assertEqual(snapshot.questions_blocking, 1)

    def test_the_check_page_labels_it(self):
        """SCREAMING-KEBAB-CASE in the dashboard makes a reviewer decode it."""
        from maths.views_admin import CODE_LABELS

        self.assertIn(MISSING_FIGURE, CODE_LABELS)
