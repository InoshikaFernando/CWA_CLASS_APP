"""Model + plugin-dispatch tests for fill-in-the-blank questions.

The ``Question.clean()`` branch that validates ``blank_spec`` against the gaps in
the question text, the ``blank_data`` render helper, ``rebuild_blank_spec`` (the
shared derivation), answer display, and the maths-plugin grading dispatch
(homework take surface). Mirrors ``test_table_of_values_model``.
"""
import json

from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question
from maths.plugin import MathsPlugin

SENTENCE = (
    'Out of 100 000 births, 99 231 females are expected to survive to the age '
    'of ___. From that age, the survivors are expected to ___ for another '
    '67.0 years.'
)
SPEC = {'blanks': [{'answers': ['15']}, {'answers': ['live', 'survive']}]}


def _payload(*values):
    return json.dumps({'blanks': list(values)})


class FillBlankModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992, defaults={'display_name': 'fill_blank fixture'})

    def _build(self, **overrides):
        fields = dict(
            level=self.level,
            question_text=SENTENCE,
            question_type=Question.FILL_BLANK,
            difficulty=1,
            points=1,
            blank_spec=SPEC,
        )
        fields.update(overrides)
        return Question(**fields)

    # ── clean(): spec validated against the text ─────────────────────────

    def test_valid_spec_passes(self):
        self._build().full_clean()  # must not raise

    def test_spec_is_optional(self):
        # A fill_blank question with no spec is the legacy single-box shape,
        # which still works and must keep validating.
        self._build(blank_spec=None).full_clean()

    def test_rejects_a_spec_that_does_not_match_the_text(self):
        q = self._build(question_text='Only one gap: ___')
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('blank_spec', ctx.exception.error_dict)

    def test_rejects_a_malformed_spec(self):
        q = self._build(blank_spec={'blanks': [{'answers': []}, {'answers': ['x']}]})
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('blank_spec', ctx.exception.error_dict)

    def test_rejects_a_spec_on_another_type(self):
        # blank_spec is never read for another type, so one set there is a
        # mis-set field rather than a stored preference.
        q = self._build(question_type=Question.SHORT_ANSWER)
        with self.assertRaises(ValidationError) as ctx:
            q.full_clean()
        self.assertIn('blank_spec', ctx.exception.error_dict)

    def test_answer_rows_are_allowed(self):
        # Unlike the spec-graded geometry types, a converted question KEEPS its
        # original answer rows — that is what makes the conversion reversible.
        q = self._build()
        q.save()
        Answer.objects.create(question=q, answer_text='15; live', is_correct=True)
        q.clean()  # must not raise

    # ── blank_data render helper ─────────────────────────────────────────

    def test_render_data_interleaves_text_and_gaps(self):
        d = self._build().blank_data
        self.assertEqual(d['count'], 2)
        gaps = [p for p in d['parts'] if 'index' in p]
        text = [p for p in d['parts'] if 'text' in p]
        self.assertEqual([g['index'] for g in gaps], [0, 1])
        self.assertEqual(len(text), 3)
        self.assertTrue(text[0]['text'].startswith('Out of 100 000 births'))
        self.assertTrue(text[2]['text'].endswith('67.0 years.'))

    def test_render_data_carries_the_answer_for_the_teacher_key(self):
        gaps = [p for p in self._build().blank_data['parts'] if 'index' in p]
        self.assertEqual(gaps[0]['answer'], '15')
        self.assertEqual(gaps[1]['answer'], 'live or survive')

    def test_input_size_follows_the_longest_answer(self):
        gaps = [p for p in self._build().blank_data['parts'] if 'index' in p]
        # "15" is shorter than the floor; "survive" (7) sits between the bounds.
        self.assertEqual(gaps[0]['size'], 4)
        self.assertEqual(gaps[1]['size'], 7)

    def test_render_data_none_without_a_spec(self):
        self.assertIsNone(self._build(blank_spec=None).blank_data)

    def test_render_data_none_for_other_types(self):
        q = Question(level=self.level, question_text=SENTENCE, points=1,
                     question_type=Question.SHORT_ANSWER)
        self.assertIsNone(q.blank_data)

    def test_render_data_none_when_the_spec_drifted_from_the_text(self):
        # Content edited around the validator must degrade to the plain box
        # rather than render a sentence with a gap that has no input.
        q = self._build(question_text='Only one gap: ___')
        self.assertIsNone(q.blank_data)

    # ── rebuild_blank_spec — the shared derivation ───────────────────────

    def test_rebuild_from_one_row_per_blank(self):
        q = self._build(blank_spec=None)
        q.save()
        Answer.objects.create(question=q, answer_text='15', is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text='live', is_correct=True, order=2)
        applied, reason = q.rebuild_blank_spec()
        self.assertTrue(applied, reason)
        self.assertEqual(
            q.blank_spec, {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_rebuild_uses_row_order_not_insertion_order(self):
        q = self._build(blank_spec=None)
        q.save()
        Answer.objects.create(question=q, answer_text='live', is_correct=True, order=2)
        Answer.objects.create(question=q, answer_text='15', is_correct=True, order=1)
        q.rebuild_blank_spec()
        self.assertEqual(q.blank_spec['blanks'][0]['answers'], ['15'])

    def test_rebuild_ignores_wrong_answers(self):
        q = self._build(blank_spec=None)
        q.save()
        Answer.objects.create(question=q, answer_text='15; live', is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text='20; die', is_correct=False, order=2)
        applied, _ = q.rebuild_blank_spec()
        self.assertTrue(applied)
        self.assertEqual(len(q.blank_spec['blanks']), 2)

    def test_rebuild_refuses_and_leaves_the_field_alone(self):
        q = self._build(blank_spec=None)
        q.save()
        Answer.objects.create(question=q, answer_text='fifteen and living',
                              is_correct=True, order=1)
        applied, reason = q.rebuild_blank_spec()
        self.assertFalse(applied)
        self.assertIsNone(q.blank_spec)
        self.assertTrue(reason)

    # ── answer display ───────────────────────────────────────────────────

    def test_correct_answer_display_reads_the_spec(self):
        q = self._build()
        q.save()
        # The pre-conversion row is still there and must NOT be what is shown.
        Answer.objects.create(question=q, answer_text='15; live', is_correct=True)
        self.assertEqual(q.correct_answer_display(), '15, live or survive')

    def test_display_text_answer_makes_the_payload_readable(self):
        self.assertEqual(
            self._build().display_text_answer(_payload('15', 'live')), '15, live')

    def test_display_text_answer_leaves_other_answers_alone(self):
        q = self._build(question_type=Question.SHORT_ANSWER, blank_spec=None)
        self.assertEqual(q.display_text_answer('42'), '42')

    # ── grading, on every surface that routes through the model ──────────

    def test_grade_text_answer_accepts_a_full_sentence(self):
        q = self._build()
        q.save()
        self.assertTrue(q.grade_text_answer(_payload('15', 'survive')))

    def test_grade_text_answer_is_all_or_nothing(self):
        q = self._build()
        q.save()
        self.assertFalse(q.grade_text_answer(_payload('15', 'die')))

    def test_grade_text_answer_needs_no_answer_rows(self):
        # The accepted answers live in the spec, so a question converted and
        # then stripped of its rows still grades.
        q = self._build()
        q.save()
        self.assertFalse(q.answers.exists())
        self.assertTrue(q.grade_text_answer(_payload('15', 'live')))

    def test_without_a_spec_it_still_grades_as_plain_text(self):
        q = self._build(blank_spec=None)
        q.save()
        Answer.objects.create(question=q, answer_text='15', is_correct=True)
        self.assertTrue(q.grade_text_answer('15'))

    # ── plugin grading dispatch (homework take surface) ──────────────────

    def test_plugin_grades_correct_submission(self):
        q = self._build()
        q.save()
        result = MathsPlugin().grade_answer(
            q.pk, {f'answer_{q.id}': _payload('15', 'live')})
        self.assertTrue(result['is_correct'])
        self.assertEqual(result['points_earned'], q.points)

    def test_plugin_grades_wrong_submission(self):
        q = self._build()
        q.save()
        result = MathsPlugin().grade_answer(
            q.pk, {f'answer_{q.id}': _payload('15', 'die')})
        self.assertFalse(result['is_correct'])
        self.assertEqual(result['points_earned'], 0)
