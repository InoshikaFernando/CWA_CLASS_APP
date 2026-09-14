"""Semantic question review shows up on the AI usage dashboard.

`AIUsageLog.SOURCE_QUESTION_REVIEW` has existed in the ledger's choices since it
was written and nothing ever emitted it, so the dashboard reported three of the
four AI spenders and the fourth read as a pipeline that doesn't exist.

It is not recorded through that ledger, and shouldn't be. The ledger is
page-based and prices a whole provider at one rate; review is per question and
deliberately runs a cheap first pass with a stronger adjudicator, priced per
model from AI_REVIEW_RATES. Putting it in the page table would invent a $/page
for work with no pages, and pricing it through the ledger would bill the cheap
model at the expensive one's rate. It gets its own section, from its own table —
the same shape as AI grading.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser
from classroom.models import Level, Subject, Topic
from maths.models import Question, QuestionAIReview
from taskqueue.dashboard import (
    aggregate_question_review, aggregate_usage, render_markdown,
)
from taskqueue.models import AIUsageLog


class QuestionReviewOnTheDashboardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'qr_dash', 'qr_dash@test.internal', 'pw1!')
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level, _ = Level.objects.get_or_create(
            level_number=4, defaults={'display_name': 'Year 4'})
        cls.topic = Topic.objects.create(
            subject=subject, name='Fractions', slug='fractions-qr')

    def _question(self, text='What is 1/2 + 1/4?'):
        return Question.objects.create(
            question_text=text, question_type='short_answer',
            topic=self.topic, level=self.level, difficulty=1, points=1,
        )

    def _review(self, *, input_tokens=1000, output_tokens=200,
                cost=Decimal('0.0050'), escalated=False):
        return QuestionAIReview.objects.create(
            question=self._question(),
            verdict=QuestionAIReview.VERDICT_OK,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost, escalated=escalated,
        )

    def _markdown(self, **kwargs):
        rows, totals = aggregate_usage(AIUsageLog.objects.all())
        return render_markdown(rows, totals, window='last 30 days', **kwargs)

    def test_reviews_are_summed_per_question_not_per_page(self):
        self._review(input_tokens=1000, output_tokens=200, cost=Decimal('0.0050'))
        self._review(input_tokens=3000, output_tokens=400, cost=Decimal('0.0150'),
                     escalated=True)

        summary = aggregate_question_review(days=30)

        self.assertEqual(summary['reviews'], 2)
        self.assertEqual(summary['escalated'], 1)
        self.assertEqual(summary['input_tokens'], 4000)
        self.assertEqual(summary['output_tokens'], 600)
        self.assertEqual(summary['cost'], Decimal('0.0200'))
        self.assertEqual(summary['per_review'], Decimal('0.0100'))

    def test_the_window_is_honoured(self):
        old = self._review()
        QuestionAIReview.objects.filter(pk=old.pk).update(
            reviewed_at=timezone.now() - timezone.timedelta(days=45))
        self._review()

        self.assertEqual(aggregate_question_review(days=30)['reviews'], 1)
        self.assertEqual(aggregate_question_review()['reviews'], 2)

    def test_the_section_is_rendered_and_counted_in_the_grand_total(self):
        self._review(cost=Decimal('0.2500'))

        markdown = self._markdown(review=aggregate_question_review(days=30))

        self.assertIn('### Question review (per question)', markdown)
        self.assertIn('$/question', markdown)
        self.assertIn('$0.2500', markdown)
        self.assertIn('Total AI cost — **$0.2500**', markdown)
        # It must NOT land in the page table, which would invent a $/page.
        page_table = markdown.split('### Question review')[0]
        self.assertNotIn('Question review', page_table)

    def test_a_run_with_no_configured_rate_says_the_total_is_a_floor(self):
        """Tokens are always known; cost is not. An under-report must be visible."""
        self._review(cost=Decimal('0.0100'))
        self._review(cost=None)

        summary = aggregate_question_review(days=30)
        self.assertEqual(summary['unpriced'], 1)

        markdown = self._markdown(review=summary)
        self.assertIn('no configured', markdown)
        self.assertIn('floor', markdown)

    def test_nothing_is_rendered_when_nothing_was_reviewed(self):
        markdown = self._markdown(review=aggregate_question_review(days=30))
        self.assertNotIn('Question review (per question)', markdown)

    def test_the_dashboard_still_renders_without_the_review_data(self):
        """render_markdown is called with hand-built rows elsewhere."""
        self.assertNotIn('Question review', self._markdown())
