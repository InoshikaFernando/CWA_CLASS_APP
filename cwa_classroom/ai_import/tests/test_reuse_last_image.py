"""Tests for the preview "Same image as previous" control — the manual
counterpart to the extractor's automatic shared-figure carry-over. It lets a
teacher assign a question the image already chosen on an earlier question when
the automatic detection missed a figure shared across consecutive questions.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School

from ai_import.models import AIImportSession


_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    'awAAAABJRU5ErkJggg=='
)


class ReuseLastImageControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('sup', 'sup@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='ris', admin=cls.user)

    def _session(self, question_count):
        questions = []
        for i in range(question_count):
            questions.append({
                'question_text': f'Q{i}?', 'question_type': 'short_answer',
                'image_ref': 'page1_figure1.png' if i == 0 else None,
            })
        return AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': questions,
            },
            extracted_images={'page1_figure1.png': _PNG_B64},
        )

    def test_reuse_button_shown_on_later_questions_only(self):
        s = self._session(question_count=3)
        self.client.force_login(self.user)
        html = self.client.get(reverse('ai_import:preview', args=[s.pk])).content.decode()

        # The JS helper is present.
        self.assertIn('function reuseLastImage', html)
        # First question (idx 0) has no "previous" — no reuse control.
        self.assertNotIn('data-reuse="0"', html)
        # Later questions get the control.
        self.assertIn('data-reuse="1"', html)
        self.assertIn('data-reuse="2"', html)
        self.assertIn('onclick="reuseLastImage(1)"', html)

    def test_single_question_has_no_reuse_button(self):
        s = self._session(question_count=1)
        self.client.force_login(self.user)
        html = self.client.get(reverse('ai_import:preview', args=[s.pk])).content.decode()
        # No rendered reuse button (the JS helper definition may still appear).
        self.assertNotIn('onclick="reuseLastImage(', html)
