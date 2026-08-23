"""The shared saver must persist how a question is marked.

``save_questions_from_session`` backs BOTH the AI PDF import and the worksheet
confirm step, and it never wrote ``validation_type`` or ``grading_rubric`` — so
every question it saved fell to the model default, ``auto``. A drawing question
routed to the teacher in the preview was silently un-routed on the way into the
database, and the student got a text box for a Venn diagram after all.
"""
from django.test import TestCase

from accounts.models import CustomUser
from ai_import.models import AIImportSession
from ai_import.services import save_questions_from_session
from classroom.models import Level
from maths.models import Question
from worksheets.services import CONSTRUCTION_RUBRIC


def _payload(*questions):
    return {
        'year_level': 8, 'subject': 'Mathematics', 'strand': 'Statistics',
        'topic': 'Probability', 'questions': list(questions),
    }


class SaveDrawingQuestionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'dqi_super', 'dqi_super@test.internal', 'pw1!')
        Level.objects.get_or_create(
            level_number=8, defaults={'display_name': 'Year 8'})

    def _save(self, *questions):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='dq.pdf',
            extracted_data=_payload(*questions),
        )
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_a_drawing_question_lands_human_graded(self):
        # The reported shape: no stored answer, because there is nothing to
        # type. This is what the extractor actually produces for these.
        result = self._save({
            'question_text': 'Suppose we are rolling a die. Illustrate on a Venn '
                             'diagram the sets A = {1, 3, 5} and B = {2, 4, 6}.',
            'question_type': 'short_answer', 'difficulty': 2, 'points': 2,
            'answers': [],
        })
        self.assertEqual(result['failed'], 0, result.get('errors'))

        q = Question.objects.get(question_text__startswith='Suppose we are rolling')
        self.assertEqual(q.validation_type, Question.VALIDATION_HUMAN)
        self.assertEqual(q.grading_rubric, CONSTRUCTION_RUBRIC)

    def test_a_ticked_answer_keeps_the_question_gradable(self):
        """An accepted trade-off, not an oversight.

        If the extractor is confident enough to tick an answer, the app can mark
        what the student types and this leaves it alone — even though the
        wording mentions a diagram. A production dry run over 19,773 bank
        questions showed the opposite bias is far more expensive: keying on the
        wording alone hid ~40 questions that had graded correctly for years
        ("Complete the table for Output = 6x", "Write the coordinates of the
        ship shown on the grid"). A missed drawing stays AI-graded and a teacher
        can see it; a hidden question is invisible to everyone.
        """
        self._save({
            'question_text': 'Draw a tree diagram and give the probability of '
                             'two heads.',
            'question_type': 'short_answer', 'difficulty': 2, 'points': 2,
            'answers': [{'text': '0.25', 'is_correct': True}],
        })
        q = Question.objects.get(question_text__startswith='Draw a tree diagram and')
        self.assertEqual(q.validation_type, 'auto')

    def test_a_teacher_marked_question_keeps_its_rubric(self):
        self._save({
            'question_text': 'Draw a Venn diagram for these two sets.',
            'question_type': 'short_answer', 'difficulty': 2, 'points': 2,
            'validation_type': 'human_graded',
            'grading_rubric': 'Two overlapping circles; 8 in the intersection.',
            'answers': [],
        })
        q = Question.objects.get(question_text='Draw a Venn diagram for these two sets.')
        self.assertEqual(q.validation_type, Question.VALIDATION_HUMAN)
        self.assertEqual(q.grading_rubric, 'Two overlapping circles; 8 in the intersection.')

    def test_an_ordinary_question_is_still_auto(self):
        self._save({
            'question_text': 'What is 24 divided by 6?',
            'question_type': 'short_answer', 'difficulty': 1, 'points': 1,
            'answers': [{'text': '4', 'is_correct': True}],
        })
        q = Question.objects.get(question_text='What is 24 divided by 6?')
        self.assertEqual(q.validation_type, 'auto')

    def test_a_table_imports_as_an_answerable_question(self):
        # A table to fill in is convertible, so it must NOT go to the teacher.
        result = self._save({
            'question_text': 'Complete the table for y = x + 1.',
            'question_type': 'table_of_values', 'difficulty': 1, 'points': 1,
            'table_spec': {
                'headers': ['x', 'y'],
                'rows': [[{'given': '0'}, {'answer': '1'}],
                         [{'given': '3'}, {'answer': '4'}]],
            },
            'answers': [],
        })
        self.assertEqual(result['failed'], 0, result.get('errors'))

        q = Question.objects.get(question_text='Complete the table for y = x + 1.')
        self.assertEqual(q.question_type, Question.TABLE_OF_VALUES)
        self.assertEqual(q.validation_type, 'auto')
        # The spec has to survive the save or the table renders empty.
        self.assertEqual(q.table_spec['headers'], ['x', 'y'])
        self.assertEqual(len(q.table_spec['rows']), 2)

    def test_a_malformed_table_is_skipped_not_imported_broken(self):
        result = self._save({
            'question_text': 'Complete this table.',
            'question_type': 'table_of_values', 'difficulty': 1, 'points': 1,
            'table_spec': {'headers': ['x', 'y'], 'rows': []},   # no rows
            'answers': [],
        })
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Complete this table.').exists())
