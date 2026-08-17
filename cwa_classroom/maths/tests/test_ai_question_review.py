"""Tests for AI-assisted question review (CPP-380).

Both providers are stubbed throughout — **no test makes a live API call**, and
none should ever be added. The behaviour worth guarding is the decision logic
around the models, not the models themselves.
"""
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from classroom.models import Level, Subject, Topic
from maths import ai_review
from maths.ai_review import ProviderResult, review_question
from maths.models import Answer, Question, QuestionAIReview

RATES = '{"cheap-model": {"input": 1, "output": 2}, ' \
        '"strong-model": {"input": 10, "output": 20}}'


def _stub(ok, reason='', tokens=(100, 20), error=''):
    """A provider that always returns the same opinion."""
    def _call(payload, model):
        return ProviderResult(ok=ok, reason=reason, model=model,
                              input_tokens=tokens[0], output_tokens=tokens[1],
                              error=error)
    return _call


class ReviewDecisionTests(TestCase):
    """The two-tier decision: who can flag, and who cannot."""

    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.create(level_number=987, display_name='AI')
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='AI Review', slug='ai-review',
            is_active=True)
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Calculate: 1/2 + 1/4',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        Answer.objects.create(question=cls.question, answer_text='3/4',
                              is_correct=True, order=1)
        Answer.objects.create(question=cls.question, answer_text='1/4',
                              is_correct=False, order=2)

    def _review(self, first, second=None):
        providers = {'openai': first, 'anthropic': second or _stub(True)}
        with mock.patch.dict(ai_review.PROVIDERS, providers):
            return review_question(
                self.question,
                first_pass_model='cheap-model',
                adjudicator_model='strong-model')

    def test_clean_question_is_not_escalated(self):
        # The cheap pass raising no doubt must not spend the adjudicator.
        outcome = self._review(_stub(True))
        self.assertEqual(outcome.verdict, 'ok')
        self.assertFalse(outcome.escalated)
        self.assertEqual(outcome.adjudicator_model, '')

    def test_cheap_pass_alone_cannot_flag(self):
        # Cheap model objects, adjudicator does not — providers disagree, so
        # the content stands. One model must never overrule authored material.
        outcome = self._review(_stub(False, 'looks wrong'), _stub(True))
        self.assertEqual(outcome.verdict, 'ok')
        self.assertTrue(outcome.escalated)

    def test_flagged_only_when_both_object(self):
        outcome = self._review(_stub(False, 'ambiguous'),
                               _stub(False, 'missing information'))
        self.assertEqual(outcome.verdict, 'flagged')
        self.assertEqual(outcome.reason, 'missing information')
        self.assertTrue(outcome.escalated)

    def test_first_pass_error_is_recorded_not_treated_as_clean(self):
        outcome = self._review(_stub(True, error='RateLimitError()'))
        self.assertEqual(outcome.verdict, 'error')
        self.assertIn('first pass failed', outcome.reason)

    def test_adjudicator_error_leaves_the_objection_unconfirmed(self):
        outcome = self._review(_stub(False, 'suspect'),
                               _stub(True, error='Timeout()'))
        self.assertEqual(outcome.verdict, 'error')
        self.assertIn('adjudicator failed', outcome.reason)

    @override_settings()
    def test_cost_sums_both_tiers_when_rates_are_configured(self):
        with mock.patch.dict('os.environ', {'AI_REVIEW_RATES': RATES}):
            outcome = self._review(_stub(False, 'x'), _stub(False, 'y'))
        # cheap: 100 in @ $1/M + 20 out @ $2/M ; strong: 100 @ $10 + 20 @ $20
        expected = (Decimal('0.0001') + Decimal('0.00004')
                    + Decimal('0.001') + Decimal('0.0004'))
        self.assertEqual(outcome.cost_usd, expected)

    def test_cost_is_none_when_rate_is_unknown(self):
        with mock.patch.dict('os.environ', {'AI_REVIEW_RATES': ''}):
            outcome = self._review(_stub(True))
        self.assertIsNone(outcome.cost_usd)


class VerdictParsingTests(TestCase):

    def test_plain_json(self):
        self.assertEqual(ai_review._parse_verdict('{"ok": true, "reason": ""}'),
                         (True, ''))

    def test_fenced_json(self):
        ok, reason = ai_review._parse_verdict(
            '```json\n{"ok": false, "reason": "ambiguous"}\n```')
        self.assertFalse(ok)
        self.assertEqual(reason, 'ambiguous')

    def test_prose_around_json(self):
        ok, _ = ai_review._parse_verdict('Sure! {"ok": true} Hope that helps.')
        self.assertTrue(ok)

    def test_missing_ok_key_is_an_error(self):
        with self.assertRaises(ValueError):
            ai_review._parse_verdict('{"reason": "no verdict"}')

    def test_empty_reply_is_an_error(self):
        with self.assertRaises(ValueError):
            ai_review._parse_verdict('')


