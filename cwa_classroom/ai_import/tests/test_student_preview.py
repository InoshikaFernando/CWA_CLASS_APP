"""CPP-389 — "Preview as student" on the AI Import review screen.

Covers the two question types this feature was actually asked for: a
measurement, whose whole risk is the tolerance, and a parabola, where the answer
is matched as plain text so an equivalent form is marked wrong.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from ai_import.models import AIImportSession
from classroom.models import Level, School
from maths.models import Question


class AIImportStudentPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('aisp', 'aisp@x.com', 'pw')
        cls.other = CustomUser.objects.create_superuser('aisp2', 'aisp2@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='aisps', admin=cls.user)
        Level.objects.create(level_number=9, display_name='Year 9')

    def _session(self, question):
        return AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 9, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [question],
            },
            extracted_images={},
        )

    def _post(self, session, posted, extra=None, user=None):
        self.client.force_login(user or self.user)
        data = {'preview_index': 0, **posted}
        data.update(extra or {})
        return self.client.post(
            reverse('ai_import:question_preview', args=[session.pk]), data)

    # --- measurement -------------------------------------------------------
    MEASURE = {
        'question_text': 'Measure angle a.', 'question_type': 'measure',
        'numeric_answer': '135', 'answer_unit': '°', 'difficulty': 1, 'points': 1,
    }
    MEASURE_POST = {
        'q_0_text': 'Measure angle a.',
        'q_0_type': 'measure',
        'q_0_validation_type': 'auto',
        'q_0_difficulty': '1',
        'q_0_points': '1',
        'q_0_measure_numeric_answer': '135',
        'q_0_measure_answer_unit': '°',
    }

    def test_a_measurement_with_no_tolerance_warns_before_it_is_imported(self):
        response = self._post(self._session(self.MEASURE), self.MEASURE_POST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no tolerance')

    def test_a_measurement_is_marked_within_the_tolerance_the_teacher_sets(self):
        session = self._session(self.MEASURE)
        posted = dict(self.MEASURE_POST, q_0_measure_answer_tolerance='2')
        self.assertContains(
            self._post(session, posted, {'preview_answer': '134'}), 'Marked correct')
        self.assertContains(
            self._post(session, posted, {'preview_answer': '120'}), 'Marked wrong')

    def test_without_a_tolerance_a_near_miss_is_marked_wrong(self):
        response = self._post(
            self._session(self.MEASURE), self.MEASURE_POST, {'preview_answer': '134'})
        self.assertContains(response, 'Marked wrong')

    # --- parabola ----------------------------------------------------------
    PARABOLA = {
        'question_text': 'Write the equation of this parabola.',
        'question_type': 'short_answer', 'difficulty': 2, 'points': 2,
        'answers': [{'text': 'y = (x - 2)^2 + 1', 'is_correct': True}],
    }
    PARABOLA_POST = {
        'q_0_text': 'Write the equation of this parabola.',
        'q_0_type': 'short_answer',
        'q_0_validation_type': 'auto',
        'q_0_difficulty': '2',
        'q_0_points': '2',
        'q_0_answer_0_text': 'y = (x - 2)^2 + 1',
        'q_0_answer_0_correct': 'on',
    }

    def test_an_equivalent_parabola_form_is_shown_being_marked_wrong(self):
        """What the teacher could not find out before importing.

        Neither importer sets ``answer_format``, so the expanded form of the
        same curve is marked wrong. The preview both warns up front and
        demonstrates it when the teacher tries the other form.
        """
        session = self._session(self.PARABOLA)
        warned = self._post(session, self.PARABOLA_POST)
        self.assertContains(warned, 'matches text literally')

        tried = self._post(
            session, self.PARABOLA_POST, {'preview_answer': 'y = x^2 - 4x + 5'})
        self.assertContains(tried, 'Marked wrong')

    def test_adding_the_other_form_as_an_answer_fixes_it_in_the_preview(self):
        session = self._session(self.PARABOLA)
        posted = dict(
            self.PARABOLA_POST,
            q_0_answer_1_text='y = x^2 - 4x + 5',
            q_0_answer_1_correct='on',
        )
        response = self._post(session, posted, {'preview_answer': 'y = x^2 - 4x + 5'})
        self.assertContains(response, 'Marked correct')

    # --- housekeeping ------------------------------------------------------
    def test_preview_writes_nothing(self):
        before = Question.objects.count()
        self._post(
            self._session(self.PARABOLA), self.PARABOLA_POST,
            {'preview_answer': 'y = (x - 2)^2 + 1'})
        self.assertEqual(Question.objects.count(), before)

    def test_another_users_session_cannot_be_previewed(self):
        response = self._post(
            self._session(self.PARABOLA), self.PARABOLA_POST, user=self.other)
        self.assertEqual(response.status_code, 404)

    def test_the_review_page_offers_the_preview(self):
        session = self._session(self.PARABOLA)
        self.client.force_login(self.user)
        html = self.client.get(
            reverse('ai_import:preview', args=[session.pk])).content.decode()
        self.assertIn('data-preview-open="0"', html)
        self.assertIn('data-preview-all', html)
        self.assertIn('question-preview/', html)
