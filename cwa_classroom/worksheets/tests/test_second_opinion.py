"""Second-opinion verification of every PDF extraction (CPP-384).

Only the ai_import path ever got a second model's opinion. Worksheet and
homework PDFs — which author real questions students then sit — went straight
from one model's reading of the page into the question bank unchecked. CPP-377
is what that costs: 14 questions with distractors equal to the correct answer,
found only when a Year 7 student complained he was being marked wrong.

Both paths share ``extract_and_classify_worksheet``, so these tests pin the
verification onto that shared pipeline and pin the vendor accounting onto each
caller separately.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher
from taskqueue.models import AIUsageLog
from worksheets.models import WorksheetUploadSession
from worksheets.services import _second_opinion, extract_and_classify_worksheet
from worksheets.tasks import process_worksheet_pdf


def _pages():
    return {
        'pages': [
            {'page_num': 1, 'text': 'q1', 'screenshot': 'B64PAGE1'},
            {'page_num': 2, 'text': 'q2', 'screenshot': 'B64PAGE2'},
        ],
        'page_count': 2,
    }


class SecondOpinionHelperTests(TestCase):
    """The helper itself: what it runs, what it passes, what it survives."""

    def test_runs_the_deterministic_guard_and_the_paid_verifier(self):
        result = {'questions': [{'question_text': 'Which is larger?'}]}
        with patch('ai_import.verification.flag_visual_comparisons') as flag, \
             patch('ai_import.verification.verify_answers',
                   return_value={'checked': 1, 'flagged': 0}) as verify:
            summary = _second_opinion(result, _pages())

        flag.assert_called_once_with(result['questions'])
        self.assertEqual(summary, {'checked': 1, 'flagged': 0})
        self.assertIs(verify.call_args.args[0], result['questions'])

    def test_source_page_screenshots_are_handed_to_the_verifier(self):
        # Without the page images the verifier can only do a text-only check, so
        # a wrong transcription of the page — the CPP-377 failure mode — would
        # be invisible to it.
        result = {'questions': [{'question_text': 'q'}]}
        with patch('ai_import.verification.flag_visual_comparisons'), \
             patch('ai_import.verification.verify_answers',
                   return_value={}) as verify:
            _second_opinion(result, _pages())

        self.assertEqual(verify.call_args.kwargs['page_images'],
                         {1: 'B64PAGE1', 2: 'B64PAGE2'})

    def test_pages_without_a_screenshot_are_skipped_not_passed_as_none(self):
        pages = {'pages': [{'page_num': 1, 'screenshot': ''},
                           {'page_num': 2, 'screenshot': 'B64PAGE2'}],
                 'page_count': 2}
        result = {'questions': [{'question_text': 'q'}]}
        with patch('ai_import.verification.flag_visual_comparisons'), \
             patch('ai_import.verification.verify_answers',
                   return_value={}) as verify:
            _second_opinion(result, pages)

        self.assertEqual(verify.call_args.kwargs['page_images'], {2: 'B64PAGE2'})

    def test_no_questions_means_no_api_call(self):
        with patch('ai_import.verification.verify_answers') as verify:
            self.assertIsNone(_second_opinion({'questions': []}, _pages()))
        verify.assert_not_called()

    def test_a_verifier_failure_never_loses_the_extraction(self):
        # A quality aid, not a gate: an upload that classified successfully must
        # survive the second opinion being unavailable.
        result = {'questions': [{'question_text': 'q'}]}
        with patch('ai_import.verification.flag_visual_comparisons'), \
             patch('ai_import.verification.verify_answers',
                   side_effect=RuntimeError('OpenAI down')):
            self.assertIsNone(_second_opinion(result, _pages()))

    def test_flags_from_the_verifier_stay_on_the_questions(self):
        result = {'questions': [{'question_text': 'q'}]}

        def flag_it(questions, page_images=None):
            questions[0]['needs_review'] = True
            questions[0]['review_reason'] = 'Verifier answered 7, not 8.'
            return {'checked': 1, 'flagged': 1}

        with patch('ai_import.verification.flag_visual_comparisons'), \
             patch('ai_import.verification.verify_answers', side_effect=flag_it):
            _second_opinion(result, _pages())

        self.assertTrue(result['questions'][0]['needs_review'])
        self.assertIn('7', result['questions'][0]['review_reason'])


class PipelineWiringTests(TestCase):
    """Step 4 really is part of the shared pipeline, for BOTH callers."""

    def _run(self, verification):
        pdf = MagicMock()
        pdf.read.return_value = b'%PDF-1.4 fake'
        classified = {'questions': [{'question_text': 'q'}], 'usage': {}}

        with patch('fitz.open') as fitz_open, \
             patch('worksheets.services.extract_worksheet_pages',
                   return_value=_pages()), \
             patch('worksheets.services.classify_worksheet_questions',
                   return_value=classified), \
             patch('worksheets.services.render_question_images',
                   return_value=(classified, {})), \
             patch('worksheets.services._second_opinion',
                   return_value=verification) as second:
            fitz_open.return_value = MagicMock(__len__=lambda self: 2)
            output = extract_and_classify_worksheet(pdf, [], [])

        return output, second

    def test_extraction_records_the_verification_summary(self):
        output, second = self._run({'checked': 1, 'flagged': 1,
                                    'input_tokens': 900, 'output_tokens': 40})

        second.assert_called_once()
        self.assertEqual(output['result']['verification']['flagged'], 1)

    def test_a_disabled_verifier_is_recorded_as_none_not_omitted(self):
        # An absent key must look absent. Leaving the key out entirely would be
        # indistinguishable from "verified, nothing wrong".
        output, _ = self._run(None)
        self.assertIn('verification', output['result'])
        self.assertIsNone(output['result']['verification'])

    def test_the_pdf_is_closed_even_if_the_second_opinion_explodes(self):
        pdf = MagicMock()
        pdf.read.return_value = b'%PDF-1.4 fake'
        classified = {'questions': [], 'usage': {}}
        doc = MagicMock(__len__=lambda self: 1)

        with patch('fitz.open', return_value=doc), \
             patch('worksheets.services.extract_worksheet_pages',
                   return_value=_pages()), \
             patch('worksheets.services.classify_worksheet_questions',
                   return_value=classified), \
             patch('worksheets.services.render_question_images',
                   return_value=(classified, {})), \
             patch('worksheets.services._second_opinion',
                   side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                extract_and_classify_worksheet(pdf, [], [])

        doc.close.assert_called_once()


@override_settings(CLAUDE_INPUT_COST_PER_MTOK=5.0,
                   CLAUDE_OUTPUT_COST_PER_MTOK=25.0,
                   OPENAI_INPUT_COST_PER_MTOK=2.5,
                   OPENAI_OUTPUT_COST_PER_MTOK=10.0)
class WorksheetVerifierBillingTests(TestCase):
    """The verifier's tokens reach the ledger as the worksheet path's own cost."""

    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_verify_owner', 'ws_verify_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(role)
        cls.school = School.objects.create(
            name='WS Verify School', slug='ws-verify-school', admin=cls.owner)
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

    def _session(self):
        return WorksheetUploadSession.objects.create(
            user=self.owner, school=self.school, pdf_filename='ws.pdf',
            status=WorksheetUploadSession.STATUS_PROCESSING,
            pdf_file=SimpleUploadedFile('ws.pdf', b'%PDF-1.4 fake',
                                        content_type='application/pdf'))

    def _process(self, verification):
        session = self._session()
        with patch('worksheets.tasks.extract_and_classify_worksheet') as extract:
            extract.return_value = {
                'result': {'questions': [{'q': 1}],
                           'usage': {'input_tokens': 1_000_000,
                                     'output_tokens': 0, 'total_tokens': 1_000_000},
                           'verification': verification},
                'extracted_images': {},
                'page_count': 2,
            }
            process_worksheet_pdf(session.pk)
        return session

    def test_verifier_tokens_are_billed_to_openai_under_the_worksheet_source(self):
        # Both vendors bill this one upload. Merging them would price OpenAI's
        # tokens at Claude's rate; tagging them ai_import would make worksheets
        # look free.
        self._process({'input_tokens': 1_000_000, 'output_tokens': 0})

        row = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_OPENAI)
        self.assertEqual(row.source, AIUsageLog.SOURCE_WORKSHEET)
        self.assertEqual(row.est_cost_usd, Decimal('2.50000'))

        claude = AIUsageLog.objects.get(provider=AIUsageLog.PROVIDER_ANTHROPIC)
        self.assertEqual(claude.source, AIUsageLog.SOURCE_WORKSHEET)
        self.assertEqual(claude.est_cost_usd, Decimal('5.00000'))

    def test_no_openai_row_when_the_verifier_did_not_run(self):
        self._process(None)
        self.assertFalse(AIUsageLog.objects.filter(
            provider=AIUsageLog.PROVIDER_OPENAI).exists())

    def test_no_openai_row_for_a_zero_token_summary(self):
        # The verifier reports a summary even when it couldn't build a client;
        # a $0 row would be noise in the dashboard.
        self._process({'input_tokens': 0, 'output_tokens': 0, 'error': 'no key'})
        self.assertFalse(AIUsageLog.objects.filter(
            provider=AIUsageLog.PROVIDER_OPENAI).exists())
