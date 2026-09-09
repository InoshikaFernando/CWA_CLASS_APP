"""Tests for the preview "Same image as previous" control — the manual
counterpart to the extractor's automatic shared-figure carry-over. It lets a
teacher assign a question the image already chosen on an earlier question when
the automatic detection missed a figure shared across consecutive questions.
"""
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School, Subject, Topic, Level

from ai_import.models import AIImportSession
from ai_import.services import save_questions_from_session


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


class SharedFigureSaveTests(TestCase):
    """``save_questions_from_session`` with several questions on ONE figure.

    Shared by the AI-import and worksheet confirm flows. The preview control
    assigns the earlier question's ref verbatim, so the saver sees two questions
    pointing at the same ref and must store the picture once.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('shs', 'shs@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='shs', admin=cls.user)
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Statistics', slug='statistics', subject=cls.subject)

    def setUp(self):
        # Per test: a class-level override would let InMemoryStorage carry files
        # between tests, and storage uniquifies a repeated name.
        override = override_settings(STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        override.enable()
        self.addCleanup(override.disable)

    def _session(self, texts, ref='chart.png'):
        return AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 7, 'subject': 'Mathematics', 'strand': '',
                'topic': 'Statistics',
                'questions': [
                    {'question_text': t, 'question_type': 'short_answer',
                     'image_ref': ref, 'difficulty': 1, 'points': 1,
                     'answers': [{'text': '20', 'is_correct': True}]}
                    for t in texts
                ],
            },
            extracted_images={ref: _PNG_B64},
        )

    def test_questions_sharing_a_figure_store_it_once(self):
        from maths.models import Question as MQ

        session = self._session(['How many chose chocolate?', 'How many chose chips?'])
        result = save_questions_from_session(session, self.user)

        self.assertEqual(result['failed'], 0, result['errors'])
        self.assertEqual(result['inserted'], 2)
        saved = list(MQ.objects.filter(level=self.level).order_by('pk'))
        self.assertEqual(len(saved), 2)
        # One stored file, referenced by both questions.
        self.assertEqual(saved[0].image.name, saved[1].image.name)
        self.assertEqual(saved[0].image.name, 'questions/year7/statistics/chart.png')
        self.assertEqual(
            default_storage.listdir('questions/year7/statistics')[1], ['chart.png'])

    def test_distinct_figures_still_get_their_own_files(self):
        from maths.models import Question as MQ

        session = self._session(['Name this shape'])
        session.extracted_data['questions'].append({
            'question_text': 'Name this other shape', 'question_type': 'short_answer',
            'image_ref': 'other.png', 'difficulty': 1, 'points': 1,
            'answers': [{'text': 'square', 'is_correct': True}],
        })
        session.extracted_images['other.png'] = _PNG_B64
        session.save()

        result = save_questions_from_session(session, self.user)

        self.assertEqual(result['failed'], 0, result['errors'])
        saved = list(MQ.objects.filter(level=self.level).order_by('pk'))
        self.assertNotEqual(saved[0].image.name, saved[1].image.name)
        self.assertEqual(
            sorted(default_storage.listdir('questions/year7/statistics')[1]),
            ['chart.png', 'other.png'])
