"""Fill-in-the-blank end-to-end through the AI-import path.

Proves the importer builds a ``blank_spec`` from the answers it was given
whenever the extracted text carries "___" gaps — including when the extractor
typed the sentence ``short_answer``, which is how a multi-gap question routinely
comes back — and that a question it cannot map is imported anyway, as a working
single box, and *said out loud* rather than silently left half-converted.
"""
import json

from django.test import TestCase

from accounts.models import CustomUser
from ai_import.models import AIImportSession
from ai_import.services import save_questions_from_session
from classroom.models import Level
from maths.models import Question

SENTENCE = (
    'Out of 100 000 births, 99 231 females are expected to survive to the age '
    'of ___. From that age, the survivors are expected to ___ for another '
    '67.0 years.'
)


def _payload(question_type='fill_blank', text=SENTENCE, answers=('15; live',)):
    return {
        'year_level': 10, 'subject': 'Mathematics', 'strand': 'Statistics',
        'topic': 'Life Tables',
        'questions': [{
            'question_text': text,
            'question_type': question_type,
            'difficulty': 2,
            'points': 1,
            'answers': [{'text': a, 'is_correct': True} for a in answers],
        }],
    }


class SaveFillBlankTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'fb_super', 'fb_super@test.internal', 'pw1!')
        Level.objects.get_or_create(
            level_number=10, defaults={'display_name': 'Year 10'})

    def _save(self, data):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='life-tables.pdf', extracted_data=data)
        return save_questions_from_session(session, self.user, data)

    def test_builds_the_spec_from_one_semicolon_separated_answer(self):
        result = self._save(_payload())
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['blanks_built'], 1)

        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertEqual(
            q.blank_spec,
            {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_the_imported_question_grades(self):
        self._save(_payload())
        q = Question.objects.get(question_text=SENTENCE)
        self.assertTrue(q.grade_text_answer(json.dumps({'blanks': ['15', 'live']})))
        self.assertFalse(q.grade_text_answer(json.dumps({'blanks': ['15', 'die']})))

    def test_promotes_a_sentence_the_extractor_typed_short_answer(self):
        # The case from the worksheet this was built for: a two-gap sentence
        # comes back as short_answer, which one box cannot ask.
        self._save(_payload(question_type='short_answer'))
        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertIsNotNone(q.blank_spec)

    def test_pipe_lists_alternatives_for_one_gap(self):
        self._save(_payload(answers=('15; live|survive',)))
        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(q.blank_spec['blanks'][1]['answers'], ['live', 'survive'])

    def test_one_answer_per_gap_also_works(self):
        self._save(_payload(answers=('15', 'live')))
        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(
            q.blank_spec,
            {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_the_answer_rows_are_kept(self):
        self._save(_payload())
        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual([a.answer_text for a in q.answers.all()], ['15; live'])

    def test_a_question_without_gaps_is_untouched(self):
        self._save(_payload(text='What is 2 + 2?', answers=('4',)))
        q = Question.objects.get(question_text='What is 2 + 2?')
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, Question.FILL_BLANK)

    def test_an_unmappable_sentence_imports_as_a_single_box_and_is_reported(self):
        result = self._save(_payload(answers=('fifteen and living',)))
        self.assertEqual(result['failed'], 0)      # it imported fine
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['blanks_built'], 0)
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('does not split', result['warnings'][0])

        q = Question.objects.get(question_text=SENTENCE)
        self.assertIsNone(q.blank_spec)
        # Still a working question — it grades the way it always did.
        self.assertTrue(q.grade_text_answer('fifteen and living'))

    def test_choice_questions_are_never_promoted(self):
        self._save(_payload(question_type='multiple_choice',
                            text='Which age? ___', answers=('15',)))
        q = Question.objects.get(question_text='Which age? ___')
        self.assertEqual(q.question_type, 'multiple_choice')
        self.assertIsNone(q.blank_spec)
