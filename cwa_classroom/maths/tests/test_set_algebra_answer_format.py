"""
Tests for the set_algebra_answer_format management command.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question


class SetAlgebraAnswerFormatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.create(level_number=9, display_name='Year 9')
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')

        cls.algebra = Topic.objects.create(name='Algebra', slug='algebra', subject=subject)
        cls.quadratic = Topic.objects.create(
            name='Algebra 2- Quadratic', slug='alg-quad', subject=subject, parent=cls.algebra,
        )
        cls.factorising = Topic.objects.create(
            name='Factorising Algebra', slug='alg-fact', subject=subject, parent=cls.algebra,
        )
        cls.fractions = Topic.objects.create(name='Fractions', slug='fractions', subject=subject)

        def make(topic, qtype):
            q = Question.objects.create(
                level=cls.level, topic=topic, question_type=qtype,
                question_text=f'{topic.name} {qtype}',
            )
            Answer.objects.create(question=q, answer_text='x', is_correct=True)
            return q

        cls.q_quad_typed = make(cls.quadratic, 'short_answer')      # should flag
        cls.q_quad_mcq = make(cls.quadratic, 'multiple_choice')     # not typed → skip
        cls.q_fact_typed = make(cls.factorising, 'short_answer')    # flag unless excluded
        cls.q_root_calc = make(cls.algebra, 'calculation')          # should flag
        cls.q_fractions = make(cls.fractions, 'short_answer')       # not algebra → skip

    def _format(self, q):
        return Question.objects.get(pk=q.pk).answer_format

    def test_dry_run_changes_nothing(self):
        out = StringIO()
        call_command('set_algebra_answer_format', stdout=out)
        self.assertIn('Typed questions to flag as algebra: 3', out.getvalue())
        for q in (self.q_quad_typed, self.q_fact_typed, self.q_root_calc):
            self.assertEqual(self._format(q), 'text')  # nothing written

    def test_apply_flags_typed_algebra_questions_only(self):
        call_command('set_algebra_answer_format', '--apply')
        self.assertEqual(self._format(self.q_quad_typed), 'algebra')
        self.assertEqual(self._format(self.q_root_calc), 'algebra')
        self.assertEqual(self._format(self.q_fact_typed), 'algebra')
        # MCQ in an algebra topic is untouched (answer_format is irrelevant there)
        self.assertEqual(self._format(self.q_quad_mcq), 'text')
        # Non-algebra topic untouched
        self.assertEqual(self._format(self.q_fractions), 'text')

    def test_exclude_topic_skips_factorising(self):
        call_command(
            'set_algebra_answer_format', '--apply', '--exclude-topic', 'Factorising',
        )
        self.assertEqual(self._format(self.q_quad_typed), 'algebra')
        self.assertEqual(self._format(self.q_root_calc), 'algebra')
        # Factorise sub-topic excluded — keeps text (its bracket answers would
        # otherwise be mis-graded by the polynomial grader).
        self.assertEqual(self._format(self.q_fact_typed), 'text')

    def test_term_narrows_scope(self):
        call_command('set_algebra_answer_format', '--apply', '--term', 'Quadratic')
        self.assertEqual(self._format(self.q_quad_typed), 'algebra')
        # The root "Algebra" calculation is outside a "Quadratic" subtree.
        self.assertEqual(self._format(self.q_root_calc), 'text')
