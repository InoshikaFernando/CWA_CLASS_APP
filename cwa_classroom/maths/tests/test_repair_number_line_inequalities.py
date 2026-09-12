"""``repair_number_line_inequalities`` — the questions already in the bank.

The reported Q10/Q11 were stored with their answer key spelled out as a list of
ticks that stopped one short, so a correct graph was marked wrong. Deriving the
key from the inequality fixes every question that STATES one; this command is
what converts the stored specs. These pin what it repairs, what it refuses to
touch, and that it is a dry run until asked.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from classroom.models import Level
from maths.geometry_grading import grade_number_line
from maths.models import Question


def _marks(values):
    return '{"marks": [%s]}' % ', '.join(str(v) for v in values)


class RepairNumberLineInequalitiesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=995, defaults={'display_name': 'inequality repair fixture'})

    def _question(self, text, spec):
        return Question.objects.create(
            level=self.level, question_text=text, difficulty=1, points=1,
            question_type=Question.NUMBER_LINE, number_line_spec=spec,
        )

    def _q10(self):
        """The reported question, exactly as it grades today: the key stops at
        -3, so the student's correct mark on the boundary reads as an extra."""
        return self._question(
            'Draw a graph for the inequality k <= -2.',
            {'min': -7, 'max': 7, 'step': 1, 'mode': 'mark',
             'target': [-7, -6, -5, -4, -3]},
        )

    def _q11(self):
        return self._question(
            'Draw a graph for the inequality m > 1.',
            {'min': -7, 'max': 7, 'step': 1, 'mode': 'mark',
             'target': [2, 3, 4, 5, 6]},
        )

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command('repair_number_line_inequalities', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    # ── the reported bug, before and after ───────────────────────────────

    def test_the_reported_answers_are_wrong_before_the_repair(self):
        q10, q11 = self._q10(), self._q11()
        self.assertFalse(grade_number_line(
            q10.number_line_spec, _marks([-2, -3, -4, -5, -6, -7])))
        self.assertFalse(grade_number_line(
            q11.number_line_spec, _marks([2, 3, 4, 5, 6, 7])))

    def test_repair_makes_the_reported_answers_correct(self):
        q10, q11 = self._q10(), self._q11()
        self._run('--apply')
        q10.refresh_from_db()
        q11.refresh_from_db()
        self.assertEqual(q10.number_line_spec['inequality'],
                         {'op': '<=', 'value': -2})
        self.assertEqual(q10.number_line_spec['target'],
                         [-7, -6, -5, -4, -3, -2])
        self.assertTrue(grade_number_line(
            q10.number_line_spec, _marks([-2, -3, -4, -5, -6, -7])))
        self.assertEqual(q11.number_line_spec['inequality'], {'op': '>', 'value': 1})
        self.assertTrue(grade_number_line(
            q11.number_line_spec, _marks([2, 3, 4, 5, 6, 7])))

    def test_repaired_answers_still_reject_a_wrong_graph(self):
        q10 = self._q10()
        self._run('--apply')
        q10.refresh_from_db()
        # The boundary belongs in the answer, so leaving it out is still wrong,
        # and so is a mark past it.
        self.assertFalse(grade_number_line(
            q10.number_line_spec, _marks([-7, -6, -5, -4, -3])))
        self.assertFalse(grade_number_line(
            q10.number_line_spec, _marks([-7, -6, -5, -4, -3, -2, -1])))

    # ── dry run / reporting ──────────────────────────────────────────────

    def test_dry_run_writes_nothing(self):
        q10 = self._q10()
        out, _err = self._run()
        self.assertIn('Dry run', out)
        self.assertIn(f'Q{q10.id}', out)
        q10.refresh_from_db()
        self.assertNotIn('inequality', q10.number_line_spec)
        self.assertEqual(q10.number_line_spec['target'], [-7, -6, -5, -4, -3])

    def test_reports_the_stored_and_correct_keys(self):
        self._q10()
        out, _err = self._run()
        self.assertIn('[-7, -6, -5, -4, -3]', out)          # stored
        self.assertIn('[-7, -6, -5, -4, -3, -2]', out)      # correct

    def test_single_question_scope(self):
        q10, q11 = self._q10(), self._q11()
        self._run('--question', str(q10.id), '--apply')
        q10.refresh_from_db()
        q11.refresh_from_db()
        self.assertIn('inequality', q10.number_line_spec)
        self.assertNotIn('inequality', q11.number_line_spec)

    def test_unknown_question_id_errors(self):
        with self.assertRaises(CommandError):
            self._run('--question', '999999')

    # ── what it refuses to touch ─────────────────────────────────────────

    def test_leaves_a_plain_mark_question_alone(self):
        q = self._question('Mark 2 on the number line.',
                           {'min': -3, 'max': 7, 'step': 1,
                            'mode': 'mark', 'target': [2]})
        self._run('--apply')
        q.refresh_from_db()
        self.assertEqual(q.number_line_spec['target'], [2])
        self.assertNotIn('inequality', q.number_line_spec)

    def test_leaves_a_compound_inequality_alone(self):
        # Two statements in one question — a person decides, not a guess.
        q = self._question('Draw a graph for 1 < x <= 4.',
                           {'min': -7, 'max': 7, 'step': 1,
                            'mode': 'mark', 'target': [2, 3, 4]})
        self._run('--apply')
        q.refresh_from_db()
        self.assertNotIn('inequality', q.number_line_spec)

    def test_leaves_a_read_mode_question_alone(self):
        q = self._question('The arrow shows a value where x > 1. Read it.',
                           {'min': -7, 'max': 7, 'step': 1,
                            'mode': 'read', 'given': [3]})
        self._run('--apply')
        q.refresh_from_db()
        self.assertNotIn('inequality', q.number_line_spec)

    def test_an_inequality_no_tick_satisfies_is_reported_not_repaired(self):
        # The line stops at -7, so "k < -7" has nothing to mark: the scale is
        # wrong, and an empty answer key would be worse than the broken one.
        q = self._question('Draw a graph for the inequality k < -7.',
                           {'min': -7, 'max': 7, 'step': 1,
                            'mode': 'mark', 'target': [-7]})
        _out, err = self._run('--apply')
        self.assertIn(f'Q{q.id}', err)
        q.refresh_from_db()
        self.assertNotIn('inequality', q.number_line_spec)

    # ── converting a key that was already right, and re-running ──────────

    def test_converts_a_correct_enumeration_too(self):
        q = self._question('Draw a graph for the inequality x >= 5.',
                           {'min': -7, 'max': 7, 'step': 1,
                            'mode': 'mark', 'target': [5, 6, 7]})
        self._run('--apply')
        q.refresh_from_db()
        self.assertEqual(q.number_line_spec['inequality'], {'op': '>=', 'value': 5})
        self.assertEqual(q.number_line_spec['target'], [5, 6, 7])

    def test_second_run_is_a_no_op(self):
        q10 = self._q10()
        self._run('--apply')
        q10.refresh_from_db()
        first = dict(q10.number_line_spec)
        out, _err = self._run('--apply')
        q10.refresh_from_db()
        self.assertEqual(q10.number_line_spec, first)
        self.assertIn('0 question(s) repaired', out)
