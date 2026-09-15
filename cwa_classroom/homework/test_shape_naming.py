"""The homework upload has no name-the-shape switch any more.

Shape sheets are detected per item by the classifier (``name_the_shape`` in
``worksheets/services.py``, tested there); the upload form, the session model
and the background task carry no mode flag.
"""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing.testing import grant_ai_pages
from classroom.models import School
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf


class HomeworkSessionHasNoModeFlagTests(TestCase):
    def test_the_field_is_gone(self):
        self.assertFalse(any(f.name == 'shape_naming'
                             for f in HomeworkUploadSession._meta.get_fields()))


class ProcessHomeworkPdfForwardsNoModeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_t', 'hw_t@test.internal', 'pw1!')
        cls.school = School.objects.create(name='HW SN', slug='hw-sn', admin=cls.user)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_extract_is_called_without_a_mode_flag(self, mock_extract):
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {'total_tokens': 0}},
            'extracted_images': {}, 'page_count': 1,
        }
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'),
        )
        process_homework_pdf(session.pk, [], [])
        self.assertNotIn('shape_naming', mock_extract.call_args.kwargs)


class HomeworkUploadPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('hw_uv', 'hw_uv@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='HW UV', slug='hw-uv', admin=cls.user)
        grant_ai_pages(cls.school)

    def test_upload_page_has_no_checkbox_and_says_shapes_are_detected(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('homework:pdf_upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="shape_naming"')
        self.assertContains(resp, 'detected automatically')

    @patch('homework.views.log_event')
    @patch('billing.entitlements.get_school_for_user')
    @patch('taskqueue.services.django_rq.get_queue')
    def test_a_stale_shape_naming_field_in_the_post_is_ignored(
            self, mock_get_queue, mock_school, _log):
        mock_school.return_value = self.school
        mock_job = MagicMock(); mock_job.id = 'j1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue
        self.client.force_login(self.user)
        pdf = SimpleUploadedFile('hw.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        self.client.post(reverse('homework:pdf_upload'), {'pdf_file': pdf, 'shape_naming': 'on'})
        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertFalse(hasattr(session, 'shape_naming'))
