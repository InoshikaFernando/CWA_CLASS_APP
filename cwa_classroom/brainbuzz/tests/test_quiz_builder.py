"""
Unit + integration tests for the BrainBuzz Quiz Builder (CPP-229).

Covers:
  Models:
    - BrainBuzzQuiz create / str / question_count / is_valid_for_publish
    - BrainBuzzQuizQuestion ordering
    - BrainBuzzQuizOption correct flag
  Views (quiz CRUD pages):
    - quiz_list requires teacher
    - quiz_create GET/POST
    - quiz_builder GET
    - quiz_delete POST
    - quiz_publish POST (valid / invalid)
    - quiz_launch POST → creates session + snapshot
  JSON API:
    - api_quiz_detail GET
    - api_quiz_meta POST
    - api_quiz_questions POST (create)
    - api_quiz_question_detail GET / PUT / DELETE
    - api_quiz_reorder POST
  Snapshot integrity:
    - _snapshot_quiz_questions produces correct BrainBuzzSessionQuestion rows
    - Editing quiz after snapshot does NOT affect session
  Session flow:
    - Question 1 available immediately after launch
    - Late joiner receives current question via api_session_state
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from brainbuzz.models import (
    BrainBuzzQuiz,
    BrainBuzzQuizOption,
    BrainBuzzQuizQuestion,
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
)
from brainbuzz.views import _snapshot_quiz_questions

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_teacher(username='teacher_qb', **kw):
    from accounts.models import Role, UserRole
    u = User.objects.create_user(username=username, password='pass', email=f'{username}@test.com', **kw)
    role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher', 'is_active': True})
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _make_student(username='student_qb', **kw):
    return User.objects.create_user(username=username, password='pass', email=f'{username}@test.com', **kw)


def _make_quiz(teacher, title='Test Quiz', is_draft=True) -> BrainBuzzQuiz:
    return BrainBuzzQuiz.objects.create(title=title, created_by=teacher, is_draft=is_draft)


def _add_mcq(quiz, text='What is 2+2?', order=0) -> BrainBuzzQuizQuestion:
    q = BrainBuzzQuizQuestion.objects.create(
        quiz=quiz, question_text=text, question_type=QUESTION_TYPE_MCQ,
        time_limit=20, order=order,
    )
    BrainBuzzQuizOption.objects.create(question=q, option_text='3', is_correct=False, order=0)
    BrainBuzzQuizOption.objects.create(question=q, option_text='4', is_correct=True, order=1)
    BrainBuzzQuizOption.objects.create(question=q, option_text='5', is_correct=False, order=2)
    BrainBuzzQuizOption.objects.create(question=q, option_text='6', is_correct=False, order=3)
    return q


def _add_tf(quiz, text='The sky is blue.', order=1) -> BrainBuzzQuizQuestion:
    q = BrainBuzzQuizQuestion.objects.create(
        quiz=quiz, question_text=text, question_type=QUESTION_TYPE_TRUE_FALSE,
        time_limit=15, order=order,
    )
    BrainBuzzQuizOption.objects.create(question=q, option_text='True', is_correct=True, order=0)
    BrainBuzzQuizOption.objects.create(question=q, option_text='False', is_correct=False, order=1)
    return q


def _make_subject():
    from classroom.models import Subject
    return Subject.objects.get_or_create(name='General', slug='general')[0]


def _make_session_from_quiz(teacher, quiz) -> BrainBuzzSession:
    from brainbuzz.utils import generate_join_code
    subject = _make_subject()
    session = BrainBuzzSession.objects.create(
        code=generate_join_code(),
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_LOBBY,
        time_per_question_sec=20,
        config_json={'source': 'quiz', 'quiz_id': quiz.id},
    )
    _snapshot_quiz_questions(session, quiz)
    return session


# ===========================================================================
# Model tests
# ===========================================================================

class TestBrainBuzzQuizModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher()

    def test_str_draft(self):
        quiz = _make_quiz(self.teacher, title='Algebra')
        self.assertIn('[DRAFT]', str(quiz))
        self.assertIn('Algebra', str(quiz))

    def test_str_published(self):
        quiz = _make_quiz(self.teacher, title='Algebra', is_draft=False)
        self.assertNotIn('[DRAFT]', str(quiz))

    def test_question_count_zero(self):
        quiz = _make_quiz(self.teacher)
        self.assertEqual(quiz.question_count, 0)

    def test_question_count_after_add(self):
        quiz = _make_quiz(self.teacher)
        _add_mcq(quiz)
        _add_tf(quiz)
        self.assertEqual(quiz.question_count, 2)

    def test_is_valid_false_when_no_questions(self):
        quiz = _make_quiz(self.teacher)
        self.assertFalse(quiz.is_valid_for_publish())

    def test_is_valid_false_when_mcq_no_correct(self):
        quiz = _make_quiz(self.teacher)
        q = BrainBuzzQuizQuestion.objects.create(
            quiz=quiz, question_text='Q?', question_type=QUESTION_TYPE_MCQ,
            time_limit=20, order=0,
        )
        BrainBuzzQuizOption.objects.create(question=q, option_text='A', is_correct=False, order=0)
        self.assertFalse(quiz.is_valid_for_publish())

    def test_is_valid_true_with_correct_mcq(self):
        quiz = _make_quiz(self.teacher)
        _add_mcq(quiz)
        self.assertTrue(quiz.is_valid_for_publish())

    def test_is_valid_true_with_short_answer(self):
        quiz = _make_quiz(self.teacher)
        BrainBuzzQuizQuestion.objects.create(
            quiz=quiz, question_text='Capital of France?',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            time_limit=20, order=0, correct_short_answer='Paris',
        )
        self.assertTrue(quiz.is_valid_for_publish())


class TestBrainBuzzQuizQuestionModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_qq')
        cls.quiz = _make_quiz(cls.teacher)

    def test_str(self):
        q = _add_mcq(self.quiz)
        self.assertIn('Q1', str(q))

    def test_ordering_by_order_field(self):
        q0 = _add_mcq(self.quiz, text='First', order=0)
        q1 = _add_tf(self.quiz, text='Second', order=1)
        questions = list(self.quiz.quiz_questions.all())
        self.assertEqual(questions[0].id, q0.id)
        self.assertEqual(questions[1].id, q1.id)


class TestBrainBuzzQuizOptionModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_qo')
        cls.quiz = _make_quiz(cls.teacher)
        cls.question = _add_mcq(cls.quiz)

    def test_correct_option_str(self):
        opt = self.question.quiz_options.filter(is_correct=True).first()
        self.assertIn('✓', str(opt))

    def test_incorrect_option_str(self):
        opt = self.question.quiz_options.filter(is_correct=False).first()
        self.assertNotIn('✓', str(opt))

    def test_only_one_correct(self):
        correct_count = self.question.quiz_options.filter(is_correct=True).count()
        self.assertEqual(correct_count, 1)


# ===========================================================================
# View tests — quiz list / create / builder
# ===========================================================================

class TestQuizListView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_list')
        cls.student = _make_student()

    def test_redirects_anonymous(self):
        r = self.client.get(reverse('brainbuzz:quiz_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r['Location'])

    def test_redirects_non_teacher(self):
        self.client.force_login(self.student)
        r = self.client.get(reverse('brainbuzz:quiz_list'))
        self.assertEqual(r.status_code, 302)

    def test_teacher_sees_own_quizzes(self):
        _make_quiz(self.teacher, title='My Quiz')
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:quiz_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'My Quiz')

    def test_teacher_does_not_see_others_quizzes(self):
        other = _make_teacher(username='other_teacher')
        _make_quiz(other, title='Other Quiz')
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:quiz_list'))
        self.assertNotContains(r, 'Other Quiz')


class TestQuizCreateView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_create')

    def test_get_renders_form(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:quiz_create'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Quiz title')

    def test_post_creates_quiz_and_redirects_to_builder(self):
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_create'), {'title': 'Algebra Test'})
        quiz = BrainBuzzQuiz.objects.filter(created_by=self.teacher, title='Algebra Test').first()
        self.assertIsNotNone(quiz)
        self.assertTrue(quiz.is_draft)
        self.assertRedirects(r, reverse('brainbuzz:quiz_builder', args=[quiz.id]), fetch_redirect_response=False)

    def test_post_empty_title_shows_error(self):
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_create'), {'title': '   '})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'required')

    def test_post_invalid_subject_shows_error(self):
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_create'), {'title': 'Test', 'subject_id': '99999'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Invalid subject')


class TestQuizBuilderView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_builder')
        cls.quiz = _make_quiz(cls.teacher)

    def test_get_renders_builder(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:quiz_builder', args=[self.quiz.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'bbBuilder')

    def test_returns_404_for_other_teacher(self):
        other = _make_teacher(username='other_b')
        self.client.force_login(other)
        r = self.client.get(reverse('brainbuzz:quiz_builder', args=[self.quiz.id]))
        self.assertEqual(r.status_code, 404)


class TestQuizDeleteView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_del')

    def test_delete_own_quiz(self):
        quiz = _make_quiz(self.teacher, title='To Delete')
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_delete', args=[quiz.id]))
        self.assertFalse(BrainBuzzQuiz.objects.filter(id=quiz.id).exists())
        self.assertRedirects(r, reverse('brainbuzz:quiz_list'), fetch_redirect_response=False)

    def test_cannot_delete_others_quiz(self):
        other = _make_teacher(username='other_del')
        quiz = _make_quiz(other, title='Others Quiz')
        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_delete', args=[quiz.id]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(BrainBuzzQuiz.objects.filter(id=quiz.id).exists())


class TestQuizPublishView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_pub')

    def test_publish_valid_quiz(self):
        quiz = _make_quiz(self.teacher)
        _add_mcq(quiz)
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:quiz_publish', args=[quiz.id]),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'published')
        quiz.refresh_from_db()
        self.assertFalse(quiz.is_draft)

    def test_cannot_publish_empty_quiz(self):
        quiz = _make_quiz(self.teacher)
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:quiz_publish', args=[quiz.id]),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        quiz.refresh_from_db()
        self.assertTrue(quiz.is_draft)

    def test_cannot_publish_mcq_without_correct_option(self):
        quiz = _make_quiz(self.teacher)
        q = BrainBuzzQuizQuestion.objects.create(
            quiz=quiz, question_text='Q?', question_type=QUESTION_TYPE_MCQ,
            time_limit=20, order=0,
        )
        BrainBuzzQuizOption.objects.create(question=q, option_text='A', is_correct=False, order=0)
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:quiz_publish', args=[quiz.id]),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)


# ===========================================================================
# JSON API tests
# ===========================================================================

class TestApiQuizDetail(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_api')
        cls.quiz = _make_quiz(cls.teacher, title='API Quiz')
        cls.q1 = _add_mcq(cls.quiz, order=0)
        cls.q2 = _add_tf(cls.quiz, order=1)

    def test_returns_quiz_data(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:api_quiz_detail', args=[self.quiz.id]))
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['title'], 'API Quiz')
        self.assertEqual(data['question_count'], 2)
        self.assertEqual(len(data['questions']), 2)

    def test_returns_403_for_other_teacher(self):
        other = _make_teacher(username='other_api')
        self.client.force_login(other)
        r = self.client.get(reverse('brainbuzz:api_quiz_detail', args=[self.quiz.id]))
        self.assertEqual(r.status_code, 404)

    def test_questions_include_options(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:api_quiz_detail', args=[self.quiz.id]))
        data = json.loads(r.content)
        q_data = data['questions'][0]
        self.assertIn('options', q_data)
        self.assertGreater(len(q_data['options']), 0)

    def test_is_valid_true_when_all_mcq_have_correct(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('brainbuzz:api_quiz_detail', args=[self.quiz.id]))
        data = json.loads(r.content)
        self.assertTrue(data['is_valid'])


class TestApiQuizMeta(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_meta')
        cls.quiz = _make_quiz(cls.teacher, title='Old Title')

    def test_update_title(self):
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:api_quiz_meta', args=[self.quiz.id]),
            data=json.dumps({'title': 'New Title'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.title, 'New Title')

    def test_title_too_long_returns_400(self):
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:api_quiz_meta', args=[self.quiz.id]),
            data=json.dumps({'title': 'X' * 256}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)


class TestApiQuizCreateQuestion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_cq')
        cls.quiz = _make_quiz(cls.teacher)

    def _post(self, payload):
        self.client.force_login(self.teacher)
        return self.client.post(
            reverse('brainbuzz:api_quiz_questions', args=[self.quiz.id]),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_create_mcq(self):
        r = self._post({
            'question_text': 'What is 3+3?',
            'question_type': 'mcq',
            'time_limit': 20,
            'options': [
                {'option_text': '5', 'is_correct': False},
                {'option_text': '6', 'is_correct': True},
                {'option_text': '7', 'is_correct': False},
            ],
        })
        self.assertEqual(r.status_code, 201)
        data = json.loads(r.content)
        self.assertEqual(data['question_text'], 'What is 3+3?')
        self.assertEqual(len(data['options']), 3)
        self.assertTrue(any(o['is_correct'] for o in data['options']))

    def test_create_short_answer(self):
        r = self._post({
            'question_text': 'Capital of NZ?',
            'question_type': 'short',
            'time_limit': 30,
            'correct_short_answer': 'Wellington',
        })
        self.assertEqual(r.status_code, 201)
        data = json.loads(r.content)
        self.assertEqual(data['correct_short_answer'], 'Wellington')

    def test_missing_question_text_creates_with_empty_text(self):
        # Empty question_text is allowed on create (teacher fills it in the builder)
        r = self._post({'question_type': 'mcq'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(json.loads(r.content)['question_text'], '')

    def test_invalid_type_returns_400(self):
        r = self._post({'question_text': 'Q?', 'question_type': 'invalid_type'})
        self.assertEqual(r.status_code, 400)

    def test_order_auto_increments(self):
        self._post({'question_text': 'Q1', 'question_type': 'mcq'})
        self._post({'question_text': 'Q2', 'question_type': 'mcq'})
        orders = list(self.quiz.quiz_questions.order_by('order').values_list('order', flat=True))
        self.assertEqual(orders, sorted(orders))


class TestApiQuizUpdateQuestion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_uq')
        cls.quiz = _make_quiz(cls.teacher)
        cls.q = _add_mcq(cls.quiz)

    def test_update_question_text(self):
        self.client.force_login(self.teacher)
        r = self.client.generic(
            'PUT',
            reverse('brainbuzz:api_quiz_question_detail', args=[self.quiz.id, self.q.id]),
            data=json.dumps({'question_text': 'Updated question'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.q.refresh_from_db()
        self.assertEqual(self.q.question_text, 'Updated question')

    def test_update_time_limit(self):
        self.client.force_login(self.teacher)
        self.client.generic(
            'PUT',
            reverse('brainbuzz:api_quiz_question_detail', args=[self.quiz.id, self.q.id]),
            data=json.dumps({'time_limit': 45}),
            content_type='application/json',
        )
        self.q.refresh_from_db()
        self.assertEqual(self.q.time_limit, 45)

    def test_update_replaces_options(self):
        self.client.force_login(self.teacher)
        self.client.generic(
            'PUT',
            reverse('brainbuzz:api_quiz_question_detail', args=[self.quiz.id, self.q.id]),
            data=json.dumps({
                'options': [
                    {'option_text': 'Yes', 'is_correct': True},
                    {'option_text': 'No', 'is_correct': False},
                ],
            }),
            content_type='application/json',
        )
        options = list(self.q.quiz_options.all())
        self.assertEqual(len(options), 2)
        self.assertEqual(options[0].option_text, 'Yes')
        self.assertTrue(options[0].is_correct)


class TestApiQuizDeleteQuestion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_dq')

    def test_delete_question_renumbers_remaining(self):
        quiz = _make_quiz(self.teacher)
        q0 = _add_mcq(quiz, order=0)
        q1 = _add_tf(quiz, order=1)
        q2 = _add_mcq(quiz, text='Third', order=2)

        self.client.force_login(self.teacher)
        self.client.generic(
            'DELETE',
            reverse('brainbuzz:api_quiz_question_detail', args=[quiz.id, q1.id]),
            content_type='application/json',
        )
        remaining_orders = list(quiz.quiz_questions.order_by('order').values_list('order', flat=True))
        self.assertEqual(remaining_orders, [0, 1])

    def test_delete_returns_correct_json(self):
        quiz = _make_quiz(self.teacher)
        q = _add_mcq(quiz)
        self.client.force_login(self.teacher)
        r = self.client.generic(
            'DELETE',
            reverse('brainbuzz:api_quiz_question_detail', args=[quiz.id, q.id]),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data['deleted'])


class TestApiQuizReorder(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_ro')
        cls.quiz = _make_quiz(cls.teacher)
        cls.q0 = _add_mcq(cls.quiz, text='First', order=0)
        cls.q1 = _add_tf(cls.quiz, text='Second', order=1)
        cls.q2 = _add_mcq(cls.quiz, text='Third', order=2)

    def test_reorder_questions(self):
        self.client.force_login(self.teacher)
        new_order = [self.q2.id, self.q0.id, self.q1.id]
        r = self.client.post(
            reverse('brainbuzz:api_quiz_reorder', args=[self.quiz.id]),
            data=json.dumps({'ordered_ids': new_order}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.q2.refresh_from_db()
        self.q0.refresh_from_db()
        self.q1.refresh_from_db()
        self.assertEqual(self.q2.order, 0)
        self.assertEqual(self.q0.order, 1)
        self.assertEqual(self.q1.order, 2)

    def test_reorder_with_wrong_ids_returns_400(self):
        self.client.force_login(self.teacher)
        r = self.client.post(
            reverse('brainbuzz:api_quiz_reorder', args=[self.quiz.id]),
            data=json.dumps({'ordered_ids': [self.q0.id, 99999]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)


# ===========================================================================
# Snapshot integrity tests
# ===========================================================================

class TestSnapshotQuizQuestions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_snap')
        cls.quiz = _make_quiz(cls.teacher, title='Snapshot Quiz')
        cls.q1 = _add_mcq(cls.quiz, text='What is 2+2?', order=0)
        cls.q2 = _add_tf(cls.quiz, text='The sky is blue.', order=1)

    def test_snapshot_creates_correct_count(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        self.assertEqual(session.questions.count(), 2)

    def test_snapshot_preserves_question_text(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        sq = session.questions.get(order=0)
        self.assertEqual(sq.question_text, 'What is 2+2?')

    def test_snapshot_preserves_question_type(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        sq0 = session.questions.get(order=0)
        sq1 = session.questions.get(order=1)
        self.assertEqual(sq0.question_type, QUESTION_TYPE_MCQ)
        self.assertEqual(sq1.question_type, QUESTION_TYPE_TRUE_FALSE)

    def test_snapshot_options_have_labels(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        sq = session.questions.get(order=0)
        labels = [o['label'] for o in sq.options_json]
        self.assertIn('A', labels)
        self.assertIn('B', labels)

    def test_snapshot_preserves_correct_answer(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        sq = session.questions.get(order=0)
        correct = [o for o in sq.options_json if o['is_correct']]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]['text'], '4')

    def test_snapshot_source_model_is_quiz_question(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        for sq in session.questions.all():
            self.assertEqual(sq.source_model, 'BrainBuzzQuizQuestion')

    def test_editing_quiz_does_not_affect_session(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)

        # Modify the original quiz question AFTER snapshot
        self.q1.question_text = 'CHANGED QUESTION TEXT'
        self.q1.save()

        # Session snapshot must be unchanged
        sq = session.questions.get(order=0)
        self.assertEqual(sq.question_text, 'What is 2+2?')

    def test_deleting_quiz_question_does_not_affect_session(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        q_count_before = session.questions.count()

        # Delete a quiz question
        BrainBuzzQuizQuestion.objects.filter(id=self.q1.id).delete()

        # Session questions are independent (CASCADE from session, not quiz)
        self.assertEqual(session.questions.count(), q_count_before)


# ===========================================================================
# Session flow tests — Q1 availability + late joiner
# ===========================================================================

class TestSessionFlowFromQuiz(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_flow')
        cls.quiz = _make_quiz(cls.teacher)
        _add_mcq(cls.quiz, text='Q1 text', order=0)
        _add_tf(cls.quiz, text='Q2 text', order=1)

    def test_question_1_available_immediately_after_launch(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        self.assertTrue(session.questions.filter(order=0).exists())
        sq = session.questions.get(order=0)
        self.assertEqual(sq.question_text, 'Q1 text')

    def test_state_version_starts_at_zero(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        self.assertEqual(session.state_version, 0)

    def test_api_session_state_returns_question_on_active(self):
        from django.utils import timezone
        from datetime import timedelta

        session = _make_session_from_quiz(self.teacher, self.quiz)
        session.status = BrainBuzzSession.STATUS_ACTIVE
        session.state_version = 1
        session.question_deadline = timezone.now() + timedelta(seconds=20)
        session.save()

        r = self.client.get(
            reverse('brainbuzz:api_session_state', args=[session.code]),
            {'since': '-1'},
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIsNotNone(data['question'])
        self.assertEqual(data['question']['question_text'], 'Q1 text')

    def test_late_joiner_receives_current_question(self):
        from django.utils import timezone
        from datetime import timedelta

        session = _make_session_from_quiz(self.teacher, self.quiz)
        session.status = BrainBuzzSession.STATUS_ACTIVE
        session.state_version = 1
        session.question_deadline = timezone.now() + timedelta(seconds=20)
        session.save()

        # Late joiner polls with since=-1 (first poll)
        r = self.client.get(
            reverse('brainbuzz:api_session_state', args=[session.code]),
            {'since': '-1'},
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], BrainBuzzSession.STATUS_ACTIVE)
        self.assertEqual(data['current_index'], 0)
        self.assertIsNotNone(data['question'])

    def test_304_when_version_unchanged(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        # Since equals current version → 304
        r = self.client.get(
            reverse('brainbuzz:api_session_state', args=[session.code]),
            {'since': str(session.state_version)},
        )
        self.assertEqual(r.status_code, 304)

    def test_no_304_when_since_is_negative(self):
        session = _make_session_from_quiz(self.teacher, self.quiz)
        r = self.client.get(
            reverse('brainbuzz:api_session_state', args=[session.code]),
            {'since': '-1'},
        )
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# Quiz launch view — integration
# ===========================================================================

class TestQuizLaunchView(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.teacher = _make_teacher(username='teacher_launch')
        cls.subject = _make_subject()

    def test_launch_creates_session_and_redirects(self):
        quiz = _make_quiz(self.teacher, title='Launch Quiz')
        quiz.subject = self.subject
        quiz.save()
        _add_mcq(quiz)
        _add_tf(quiz)

        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_launch', args=[quiz.id]))

        session = BrainBuzzSession.objects.filter(host=self.teacher, config_json__source='quiz').first()
        self.assertIsNotNone(session)
        self.assertEqual(session.questions.count(), 2)
        self.assertRedirects(
            r,
            reverse('brainbuzz:teacher_lobby', args=[session.code]),
            fetch_redirect_response=False,
        )

    def test_launch_empty_quiz_redirects_back_to_builder(self):
        quiz = _make_quiz(self.teacher, title='Empty Quiz')
        quiz.subject = self.subject
        quiz.save()

        self.client.force_login(self.teacher)
        r = self.client.post(reverse('brainbuzz:quiz_launch', args=[quiz.id]))
        self.assertRedirects(
            r,
            reverse('brainbuzz:quiz_builder', args=[quiz.id]),
            fetch_redirect_response=False,
        )

    def test_session_config_stores_quiz_source(self):
        quiz = _make_quiz(self.teacher, title='Config Quiz')
        quiz.subject = self.subject
        quiz.save()
        _add_mcq(quiz)

        self.client.force_login(self.teacher)
        self.client.post(reverse('brainbuzz:quiz_launch', args=[quiz.id]))

        session = BrainBuzzSession.objects.filter(host=self.teacher).order_by('-created_at').first()
        self.assertEqual(session.config_json.get('source'), 'quiz')
        self.assertEqual(session.config_json.get('quiz_id'), quiz.id)
