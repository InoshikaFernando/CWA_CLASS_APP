"""
Unit tests for CPP-250: BrainBuzz question + answer image rendering.

Covers:
  - _snapshot_maths_questions copies question image_url
  - _snapshot_maths_questions copies per-option image_url from answer_image
  - Empty image_url when source question/answer has no image
  - _session_state_payload exposes image_url in question dict
  - _session_state_payload exposes image_url in options
  - Sessions over imageless questions produce no image_url noise
"""
from unittest.mock import MagicMock, patch, PropertyMock

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Role
from classroom.models import Subject, Level, Topic
from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    QUESTION_TYPE_MCQ,
)
from brainbuzz.views import _snapshot_maths_questions, _session_state_payload

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username='img_teacher'):
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@test.com')
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject():
    return Subject.objects.get_or_create(slug='img-maths', defaults={'name': 'Image Maths'})[0]


def _make_level():
    return Level.objects.get_or_create(level_number=901, defaults={'display_name': 'Image Test Level'})[0]


def _make_topic(subject, level):
    topic, _ = Topic.objects.get_or_create(
        slug='img-topic',
        defaults={'name': 'Image Topic', 'subject': subject},
    )
    topic.levels.add(level)
    return topic


def _make_session(teacher, subject):
    return BrainBuzzSession.objects.create(
        code='IMGT01',
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=20,
    )


def _make_maths_question(topic, level, question_type='multiple_choice', image_name=None):
    """Return a mock maths Question with controllable image field."""
    from maths.models import Question
    q = MagicMock(spec=Question)
    q.id = 1
    q.question_text = 'What is 2 + 2?'
    q.question_type = question_type
    q.image = MagicMock()
    if image_name:
        q.image.name = image_name
        q.image.url = f'/media/questions/{image_name}'
    else:
        q.image.name = ''
    q.topic_id = topic.id
    q.level_id = level.id
    return q


def _make_maths_answer(answer_text, is_correct, image_name=None):
    """Return a mock maths Answer with controllable answer_image field."""
    from maths.models import Answer
    a = MagicMock(spec=Answer)
    a.answer_text = answer_text
    a.is_correct = is_correct
    a.answer_image = MagicMock()
    if image_name:
        a.answer_image.name = image_name
        a.answer_image.url = f'/media/answers/{image_name}'
    else:
        a.answer_image.name = ''
    return a


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

