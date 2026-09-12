"""Everything that is NOT an inequality graph still behaves exactly as before.

The inequality fix changed shared ground: ``number_line_targets`` now feeds both
grading and the answer key, ``validate_number_line_spec`` grew a branch, and a
management command sweeps the question bank. Each of those is reached by every
number-line question in the app, and the command sees every question of every
type, so the blast radius is wider than the questions it was written for.

These pin the blast radius shut:

  * a plain mark / read spec grades, validates and renders precisely as it did;
  * the question's TEXT never reaches the grader — reading an inequality off the
    wording belongs to the repair command alone, and wiring it into grading
    would silently rewrite the answer to questions nobody asked about;
  * the repair command leaves every other question — other modes, other types —
    byte-identical.

Pinning the OLD behaviour on purpose: if a later change to the inequality path
moves any of this, these fail rather than the app quietly re-marking questions
that were never broken.
"""
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from io import StringIO

from classroom.models import Level
from maths.geometry_grading import (
    grade_number_line,
    number_line_targets,
    parse_inequality_text,
    validate_number_line_spec,
)
from maths.models import Answer, Question

PLAIN_MARK = {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2, 5]}
PLAIN_READ = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]}


class PlainSpecGradingUnchangedTests(SimpleTestCase):
    """The mark/read behaviour that existed before the inequality block."""

    def test_mark_set_comparison(self):
        self.assertTrue(grade_number_line(PLAIN_MARK, '{"marks": [2, 5]}'))
        self.assertTrue(grade_number_line(PLAIN_MARK, '{"marks": [5, 2]}'))
        self.assertFalse(grade_number_line(PLAIN_MARK, '{"marks": [2]}'))
        self.assertFalse(grade_number_line(PLAIN_MARK, '{"marks": [2, 5, 6]}'))

    def test_mark_int_float_equivalence(self):
        self.assertTrue(grade_number_line(PLAIN_MARK, '{"marks": [2.0, 5.0]}'))

    def test_mark_malformed_payload_is_wrong_not_an_error(self):
        for payload in ('', 'not json', '{"marks": "x"}', '{}', None):
            self.assertFalse(grade_number_line(PLAIN_MARK, payload))

    def test_read_exact_and_tolerance(self):
        self.assertTrue(grade_number_line(PLAIN_READ, '6'))
        self.assertFalse(grade_number_line(PLAIN_READ, '7'))
        tol = dict(PLAIN_READ, tolerance=1)
        self.assertTrue(grade_number_line(tol, '7'))
        self.assertFalse(grade_number_line(tol, '8'))

    def test_read_multiset_and_units(self):
        multi = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [2, 8]}
        self.assertTrue(grade_number_line(multi, '8 2'))
        self.assertFalse(grade_number_line(multi, '2, 8, 8'))
        self.assertTrue(grade_number_line(PLAIN_READ, '6 cm'))

    def test_decimal_step_spec(self):
        spec = {'min': 0, 'max': 0.3, 'step': 0.1, 'mode': 'mark', 'target': [0.3]}
        validate_number_line_spec(spec)
        self.assertTrue(grade_number_line(spec, '{"marks": [0.3]}'))

    def test_targets_are_the_stored_list_untouched(self):
        # Same values, same order — nothing derived, nothing re-sorted.
        self.assertEqual(number_line_targets(PLAIN_MARK), [2, 5])
        self.assertEqual(number_line_targets({'min': -3, 'max': 7, 'step': 1,
                                              'mode': 'mark', 'target': [5, 2]}),
                         [5, 2])

    def test_read_target_defaults_to_given(self):
        self.assertEqual(number_line_targets(PLAIN_READ), [6])
        explicit = dict(PLAIN_READ, target=[4])
        self.assertEqual(number_line_targets(explicit), [4])

    def test_no_targets_at_all_grades_wrong(self):
        self.assertFalse(grade_number_line({'min': 0, 'max': 5, 'step': 1,
                                            'mode': 'mark'}, '{"marks": [2]}'))
        self.assertFalse(grade_number_line('nope', '{"marks": [2]}'))


