"""Name-the-shape mode — homework upload wiring + task threading."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf


class HomeworkSessionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_sn', 'hw_sn@test.internal', 'pw1!')

    def test_defaults_off(self):
        s = HomeworkUploadSession.objects.create(user=self.user, pdf_filename='a.pdf')
        self.assertFalse(s.shape_naming)

    def test_can_enable(self):
        s = HomeworkUploadSession.objects.create(
            user=self.user, pdf_filename='a.pdf', shape_naming=True)
        s.refresh_from_db()
        self.assertTrue(s.shape_naming)


class ProcessHomeworkPdfPassesShapeNamingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_t', 'hw_t@test.internal', 'pw1!')
        cls.school = School.objects.create(name='HW SN', slug='hw-sn', admin=cls.user)

    def _session(self, **overrides):
        defaults = dict(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'),
        )
        defaults.update(overrides)
        return HomeworkUploadSession.objects.create(**defaults)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_shape_naming_flag_forwarded(self, mock_extract):
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {'total_tokens': 0}},
            'extracted_images': {}, 'page_count': 1,
        }
        session = self._session(shape_naming=True)
        process_homework_pdf(session.pk, [], [])
        self.assertEqual(mock_extract.call_args.kwargs['shape_naming'], True)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_default_flag_forwarded_false(self, mock_extract):
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {'total_tokens': 0}},
            'extracted_images': {}, 'page_count': 1,
        }
        session = self._session()
        process_homework_pdf(session.pk, [], [])
        self.assertEqual(mock_extract.call_args.kwargs['shape_naming'], False)


class HomeworkUploadViewShapeNamingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_uv', 'hw_uv@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='HW UV', slug='hw-uv', admin=cls.user)

    @patch('homework.views.log_event')
    @patch('billing.entitlements.get_school_for_user')
    @patch('taskqueue.services.django_rq.get_queue')
    def _post(self, data, mock_get_queue, mock_school, _log):
        mock_school.return_value = self.school
        mock_job = MagicMock(); mock_job.id = 'j1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue
        self.client.force_login(self.user)
        pdf = SimpleUploadedFile('hw.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        return self.client.post(reverse('homework:pdf_upload'), {'pdf_file': pdf, **data})

    def test_checkbox_on_sets_shape_naming(self):
        self._post({'shape_naming': 'on'})
        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertTrue(session.shape_naming)

    def test_checkbox_absent_defaults_off(self):
        self._post({})
        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertFalse(session.shape_naming)

    def test_upload_page_renders_shape_naming_checkbox(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('homework:pdf_upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="shape_naming"')