class SnapshotImageUrlTests(TestCase):

    def setUp(self):
        self.teacher = _make_teacher()
        self.subject = _make_subject()
        self.level = _make_level()
        self.topic = _make_topic(self.subject, self.level)
        self.session = _make_session(self.teacher, self.subject)

    def _run_snapshot(self, questions, answers_by_q):
        """Patch DB queries and run _snapshot_maths_questions."""
        from maths.models import Question, Answer

        with patch.object(Question.objects, 'filter') as mock_q_filter, \
             patch.object(Answer.objects, 'filter') as mock_a_filter:

            mock_q_qs = MagicMock()
            mock_q_qs.exclude.return_value = mock_q_qs
            mock_q_qs.order_by.return_value = mock_q_qs
            mock_q_qs.__getitem__ = lambda self, _: questions
            mock_q_qs.__iter__ = lambda self: iter(questions)
            mock_q_filter.return_value = mock_q_qs

            def answer_filter_side_effect(**kwargs):
                q = kwargs.get('question')
                mock_a_qs = MagicMock()
                mock_a_qs.order_by.return_value = answers_by_q.get(id(q), [])
                return mock_a_qs

            mock_a_filter.side_effect = answer_filter_side_effect

            _snapshot_maths_questions(self.session, self.topic.id, self.level.id, len(questions))

    def test_snapshot_copies_question_image_url(self):
        q = _make_maths_question(self.topic, self.level, image_name='test.png')
        a = _make_maths_answer('Answer A', True)
        self._run_snapshot([q], {id(q): [a]})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.image_url, '/media/questions/test.png')

    def test_snapshot_empty_image_url_when_no_image(self):
        q = _make_maths_question(self.topic, self.level, image_name=None)
        a = _make_maths_answer('Answer A', True)
        self._run_snapshot([q], {id(q): [a]})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.image_url, '')

    def test_snapshot_option_image_url_populated(self):
        q = _make_maths_question(self.topic, self.level)
        answers = [
            _make_maths_answer('Correct', True, image_name='ans_correct.png'),
            _make_maths_answer('Wrong', False, image_name=None),
        ]
        self._run_snapshot([q], {id(q): answers})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.options_json[0]['image_url'], '/media/answers/ans_correct.png')
        self.assertEqual(sq.options_json[1]['image_url'], '')

    def test_snapshot_option_image_url_empty_when_no_answer_image(self):
        q = _make_maths_question(self.topic, self.level)
        answers = [
            _make_maths_answer('A', True, image_name=None),
            _make_maths_answer('B', False, image_name=None),
        ]
        self._run_snapshot([q], {id(q): answers})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        for opt in sq.options_json:
            self.assertEqual(opt['image_url'], '')

    def test_snapshot_options_include_image_url_key_always(self):
        """image_url key must be present on every option, even when empty."""
        q = _make_maths_question(self.topic, self.level)
        a = _make_maths_answer('Only option', True)
        self._run_snapshot([q], {id(q): [a]})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        for opt in sq.options_json:
            self.assertIn('image_url', opt)

    def test_snapshot_image_url_exception_falls_back_to_empty(self):
        """If .url raises (e.g. missing file), image_url should be '' not an error."""
        q = _make_maths_question(self.topic, self.level)
        q.image.name = 'broken.png'
        q.image.url = PropertyMock(side_effect=Exception('storage error'))

        # Trigger the exception path by making .url raise
        bad_image = MagicMock()
        bad_image.name = 'broken.png'
        type(bad_image).url = PropertyMock(side_effect=Exception('storage error'))
        q.image = bad_image

        a = _make_maths_answer('A', True)
        self._run_snapshot([q], {id(q): [a]})

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.image_url, '')

    def test_quiz_snapshot_unaffected(self):
        """BrainBuzzQuizQuestion snapshot still works — no image fields exist there."""
        from brainbuzz.models import BrainBuzzQuiz, BrainBuzzQuizQuestion
        quiz = BrainBuzzQuiz.objects.create(
            title='Image Test Quiz',
            created_by=self.teacher,
            subject=self.subject,
        )
        BrainBuzzQuizQuestion.objects.create(
            quiz=quiz,
            order=0,
            question_text='Quiz Q1',
            question_type=QUESTION_TYPE_MCQ,
        )
        from brainbuzz.views import _snapshot_quiz_questions
        _snapshot_quiz_questions(self.session, quiz)

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        # Quiz questions don't have image_url set (defaults to '')
        self.assertEqual(sq.image_url, '')


# ---------------------------------------------------------------------------
# Payload tests
# ---------------------------------------------------------------------------

class PayloadImageUrlTests(TestCase):

    def setUp(self):
        self.teacher = _make_teacher('payload_teacher')
        self.subject = _make_subject()
        self.session = BrainBuzzSession.objects.create(
            code='PAYIMG',
            host=self.teacher,
            subject=self.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            current_index=0,
            time_per_question_sec=20,
        )

    def _make_sq(self, image_url='', options=None):
        return BrainBuzzSessionQuestion.objects.create(
            session=self.session,
            order=0,
            question_text='Test question?',
            question_type=QUESTION_TYPE_MCQ,
            image_url=image_url,
            options_json=options or [
                {'label': 'A', 'text': 'Alpha', 'is_correct': True, 'image_url': ''},
                {'label': 'B', 'text': 'Beta', 'is_correct': False, 'image_url': ''},
            ],
            source_model='Test',
            source_id=1,
        )

    def test_payload_exposes_question_image_url(self):
        self._make_sq(image_url='/media/questions/q.png')
        payload = _session_state_payload(self.session)
        self.assertEqual(payload['question']['image_url'], '/media/questions/q.png')

    def test_payload_question_image_url_empty_when_not_set(self):
        self._make_sq(image_url='')
        payload = _session_state_payload(self.session)
        self.assertEqual(payload['question']['image_url'], '')

    def test_payload_exposes_option_image_url(self):
        opts = [
            {'label': 'A', 'text': 'With image', 'is_correct': True, 'image_url': '/media/answers/a.png'},
            {'label': 'B', 'text': 'No image',  'is_correct': False, 'image_url': ''},
        ]
        self._make_sq(options=opts)
        payload = _session_state_payload(self.session)
        self.assertEqual(payload['question']['options'][0]['image_url'], '/media/answers/a.png')
        self.assertEqual(payload['question']['options'][1]['image_url'], '')

    def test_payload_question_image_url_key_always_present(self):
        self._make_sq(image_url='')
        payload = _session_state_payload(self.session)
        self.assertIn('image_url', payload['question'])

    def test_payload_no_question_returns_none(self):
        """Session with no questions at current_index returns question=None safely."""
        payload = _session_state_payload(self.session)
        self.assertIsNone(payload['question'])