class ValidationUnchangedTests(SimpleTestCase):
    """The strict gate accepts and refuses exactly what it used to.

    The mark branch became an ``elif`` behind the inequality check and the read
    branch a standalone ``if`` — a restructure that would be easy to get subtly
    wrong, so every previously-pinned case is re-pinned here.
    """

    VALID = (
        ('mark', {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2]}),
        ('read', {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]}),
        ('read with explicit target',
         {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6], 'target': [6]}),
        ('read with tolerance',
         {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6], 'tolerance': 1}),
        ('mode defaults to mark', {'min': 0, 'max': 5, 'step': 1, 'target': [3]}),
        ('multi-target mark',
         {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2, 5]}),
    )

    INVALID = (
        ('not an object', [1, 2, 3]),
        ('min not below max',
         {'min': 5, 'max': 5, 'step': 1, 'mode': 'mark', 'target': [5]}),
        ('bad step', {'min': 0, 'max': 5, 'step': -1, 'mode': 'mark', 'target': [3]}),
        ('unknown mode',
         {'min': 0, 'max': 5, 'step': 1, 'mode': 'wiggle', 'target': [3]}),
        ('off-tick target',
         {'min': 0, 'max': 10, 'step': 2, 'mode': 'mark', 'target': [3]}),
        ('out-of-range target',
         {'min': 0, 'max': 5, 'step': 1, 'mode': 'mark', 'target': [9]}),
        ('empty target', {'min': 0, 'max': 5, 'step': 1, 'mode': 'mark', 'target': []}),
        ('mark with no target', {'min': 0, 'max': 5, 'step': 1, 'mode': 'mark'}),
        ('read with no given', {'min': 0, 'max': 5, 'step': 1, 'mode': 'read'}),
        ('read with off-tick target',
         {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6], 'target': [3]}),
        ('negative tolerance',
         {'min': 0, 'max': 5, 'step': 1, 'mode': 'read', 'given': [3], 'tolerance': -1}),
        ('too many ticks',
         {'min': 0, 'max': 5000, 'step': 1, 'mode': 'mark', 'target': [3]}),
    )

    def test_valid_specs_still_validate(self):
        for label, spec in self.VALID:
            with self.subTest(label):
                validate_number_line_spec(spec)  # must not raise

    def test_invalid_specs_still_raise(self):
        for label, spec in self.INVALID:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    validate_number_line_spec(spec)


