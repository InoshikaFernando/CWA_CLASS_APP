"""Homework PDF upload: live progress + dead-worker detection.

An upload whose work-horse is hard-killed (OOM, crash) never runs its failure
handler, so before this the session sat in 'processing' and the polling page
span forever. The worker now heartbeats as it works, and the poll endpoint fails
a session whose heartbeat has gone stale.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import School
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf


class _TeacherFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_prog', 'hw_prog@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='Prog School', slug='prog-school', admin=cls.user)

    def _session(self, **overrides):
        defaults = dict(
            user=self.user, school=self.school,
            pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'),
        )
        defaults.update(overrides)
        return HomeworkUploadSession.objects.create(**defaults)

    def _age(self, session, minutes):
        HomeworkUploadSession.objects.filter(pk=session.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes))
        session.refresh_from_db()


@patch('homework.tasks.HEARTBEAT_MIN_INTERVAL_S', 0)
class ProgressHeartbeatTests(_TeacherFixture):
    """The task reports what it is doing onto the session."""

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_task_records_progress_from_the_pipeline(self, mock_extract):
        session = self._session()
        seen = {}

        def fake_extract(pdf_io, topics, levels, shape_naming=False, progress=None,
                         page_selection=None):
            progress('Read 2 of 5 sections…')
            seen['session'] = HomeworkUploadSession.objects.get(pk=session.pk)
            return {'result': {'questions': [], 'usage': {}},
                    'extracted_images': {}, 'page_count': 3}

        mock_extract.side_effect = fake_extract
        process_homework_pdf(session.pk, [], [])

        self.assertEqual(seen['session'].progress_message, 'Read 2 of 5 sections…')
        self.assertIsNotNone(seen['session'].progress_updated_at)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_progress_is_cleared_when_the_upload_finishes(self, mock_extract):
        session = self._session()
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {'total_tokens': 5}},
            'extracted_images': {}, 'page_count': 1,
        }

        process_homework_pdf(session.pk, [], [])

        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_DONE)
        self.assertEqual(session.progress_message, '')

    def test_a_failed_heartbeat_write_is_swallowed(self):
        """Heartbeat writes are best-effort — they must never fail the job."""
        from homework.tasks import _progress_reporter

        session = self._session()
        report = _progress_reporter(session.pk)
        with patch('homework.models.HomeworkUploadSession.objects.filter',
                   side_effect=Exception('db wobble')):
            report('Read 1 of 2 sections…')  # must not raise

        session.refresh_from_db()
        self.assertEqual(session.progress_message, '')

    def test_progress_message_is_truncated_to_the_column_width(self):
        session = self._session()
        from homework.tasks import _progress_reporter

        _progress_reporter(session.pk)('x' * 500)

        session.refresh_from_db()
        self.assertEqual(len(session.progress_message), 200)


@override_settings(HOMEWORK_PDF_STALL_MINUTES=10)
class StalledUploadTests(_TeacherFixture):
    """A session whose worker went silent must not be polled forever."""

    def setUp(self):
        self.client.force_login(self.user)

    def test_status_endpoint_keeps_polling_while_the_worker_reports_in(self):
        session = self._session(progress_message='Read 1 of 4 sections…')
        self._age(session, 25)  # long job, but…
        HomeworkUploadSession.objects.filter(pk=session.pk).update(
            progress_updated_at=timezone.now())  # …still alive

        resp = self.client.get(reverse('homework:pdf_status', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('HX-Redirect', resp)
        self.assertContains(resp, 'Read 1 of 4 sections')
        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_PROCESSING)

    def test_status_endpoint_fails_a_session_whose_heartbeat_went_stale(self):
        session = self._session(progress_message='Read 1 of 4 sections…')
        self._age(session, 40)
        HomeworkUploadSession.objects.filter(pk=session.pk).update(
            progress_updated_at=timezone.now() - timedelta(minutes=15))

        resp = self.client.get(reverse('homework:pdf_status', args=[session.pk]))

        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_ERROR)
        self.assertIn('did not report any progress', session.error_message)
        self.assertIn(reverse('homework:pdf_upload'), resp['HX-Redirect'])

    def test_status_endpoint_fails_a_session_that_never_started(self):
        """No heartbeat at all — the job died before it could report anything."""
        session = self._session()
        self._age(session, 15)

        resp = self.client.get(reverse('homework:pdf_status', args=[session.pk]))

        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_ERROR)
        self.assertIn('HX-Redirect', resp)

    def test_processing_page_does_not_start_a_poll_for_a_dead_session(self):
        session = self._session()
        self._age(session, 30)

        resp = self.client.get(reverse('homework:pdf_processing', args=[session.pk]))

        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_ERROR)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('homework:pdf_upload'), resp['Location'])

    def test_processing_page_jumps_straight_to_a_finished_session(self):
        session = self._session(status=HomeworkUploadSession.STATUS_DONE)

        resp = self.client.get(reverse('homework:pdf_processing', args=[session.pk]))

        self.assertRedirects(
            resp, reverse('homework:pdf_preview', args=[session.pk]),
            fetch_redirect_response=False,
        )


class UploadJobTimeoutTests(_TeacherFixture):
    """Big worksheets must not be killed mid-flight by the queue default."""

    @patch('homework.views.log_event')
    @patch('billing.entitlements.get_school_for_user')
    @patch('taskqueue.services.django_rq.get_queue')
    @override_settings(HOMEWORK_PDF_JOB_TIMEOUT=2700)
    def test_upload_enqueues_with_the_long_pdf_timeout(
            self, mock_get_queue, mock_school, _mock_log):
        mock_school.return_value = self.school
        mock_job = MagicMock(); mock_job.id = 'hw-job-timeout'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        self.client.force_login(self.user)
        pdf = SimpleUploadedFile('big.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        self.client.post(reverse('homework:pdf_upload'), {'pdf_file': pdf})

        self.assertEqual(mock_queue.enqueue.call_args.kwargs['job_timeout'], 2700)


class SkippedPagesNoticeTests(_TeacherFixture):
    """Pages the extractor skipped are shown, not silently dropped."""

    def setUp(self):
        self.client.force_login(self.user)

    def test_preview_names_the_skipped_pages(self):
        session = self._session(
            status=HomeworkUploadSession.STATUS_DONE,
            page_count=24,
            extracted_data={
                'questions': [],
                'skipped_pages': [
                    {'page': 1, 'reason': 'answer_sheet'},
                    {'page': 21, 'reason': 'answer_key'},
                ],
            },
        )

        resp = self.client.get(reverse('homework:pdf_preview', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Skipped 2 pages', body)
        self.assertIn('page 1 (multiple-choice answer sheet)', body)
        self.assertIn('page 21 (answer key)', body)

    def test_preview_says_nothing_when_no_page_was_skipped(self):
        session = self._session(
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={'questions': []},
        )

        resp = self.client.get(reverse('homework:pdf_preview', args=[session.pk]))

        self.assertNotIn('with no questions on', resp.content.decode())


@patch('homework.tasks.HEARTBEAT_MIN_INTERVAL_S', 0)
class HeartbeatThreadSafetyTests(_TeacherFixture):
    """The pipeline reports from its classification threads, not just the main one."""

    def test_a_worker_thread_closes_the_connection_it_opened(self):
        """Django opens a connection per thread; a worker never closes them."""
        import threading

        from homework.tasks import _progress_reporter

        session = self._session()
        report = _progress_reporter(session.pk)

        with patch('homework.tasks.connection') as mock_connection:
            done = threading.Event()

            def in_thread():
                report('Read 1 of 4 sections…')
                done.set()

            worker = threading.Thread(target=in_thread)
            worker.start()
            worker.join(5)
            self.assertTrue(done.is_set())
            mock_connection.close.assert_called_once()

    def test_the_main_thread_keeps_its_connection(self):
        from homework.tasks import _progress_reporter

        session = self._session()
        with patch('homework.tasks.connection') as mock_connection:
            _progress_reporter(session.pk)('Read 2 of 4 sections…')

        mock_connection.close.assert_not_called()


class AnswerKeyNoticeTests(_TeacherFixture):
    """The preview says the answers came from the paper's key, and what to check."""

    def setUp(self):
        self.client.force_login(self.user)

    def _preview(self, answer_key, questions=None):
        session = self._session(
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={'questions': questions or [], 'answer_key': answer_key},
        )
        return self.client.get(
            reverse('homework:pdf_preview', args=[session.pk])).content.decode()

    def test_it_reports_what_the_key_supplied_and_corrected(self):
        body = self._preview({
            'pages': [21, 22], 'rows_found': 50, 'applied': 50,
            'agreed': 48, 'corrected': 2, 'explanation_only': 0,
            'unmatched_rows': [], 'questions_without_number': 0,
        })

        self.assertIn('Used the answer key on pages', body)
        self.assertIn('50 of 50 answers', body)
        self.assertIn('applied to the questions', body)
        self.assertIn('2</strong> disagreed', body)

    def test_it_reports_rows_and_questions_that_could_not_be_matched(self):
        body = self._preview({
            'pages': [12], 'rows_found': 10, 'applied': 6,
            'agreed': 6, 'corrected': 0, 'explanation_only': 1,
            'unmatched_rows': [7, 8], 'questions_without_number': 3,
        })

        self.assertIn('No question matched answers', body)
        self.assertIn('3 questions', body)

    def test_a_flagged_question_shows_the_review_badge(self):
        body = self._preview(
            {'pages': [21], 'rows_found': 1, 'applied': 1, 'agreed': 0,
             'corrected': 1, 'explanation_only': 0, 'unmatched_rows': [],
             'questions_without_number': 0},
            questions=[{
                'question_text': 'What is 2 + 2?', 'question_type': 'multiple_choice',
                'needs_review': True, 'review_reason': "The paper's answer key says C.",
                'answers': [{'text': '4', 'is_correct': True}],
            }],
        )

        self.assertIn('⚠ Review', body)
        self.assertIn("The paper&#x27;s answer key says C.", body)

    def test_no_banner_without_a_key(self):
        body = self._preview({})
        self.assertNotIn('Used the answer key', body)
