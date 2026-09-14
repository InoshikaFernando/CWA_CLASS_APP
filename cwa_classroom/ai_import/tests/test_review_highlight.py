"""Tests for the flagged-question highlight on the AI-import preview.

A question the verifier flags (``needs_review``) used to say so with one small
badge in the card header, which is easy to scroll straight past on a long
preview. The whole card now goes red until the teacher ticks "Reviewed", and that
tick is posted so it survives leaving and coming back to the page.
"""
import re

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School

from ai_import.models import AIImportSession


class AIImportReviewHighlightTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('airh', 'airh@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='airhs', admin=cls.user)

    def _session(self, **q0):
        q = {'question_text': 'Suspect?', 'question_type': 'short_answer',
             'needs_review': True, 'review_reason': 'answers disagree',
             'difficulty': 1, 'points': 1, 'include': True}
        q.update(q0)
        return AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [
                    q,
                    {'question_text': 'Fine?', 'question_type': 'short_answer',
                     'difficulty': 1, 'points': 1, 'include': True},
                ],
            },
        )

    def _preview_html(self, session):
        self.client.force_login(self.user)
        return self.client.get(reverse('ai_import:preview', args=[session.pk])).content.decode()

    @staticmethod
    def _card_classes(html, idx):
        """The class attribute of question card `idx` — so a test asserts on the
        card itself, not on the CSS rule that happens to name the same class."""
        m = re.search(
            r'<div class="([^"]*)"[^>]*id="question-card-%d"' % idx, html)
        assert m, f'question-card-{idx} not found in the preview'
        return m.group(1)

    def test_flagged_card_is_red_and_offers_a_reviewed_tick(self):
        html = self._preview_html(self._session())
        self.assertIn('needs-review', self._card_classes(html, 0))
        self.assertIn('.question-card.needs-review', html)    # the red rule itself
        self.assertIn('data-testid="review-ack-0"', html)
        self.assertIn('name="q_0_review_ack"', html)

    def test_unflagged_card_is_not_red_and_has_no_tick(self):
        html = self._preview_html(self._session())
        self.assertNotIn('needs-review', self._card_classes(html, 1))
        self.assertNotIn('data-testid="review-ack-1"', html)
        self.assertNotIn('data-testid="review-badge-1"', html)

    def test_an_acknowledged_card_renders_normal_with_the_tick_kept(self):
        html = self._preview_html(self._session(review_ack=True))
        self.assertNotIn('needs-review', self._card_classes(html, 0))
        self.assertIn('data-testid="review-badge-0"', html)   # badge stays as a record
        ack = re.search(r'name="q_0_review_ack"[^>]*', html).group(0)
        self.assertIn('checked', ack)

    def test_the_reviewed_tick_persists_through_the_preview_post(self):
        s = self._session()
        self.client.force_login(self.user)
        r = self.client.post(reverse('ai_import:preview', args=[s.pk]), {
            'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
            'q_0_include': 'on', 'q_0_text': 'Suspect?', 'q_0_type': 'short_answer',
            'q_0_difficulty': 1, 'q_0_points': 1, 'q_0_review_ack': 'on',
            'q_1_include': 'on', 'q_1_text': 'Fine?', 'q_1_type': 'short_answer',
            'q_1_difficulty': 1, 'q_1_points': 1,
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        q0, q1 = s.extracted_data['questions'][:2]
        self.assertTrue(q0['review_ack'])
        self.assertTrue(q0['needs_review'])          # the flag itself is not erased
        self.assertFalse(q1['review_ack'])

    def test_unticking_reviewed_brings_the_highlight_back(self):
        s = self._session(review_ack=True)
        self.client.force_login(self.user)
        self.client.post(reverse('ai_import:preview', args=[s.pk]), {
            'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
            'q_0_include': 'on', 'q_0_text': 'Suspect?', 'q_0_type': 'short_answer',
            'q_0_difficulty': 1, 'q_0_points': 1,
            'q_1_include': 'on', 'q_1_text': 'Fine?', 'q_1_type': 'short_answer',
            'q_1_difficulty': 1, 'q_1_points': 1,
        })
        s.refresh_from_db()
        self.assertFalse(s.extracted_data['questions'][0]['review_ack'])
