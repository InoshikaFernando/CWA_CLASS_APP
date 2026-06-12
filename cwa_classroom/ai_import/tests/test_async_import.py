"""CPP-307b: async AI import — task function, upload enqueue, status polling."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from ai_import.models import AIImportSession
from ai_import.tasks import process_pdf_import


def _make_session(user, school, **overrides):
    defaults = dict(
        user=user,
        school=school,
        pdf_filename='quiz.pdf',
        status=AIImportSession.STATUS_PROCESSING,
        pdf_file=SimpleUploadedFile('quiz.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
    )
    defaults.update(overrides)
    return AIImportSession.objects.create(**defaults)


class ProcessPdfImportTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('ai_u', 'ai_u@test.internal', 'pw1!')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'})
        cls.user.roles.add(admin_role)
        cls.school = School.objects.create(name='AI School', slug='ai-school', admin=cls.user)

    @patch('ai_import.tasks.classify_questions')
    @patch('ai_import.tasks.extract_pdf_content')
    def test_success_marks_ready_and_stores_result(self, mock_extract, mock_classify):
        session = _make_session(self.user, self.school)
        mock_extract.return_value = {
            'page_count': 3,
            'pages': [{'images': [{'ref': 'p1_img1.png', 'base64': 'abc'}]}],
        }
        mock_classify.return_value = {
            'questions': [{'question_text': 'Q1'}],
            'usage': {'total_tokens': 120},
        }

        result = process_pdf_import(session.pk)

        session.refresh_from_db()
        self.assertEqual(session.status, AIImportSession.STATUS_READY)
        self.assertEqual(session.page_count, 3)
        self.assertEqual(session.tokens_used, 120)
        self.assertEqual(session.extracted_images, {'p1_img1.png': 'abc'})
        self.assertEqual(len(session.extracted_data['questions']), 1)
        self.assertEqual(result['questions'], 1)

    @patch('ai_import.tasks.classify_questions')
    @patch('ai_import.tasks.extract_pdf_content')
    def test_preserves_preset_classroom_id(self, mock_extract, mock_classify):
        session = _make_session(self.user, self.school, extracted_data={'classroom_id': 42})
        mock_extract.return_value = {'page_count': 1, 'pages': []}
        mock_classify.return_value = {'questions': [], 'usage': {}}

        process_pdf_import(session.pk)

        session.refresh_from_db()
        self.assertEqual(session.extracted_data['classroom_id'], 42)

    @patch('ai_import.tasks.extract_pdf_content', side_effect=ValueError('bad pdf'))
    def test_failure_marks_failed_and_reraises(self, _mock_extract):
        session = _make_session(self.user, self.school)
        with self.assertRaises(ValueError):
            process_pdf_import(session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, AIImportSession.STATUS_FAILED)
        self.assertIn('bad pdf', session.error_message)

    def test_missing_pdf_file_fails_gracefully(self):
        session = _make_session(self.user, self.school, pdf_file=None)
        with self.assertRaises(ValueError):
            process_pdf_import(session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, AIImportSession.STATUS_FAILED)


class UploadEnqueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            'ai_super', 'ai_super@test.internal', 'pw1!')
        cls.school = School.objects.create(
            name='Super School', slug='super-school', admin=cls.superuser)

    @patch('ai_import.views.get_school_for_user')
    @patch('ai_import.tasks.process_pdf_import')
    @patch('taskqueue.services.django_rq.get_queue')
    @patch('ai_import.services.get_pdf_page_count', return_value=2)
    def test_upload_creates_processing_session_and_redirects(
        self, _mock_count, mock_get_queue, _mock_task, mock_school,
    ):
        mock_school.return_value = self.school
        mock_job = MagicMock(); mock_job.id = 'job-1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        self.client.force_login(self.superuser)
        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        resp = self.client.post(reverse('ai_import:upload'), {'pdf_file': pdf})

        session = AIImportSession.objects.get(user=self.superuser)
        self.assertEqual(session.status, AIImportSession.STATUS_PROCESSING)
        self.assertEqual(session.page_count, 2)
        self.assertRedirects(
            resp, reverse('ai_import:processing', args=[session.pk]),
            fetch_redirect_response=False,
        )
        mock_queue.enqueue.assert_called_once()


class StatusPollTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            'ai_super2', 'ai_super2@test.internal', 'pw1!')
        cls.other = CustomUser.objects.create_superuser(
            'ai_other', 'ai_other@test.internal', 'pw1!')
        cls.school = School.objects.create(
            name='Status School', slug='status-school', admin=cls.superuser)

    def test_status_processing_renders_partial(self):
        session = _make_session(self.superuser, self.school)
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('ai_import:status', args=[session.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('HX-Redirect', resp)

    def test_status_ready_sends_hx_redirect(self):
        session = _make_session(self.superuser, self.school, status=AIImportSession.STATUS_READY)
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('ai_import:status', args=[session.pk]))
        self.assertEqual(resp['HX-Redirect'], reverse('ai_import:preview', args=[session.pk]))

    def test_other_user_cannot_poll_session(self):
        session = _make_session(self.superuser, self.school)
        self.client.force_login(self.other)
        resp = self.client.get(reverse('ai_import:status', args=[session.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_preview_redirects_while_processing(self):
        session = _make_session(self.superuser, self.school)
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('ai_import:preview', args=[session.pk]))
        self.assertRedirects(
            resp, reverse('ai_import:processing', args=[session.pk]),
            fetch_redirect_response=False,
        )
