"""Page selection through the AI-import upload view, task and quota check."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from ai_import.models import AIImportSession, AIImportUsage
from ai_import.tasks import process_pdf_import
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from billing.page_quota import current_period_start
from classroom.models import School


def _pdf_bytes(page_count):
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'Question on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


class AIImportPageSelectionUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            'ai_ps_super', 'ai_ps_super@test.internal', 'pw1!')
        cls.school = School.objects.create(
            name='AI PS School', slug='ai-ps-school', admin=cls.superuser)

    def setUp(self):
        self.client.force_login(self.superuser)

    @patch('ai_import.views.get_school_for_user')
    @patch('ai_import.tasks.process_pdf_import')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, spec, mock_get_queue, _mock_task, mock_school, pages=6):
        mock_school.return_value = self.school
        job = MagicMock(); job.id = 'job-1'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue

        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(pages), content_type='application/pdf')
        data = {'pdf_file': pdf}
        if spec is not None:
            data['page_selection'] = spec
        return self.client.post(reverse('ai_import:upload'), data)

    def test_upload_page_offers_the_field(self):
        resp = self.client.get(reverse('ai_import:upload'))
        self.assertContains(resp, 'name="page_selection"')
        self.assertContains(resp, 'Pages to extract')

    def test_valid_spec_is_stored_on_the_session(self):
        self._upload('2-4')
        session = AIImportSession.objects.get(user=self.superuser)
        self.assertEqual(session.page_selection, '2-4')

    def test_only_the_selected_pages_are_counted_against_quota(self):
        """A 6-page paper with pages 2-4 selected costs 3 pages, not 6."""
        self._upload('2-4')
        session = AIImportSession.objects.get(user=self.superuser)
        self.assertEqual(session.page_count, 3)

    def test_no_selection_counts_every_page(self):
        self._upload('')
        session = AIImportSession.objects.get(user=self.superuser)
        self.assertEqual(session.page_count, 6)

    def test_out_of_range_spec_is_rejected_without_creating_a_session(self):
        resp = self._upload('9-12')

        self.assertFalse(AIImportSession.objects.exists())
        self.assertRedirects(
            resp, reverse('ai_import:upload'), fetch_redirect_response=False)


class AIImportQuotaWithSelectionTests(TestCase):
    """Selecting fewer pages must be enough to get an upload under the quota.

    This is the point of charging for selected pages rather than the whole PDF:
    a teacher with 4 pages left this month can still import the 3 question pages
    out of a 10-page paper.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'ai_ps_quota', 'ai_ps_quota@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False,
        )
        cls.school = School.objects.create(
            name='AI PS Quota School', slug='ai-ps-quota-school', admin=cls.user)

        # A real 50-page tier with 46 already spent, rather than a patched
        # quota helper: the budget now lives in billing.page_quota and is
        # charged at upload, so the arithmetic under test is the real one.
        plan = InstitutePlan.objects.create(
            name='AI PS Quota Plan', slug='ai-ps-quota-plan', price=Decimal('89.00'),
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        sub = SchoolSubscription.objects.create(
            school=cls.school, plan=plan, status='active',
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        ModuleProduct.objects.update_or_create(
            module='ai_import_professional',
            defaults={'name': 'AI Import - Professional',
                      'price': Decimal('30.00'), 'pages_per_month': 50},
        )
        ModuleSubscription.objects.create(
            school_subscription=sub, module='ai_import_professional', is_active=True,
        )
        AIImportUsage.objects.create(
            school=cls.school, period_start=current_period_start(),
            pages_processed=46, tokens_used=0,
        )

    @patch('ai_import.views._has_ai_import_access', return_value=True)
    @patch('ai_import.views.get_school_for_user')
    @patch('ai_import.tasks.process_pdf_import')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, spec, mock_get_queue, _mock_task,
                mock_school, _mock_access):
        mock_school.return_value = self.school
        job = MagicMock(); job.id = 'job-1'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue

        self.client.force_login(self.user)
        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(10), content_type='application/pdf')
        return self.client.post(
            reverse('ai_import:upload'),
            {'pdf_file': pdf, 'page_selection': spec},
        )

    def test_whole_paper_is_blocked_when_it_exceeds_the_remaining_quota(self):
        self._upload('')
        self.assertFalse(AIImportSession.objects.exists())

    def test_a_selection_within_the_remaining_quota_is_allowed(self):
        self._upload('2-4')

        session = AIImportSession.objects.get(user=self.user)
        self.assertEqual(session.page_count, 3)
        self.assertEqual(session.page_selection, '2-4')

    def test_a_selection_still_over_the_quota_is_blocked(self):
        self._upload('2-9')
        self.assertFalse(AIImportSession.objects.exists())


class AIImportPageSelectionTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'ai_ps_task', 'ai_ps_task@test.internal', 'pw1!')
        cls.school = School.objects.create(
            name='AI PS Task School', slug='ai-ps-task-school', admin=cls.user)

    def _session(self, **overrides):
        defaults = dict(
            user=self.user, school=self.school, pdf_filename='q.pdf',
            status=AIImportSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('q.pdf', b'%PDF-1.4 x'),
        )
        defaults.update(overrides)
        return AIImportSession.objects.create(**defaults)

    @patch('ai_import.tasks.classify_questions')
    @patch('ai_import.tasks.extract_pdf_content')
    def test_task_passes_the_stored_spec_to_extraction(self, mock_extract, mock_classify):
        mock_extract.return_value = {'page_count': 3, 'pages': [], 'page_selection': None}
        mock_classify.return_value = {'questions': [], 'usage': {}}
        session = self._session(page_selection='2-4')

        process_pdf_import(session.pk)

        self.assertEqual(mock_extract.call_args.kwargs['page_selection'], '2-4')

    @patch('ai_import.tasks.classify_questions')
    @patch('ai_import.tasks.extract_pdf_content')
    def test_selection_summary_is_stored_for_the_preview(self, mock_extract, mock_classify):
        from worksheets.page_selection import selection_summary

        summary = selection_summary('2-4', [2, 3, 4], 6)
        mock_extract.return_value = {
            'page_count': 3, 'pages': [], 'page_selection': summary,
        }
        mock_classify.return_value = {'questions': [], 'usage': {}}
        session = self._session(page_selection='2-4')

        process_pdf_import(session.pk)

        session.refresh_from_db()
        self.assertEqual(
            session.extracted_data['page_selection']['excluded'], [1, 5, 6])

    @patch('ai_import.tasks.classify_questions')
    @patch('ai_import.tasks.extract_pdf_content')
    def test_only_the_extracted_pages_are_billed(self, mock_extract, mock_classify):
        from taskqueue.models import AIUsageLog

        mock_extract.return_value = {'page_count': 3, 'pages': [], 'page_selection': None}
        mock_classify.return_value = {'questions': [], 'usage': {'total_tokens': 9}}
        session = self._session(page_selection='2-4')

        process_pdf_import(session.pk)

        log = AIUsageLog.objects.get(session_id=session.pk)
        self.assertEqual(log.pages, 3)
