"""CPP-327: async worksheet PDF upload — task, enqueue, status polling."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher
from worksheets.models import WorksheetUploadSession
from worksheets.tasks import process_worksheet_pdf


class WorksheetAsyncTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'ws_owner', 'ws_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS Async School', slug='ws-async-school', admin=cls.owner,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)
        cls.other = CustomUser.objects.create_user(
            'ws_other', 'ws_other@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.other.roles.add(owner_role)

    def _session(self, **overrides):
        defaults = dict(
            user=self.owner, school=self.school,
            pdf_filename='ws.pdf',
            status=WorksheetUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('ws.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
        )
        defaults.update(overrides)
        return WorksheetUploadSession.objects.create(**defaults)


class ProcessWorksheetPdfTaskTests(WorksheetAsyncTestBase):
    @patch('worksheets.tasks.extract_and_classify_worksheet')
    def test_success_marks_ready_and_stores_result(self, mock_extract):
        session = self._session()
        mock_extract.return_value = {
            'result': {'questions': [{'q': 1}, {'q': 2}], 'usage': {'total_tokens': 150}},
            'extracted_images': {'img1': 'data'},
            'page_count': 4,
        }

        result = process_worksheet_pdf(session.pk)

        session.refresh_from_db()
        self.assertEqual(session.status, WorksheetUploadSession.STATUS_READY)
        self.assertEqual(session.page_count, 4)
        self.assertEqual(session.tokens_used, 150)
        self.assertEqual(session.extracted_images, {'img1': 'data'})
        self.assertEqual(len(session.extracted_data['questions']), 2)
        self.assertEqual(result['questions'], 2)

    @patch('worksheets.tasks.extract_and_classify_worksheet')
    def test_success_records_ai_usage_ledger_row(self, mock_extract):
        from decimal import Decimal

        from taskqueue.models import AIUsageLog

        session = self._session()
        mock_extract.return_value = {
            'result': {
                'questions': [{'q': 1}],
                'usage': {'input_tokens': 30_000, 'output_tokens': 15_000,
                          'total_tokens': 45_000},
            },
            'extracted_images': {},
            'page_count': 13,
        }

        process_worksheet_pdf(session.pk)

        log = AIUsageLog.objects.get(session_id=session.pk)
        self.assertEqual(log.source, AIUsageLog.SOURCE_WORKSHEET)
        self.assertEqual(log.school_id, session.school_id)
        self.assertEqual(log.pages, 13)
        self.assertEqual(log.input_tokens, 30_000)
        self.assertEqual(log.output_tokens, 15_000)
        # 30k in @ $5/M + 15k out @ $25/M = 0.525 (Opus 4.8 rates)
        self.assertEqual(log.est_cost_usd, Decimal('0.52500'))

    @patch('worksheets.tasks.extract_and_classify_worksheet', side_effect=RuntimeError('ocr boom'))
    def test_failure_marks_failed_and_reraises(self, _mock):
        session = self._session()
        with self.assertRaises(RuntimeError):
            process_worksheet_pdf(session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, WorksheetUploadSession.STATUS_FAILED)
        self.assertIn('ocr boom', session.error_message)

    def test_missing_pdf_file_fails_gracefully(self):
        session = self._session(pdf_file=None)
        with self.assertRaises(ValueError):
            process_worksheet_pdf(session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, WorksheetUploadSession.STATUS_FAILED)


class WorksheetUploadEnqueueTests(WorksheetAsyncTestBase):
    def setUp(self):
        self.client.force_login(self.owner)

    @patch('worksheets.tasks.process_worksheet_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def test_upload_creates_processing_session_and_redirects(self, mock_get_queue, _task):
        mock_job = MagicMock(); mock_job.id = 'ws-job-1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        resp = self.client.post(reverse('worksheets:upload'), {'pdf_file': pdf})

        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertEqual(session.status, WorksheetUploadSession.STATUS_PROCESSING)
        self.assertTrue(session.pdf_file)
        self.assertRedirects(
            resp, reverse('worksheets:processing', args=[session.pk]),
            fetch_redirect_response=False,
        )
        mock_queue.enqueue.assert_called_once()

    @patch('taskqueue.services.django_rq.get_queue', side_effect=ConnectionError('redis down'))
    def test_enqueue_failure_deletes_session_and_shows_message(self, _mock):
        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        resp = self.client.post(reverse('worksheets:upload'), {'pdf_file': pdf})
        # Orphaned session cleaned up, redirected back to upload.
        self.assertFalse(WorksheetUploadSession.objects.filter(user=self.owner).exists())
        self.assertRedirects(
            resp, reverse('worksheets:upload'), fetch_redirect_response=False,
        )


class WorksheetStatusPollTests(WorksheetAsyncTestBase):
    def test_status_processing_renders_partial(self):
        session = self._session()
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('worksheets:status', args=[session.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('HX-Redirect', resp)

    def test_status_ready_sends_hx_redirect(self):
        session = self._session(status=WorksheetUploadSession.STATUS_READY)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('worksheets:status', args=[session.pk]))
        self.assertEqual(resp['HX-Redirect'], reverse('worksheets:preview', args=[session.pk]))

    def test_other_user_cannot_poll_session(self):
        session = self._session()
        self.client.force_login(self.other)
        resp = self.client.get(reverse('worksheets:status', args=[session.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_preview_redirects_while_processing(self):
        session = self._session()
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('worksheets:preview', args=[session.pk]))
        self.assertRedirects(
            resp, reverse('worksheets:processing', args=[session.pk]),
            fetch_redirect_response=False,
        )
