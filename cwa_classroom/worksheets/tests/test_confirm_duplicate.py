"""Regression: confirm must not 500 when extracted questions share text.

Several extracted questions can resolve to the SAME saved maths.Question (e.g.
when their question_text is identical because the distinguishing part is an
image). The confirm link step used to ``create`` a WorksheetQuestion per match,
violating the (worksheet, subject_slug, content_id) unique constraint. It now
uses get_or_create.
"""
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetQuestion, WorksheetUploadSession

from .test_views import WorksheetConfirmViewTestBase


class TestConfirmDuplicateQuestions(WorksheetConfirmViewTestBase):

    def _dupes(self, n=3):
        q = {
            'include': True,
            'question_text': 'Solve for x.',   # identical across all n
            'question_type': 'short_answer',
            'difficulty': 1,
            'points': 1,
            'year_level': 6,
            'topic': 'cv-test-addition',
            'subject': 'Mathematics',
            'explanation': '',
            'answers': [],
        }
        return [dict(q) for _ in range(n)]

    def test_identical_text_questions_do_not_crash(self):
        session = self._make_session(questions=self._dupes(3))
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        # Must be a redirect, not a 500 IntegrityError.
        self.assertIn(response.status_code, (301, 302))
        session.refresh_from_db()
        self.assertTrue(session.is_confirmed)

    def test_worksheet_created_with_deduped_link(self):
        session = self._make_session(questions=self._dupes(3))
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        self.client.post(url)

        ws = Worksheet.objects.filter(school=self.school).order_by('-id').first()
        self.assertIsNotNone(ws)
        # The duplicates collapse to a single linked question — and crucially, no
        # duplicate-content_id rows were attempted.
        links = WorksheetQuestion.objects.filter(worksheet=ws)
        content_ids = list(links.values_list('content_id', flat=True))
        self.assertEqual(len(content_ids), len(set(content_ids)))  # no duplicates
