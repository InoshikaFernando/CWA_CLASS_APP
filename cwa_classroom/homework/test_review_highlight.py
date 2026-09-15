"""Tests for the flagged-question highlight on the homework PDF preview.

A question the verifier flags (``needs_review``) used to say so with one small
badge in the card header, which is easy to scroll straight past on a 40-question
preview. The whole card now goes red until the teacher ticks "Reviewed", and that
tick is posted so it survives leaving and coming back to the page.
"""
import re

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher

from .models import HomeworkUploadSession


class HomeworkReviewHighlightTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('hrh1', 'hrh1@x.com', 'pw')
        cls.teacher.roles.add(role)
        admin = CustomUser.objects.create_user('hrha', 'hrha@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='hrhs', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

    def _session(self, **q0):
        q = {'question_text': 'Suspect?', 'question_type': 'short_answer',
             'needs_review': True, 'review_reason': 'answers disagree',
             'difficulty': 1, 'points': 1, 'include': True}
        q.update(q0)
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='t.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            homework_title='HW',
            extracted_data={'year_level': 5, 'questions': [
                q,
                {'question_text': 'Fine?', 'question_type': 'short_answer',
                 'difficulty': 1, 'points': 1, 'include': True},
            ]},
        )

    def _preview_html(self, session):
        self.client.force_login(self.teacher)
        return self.client.get(reverse('homework:pdf_preview', args=[session.pk])).content.decode()

    @staticmethod
    def _card_classes(html, idx):
        """The class attribute of question card `idx` — so a test asserts on the
        card itself, not on the CSS rule that happens to name the same class."""
        m = re.search(r'<div class="([^"]*)"\s*\n\s*id="card-%d"[ >]' % idx, html)
        assert m, f'card-{idx} not found in the preview'
        return m.group(1)

    def test_flagged_card_is_red_and_offers_a_reviewed_tick(self):
        html = self._preview_html(self._session())
        self.assertIn('needs-review', self._card_classes(html, 0))
        self.assertIn('.q-card.needs-review', html)          # the red rule itself
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
        self.assertIn('name="q_0_review_ack"', html)
        ack = re.search(r'name="q_0_review_ack"[^>]*', html).group(0)
        self.assertIn('checked', ack)

    def test_the_reviewed_tick_persists_through_the_preview_post(self):
        s = self._session()
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('homework:pdf_preview', args=[s.pk]), {
            'homework_title': 'HW', 'year_level': 5, 'topic': '',
            'question_order': '0,1',
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
        self.client.force_login(self.teacher)
        self.client.post(reverse('homework:pdf_preview', args=[s.pk]), {
            'homework_title': 'HW', 'year_level': 5, 'topic': '',
            'question_order': '0,1',
            'q_0_include': 'on', 'q_0_text': 'Suspect?', 'q_0_type': 'short_answer',
            'q_0_difficulty': 1, 'q_0_points': 1,
            'q_1_include': 'on', 'q_1_text': 'Fine?', 'q_1_type': 'short_answer',
            'q_1_difficulty': 1, 'q_1_points': 1,
        })
        s.refresh_from_db()
        self.assertFalse(s.extracted_data['questions'][0]['review_ack'])


class HomeworkReviewPointsTests(HomeworkReviewHighlightTests):
    """The flagged card says WHAT to check, not just that something is off.

    The reason used to be the review badge's title= tooltip, so a teacher had to
    hover a 10px badge to learn the verifier disagreed about the answer — and
    otherwise re-read the whole question to find it. See
    ai_import.review_points, which splits the reason into per-field points.
    """

    _REASON = ('Second-opinion check disagreed: verifier answered "4" vs "5". '
               'Image check: the crop cuts off part of the figure.')

    def test_the_reason_is_visible_on_the_card(self):
        html = self._preview_html(self._session(review_reason=self._REASON))
        self.assertIn('What to check', html)
        self.assertIn('data-testid="review-point-0-0"', html)
        self.assertIn('verifier answered', html.replace('&quot;', '"'))

    def test_a_point_gets_a_chip_to_the_field_it_is_about(self):
        html = self._preview_html(self._session(review_reason=self._REASON))
        self.assertIn('data-review-jump="answer"', html)
        self.assertIn('data-review-jump="image"', html)
        self.assertIn('data-review-field="answer"', html)
        self.assertIn('data-review-field="image"', html)

    def test_the_strip_sits_outside_the_collapsible_body(self):
        """A collapsed card still has to say what to check — that is the whole
        point of not having to open the question."""
        html = self._preview_html(self._session(review_reason=self._REASON))
        strip = html.index('id="review-points-0"')
        body = html.index('id="body-0"')
        self.assertLess(strip, body)

    def test_an_unflagged_question_gets_no_strip(self):
        html = self._preview_html(self._session())
        self.assertNotIn('data-testid="review-point-1-0"', html)
