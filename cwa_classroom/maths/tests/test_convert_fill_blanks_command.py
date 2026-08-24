"""Tests for the ``convert_fill_blanks`` management command.

The command finds typed questions whose text carries "___" gaps and turns them
into fill-in-the-blank questions. What is checked here is mostly what it must
NOT do: not write on a dry run, not touch the answer rows, not convert an MCQ,
and above all not guess when the stored answer cannot be mapped onto the gaps.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question

SENTENCE = 'The survivors are expected to ___ for another ___ years.'


class ConvertFillBlanksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993, defaults={'display_name': 'convert fixture'})

    def _question(self, text=SENTENCE, answer='live; 67.0',
                  question_type=Question.SHORT_ANSWER, **overrides):
        fields = dict(
            level=self.level, question_text=text, question_type=question_type,
            difficulty=1, points=1,
        )
        fields.update(overrides)
        q = Question.objects.create(**fields)
        if answer is not None:
            Answer.objects.create(question=q, answer_text=answer,
                                  is_correct=True, order=1)
        return q

    def _run(self, *args):
        out = StringIO()
        call_command('convert_fill_blanks', *args, stdout=out, stderr=out)
        return out.getvalue()

    # ── the happy path ───────────────────────────────────────────────────

    def test_apply_converts_and_sets_the_type(self):
        q = self._question()
        self._run('--apply')
        q.refresh_from_db()
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertEqual(
            q.blank_spec,
            {'blanks': [{'answers': ['live']}, {'answers': ['67.0']}]})

    def test_the_converted_question_grades(self):
        q = self._question()
        self._run('--apply')
        q.refresh_from_db()
        self.assertTrue(q.grade_text_answer('{"blanks": ["live", "67.0"]}'))

    def test_dry_run_writes_nothing(self):
        q = self._question()
        output = self._run()
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, Question.SHORT_ANSWER)
        self.assertIn('Would convert 1', output)

    def test_the_answer_rows_survive(self):
        # Keeping them is what BrainBuzz snapshots, what exports carry, and what
        # makes --revert lossless.
        q = self._question()
        self._run('--apply')
        self.assertEqual([a.answer_text for a in q.answers.all()], ['live; 67.0'])

    def test_rerunning_is_a_no_op(self):
        q = self._question()
        self._run('--apply')
        output = self._run('--apply')
        self.assertIn('No questions matched', output)
        q.refresh_from_db()
        self.assertIsNotNone(q.blank_spec)

    # ── what it refuses to touch ─────────────────────────────────────────

    def test_leaves_choice_questions_alone(self):
        q = self._question(question_type=Question.MULTIPLE_CHOICE)
        self._run('--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, Question.MULTIPLE_CHOICE)

    def test_leaves_questions_without_gaps_alone(self):
        q = self._question(text='What is 2 + 2?', answer='4')
        self._run('--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)

    def test_a_single_underscore_is_not_a_gap(self):
        q = self._question(text='Find a_1 given a_2 = 5.', answer='3')
        self._run('--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)

    def test_reports_rather_than_guesses_an_unmappable_answer(self):
        q = self._question(answer='live for sixty seven years')
        output = self._run('--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, Question.SHORT_ANSWER)
        self.assertIn(f'Q{q.pk}', output)
        self.assertIn('does not split', output)
        self.assertIn('1 skipped', output)

    def test_reports_a_question_with_no_stored_answer(self):
        q = self._question(answer=None)
        output = self._run('--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertIn('no correct answer', output)

    # ── scoping ──────────────────────────────────────────────────────────

    def test_min_blanks_targets_multi_gap_sentences(self):
        one = self._question(text='The answer is ___.', answer='42')
        two = self._question()
        self._run('--min-blanks', '2', '--apply')
        one.refresh_from_db()
        two.refresh_from_db()
        self.assertIsNone(one.blank_spec)
        self.assertIsNotNone(two.blank_spec)

    def test_id_filter_limits_the_scope(self):
        first = self._question()
        second = self._question()
        self._run('--id', str(first.pk), '--apply')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(first.blank_spec)
        self.assertIsNone(second.blank_spec)

    def test_level_filter_limits_the_scope(self):
        other, _ = Level.objects.get_or_create(
            level_number=994, defaults={'display_name': 'other'})
        mine = self._question()
        theirs = self._question(level=other)
        self._run('--level', '993', '--apply')
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertIsNotNone(mine.blank_spec)
        self.assertIsNone(theirs.blank_spec)

    def test_force_rebuilds_an_existing_spec(self):
        q = self._question()
        self._run('--apply')
        q.answers.update(answer_text='survive; 70.0')
        self._run('--force', '--apply')
        q.refresh_from_db()
        self.assertEqual(q.blank_spec['blanks'][0]['answers'], ['survive'])

    # ── revert ───────────────────────────────────────────────────────────

    def test_revert_clears_the_spec_and_leaves_a_working_question(self):
        q = self._question()
        self._run('--apply')
        self._run('--revert', '--apply')
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        # Back to the single-box form, still grading against its original answer.
        self.assertTrue(q.grade_text_answer('live; 67.0'))

    def test_revert_dry_run_writes_nothing(self):
        q = self._question()
        self._run('--apply')
        self._run('--revert')
        q.refresh_from_db()
        self.assertIsNotNone(q.blank_spec)


class BareUnitAnswerRepairTests(TestCase):
    """``--add-bare-unit-answers``: the one refusal with a mechanical fix.

    Fourteen metric-conversion questions on production stored "5300 mL" as the
    only answer to "= _____ mL", which inline reads "= [5300 mL] mL" and marks
    the obvious "5300" wrong. The flag stores the bare value beside it.
    """

    UNIT_Q = 'Convert to millilitres: 5.3 L = _____ mL'

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992, defaults={'display_name': 'unit fixture'})

    def _question(self, text=None, answers=('5300 mL',)):
        q = Question.objects.create(
            level=self.level, question_text=text or self.UNIT_Q,
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        for order, answer_text in enumerate(answers, start=1):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=True, order=order)
        return q

    def _run(self, *args):
        out = StringIO()
        call_command('convert_fill_blanks', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_without_the_flag_the_question_is_refused(self):
        q = self._question()
        out = self._run('--apply')
        self.assertIn('repeat the unit', out)
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.answers.count(), 1)

    def test_the_flag_adds_the_bare_value_and_converts(self):
        q = self._question()
        out = self._run('--add-bare-unit-answers', '--apply')
        q.refresh_from_db()
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertEqual(q.blank_spec,
                         {'blanks': [{'answers': ['5300 mL', '5300']}]})
        self.assertIn("+ '5300'", out)
        self.assertIn('Added a bare-value answer to 1 question', out)

    def test_the_original_answer_row_is_kept(self):
        # A student who writes the unit was correct before the gap went inline
        # and must still be.
        q = self._question()
        self._run('--add-bare-unit-answers', '--apply')
        texts = sorted(a.answer_text for a in q.answers.all())
        self.assertEqual(texts, ['5300', '5300 mL'])
        self.assertTrue(q.answers.filter(answer_text='5300 mL',
                                         is_correct=True).exists())

    def test_both_spellings_grade_correct_afterwards(self):
        q = self._question()
        self._run('--add-bare-unit-answers', '--apply')
        q.refresh_from_db()
        self.assertTrue(q.grade_text_answer('{"blanks": ["5300"]}'))
        self.assertTrue(q.grade_text_answer('{"blanks": ["5300 mL"]}'))
        self.assertFalse(q.grade_text_answer('{"blanks": ["53"]}'))

    def test_a_dry_run_writes_nothing_but_reports_the_real_outcome(self):
        # The rows are written inside a savepoint and rolled back, so the dry
        # run can show the spec the real run would build. Nothing may survive.
        q = self._question()
        out = self._run('--add-bare-unit-answers')
        self.assertIn('Would add a bare-value answer to 1 question', out)
        self.assertIn('Would convert 1 question', out)
        q.refresh_from_db()
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, Question.SHORT_ANSWER)
        self.assertEqual(q.answers.count(), 1)

    def test_running_twice_adds_nothing_the_second_time(self):
        q = self._question()
        self._run('--add-bare-unit-answers', '--apply')
        self._run('--add-bare-unit-answers', '--apply', '--force')
        self.assertEqual(q.answers.count(), 2)

    def test_a_question_it_cannot_repair_keeps_its_own_reason(self):
        # Not re-reported as "nothing to convert" — the refusal a human has to
        # act on must survive the attempted repair.
        self._question(text='The area is ___ and the perimeter is ___.',
                       answers=('12 and 14 and 16',))
        out = self._run('--add-bare-unit-answers', '--apply')
        self.assertIn('does not split into 2 values', out)
        self.assertNotIn('nothing to convert', out)

    def test_it_leaves_other_questions_alone(self):
        q = self._question(text='An _______ is a whole number.',
                           answers=('integer',))
        self._run('--add-bare-unit-answers', '--apply')
        q.refresh_from_db()
        self.assertEqual(q.answers.count(), 1)
        self.assertEqual(q.blank_spec, {'blanks': [{'answers': ['integer']}]})

