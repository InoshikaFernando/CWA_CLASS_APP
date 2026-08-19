"""Homework PDF imports get a second opinion too, billed to homework (CPP-384).

Homework PDFs author real questions students then sit, so they need the same
independent check as any other import. The verification itself lives in the
shared extractor (see worksheets/tests/test_second_opinion.py); what has to be
proved separately here is that the homework path records the verifier's spend as
*homework's* cost — the shared extractor cannot know which caller it is serving.
"""
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role
from classroom.models import School
from homework.models import HomeworkUploadSession
from homework.tasks import process_homework_pdf
from taskqueue.models import AIUsageLog


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class HomeworkVerifierBillingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            'hw_verify', 'hw_verify@test.internal', 'pw1!')
        role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(role)
        cls.school = School.objects.create(
            name='HW Verify School', slug='hw-verify-school', admin=cls.user)

    def _process(self, verification):
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'))
        with patch('worksheets.services.extract_and_classify_worksheet') as extract:
            extract.return_value = {
                'result': {'questions': [{'q': 1}],
                           'usage': {'input_tokens': 1_000_000,
                                     'output_tokens': 0,
                                     'total_tokens': 1_000_000},
                           'verification': verification},
                'extracted_images': {},
                'page_count': 3,
            }
            process_homework_pdf(session.pk, [], [])
        return session

    def test_verifier_tokens_are_billed_to_openai_under_the_homework_source(self):
        self._process({'input_tokens': 1_000_000, 'output_tokens': 0})

        row = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_OPENAI)
        self.assertEqual(row.source, AIUsageLog.SOURCE_HOMEWORK)
        self.assertEqual(row.est_cost_usd, Decimal('2.50000'))

        claude = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_ANTHROPIC)
        self.assertEqual(claude.source, AIUsageLog.SOURCE_HOMEWORK)

    def test_no_openai_row_when_the_verifier_did_not_run(self):
        self._process(None)
        self.assertFalse(AIUsageLog.objects.filter(
            provider=AIUsageLog.PROVIDER_OPENAI).exists())

    def test_the_upload_still_completes(self):
        # The verification must not become a gate on the import.
        session = self._process({'input_tokens': 10, 'output_tokens': 1})
        session.refresh_from_db()
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_DONE)

    def test_review_flags_survive_into_the_saved_questions(self):
        # The teacher's preview reads needs_review off extracted_data, so the
        # flag has to be persisted, not just set in memory in the worker.
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('hw.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'))
        with patch('worksheets.services.extract_and_classify_worksheet') as extract:
            extract.return_value = {
                'result': {
                    'questions': [{'question_text': 'q',
                                   'needs_review': True,
                                   'review_reason': 'Verifier answered 7, not 8.'}],
                    'usage': {},
                    'verification': {'checked': 1, 'flagged': 1,
                                     'input_tokens': 10, 'output_tokens': 1},
                },
                'extracted_images': {},
                'page_count': 1,
            }
            process_homework_pdf(session.pk, [], [])

        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        self.assertTrue(saved['needs_review'])
        self.assertIn('7', saved['review_reason'])
