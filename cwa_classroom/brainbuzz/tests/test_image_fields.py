"""
test_image_fields.py
~~~~~~~~~~~~~~~~~~~~
Tests for image propagation through the BrainBuzz snapshot pipeline.

Coverage:
  - Snapshot copies question image_url from maths.Question.image
  - Snapshot copies per-option image_url from maths.Answer.answer_image
  - Questions without images produce empty image_url (no broken-image markup)
  - image_url key always present on every option even when empty
  - Quiz questions snapshot unaffected by image fields
  - _session_state_payload exposes image_url in the question dict
  - Per-option image_url is present in the payload options array
  - image_url NOT stripped by is_correct filter for students
  - api_session_state endpoint returns image_url in JSON body
"""
import json
from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from brainbuzz.models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    QUESTION_TYPE_MCQ,
)
from brainbuzz.views import _session_state_payload

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(host, code='IMG001'):
    from classroom.models import Subject
    subject, _ = Subject.objects.get_or_create(name='Mathematics', defaults={'slug': 'mathematics'})
    return BrainBuzzSession.objects.create(
        code=code,
        host=host,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=20,
    )


def _make_session_question(session, image_url='', options=None):
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=0,
        question_text='Which diagram shows a right angle?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=options or [
            {'label': 'A', 'text': 'Option A', 'is_correct': True,  'image_url': ''},
            {'label': 'B', 'text': 'Option B', 'is_correct': False, 'image_url': ''},
        ],
        image_url=image_url,
        time_limit_sec=20,
        points_base=1000,
        source_model='MathsQuestion',
        source_id=1,
    )


# ---------------------------------------------------------------------------
# Snapshot: question image_url
# ---------------------------------------------------------------------------

class TestSnapshotMathsImageUrl(TestCase):
    """_snapshot_maths_questions copies image URLs from source models."""

    def setUp(self):
        self.host = User.objects.create_user(username='snaphost', password='pass')
        self.session = _make_session(self.host)

    def _run_snapshot(self, q_mock, answer_mocks):
        from brainbuzz.views import _snapshot_maths_questions

        # The snapshot now reads answer_format off the source question; give the
        # mock a realistic string so it isn't a MagicMock at insert time.
        if not isinstance(getattr(q_mock, 'answer_format', None), str):
            q_mock.answer_format = 'text'

        with patch('maths.models.Question') as MockQ, \
             patch('maths.models.Answer') as MockA:
            MockQ.objects.filter.return_value \
                .exclude.return_value \
                .order_by.return_value.__getitem__ = lambda self_, s: [q_mock]
            MockA.objects.filter.return_value \
                .order_by.return_value = answer_mocks
            _snapshot_maths_questions(self.session, topic_id=1, level_id=1, count=1)

    def test_image_url_copied_when_question_has_image(self):
        q = MagicMock()
        q.question_text = 'Diagram Q'
        q.question_type = 'multiple_choice'
        q.image = MagicMock()
        q.image.name = 'questions/diagram.png'
        q.image.url = '/media/questions/diagram.png'
        q.id = 1

        a = MagicMock()
        a.answer_text = 'Option A'
        a.is_correct = True
        a.answer_image = None

        self._run_snapshot(q, [a])

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        self.assertEqual(sq.image_url, '/media/questions/diagram.png')

    def test_image_url_empty_when_question_has_no_image(self):
        q = MagicMock()
        q.question_text = 'No image Q'
        q.question_type = 'multiple_choice'
        q.image = None
        q.id = 2

        a = MagicMock()
        a.answer_text = 'Option A'
        a.is_correct = True
        a.answer_image = None

        self._run_snapshot(q, [a])

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        self.assertEqual(sq.image_url, '')

    def test_option_image_url_copied_when_answer_has_image(self):
        q = MagicMock()
        q.question_text = 'Image option Q'
        q.question_type = 'multiple_choice'
        q.image = None
        q.id = 3

        a = MagicMock()
        a.answer_text = 'Option A'
        a.is_correct = True
        a.answer_image = MagicMock()
        a.answer_image.name = 'answers/opt_a.png'
        a.answer_image.url = '/media/answers/opt_a.png'

        self._run_snapshot(q, [a])

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        self.assertEqual(sq.options_json[0]['image_url'], '/media/answers/opt_a.png')

    def test_option_image_url_empty_when_answer_has_no_image(self):
        q = MagicMock()
        q.question_text = 'No opt image Q'
        q.question_type = 'multiple_choice'
        q.image = None
        q.id = 4

        a = MagicMock()
        a.answer_text = 'Option A'
        a.is_correct = True
        a.answer_image = None

        self._run_snapshot(q, [a])

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        self.assertEqual(sq.options_json[0]['image_url'], '')

    def test_options_always_include_image_url_key(self):
        """image_url key must be present on every option, even when empty."""
        q = MagicMock()
        q.question_text = 'Key always present Q'
        q.question_type = 'multiple_choice'
        q.image = None
        q.id = 5

        answers = [
            MagicMock(answer_text='A', is_correct=True, answer_image=None),
            MagicMock(answer_text='B', is_correct=False, answer_image=None),
        ]
        self._run_snapshot(q, answers)

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        for opt in sq.options_json:
            self.assertIn('image_url', opt)

    def test_image_url_exception_handled_gracefully(self):
        """If .url raises (e.g. missing file in storage), falls back to ''."""
        q = MagicMock()
        q.question_text = 'Bad image Q'
        q.question_type = 'multiple_choice'
        bad_image = MagicMock()
        bad_image.name = 'questions/bad.png'
        type(bad_image).url = PropertyMock(side_effect=Exception('storage error'))
        q.image = bad_image
        q.id = 6

        a = MagicMock()
        a.answer_text = 'Option A'
        a.is_correct = True
        a.answer_image = None

        self._run_snapshot(q, [a])

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session)
        self.assertEqual(sq.image_url, '')

    def test_quiz_snapshot_unaffected(self):
        """BrainBuzzQuizQuestion snapshot works -- quiz questions have no image fields."""
        from brainbuzz.models import BrainBuzzQuiz, BrainBuzzQuizQuestion
        from brainbuzz.views import _snapshot_quiz_questions
        from classroom.models import Subject

        subject, _ = Subject.objects.get_or_create(
            name='Mathematics', defaults={'slug': 'mathematics'}
        )
        quiz = BrainBuzzQuiz.objects.create(
            title='Image Test Quiz',
            created_by=self.host,
            subject=subject,
        )
        BrainBuzzQuizQuestion.objects.create(
            quiz=quiz,
            order=0,
            question_text='Quiz Q1',
            question_type=QUESTION_TYPE_MCQ,
        )
        _snapshot_quiz_questions(self.session, quiz)

        sq = BrainBuzzSessionQuestion.objects.get(session=self.session, order=0)
        self.assertEqual(sq.image_url, '')


