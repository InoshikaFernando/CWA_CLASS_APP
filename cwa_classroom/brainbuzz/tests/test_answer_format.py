"""
Tests for algebra answer_format support in BrainBuzz.

Covers the two ways a typed short-answer reaches a live session:
  1. Quiz Builder  → BrainBuzzQuizQuestion  → _snapshot_quiz_questions
  2. Maths bank    → maths.Question          → _snapshot_maths_questions

Both must carry answer_format onto the runtime BrainBuzzSessionQuestion, and the
maths path must now populate correct_short_answer (previously hard-coded None,
which left maths short-answers ungradeable). Grading itself delegates to
is_short_answer_correct(answer_format=...), exercised here end-to-end on the
snapshotted data.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzQuiz,
    BrainBuzzQuizQuestion,
    QUESTION_TYPE_SHORT_ANSWER,
)
from brainbuzz.views import (
    _snapshot_quiz_questions,
    _snapshot_maths_questions,
    _session_state_payload,
)
from brainbuzz.scoring import is_short_answer_correct

User = get_user_model()


def _make_session(host, code='ALG001'):
    from classroom.models import Subject
    subject, _ = Subject.objects.get_or_create(name='Mathematics', defaults={'slug': 'mathematics'})
    return BrainBuzzSession.objects.create(
        code=code, host=host, subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY, time_per_question_sec=20,
    )


class QuizBuilderSnapshotTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username='alg_host', password='pass')
        self.session = _make_session(self.host)

    def test_algebra_quiz_question_carries_format_and_answer(self):
        quiz = BrainBuzzQuiz.objects.create(title='Algebra', created_by=self.host)
        BrainBuzzQuizQuestion.objects.create(
            quiz=quiz, order=0,
            question_text='Expand and simplify (2x + 3)(x - 5)',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            correct_short_answer='2x^2 - 7x - 15',
            answer_format='algebra',
        )
        _snapshot_quiz_questions(self.session, quiz)

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.answer_format, 'algebra')
        self.assertEqual(sq.correct_short_answer, '2x^2 - 7x - 15')

    def test_default_text_format_preserved(self):
        quiz = BrainBuzzQuiz.objects.create(title='Capitals', created_by=self.host)
        BrainBuzzQuizQuestion.objects.create(
            quiz=quiz, order=0, question_text='Capital of France?',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            correct_short_answer='Paris',
        )
        _snapshot_quiz_questions(self.session, quiz)
        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.answer_format, 'text')


class MathsSnapshotTests(TestCase):
    def setUp(self):
        from classroom.models import Subject, Topic, Level
        from maths.models import Question, Answer
        self.host = User.objects.create_user(username='alg_mhost', password='pass')
        self.session = _make_session(self.host, code='ALGM01')
        subject, _ = Subject.objects.get_or_create(name='Mathematics', defaults={'slug': 'mathematics'})
        self.topic = Topic.objects.create(name='Algebra', slug='algebra', subject=subject)
        self.level = Level.objects.create(level_number=9, display_name='Year 9')
        self.q = Question.objects.create(
            topic=self.topic, level=self.level,
            question_text='Expand and simplify (2x + 3)(x - 5)',
            question_type='short_answer', answer_format='algebra',
        )
        Answer.objects.create(question=self.q, answer_text='2x^2 - 7x - 15', is_correct=True, order=0)
        Answer.objects.create(question=self.q, answer_text='wrong', is_correct=False, order=1)

    def test_maths_short_answer_now_gradeable(self):
        # Previously correct_short_answer was hard-coded None -> ungradeable.
        _snapshot_maths_questions(self.session, self.topic.id, self.level.id, count=10)
        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, source_model='MathsQuestion')
        self.assertEqual(sq.answer_format, 'algebra')
        self.assertEqual(sq.correct_short_answer, '2x^2 - 7x - 15')

    def test_multiple_correct_rows_become_pipe_alternatives(self):
        from maths.models import Answer
        Answer.objects.create(question=self.q, answer_text='-7x + 2x^2 - 15', is_correct=True, order=2)
        _snapshot_maths_questions(self.session, self.topic.id, self.level.id, count=10)
        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, source_model='MathsQuestion')
        self.assertIn('2x^2 - 7x - 15', sq.correct_short_answer)
        self.assertIn('|', sq.correct_short_answer)

    def test_end_to_end_grading_on_snapshot(self):
        # Prove the snapshotted row grades algebraically the way the submit path will.
        _snapshot_maths_questions(self.session, self.topic.id, self.level.id, count=10)
        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, source_model='MathsQuestion')

        def grade(ans):
            return is_short_answer_correct(ans, sq.correct_short_answer, answer_format=sq.answer_format)

        self.assertTrue(grade('-7x + 2x^2 - 15'))    # reordered -> correct
        self.assertTrue(grade('2x²-7x-15'))          # unicode/no-space -> correct
        self.assertFalse(grade('2x^2 - 3x - 4x - 15'))  # not simplified -> wrong
        self.assertFalse(grade('(2x + 3)(x - 5)'))      # not expanded -> wrong


class PayloadTests(TestCase):
    def test_answer_format_in_session_payload(self):
        host = User.objects.create_user(username='alg_phost', password='pass')
        session = _make_session(host, code='ALGP01')
        session.status = BrainBuzzSession.STATUS_ACTIVE
        session.current_index = 0
        session.save()
        BrainBuzzSessionQuestion.objects.create(
            session=session, order=0,
            question_text='Expand (2x + 3)(x - 5)',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            correct_short_answer='2x^2 - 7x - 15',
            answer_format='algebra',
            time_limit_sec=20, points_base=1000,
            source_model='MathsQuestion', source_id=1,
        )
        payload = _session_state_payload(session)
        self.assertEqual(payload['question']['answer_format'], 'algebra')