class SelectionTests(TestCase):
    """Which questions a run picks up."""

    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.create(level_number=986, display_name='Sel')

    def _question(self, text='Calculate: 1/2 + 1/4'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        Answer.objects.create(question=q, answer_text='3/4', is_correct=True)
        return q

    def _run(self, **kwargs):
        with mock.patch.dict(ai_review.PROVIDERS,
                             {'openai': _stub(True), 'anthropic': _stub(True)}), \
             mock.patch.object(ai_review, 'FIRST_PASS_MODEL', 'cheap-model'), \
             mock.patch.object(ai_review, 'ADJUDICATOR_MODEL', 'strong-model'), \
             mock.patch.object(ai_review, 'missing_configuration', lambda: []):
            call_command('review_questions_ai', '--level', 986, '--quiet', **kwargs)

    def test_only_unreviewed_questions_are_selected(self):
        first = self._question()
        self._run()
        self.assertEqual(QuestionAIReview.objects.filter(question=first).count(), 1)

        # A second run must not re-review it.
        self._run()
        self.assertEqual(QuestionAIReview.objects.filter(question=first).count(), 1)

    def test_edited_question_is_reviewed_again(self):
        question = self._question()
        self._run()
        self.assertEqual(question.ai_reviews.count(), 1)

        # Editing invalidates the review — it vouched for older text.
        question.question_text = 'Calculate: 1/2 + 1/3'
        question.save()
        self._run()
        self.assertEqual(question.ai_reviews.count(), 2)

    def test_limit_bounds_the_run(self):
        for _ in range(5):
            self._question()
        self._run(limit=2)
        self.assertEqual(QuestionAIReview.objects.count(), 2)


class SafetyTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.create(level_number=985, display_name='Safe')
        cls.question = Question.objects.create(
            level=cls.level, question_text='Calculate: 1/2 + 1/4',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        Answer.objects.create(question=cls.question, answer_text='3/4',
                              is_correct=True, order=1)

    def test_missing_configuration_is_a_noop_not_a_failure(self):
        with mock.patch.object(ai_review, 'missing_configuration',
                               lambda: ['ANTHROPIC_API_KEY is not set']):
            call_command('review_questions_ai', '--level', 985, '--quiet')
        self.assertEqual(QuestionAIReview.objects.count(), 0)

    def test_max_cost_refuses_to_run_without_configured_rates(self):
        # A ceiling that cannot be measured is not a ceiling.
        with mock.patch.object(ai_review, 'missing_configuration', lambda: []), \
             mock.patch.dict('os.environ', {'AI_REVIEW_RATES': ''}), \
             mock.patch.object(ai_review, 'FIRST_PASS_MODEL', 'cheap-model'), \
             mock.patch.object(ai_review, 'ADJUDICATOR_MODEL', 'strong-model'):
            with self.assertRaises(CommandError) as ctx:
                call_command('review_questions_ai', '--level', 985,
                             '--max-cost', 1.0, '--quiet')
        self.assertIn('AI_REVIEW_RATES', str(ctx.exception))

    def test_dry_run_writes_nothing_and_calls_nothing(self):
        def _explode(payload, model):
            raise AssertionError('dry run must not call a provider')

        with mock.patch.dict(ai_review.PROVIDERS,
                             {'openai': _explode, 'anthropic': _explode}):
            call_command('review_questions_ai', '--level', 985, '--dry-run',
                         '--quiet')
        self.assertEqual(QuestionAIReview.objects.count(), 0)

    def test_review_never_edits_question_content(self):
        """The command routes to a human; it must not rewrite material."""
        before = {
            'text': self.question.question_text,
            'answers': list(
                self.question.answers.values_list('answer_text', 'is_correct')),
        }
        with mock.patch.dict(ai_review.PROVIDERS,
                             {'openai': _stub(False, 'wrong'),
                              'anthropic': _stub(False, 'definitely wrong')}), \
             mock.patch.object(ai_review, 'FIRST_PASS_MODEL', 'cheap-model'), \
             mock.patch.object(ai_review, 'ADJUDICATOR_MODEL', 'strong-model'), \
             mock.patch.object(ai_review, 'missing_configuration', lambda: []):
            try:
                call_command('review_questions_ai', '--level', 985, '--quiet')
            except SystemExit:
                pass          # flagged findings exit non-zero by design

        self.question.refresh_from_db()
        self.assertEqual(self.question.question_text, before['text'])
        self.assertEqual(
            list(self.question.answers.values_list('answer_text', 'is_correct')),
            before['answers'])
        self.assertEqual(
            QuestionAIReview.objects.get(question=self.question).verdict,
            QuestionAIReview.VERDICT_FLAGGED)

    def test_stale_review_is_detected(self):
        review = QuestionAIReview.objects.create(
            question=self.question, verdict=QuestionAIReview.VERDICT_OK,
            question_updated_at=self.question.updated_at)
        self.assertFalse(review.is_stale)

        self.question.question_text = 'Calculate: 1/2 + 1/3'
        self.question.save()
        review.refresh_from_db()
        self.assertTrue(review.is_stale)
