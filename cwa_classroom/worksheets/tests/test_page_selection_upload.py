"""Page selection through the worksheet upload view and background task."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher
from billing.testing import grant_ai_pages
from worksheets.models import WorksheetUploadSession
from worksheets.tasks import process_worksheet_pdf


def _pdf_bytes(page_count):
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'Question on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


class WorksheetPageSelectionUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'ws_ps_owner', 'ws_ps_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS PS School', slug='ws-ps-school', admin=cls.owner,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)
        grant_ai_pages(cls.school)

    def setUp(self):
        self.client.force_login(self.owner)

    def _post(self, spec=None, pages=6):
        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(pages), content_type='application/pdf')
        data = {'pdf_file': pdf}
        if spec is not None:
            data['page_selection'] = spec
        return self.client.post(reverse('worksheets:upload'), data)

    @patch('worksheets.tasks.process_worksheet_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, spec, mock_get_queue, _mock_task, pages=6):
        job = MagicMock(); job.id = 'job-1'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue
        return self._post(spec, pages=pages)

    def test_upload_page_offers_the_field(self):
        resp = self.client.get(reverse('worksheets:upload'))
        self.assertContains(resp, 'name="page_selection"')
        self.assertContains(resp, 'Pages to extract')

    def test_valid_spec_is_stored_on_the_session(self):
        resp = self._upload('2-4')

        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertEqual(session.page_selection, '2-4')
        self.assertRedirects(
            resp, reverse('worksheets:processing', args=[session.pk]),
            fetch_redirect_response=False,
        )

    def test_blank_spec_stores_blank(self):
        self._upload('')
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertEqual(session.page_selection, '')

    def test_missing_field_stores_blank(self):
        """An older cached form without the input must still upload."""
        self._upload(None)
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertEqual(session.page_selection, '')

    def test_a_full_range_is_normalised_to_blank(self):
        self._upload('1-6')
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertEqual(session.page_selection, '')

    def test_out_of_range_spec_is_rejected_without_creating_a_session(self):
        resp = self._upload('9-12')

        self.assertFalse(WorksheetUploadSession.objects.exists())
        self.assertRedirects(
            resp, reverse('worksheets:upload'), fetch_redirect_response=False)
        messages = [str(m) for m in self.client.get(reverse('worksheets:upload')).context['messages']]
        self.assertTrue(any('6 pages' in m for m in messages), messages)

    def test_unparseable_spec_is_rejected(self):
        self._upload('pages 2 to 4')
        self.assertFalse(WorksheetUploadSession.objects.exists())


class WorksheetPageSelectionTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'ws_ps_task', 'ws_ps_task@example.com', 'pass1!')
        cls.school = School.objects.create(
            name='WS PS Task School', slug='ws-ps-task-school', admin=cls.user)

    @patch('worksheets.tasks.extract_and_classify_worksheet')
    def test_task_passes_the_stored_spec_to_extraction(self, mock_extract):
        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {}},
            'extracted_images': {},
            'page_count': 3,
        }
        session = WorksheetUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='p.pdf',
            page_selection='2-4',
            status=WorksheetUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('p.pdf', b'%PDF-1.4 x'),
        )

        process_worksheet_pdf(session.pk)

        self.assertEqual(mock_extract.call_args.kwargs['page_selection'], '2-4')

    @patch('worksheets.tasks.extract_and_classify_worksheet')
    def test_only_the_selected_pages_are_billed(self, mock_extract):
        """Excluded pages are never read, so they must not hit the usage ledger."""
        from taskqueue.models import AIUsageLog

        mock_extract.return_value = {
            'result': {'questions': [], 'usage': {'total_tokens': 10}},
            'extracted_images': {},
            'page_count': 3,   # 3 selected out of a 10-page paper
        }
        session = WorksheetUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='p.pdf',
            page_selection='2-4',
            status=WorksheetUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('p.pdf', b'%PDF-1.4 x'),
        )

        process_worksheet_pdf(session.pk)

        session.refresh_from_db()
        self.assertEqual(session.page_count, 3)
        log = AIUsageLog.objects.get(session_id=session.pk)
        self.assertEqual(log.pages, 3)


class WorksheetPreviewNoticeTests(TestCase):
    """The preview must say which pages were left out."""

    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'ws_ps_prev', 'ws_ps_prev@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='WS PS Prev School', slug='ws-ps-prev-school', admin=cls.owner)
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

    def _session(self, page_selection_summary):
        return WorksheetUploadSession.objects.create(
            user=self.owner, school=self.school, pdf_filename='p.pdf',
            status=WorksheetUploadSession.STATUS_READY,
            page_count=3,
            extracted_data={
                'questions': [{'question_text': 'What is 2+2?',
                               'question_type': 'short_answer',
                               'correct_answer': '4'}],
                'page_selection': page_selection_summary,
            },
        )

    def test_notice_names_the_excluded_pages(self):
        from worksheets.page_selection import selection_summary

        session = self._session(selection_summary('2-4', [2, 3, 4], 6))
        self.client.force_login(self.owner)

        resp = self.client.get(reverse('worksheets:preview', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Extracted page')
        self.assertContains(resp, '2-4')
        self.assertContains(resp, '1, 5, 6')

    def test_no_notice_when_every_page_was_extracted(self):
        from worksheets.page_selection import selection_summary

        session = self._session(selection_summary('', [1, 2, 3], 3))
        self.client.force_login(self.owner)

        resp = self.client.get(reverse('worksheets:preview', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Extracted page')

    def test_a_session_predating_the_field_still_renders(self):
        session = self._session(None)
        self.client.force_login(self.owner)

        resp = self.client.get(reverse('worksheets:preview', args=[session.pk]))

        self.assertEqual(resp.status_code, 200)
