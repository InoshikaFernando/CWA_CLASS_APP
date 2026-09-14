"""Homework PDF upload is charged against — and refused by — the page allowance.

This is the hole the shared budget was built to close: homework uploads spent
real AI money per page and never touched the quota, so a school on the 600-page
tier could run several times that with the counter reading zero.
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
from homework.models import HomeworkUploadSession


def _pdf_bytes(page_count):
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'Question on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


class HomeworkUploadPageQuotaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'hw_quota_teacher', 'hw_quota@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False,
        )
        cls.school = School.objects.create(
            name='HW Quota School', slug='hw-quota-school', admin=cls.user)
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)

        plan = InstitutePlan.objects.create(
            name='HW Quota Plan', slug='hw-quota-plan', price=Decimal('89.00'),
            class_limit=5, student_limit=100, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'),
        )
        sub = SchoolSubscription.objects.create(
            school=cls.school, plan=plan, status='active',
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        for slug, pages, price in [
            ('ai_import_professional', 10, '30.00'),
            ('ai_import_enterprise', 1000, '50.00'),
        ]:
            ModuleProduct.objects.update_or_create(
                module=slug,
                defaults={'name': f'AI Import - {slug}', 'price': Decimal(price),
                          'pages_per_month': pages, 'is_active': True},
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

    @patch('homework.tasks.process_homework_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def _upload(self, pages, mock_get_queue, _mock_task, selection=''):
        # BackgroundTask.rq_job_id is unique, so a test that uploads twice
        # needs two job ids.
        self._job_seq = getattr(self, '_job_seq', 0) + 1
        job = MagicMock(); job.id = f'job-{self._job_seq}'
        queue = MagicMock(); queue.enqueue.return_value = job
        mock_get_queue.return_value = queue
        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(pages), content_type='application/pdf')
        return self.client.post(
            reverse('homework:pdf_upload'),
            {'pdf_file': pdf, 'page_selection': selection},
            follow=True,
        )

    def test_an_upload_within_the_allowance_is_charged(self):
        self._set_used(0)
        self._upload(4)
        self.assertEqual(HomeworkUploadSession.objects.count(), 1)
        self.assertEqual(self._used(), 4)

    def test_an_upload_over_the_allowance_is_refused(self):
        self._set_used(8)          # 2 left of 10
        response = self._upload(5)
        self.assertEqual(HomeworkUploadSession.objects.count(), 0)
        self.assertEqual(self._used(), 8)   # nothing charged for a refusal
        self.assertContains(response, 'Enterprise')

    def test_an_exhausted_allowance_refuses_even_one_page(self):
        self._set_used(10)
        self._upload(1)
        self.assertEqual(HomeworkUploadSession.objects.count(), 0)

    def test_a_page_selection_is_charged_only_for_what_it_selects(self):
        """Skipping the cover sheet should get an upload under the line."""
        self._set_used(7)          # 3 left
        self._upload(10, selection='2-4')
        self.assertEqual(HomeworkUploadSession.objects.count(), 1)
        self.assertEqual(self._used(), 10)

    def test_charging_accumulates_across_uploads(self):
        self._set_used(0)
        self._upload(3)
        self._upload(4)
        self.assertEqual(self._used(), 7)
        self.assertEqual(HomeworkUploadSession.objects.count(), 2)

    @patch('homework.tasks.process_homework_pdf')
    @patch('taskqueue.services.django_rq.get_queue', side_effect=RuntimeError('queue down'))
    def test_pages_are_refunded_when_the_job_cannot_be_queued(self, _q, _t):
        self._set_used(2)
        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(3), content_type='application/pdf')
        self.client.post(
            reverse('homework:pdf_upload'),
            {'pdf_file': pdf, 'page_selection': ''}, follow=True,
        )
        # Session rolled back and the pages handed back — nothing was extracted.
        self.assertEqual(HomeworkUploadSession.objects.count(), 0)
        self.assertEqual(self._used(), 2)

    def _drop_the_ai_module(self):
        ModuleSubscription.objects.filter(
            school_subscription__school=self.school,
            module='ai_import_professional',
        ).update(is_active=False)

    def test_a_school_with_no_ai_module_cannot_upload_a_pdf(self):
        """The AI module is the licence to spend AI pages, wherever you start.

        This test used to assert the opposite — "homework upload predates the
        allowance; a plain plan keeps working" — and that was the hole: the
        schools that had bought a tier were capped, and the ones that hadn't
        read PDFs with AI for free through this screen.
        """
        self._drop_the_ai_module()
        self._upload(5)
        self.assertEqual(HomeworkUploadSession.objects.count(), 0)

    def test_the_refusal_names_the_module_and_links_the_plans(self):
        from billing.page_quota import ai_plans_url

        self._drop_the_ai_module()
        pdf = SimpleUploadedFile(
            'paper.pdf', _pdf_bytes(3), content_type='application/pdf')
        response = self.client.post(
            reverse('homework:pdf_upload'),
            {'pdf_file': pdf, 'page_selection': ''}, follow=True,
        )
        body = response.content.decode()
        self.assertIn('needs an AI module', body)
        self.assertIn(ai_plans_url(), body)

    def test_authored_json_still_uploads_without_an_ai_module(self):
        """Only the AI path is gated. A hand-authored file costs no AI at all.

        The JSON branch returns before the budget check is reached, which is
        correct and entirely undocumented — exactly the ordering a later tidy-up
        moves without noticing. Pinned here.
        """
        import json as _json

        from classroom.models import Level, Subject

        # What the importer resolves a question against; same shape as
        # classroom/tests/test_assignment_json_upload.py.
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        Level.objects.get_or_create(
            level_number=4, defaults={'display_name': 'Year 4'})

        self._drop_the_ai_module()
        payload = _json.dumps({
            'topic': 'Fractions',
            'year_level': 4,
            'questions': [{
                'question_text': 'What is 1/2 + 1/4?',
                'question_type': 'multiple_choice',
                'difficulty': 1,
                'points': 1,
                'answers': [
                    {'text': '3/4', 'is_correct': True, 'order': 1},
                    {'text': '1/2', 'is_correct': False, 'order': 2},
                ],
            }],
        }).encode()
        authored = SimpleUploadedFile(
            'questions.json', payload, content_type='application/json')

        response = self.client.post(
            reverse('homework:pdf_upload'), {'json_file': authored}, follow=True,
        )

        # Asserted on the outcome, not on the absence of a phrase: the upload
        # page legitimately carries the "needs an AI module" panel for this
        # school, so a string check here would fail on a working upload.
        session = HomeworkUploadSession.objects.filter(user=self.user).first()
        self.assertIsNotNone(session, 'the authored upload was refused')
        self.assertRedirects(
            response, reverse('homework:json_confirm', args=[session.pk]))
        self.assertEqual(self._used(), 0, 'an authored upload must cost no AI pages')
