"""CPP-389 — "Preview as student" on the worksheet upload review screen.

The worksheet flow confirms through ``save_questions_from_session``, which calls
``apply_blank_format`` — so a "___" sentence really does become a sentence with
a box in each gap here, and the preview must show those gaps rather than the
single box the homework flow would give.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School
from maths.models import Question
from worksheets.models import WorksheetUploadSession


class WorksheetStudentPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('wsp1', 'wsp1@x.com', 'pw')
        cls.teacher.roles.add(role)
        cls.other = CustomUser.objects.create_user('wsp2', 'wsp2@x.com', 'pw')
        cls.other.roles.add(role)
        admin = CustomUser.objects.create_user('wspa', 'wspa@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='wsps', admin=admin)
        Level.objects.create(level_number=5, display_name='Year 5')

    def _session(self):
        return WorksheetUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_READY, page_count=1,
            is_confirmed=False, worksheet_name='WS',
            extracted_data={'year_level': 5, 'questions': [{
                'question_text': '20c is ______ hundredths.',
                'question_type': 'short_answer',
                'answers': [{'text': 'twenty', 'is_correct': True}],
                'difficulty': 1, 'points': 1, 'include': True,
            }]},
            extracted_images={},
        )

    def _post(self, session, extra=None, user=None):
        self.client.force_login(user or self.teacher)
        data = {
            'preview_index': 0,
            'q_0_text': '20c is ______ hundredths.',
            'q_0_type': 'short_answer',
            'q_0_validation_type': 'auto',
            'q_0_difficulty': '1',
            'q_0_points': '1',
            'q_0_answer_0_text': 'twenty',
            'q_0_answer_0_correct': 'on',
        }
        data.update(extra or {})
        return self.client.post(
            reverse('worksheets:question_preview', args=[session.pk]), data)

    def test_a_gapped_sentence_previews_as_gaps_on_this_flow(self):
        response = self._post(self._session())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gap 1 accepts: twenty')
        self.assertContains(response, 'data-fb-stage')

    def test_a_gap_answer_is_marked_through_the_real_grader(self):
        response = self._post(
            self._session(), extra={'preview_answer': '{"blanks": ["twenty"]}'})
        self.assertContains(response, 'Marked correct')

    def test_a_wrong_gap_answer_is_marked_wrong(self):
        response = self._post(
            self._session(), extra={'preview_answer': '{"blanks": ["thirty"]}'})
        self.assertContains(response, 'Marked wrong')

    def test_preview_writes_nothing(self):
        before = Question.objects.count()
        self._post(self._session(), extra={'preview_answer': '{"blanks": ["twenty"]}'})
        self.assertEqual(Question.objects.count(), before)

    def test_another_teachers_session_cannot_be_previewed(self):
        self.assertEqual(self._post(self._session(), user=self.other).status_code, 404)

    def test_the_review_page_offers_the_preview(self):
        session = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(
            reverse('worksheets:preview', args=[session.pk])).content.decode()
        self.assertIn('data-preview-open="0"', html)
        self.assertIn('data-preview-all', html)
        self.assertIn('question-preview/', html)
