"""
Unit tests for BrainBuzz coding exercise selection — _snapshot_coding_questions.

BrainBuzz coding sessions should only pull multiple_choice and true_false
exercises (both render via the same tile selector). write_code, short_answer,
and fill_blank exercises must be excluded.

Run with:
    pytest brainbuzz/tests/test_coding_question_types.py -v
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from brainbuzz.models import (
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
)
from brainbuzz.views import _snapshot_coding_questions
from classroom.models import Subject
from coding.models import (
    CodingAnswer,
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    TopicLevel,
)

User = get_user_model()


class SnapshotCodingQuestionTypesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.host = User.objects.create_user(
            username='bb_coding_host', password='pass', email='bb@test.com',
        )
        cls.subject = Subject.objects.get_or_create(
            slug='coding', defaults={'name': 'Coding'},
        )[0]

        lang = CodingLanguage.objects.create(slug='python', name='Python', order=1)
        topic = CodingTopic.objects.create(language=lang, slug='vars', name='Vars', order=1)
        cls.tl = TopicLevel.objects.create(topic=topic, level_choice='beginner')

        def _mcq(title, qtype):
            ex = CodingExercise.objects.create(
                topic_level=cls.tl, title=title, description=f'{title}?',
                question_type=qtype,
            )
            CodingAnswer.objects.create(exercise=ex, answer_text='Right', is_correct=True, order=0)
            CodingAnswer.objects.create(exercise=ex, answer_text='Wrong', is_correct=False, order=1)
            return ex

        cls.ex_mcq = _mcq('MCQ one', 'multiple_choice')
        cls.ex_tf = _mcq('TF one', 'true_false')
        # These three must never be pulled into a BrainBuzz coding session.
        cls.ex_write = CodingExercise.objects.create(
            topic_level=cls.tl, title='Write one', description='Write code',
            question_type='write_code',
        )
        cls.ex_short = _mcq('Short one', 'short_answer')
        cls.ex_fill = _mcq('Fill one', 'fill_blank')

    def _make_session(self):
        return BrainBuzzSession.objects.create(
            code='CODEQT', host=self.host, subject=self.subject,
            status=BrainBuzzSession.STATUS_LOBBY, time_per_question_sec=20,
        )

    def test_snapshot_includes_mcq_and_true_false(self):
        session = self._make_session()
        _snapshot_coding_questions(session, self.tl.id, count=10)

        rows = BrainBuzzSessionQuestion.objects.filter(session=session)
        source_ids = set(rows.values_list('source_id', flat=True))
        self.assertEqual(source_ids, {self.ex_mcq.id, self.ex_tf.id})

        bb_types = set(rows.values_list('question_type', flat=True))
        self.assertEqual(bb_types, {QUESTION_TYPE_MCQ, QUESTION_TYPE_TRUE_FALSE})

    def test_snapshot_excludes_write_short_and_fill(self):
        session = self._make_session()
        _snapshot_coding_questions(session, self.tl.id, count=10)

        snapped = set(
            BrainBuzzSessionQuestion.objects.filter(session=session)
            .values_list('source_id', flat=True)
        )
        for excluded in (self.ex_write.id, self.ex_short.id, self.ex_fill.id):
            self.assertNotIn(excluded, snapped)