# ---------------------------------------------------------------------------
# Payload: image_url in API response
# ---------------------------------------------------------------------------

class TestPayloadImageUrl(TestCase):
    """_session_state_payload includes image_url in the question dict."""

    def setUp(self):
        self.host = User.objects.create_user(username='payhost', password='pass')
        self.session = _make_session(self.host, code='PAYIMG')
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.save()

    def test_image_url_in_payload_when_set(self):
        _make_session_question(self.session, image_url='/media/questions/triangle.png')
        payload = _session_state_payload(self.session)
        self.assertEqual(payload['question']['image_url'], '/media/questions/triangle.png')

    def test_image_url_empty_string_in_payload_when_not_set(self):
        _make_session_question(self.session, image_url='')
        payload = _session_state_payload(self.session)
        self.assertEqual(payload['question']['image_url'], '')

    def test_image_url_key_always_present_in_payload(self):
        _make_session_question(self.session, image_url='')
        payload = _session_state_payload(self.session)
        self.assertIn('image_url', payload['question'])

    def test_option_image_url_in_payload(self):
        options = [
            {'label': 'A', 'text': '', 'is_correct': True,  'image_url': '/media/answers/a.png'},
            {'label': 'B', 'text': '', 'is_correct': False, 'image_url': ''},
        ]
        _make_session_question(self.session, options=options)
        payload = _session_state_payload(self.session, reveal_answer=True)
        self.assertEqual(payload['question']['options'][0]['image_url'], '/media/answers/a.png')
        self.assertEqual(payload['question']['options'][1]['image_url'], '')

    def test_option_image_url_not_stripped_by_is_correct_filter(self):
        """image_url on options must survive the is_correct strip for students."""
        options = [
            {'label': 'A', 'text': 'yes', 'is_correct': True,  'image_url': '/media/answers/a.png'},
            {'label': 'B', 'text': 'no',  'is_correct': False, 'image_url': ''},
        ]
        _make_session_question(self.session, options=options)
        payload = _session_state_payload(self.session, reveal_answer=False)
        self.assertNotIn('is_correct', payload['question']['options'][0])
        self.assertEqual(payload['question']['options'][0]['image_url'], '/media/answers/a.png')

    def test_payload_no_question_returns_none(self):
        """Session with no questions at current_index returns question=None safely."""
        payload = _session_state_payload(self.session)
        self.assertIsNone(payload['question'])


# ---------------------------------------------------------------------------
# API endpoint: image_url in JSON response
# ---------------------------------------------------------------------------

class TestApiImageUrl(TestCase):
    """api_session_state endpoint returns image_url in the JSON body."""

    def setUp(self):
        self.host = User.objects.create_user(username='apihost_img', password='pass')
        self.session = _make_session(self.host, code='IMG002')
        self.session.status = BrainBuzzSession.STATUS_ACTIVE
        self.session.current_index = 0
        self.session.save()
        _make_session_question(self.session, image_url='/media/questions/circle.png')

    def test_api_returns_image_url(self):
        c = Client()
        c.force_login(self.host)
        resp = c.get(f'/brainbuzz/api/session/{self.session.code}/state/')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['question']['image_url'], '/media/questions/circle.png')

    def test_api_returns_empty_image_url_when_no_image(self):
        self.session.code = 'IMG003'
        self.session.save()
        BrainBuzzSessionQuestion.objects.filter(session=self.session).update(image_url='')
        c = Client()
        c.force_login(self.host)
        resp = c.get(f'/brainbuzz/api/session/{self.session.code}/state/')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['question']['image_url'], '')
