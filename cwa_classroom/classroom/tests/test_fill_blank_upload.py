"""Bulk question upload builds fill-in-the-blank questions from "___" gaps.

``MathsQuestionParser`` is the spreadsheet/JSON/ZIP import path. Like the AI
importer and the teacher form, it routes every saved question through
``Question.apply_blank_format``, so a sentence with gaps in it arrives as a
fill-in-the-blank question no matter which of the three doors it came through —
and one whose answers cannot be mapped onto its gaps arrives as a working single
box with the reason reported, never guessed at.
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import CustomUser
from classroom.models import Level, Subject, Topic
from classroom.upload_services import MathsQuestionParser
from maths.models import Question

SENTENCE = 'A triangle has ___ sides and ___ angles.'


def _upload(questions):
    payload = {
        'strand': 'Number', 'topic': 'Fill Blank Upload', 'year_level': 7,
        'questions': questions,
    }
    return SimpleUploadedFile(
        'questions.json', json.dumps(payload).encode(), content_type='application/json')


def _question(text=SENTENCE, question_type='short_answer', answers=('3; 3',)):
    return {
        'question_text': text, 'question_type': question_type,
        'difficulty': 1, 'points': 1,
        'answers': [{'text': a, 'is_correct': True} for a in answers],
    }


class FillBlankUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'fb_upload_super', 'fb_upload@test.internal', 'pw1!')
        Level.objects.get_or_create(
            level_number=7, defaults={'display_name': 'Year 7'})
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})

    def _run(self, questions):
        return MathsQuestionParser().process(
            _upload(questions), self.user, {},
            school_id=None, dept_id=None, selected_classroom_id=None,
        )

    def test_a_sentence_with_gaps_uploads_as_fill_blank(self):
        result = self._run([_question()])
        self.assertEqual(result['failed'], 0, result['errors'])

        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertEqual(
            q.blank_spec, {'blanks': [{'answers': ['3']}, {'answers': ['3']}]})

    def test_the_uploaded_question_grades(self):
        self._run([_question()])
        q = Question.objects.get(question_text=SENTENCE)
        self.assertTrue(q.grade_text_answer('{"blanks": ["3", "3"]}'))
        self.assertFalse(q.grade_text_answer('{"blanks": ["3", "4"]}'))

    def test_a_question_without_gaps_is_untouched(self):
        self._run([_question(text='What is 2 + 2?', answers=('4',))])
        q = Question.objects.get(question_text='What is 2 + 2?')
        self.assertEqual(q.question_type, 'short_answer')
        self.assertIsNone(q.blank_spec)

    def test_a_choice_question_with_a_gap_in_its_stem_is_untouched(self):
        self._run([_question(text='A triangle has ___ sides.',
                             question_type='multiple_choice', answers=('3',))])
        q = Question.objects.get(question_text='A triangle has ___ sides.')
        self.assertEqual(q.question_type, 'multiple_choice')
        self.assertIsNone(q.blank_spec)

    def test_unmappable_answers_upload_as_a_single_box_and_are_reported(self):
        result = self._run([_question(answers=('three sides and three angles',))])
        self.assertEqual(result['inserted'], 1)   # it uploaded fine

        q = Question.objects.get(question_text=SENTENCE)
        self.assertIsNone(q.blank_spec)
        self.assertEqual(q.question_type, 'short_answer')
        self.assertTrue(any('stayed a single box' in e for e in result['errors']),
                        result['errors'])
        # Still a working question — it grades the way it always did.
        self.assertTrue(q.grade_text_answer('three sides and three angles'))

    def test_reupload_keeps_the_question_converted(self):
        self._run([_question()])
        self._run([_question()])
        q = Question.objects.get(question_text=SENTENCE)
        self.assertEqual(q.question_type, Question.FILL_BLANK)
        self.assertIsNotNone(q.blank_spec)
