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
