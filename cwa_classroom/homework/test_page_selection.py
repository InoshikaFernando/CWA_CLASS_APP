"""Page selection through the homework PDF upload view and background task."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School
from billing.testing import grant_ai_pages
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf


def _pdf_bytes(page_count):
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'Question on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


class HomeworkPageSelectionUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'hw_ps', 'hw_ps@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False,
        )
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(
            name='HW PS School', slug='hw-ps-school', admin=cls.user)
        grant_ai_pages(cls.school)

    def setUp(self):
        self.client.force_login(self.user)

    @patch('homework.tasks.process_homework_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, spec, mock_get_queue, _mock_task, pages=6):
        job = MagicMock(); job.id = 'job-1'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue

        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(pages), content_type='application/pdf')
        data = {'pdf_file': pdf}
        if spec is not None:
            data['page_selection'] = spec
        return self.client.post(reverse('homework:pdf_upload'), data)

    def test_upload_page_offers_the_field(self):
        resp = self.client.get(reverse('homework:pdf_upload'))
        self.assertContains(resp, 'name="page_selection"')
        self.assertContains(resp, 'Pages to extract')

    def test_valid_spec_is_stored_on_the_session(self):
        self._upload('2-')
        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertEqual(session.page_selection, '2-')

    def test_blank_spec_stores_blank(self):
        self._upload('')
        session = HomeworkUploadSession.objects.get(user=self.user)
        self.assertEqual(session.page_selection, '')

    def test_out_of_range_spec_is_rejected_without_creating_a_session(self):
        resp = self._upload('20-')

        self.assertFalse(HomeworkUploadSession.objects.exists())
        self.assertRedirects(
            resp, reverse('homework:pdf_upload'), fetch_redirect_response=False)

    def test_backwards_range_is_rejected(self):
        self._upload('5-2')
        self.assertFalse(HomeworkUploadSession.objects.exists())


class HomeworkPageSelectionTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'hw_ps_task', 'hw_ps_task@test.internal', 'pw1!')
        cls.school = School.objects.create(
            name='HW PS Task School', slug='hw-ps-task-school', admin=cls.user)

    @patch('worksheets.services.extract_and_classify_worksheet')
    def test_task_passes_the_stored_spec_to_extraction(self, mock_extract):
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {}},
            'extracted_images': {},
            'page_count': 2,
        }
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            page_selection='2-3',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 x'),
        )

        process_homework_pdf(session.pk, [], [])

        self.assertEqual(mock_extract.call_args.kwargs['page_selection'], '2-3')


class HomeworkPreviewNoticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'hw_ps_prev', 'hw_ps_prev@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False,
        )
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(
            name='HW PS Prev School', slug='hw-ps-prev-school', admin=cls.user)

    def _session(self, summary):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            page_count=3,
            extracted_data={
                'questions': [{'question_text': 'What is 2+2?',
                               'question_type': 'short_answer',
                               'correct_answer': '4'}],
                'page_selection': summary,
            },
        )

    def test_notice_names_the_excluded_pages(self):
        from worksheets.page_selection import selection_summary

        session = self._session(selection_summary('1-8', list(range(1, 9)), 10))
        self.client.force_login(self.user)

        resp = self.client.get(
            reverse('homework:pdf_preview', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Extracted page')
        self.assertContains(resp, '9, 10')

    def test_no_notice_when_every_page_was_extracted(self):
        from worksheets.page_selection import selection_summary

        session = self._session(selection_summary('', [1, 2, 3], 3))
        self.client.force_login(self.user)

        resp = self.client.get(
            reverse('homework:pdf_preview', args=[session.pk]))

        self.assertNotContains(resp, 'Extracted page')
