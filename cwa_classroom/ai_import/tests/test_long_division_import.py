"""Long-division end-to-end through the AI-import path.

Proves the importer turns a `long_division` payload into a question with the
right dividend/divisor and a single computed correct Answer ("Q" or "Q r R"),
ignores AI-supplied answers, skips invalid payloads, and never attaches the
worksheet layout image (the app draws the bracket itself).
"""
import base64

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import save_questions_from_session, _compute_long_division_answer
from maths.models import Question


def _ld_payload(dividend, divisor, **extra):
    q = {
        'question_text': f'Solve using long division: {dividend} ÷ {divisor}',
        'question_type': 'long_division',
        'dividend': dividend,
        'divisor': divisor,
        'difficulty': 2,
        'points': 1,
    }
    q.update(extra)
    return {
        'year_level': 5, 'subject': 'Mathematics', 'strand': 'Number',
        'topic': 'Long Division', 'questions': [q],
    }


class ComputeLongDivisionAnswerTests(TestCase):
    def test_exact_division_has_no_remainder(self):
        self.assertEqual(_compute_long_division_answer(611, 47), '13')

    def test_remainder_uses_r_format(self):
        self.assertEqual(_compute_long_division_answer(508, 9), '56 r 4')

    def test_bad_input_returns_none(self):
        self.assertIsNone(_compute_long_division_answer(100, 0))
        self.assertIsNone(_compute_long_division_answer(None, 5))


class SaveLongDivisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'ld_super', 'ld_super@test.internal', 'pw1!')
        Level.objects.get_or_create(
            level_number=5, defaults={'display_name': 'Year 5'})

    def test_creates_question_with_dividend_divisor_and_computed_answer(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g5.pdf',
            extracted_data=_ld_payload(611, 47),
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)

        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)

        q = Question.objects.get(dividend=611)
        self.assertEqual(q.question_type, 'long_division')
        self.assertEqual(q.divisor, 47)
        self.assertEqual(q.question_text, 'Solve using long division: 611 ÷ 47')

        answers = list(q.answers.all())
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0].is_correct)
        self.assertEqual(answers[0].answer_text, '13')

    def test_ai_supplied_answers_are_ignored(self):
        # Even if the model hallucinates an answer, it is recomputed from dividend/divisor.
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g5.pdf',
            extracted_data=_ld_payload(
                508, 9, answers=[{'text': '999', 'is_correct': True}]),
        )
        save_questions_from_session(session, self.user, session.extracted_data)
        q = Question.objects.get(dividend=508)
        self.assertEqual([a.answer_text for a in q.answers.all()], ['56 r 4'])

    def test_invalid_payload_is_skipped(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g5.pdf',
            extracted_data=_ld_payload(100, 0),  # divide by zero
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(dividend=100).exists())

    def test_layout_image_is_never_attached(self):
        # A worksheet bracket graphic carries no information — the app renders it.
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g5.pdf',
            extracted_data=_ld_payload(520, 10, image_ref='page1_img1.png'),
            extracted_images={'page1_img1.png': png},
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['images_saved'], 0)
        q = Question.objects.get(dividend=520)
        self.assertFalse(q.image)


class PreviewRoundTripTests(TestCase):
    """The preview edit step must preserve dividend/divisor and not rewrite the type."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'ld_prev', 'ld_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=5, defaults={'display_name': 'Year 5'})

    def test_post_preserves_long_division_fields(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g5.pdf',
            extracted_data=_ld_payload(611, 47),
        )
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '5', 'subject': 'Mathematics', 'strand': 'Number',
                'topic': 'Long Division',
                'q_0_include': 'on',
                'q_0_text': 'Solve using long division: 611 ÷ 47',
                'q_0_type': 'long_division',
                'q_0_difficulty': '2', 'q_0_points': '1',
                'q_0_year_level': '5', 'q_0_subject': 'Mathematics',
                'q_0_strand': 'Number', 'q_0_topic': 'Long Division',
                'q_0_dividend': '611', 'q_0_divisor': '47',
            },
        )
        self.assertEqual(resp.status_code, 302)  # → confirm
        session.refresh_from_db()
        q = session.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'long_division')
        self.assertEqual(q['dividend'], 611)
        self.assertEqual(q['divisor'], 47)
