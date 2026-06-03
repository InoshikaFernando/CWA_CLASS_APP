"""CPP-307c: homework PDF processing via RQ (replacing daemon threads)."""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf


class ProcessHomeworkPdfTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_u', 'hw_u@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='HW School', slug='hw-school', admin=cls.user)

    def _session(self, **overrides):
        defaults = dict(
            user=self.user, school=self.school,
            pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
        )
        defaults.update(overrides)
        return HomeworkUploadSession.objects.create(**defaults)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_success_marks_done(self, mock_extract):
        session = self._session()
        mock_extract.return_value = {
            'result': {'questions': [{'q': 1}], 'usage': {'total_tokens': 80}},
            'extracted_images': {'img1': 'data'},
            'page_count': 2,
        }

        result = process_homework_pdf(session.pk, [], [])

        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_DONE)
        self.assertEqual(session.page_count, 2)
        self.assertEqual(session.tokens_used, 80)
        self.assertEqual(session.extracted_images, {'img1': 'data'})
        self.assertEqual(result['page_count'], 2)

    @patch('worksheets.services.extract_and_classify_worksheet', side_effect=RuntimeError('ocr boom'))
    def test_failure_marks_error_and_reraises(self, _mock_extract):
        session = self._session()
        with self.assertRaises(RuntimeError):
            process_homework_pdf(session.pk, [], [])
        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_ERROR)
        self.assertIn('ocr boom', session.error_message)


class HomeworkUploadEnqueueTests(TestCase):
    """The upload view should enqueue an RQ job, not spawn a thread."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_up', 'hw_up@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='HW2', slug='hw2', admin=cls.user)

    @patch('homework.views.log_event')
    @patch('billing.entitlements.get_school_for_user')
    @patch('taskqueue.services.django_rq.get_queue')
    def test_upload_enqueues_job(self, mock_get_queue, mock_school, _mock_log):
        from unittest.mock import MagicMock
        mock_school.return_value = self.school
        mock_job = MagicMock(); mock_job.id = 'hw-job-1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        self.client.force_login(self.user)
        pdf = SimpleUploadedFile('hw.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        resp = self.client.post(reverse('homework:pdf_upload'), {'pdf_file': pdf})

        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_PROCESSING)
        self.assertRedirects(
            resp, reverse('homework:pdf_processing', args=[session.pk]),
            fetch_redirect_response=False,
        )
        mock_queue.enqueue.assert_called_once()
