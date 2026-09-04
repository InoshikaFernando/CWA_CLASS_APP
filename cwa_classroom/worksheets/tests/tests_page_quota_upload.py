"""Worksheet PDF upload draws on the same monthly page allowance.

Worksheets were the third unmetered pipeline: like homework, every page went to
the AI at full cost and the quota never moved.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from ai_import.models import AIImportUsage
from billing.models import (
    InstitutePlan, ModuleProduct, ModuleSubscription, SchoolSubscription,
)
from billing.page_quota import current_period_start
from classroom.models import School
from worksheets.models import WorksheetUploadSession


def _pdf_bytes(page_count):
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'Question on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


class WorksheetUploadPageQuotaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'ws_quota_teacher', 'ws_quota@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False,
        )
        cls.school = School.objects.create(
            name='WS Quota School', slug='ws-quota-school', admin=cls.user)
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)

        plan = InstitutePlan.objects.create(
            name='WS Quota Plan', slug='ws-quota-plan', price=Decimal('89.00'),
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
            defaults={'name': 'AI Import - Professional', 'price': Decimal('30.00'),
                      'pages_per_month': 10, 'is_active': True},
        )
        ModuleSubscription.objects.create(
            school_subscription=sub, module='ai_import_professional', is_active=True)

    def setUp(self):
        self.client.force_login(self.user)

    def _set_used(self, used):
        AIImportUsage.objects.update_or_create(
            school=self.school, period_start=current_period_start(),
            defaults={'pages_processed': used, 'tokens_used': 0},
        )

    def _used(self):
        row = AIImportUsage.objects.filter(
            school=self.school, period_start=current_period_start()).first()
        return row.pages_processed if row else 0

    @patch('worksheets.tasks.process_worksheet_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, pages, mock_get_queue, _mock_task):
        self._job_seq = getattr(self, '_job_seq', 0) + 1
        job = MagicMock(); job.id = f'ws-job-{self._job_seq}'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue
        pdf = SimpleUploadedFile(
            'sheet.pdf', _pdf_bytes(pages), content_type='application/pdf')
        return self.client.post(
            reverse('worksheets:upload'),
            {'pdf_file': pdf, 'page_selection': ''}, follow=True,
        )

    def test_an_upload_within_the_allowance_is_charged(self):
        self._set_used(0)
        self._upload(3)
        self.assertEqual(WorksheetUploadSession.objects.count(), 1)
        self.assertEqual(self._used(), 3)

    def test_an_upload_over_the_allowance_is_refused(self):
        self._set_used(9)
        self._upload(4)
        self.assertEqual(WorksheetUploadSession.objects.count(), 0)
        self.assertEqual(self._used(), 9)

    def test_worksheets_share_the_budget_with_homework(self):
        """One allowance across the pipelines, not one each."""
        self._set_used(8)      # 2 left
        self._upload(2)        # spends the rest
        self.assertEqual(self._used(), 10)
        self._upload(1)        # nothing left for the next one
        self.assertEqual(WorksheetUploadSession.objects.count(), 1)