class GradingNeverReadsTheQuestionTextTests(TestCase):
    """A stored key is the answer, even when the wording states an inequality.

    Reading the wording is the repair command's job, run deliberately by a
    person. If it ever leaked into grading, every question whose text happens to
    contain an inequality would silently have its answer replaced — including
    ones whose stored key is deliberately narrower than the whole ray.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=996, defaults={'display_name': 'isolation fixture'})

    def test_inequality_in_the_text_does_not_widen_a_plain_key(self):
        spec = {'min': -7, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [-2]}
        q = Question.objects.create(
            level=self.level, difficulty=1, points=1,
            question_text='Mark the boundary point of k <= -2 on the number line.',
            question_type=Question.NUMBER_LINE, number_line_spec=spec)
        # The question asks for ONE tick, and that is still what it takes.
        self.assertTrue(grade_number_line(q.number_line_spec, '{"marks": [-2]}'))
        self.assertFalse(grade_number_line(
            q.number_line_spec, '{"marks": [-7, -6, -5, -4, -3, -2]}'))
        self.assertEqual(q.number_line_data['target_values'], [-2])

    def test_text_between_two_numbers_is_not_an_inequality_to_read(self):
        # No variable, so nothing states a bound on anything.
        self.assertIsNone(parse_inequality_text('Which is true: 5 > 3 on the line?'))

    def test_answer_key_of_a_plain_question_is_the_stored_target(self):
        q = Question.objects.create(
            level=self.level, difficulty=1, points=1,
            question_text='Mark 2 and 5 on the number line.',
            question_type=Question.NUMBER_LINE, number_line_spec=PLAIN_MARK)
        data = q.number_line_data
        self.assertEqual(data['target_values'], [2, 5])
        self.assertEqual(len(data['dots']), 11)      # -3..7 all tappable
        self.assertEqual(data['mode'], 'mark')

    def test_answer_key_of_a_read_question_is_the_given_arrow(self):
        q = Question.objects.create(
            level=self.level, difficulty=1, points=1,
            question_text='What value does the arrow point to?',
            question_type=Question.NUMBER_LINE, number_line_spec=PLAIN_READ)
        data = q.number_line_data
        self.assertEqual(data['target_values'], [6])
        self.assertEqual([g['value'] for g in data['given']], [6])
        self.assertEqual(data['dots'], [])           # read mode taps nothing


class RepairCommandTouchesNothingElseTests(TestCase):
    """The sweep sees the whole bank. It must change only what it is for."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=997, defaults={'display_name': 'sweep fixture'})

    def _q(self, **kw):
        fields = dict(level=self.level, difficulty=1, points=1)
        fields.update(kw)
        return Question.objects.create(**fields)

    def setUp(self):
        self.plain_mark = self._q(
            question_text='Mark 2 and 5 on the number line.',
            question_type=Question.NUMBER_LINE, number_line_spec=dict(PLAIN_MARK))
        self.read = self._q(
            question_text='What value does the arrow point to?',
            question_type=Question.NUMBER_LINE, number_line_spec=dict(PLAIN_READ))
        self.numbers_only = self._q(
            question_text='Mark the number that makes 5 > 3 true.',
            question_type=Question.NUMBER_LINE,
            number_line_spec={'min': -7, 'max': 7, 'step': 1,
                              'mode': 'mark', 'target': [4]})
        self.plot = self._q(
            question_text='Plot the point where x > 1 crosses the axis.',
            question_type=Question.PLOT_POINTS,
            plane_spec={'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                        'mode': 'points', 'target': {'points': [[1, 0]]}})
        self.table = self._q(
            question_text='Complete the table for y = 2x.',
            question_type=Question.TABLE_OF_VALUES,
            table_spec={'headers': ['x', 'y'],
                        'rows': [[{'given': '1'}, {'answer': '2'}]]})
        self.calculation = self._q(
            question_text='Solve for x when x + 3 > 5.',
            question_type=Question.CALCULATION)
        Answer.objects.create(question=self.calculation, answer_text='x > 2',
                              is_correct=True)
        # Legacy shape: a question whose type was switched AWAY from number_line
        # and kept the orphaned spec. It states an inequality and has a spec to
        # rewrite, so only the question_type filter keeps the sweep off it — a
        # typed answer would start grading against a tick set nobody can mark.
        self.switched_away = self._q(
            question_text='Draw a graph for the inequality w >= 3.',
            question_type=Question.SHORT_ANSWER,
            number_line_spec={'min': -7, 'max': 7, 'step': 1, 'mode': 'mark',
                              'target': [3, 4, 5]})
        Answer.objects.create(question=self.switched_away, answer_text='w >= 3',
                              is_correct=True)
        self.before = {
            q.pk: (q.question_text, q.number_line_spec, q.plane_spec, q.table_spec)
            for q in (self.plain_mark, self.read, self.numbers_only, self.plot,
                      self.table, self.calculation, self.switched_away)
        }

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('repair_number_line_inequalities', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_apply_changes_nothing_when_there_is_no_inequality_graph(self):
        out, err = self._run('--apply')
        for pk, snapshot in self.before.items():
            q = Question.objects.get(pk=pk)
            with self.subTest(pk=pk, type=q.question_type):
                self.assertEqual(
                    (q.question_text, q.number_line_spec, q.plane_spec, q.table_spec),
                    snapshot)
        self.assertIn('0 question(s) repaired', out)
        self.assertEqual(err, '')

    def test_only_number_line_questions_are_even_considered(self):
        out, _err = self._run()
        # Three number-line questions are in scope; the plot/table/calculation
        # questions are not, whatever their wording says.
        self.assertIn('3 number-line question(s)', out)
        self.assertNotIn(f'Q{self.plot.id}:', out)
        self.assertNotIn(f'Q{self.calculation.id}:', out)
        # Not even the one carrying an orphaned spec and an inequality in its
        # wording — it is no longer a number-line question.
        self.assertNotIn(f'Q{self.switched_away.id}:', out)

    def test_a_repair_run_leaves_its_neighbours_alone(self):
        # One broken inequality graph alongside the rest: it is repaired, and
        # everything around it comes out of the sweep unchanged.
        broken = self._q(
            question_text='Draw a graph for the inequality k <= -2.',
            question_type=Question.NUMBER_LINE,
            number_line_spec={'min': -7, 'max': 7, 'step': 1, 'mode': 'mark',
                              'target': [-7, -6, -5, -4, -3]})
        self._run('--apply')
        broken.refresh_from_db()
        self.assertEqual(broken.number_line_spec['target'],
                         [-7, -6, -5, -4, -3, -2])
        for pk, snapshot in self.before.items():
            q = Question.objects.get(pk=pk)
            with self.subTest(pk=pk):
                self.assertEqual(
                    (q.question_text, q.number_line_spec, q.plane_spec, q.table_spec),
                    snapshot)

    def test_plain_questions_still_grade_after_a_sweep(self):
        self._run('--apply')
        self.plain_mark.refresh_from_db()
        self.read.refresh_from_db()
        self.assertTrue(grade_number_line(
            self.plain_mark.number_line_spec, '{"marks": [2, 5]}'))
        self.assertFalse(grade_number_line(
            self.plain_mark.number_line_spec, '{"marks": [2]}'))
        self.assertTrue(grade_number_line(self.read.number_line_spec, '6'))
