"""Column-arithmetic end-to-end through the AI-import path.

Proves the importer turns a `column_operation` payload into a question with the
right operands/operator and a single computed correct Answer, that the quiz
endpoint grades a typed numeric answer against it, and that the preview edit step
round-trips operands/operator without clobbering the type.
"""
import json
import uuid

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level, Topic
from ai_import.models import AIImportSession
from ai_import.services import save_questions_from_session
from maths.models import Question


def _column_payload(operands, operator, **extra):
    q = {
        'question_text': 'Find the difference.',
        'question_type': 'column_operation',
        'operands': operands,
        'operator': operator,
        'difficulty': 1,
        'points': 1,
    }
    q.update(extra)
    return {
        'year_level': 3, 'subject': 'Mathematics', 'strand': 'Number',
        'topic': 'Subtraction', 'questions': [q],
    }


class SaveColumnOperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_super', 'col_super@test.internal', 'pw1!')
        Level.objects.get_or_create(
            level_number=3, defaults={'display_name': 'Year 3'})

    def test_creates_question_with_operands_and_computed_answer(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload([90, 82], '-'),
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)

        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)

        q = Question.objects.get(question_text='Find the difference.')
        self.assertEqual(q.question_type, 'column_operation')
        self.assertEqual(q.operands, [90, 82])
        self.assertEqual(q.operator, '-')
        self.assertIsNone(q.school_id)  # superuser → global

        # Exactly one correct Answer, equal to the computed result.
        answers = list(q.answers.all())
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0].is_correct)
        self.assertEqual(answers[0].answer_text, '8')

    def test_ai_supplied_answers_are_ignored_for_column(self):
        # Even if the model hallucinates answer rows, the result is computed.
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload(
                [90, 82], '-', answers=[{'text': '12', 'is_correct': True}]),
        )
        save_questions_from_session(session, self.user, session.extracted_data)
        q = Question.objects.get(question_text='Find the difference.')
        self.assertEqual([a.answer_text for a in q.answers.all()], ['8'])

    def test_invalid_column_payload_is_skipped(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload([90], '-'),  # only one operand
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Find the difference.').exists())

    def test_negative_subtraction_is_rejected(self):
        # Reversed operands (smaller on top) → negative result the widget can't
        # represent. Must be skipped, not imported as an unanswerable question.
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload([82, 90], '-'),
        )
        result = save_questions_from_session(session, self.user, session.extracted_data)
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Find the difference.').exists())

    def test_multiply_glyph_is_canonicalised(self):
        # The AI may emit '×' or 'x'; we store the canonical '*' so the preview
        # operator <select> (which only offers +,-,*) round-trips faithfully.
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload([12, 12], '×', question_text='Find the product.'),
        )
        save_questions_from_session(session, self.user, session.extracted_data)
        q = Question.objects.get(question_text='Find the product.')
        self.assertEqual(q.operator, '*')
        self.assertEqual([a.answer_text for a in q.answers.all()], ['144'])


class GradeColumnOperationTests(TestCase):
    """The typed column answer is graded by the standard numeric text-answer path."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_student', 'col_student@test.internal', 'pw1!')
        cls.level, _ = Level.objects.get_or_create(
            level_number=3, defaults={'display_name': 'Year 3'})
        from classroom.models import Subject
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None, defaults={'name': 'Mathematics'})
        cls.topic, _ = Topic.objects.get_or_create(
            subject=subject, slug='subtraction', defaults={'name': 'Subtraction'})

    def _make_question(self):
        from maths.models import Answer
        q = Question.objects.create(
            level=self.level, topic=self.topic,
            question_text='Find the difference.',
            question_type=Question.COLUMN_OPERATION,
            operands=[90, 82], operator='-', difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text='8', is_correct=True, order=1)
        return q

    def _seed_session_and_submit(self, q, text_answer):
        sid = str(uuid.uuid4())
        session = self.client.session
        # Two questions so the submitted one is not the last (skips final-result path).
        session[f'tq_{sid}'] = {
            'topic_id': self.topic.id, 'level_number': 3, 'subject': 'maths',
            'questions': [{'id': q.id, 'answer_ids': []}, {'id': q.id, 'answer_ids': []}],
            'current': 0, 'correct': 0, 'start_time': 0,
        }
        session.save()
        return self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({'session_id': sid, 'question_id': q.id, 'text_answer': text_answer}),
            content_type='application/json',
        )

    def test_correct_numeric_answer_is_marked_correct(self):
        self.client.force_login(self.user)
        q = self._make_question()
        resp = self._seed_session_and_submit(q, '8')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['is_correct'])

    def test_wrong_numeric_answer_is_marked_incorrect(self):
        self.client.force_login(self.user)
        q = self._make_question()
        resp = self._seed_session_and_submit(q, '12')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['is_correct'])


class PreviewRoundTripTests(TestCase):
    """The preview edit step must preserve operands/operator and not rewrite the type."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'col_prev', 'col_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=3, defaults={'display_name': 'Year 3'})

    def test_post_preserves_column_fields(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g3.pdf',
            extracted_data=_column_payload([90, 82], '-'),
        )
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '3', 'subject': 'Mathematics', 'strand': 'Number', 'topic': 'Subtraction',
                'q_0_include': 'on',
                'q_0_text': 'Find the difference.',
                'q_0_type': 'column_operation',
                'q_0_difficulty': '1', 'q_0_points': '1',
                'q_0_year_level': '3', 'q_0_subject': 'Mathematics',
                'q_0_strand': 'Number', 'q_0_topic': 'Subtraction',
                'q_0_operands': '90, 82',
                'q_0_operator': '-',
            },
        )
        self.assertEqual(resp.status_code, 302)  # → confirm
        session.refresh_from_db()
        q = session.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'column_operation')
        self.assertEqual(q['operands'], [90, 82])
        self.assertEqual(q['operator'], '-')
