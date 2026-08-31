"""``prime_factorization`` through the AI-import path.

Proves the enum offers the type, the importer stores ``target_number`` and the
computed answer row, a question with no usable number is reported and skipped
rather than imported to mark everyone wrong, and the preview edit step
round-trips the number. Mirrors test_number_line_import.py.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import CLASSIFICATION_TOOL, save_questions_from_session
from maths.models import Question

TEXT = 'Write 60 as a product of its prime factors.'


def _payload(q):
    return {
        'year_level': 7, 'subject': 'Mathematics', 'strand': 'Number',
        'topic': 'Factors', 'questions': [q],
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_prime_factorization(self):
        enum = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                ["items"]["properties"]["question_type"]["enum"])
        self.assertIn('prime_factorization', enum)

    def test_target_number_field_present(self):
        props = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                 ["items"]["properties"])
        self.assertIn('target_number', props)

    def test_the_prompt_tells_the_model_when_to_use_it(self):
        from ai_import.services import _build_classification_prompt
        prompt = _build_classification_prompt([], [])
        self.assertIn('prime_factorization', prompt)
        self.assertIn('target_number', prompt)


class SavePrimeFactorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'pf_super', 'pf_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=7, defaults={'display_name': 'Year 7'})

    def _save(self, q):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='pf.pdf', extracted_data=_payload(q))
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_it_imports_with_its_number_and_a_computed_answer(self):
        result = self._save({
            'question_text': TEXT, 'question_type': 'prime_factorization',
            'target_number': 60, 'difficulty': 2, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        q = Question.objects.get(question_type='prime_factorization')
        self.assertEqual(q.target_number, 60)
        # One row, computed from the number — never the model's own arithmetic.
        self.assertEqual(
            [a.answer_text for a in q.answers.all()], ['2 x 2 x 3 x 5'])

    def test_the_ai_s_own_answers_are_ignored(self):
        self._save({
            'question_text': TEXT, 'question_type': 'prime_factorization',
            'target_number': 60, 'difficulty': 2, 'points': 1,
            'answers': [{'text': '4 x 15', 'is_correct': True}],
        })
        q = Question.objects.get(question_type='prime_factorization')
        self.assertEqual([a.answer_text for a in q.answers.all()], ['2 x 2 x 3 x 5'])

    def test_a_missing_number_is_reported_and_skipped(self):
        result = self._save({
            'question_text': 'Broken factorisation.',
            'question_type': 'prime_factorization',
            'difficulty': 2, 'points': 1,
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('target_number' in e for e in result['errors']))
        self.assertFalse(
            Question.objects.filter(question_text='Broken factorisation.').exists())


class PreviewRoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'pf_prev', 'pf_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=7, defaults={'display_name': 'Year 7'})

    def _session(self):
        return AIImportSession.objects.create(
            user=self.user, pdf_filename='pf.pdf',
            extracted_data=_payload({
                'question_text': TEXT, 'question_type': 'prime_factorization',
                'target_number': 60, 'difficulty': 2, 'points': 1,
            }),
        )

    def test_post_preserves_an_edited_number(self):
        session = self._session()
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '7', 'subject': 'Mathematics', 'strand': 'Number',
                'topic': 'Factors',
                'q_0_include': 'on', 'q_0_text': TEXT,
                'q_0_type': 'prime_factorization', 'q_0_difficulty': '2',
                'q_0_points': '1', 'q_0_year_level': '7',
                'q_0_subject': 'Mathematics', 'q_0_strand': 'Number',
                'q_0_topic': 'Factors',
                'q_0_target_number': '84',
            },
        )
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.extracted_data['questions'][0]['target_number'], 84)

    def test_the_preview_page_offers_the_number_editor(self):
        session = self._session()
        self.client.force_login(self.user)
        html = self.client.get(
            reverse('ai_import:preview', args=[session.pk])).content.decode()
        self.assertIn('q_0_target_number', html)
