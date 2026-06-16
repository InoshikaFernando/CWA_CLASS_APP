"""
quiz/tests.py — Audit logging tests for quiz views (CPP-270).
"""
import json
import time
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from audit.models import AuditLog
from classroom.models import Level, School, SchoolStudent, Subject, Topic
from maths.models import Answer, BasicFactsResult, Question, StudentFinalAnswer

User = get_user_model()


class QuizAuditLoggingTestBase(TestCase):
    """Shared fixtures for quiz audit tests."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Test School')
        cls.student = User.objects.create_user(
            username='quizstudent', password='pass1234', email='qs@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )

        # Create a subject, topic, and level with questions for topic quiz
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Addition', slug='addition', is_active=True,
        )
        cls.topic.levels.add(cls.level)

        # Create questions with answers for the topic
        cls.questions = []
        for i in range(12):
            q = Question.objects.create(
                question_text=f'What is {i}+1?',
                question_type='multiple_choice',
                topic=cls.topic,
                level=cls.level,
            )
            Answer.objects.create(question=q, answer_text=str(i + 1), is_correct=True, order=1)
            Answer.objects.create(question=q, answer_text=str(i + 2), is_correct=False, order=2)
            cls.questions.append(q)

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()


class TestBasicFactsQuizAuditLog(QuizAuditLoggingTestBase):
    """BasicFactsQuizView.post logs maths_quiz_completed."""

    def test_basic_facts_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a basic facts quiz to get a session
        url = reverse('basic_facts_quiz', kwargs={
            'subtopic': 'Addition', 'level_number': 100,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Extract session_id from session
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('bf_') and not k.startswith('bf_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No basic facts session key found')
        session_id = session_key[3:]  # strip 'bf_'

        # Submit answers
        data = {'session_id': session_id}
        session_data = session[session_key]
        for q in session_data['questions']:
            data[f'answer_{q["id"]}'] = str(q['answer'])

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.category, 'data_change')
        self.assertEqual(log.detail['quiz_type'], 'basic_facts')
        self.assertIn('score', log.detail)
        self.assertIn('points', log.detail)


class TestTopicQuizAuditLog(QuizAuditLoggingTestBase):
    """SubmitTopicAnswerView logs maths_quiz_completed on last answer."""

    def test_topic_quiz_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a topic quiz
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
            'topic_id': self.topic.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Find session key
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('tq_') and not k.startswith('tq_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No topic quiz session key found')
        session_id = session_key[3:]

        # Submit all answers via the AJAX endpoint
        session_data = session[session_key]
        submit_url = reverse('api_submit_topic_answer')
        for q_data in session_data['questions']:
            q = Question.objects.get(pk=q_data['id'])
            correct = q.answers.filter(is_correct=True).first()
            resp = self.client.post(
                submit_url,
                data=json.dumps({
                    'session_id': session_id,
                    'question_id': q.id,
                    'answer_id': correct.id,
                }),
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.detail['quiz_type'], 'topic')
        self.assertEqual(log.detail['topic_name'], 'Addition')
        self.assertIn('result_id', log.detail)


class TestMixedQuizAuditLog(QuizAuditLoggingTestBase):
    """MixedQuizView.post logs maths_quiz_completed."""

    def test_mixed_quiz_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a mixed quiz
        url = reverse('mixed_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Find session key
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('mq_') and not k.startswith('mq_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No mixed quiz session key found')
        session_id = session_key[3:]
        session_data = session[session_key]

        # Submit answers
        data = {'session_id': session_id}
        for qid in session_data['question_ids']:
            q = Question.objects.get(pk=qid)
            correct = q.answers.filter(is_correct=True).first()
            if q.question_type in ('multiple_choice', 'true_false'):
                data[f'answer_{q.id}'] = str(correct.id)
            else:
                data[f'text_{q.id}'] = correct.answer_text

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.detail['quiz_type'], 'mixed')
        self.assertIn('score', log.detail)


class TestAuditLogResilience(QuizAuditLoggingTestBase):
    """log_event failure must not break quiz submission."""

    def test_log_event_failure_does_not_break_basic_facts(self):
        self.client.login(username='quizstudent', password='pass1234')

        url = reverse('basic_facts_quiz', kwargs={
            'subtopic': 'Addition', 'level_number': 100,
        })
        resp = self.client.get(url)
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('bf_') and not k.startswith('bf_result_'):
                session_key = k
                break
        session_id = session_key[3:]
        session_data = session[session_key]

        data = {'session_id': session_id}
        for q in session_data['questions']:
            data[f'answer_{q["id"]}'] = str(q['answer'])

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.post(url, data)

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            BasicFactsResult.objects.filter(student=self.student).exists(),
            'BasicFactsResult not created when log_event failed',
        )


class TestInteractiveQuestionSwapWiring(TestCase):
    """Interactive question types must keep working as question #2+.

    ``_loadNext()`` advances the topic quiz by setting
    ``#question-container.innerHTML``. Per the HTML spec, <script> tags inserted
    via innerHTML do NOT execute -- so the per-question partial must carry no
    inline submit scripts. Every submit/focus helper lives in the persistent
    ``topic_quiz.html`` base script and is (re)bound by ``_initQuestion()`` after
    each swap. These tests lock that contract in so the inline scripts can't
    silently creep back into the partial.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Swap Test School')
        cls.student = User.objects.create_user(
            username='swapstudent', password='pass1234', email='swap@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Division', slug='division-swap', is_active=True,
        )
        cls.topic.levels.add(cls.level)

        cls.long_div = Question.objects.create(
            question_text='Divide 84 by 4.',
            question_type=Question.LONG_DIVISION,
            topic=cls.topic, level=cls.level,
            dividend=84, divisor=4,
        )
        Answer.objects.create(question=cls.long_div, answer_text='21', is_correct=True)

        cls.col_op = Question.objects.create(
            question_text='Add 45 and 27.',
            question_type=Question.COLUMN_OPERATION,
            topic=cls.topic, level=cls.level,
            operands=[45, 27], operator='+',
        )
        Answer.objects.create(question=cls.col_op, answer_text='72', is_correct=True)

        cls.prime = Question.objects.create(
            question_text='Find the prime factors of 12.',
            question_type=Question.PRIME_FACTORIZATION,
            topic=cls.topic, level=cls.level,
            target_number=12,
        )
        Answer.objects.create(question=cls.prime, answer_text='2x2x3', is_correct=True)

    def _render_partial(self, question):
        return render_to_string('quiz/partials/topic_question.html', {
            'question': question,
            'answers': list(question.answers.all()),
            'question_number': 2,
            'total_questions': 3,
            'session_id': 'swap-session',
        })

    def test_partial_carries_no_inline_script(self):
        """The swapped-in partial must contain no <script> tags (they'd be dead)."""
        for q in (self.long_div, self.col_op, self.prime):
            html = self._render_partial(q)
            self.assertNotIn(
                '<script', html,
                f'{q.question_type} partial must not contain an inline <script> -- '
                'it would never execute after an innerHTML swap.',
            )

    def test_partial_keeps_inline_onclick_submit(self):
        """Submit buttons keep their inline onclick -- attributes DO survive a swap."""
        self.assertIn("submitLongDivision('swap-session'", self._render_partial(self.long_div))
        self.assertIn("submitColumnOperation('swap-session'", self._render_partial(self.col_op))
        self.assertIn("submitPrimeFactorization('swap-session'", self._render_partial(self.prime))

    def test_partial_carries_swap_data_attributes(self):
        """The question card exposes session/question ids for _initQuestion()."""
        html = self._render_partial(self.long_div)
        self.assertIn('data-session-id="swap-session"', html)
        self.assertIn(f'data-question-id="{self.long_div.id}"', html)

    def test_base_script_defines_submit_and_init_helpers(self):
        """The persistent base script defines every helper the partial relies on."""
        self.client.login(username='swapstudent', password='pass1234')
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
            'topic_id': self.topic.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        for fn in (
            'function submitLongDivision',
            'function submitColumnOperation',
            'function submitPrimeFactorization',
            'function _initQuestion',
        ):
            self.assertIn(fn, content, f'{fn} must live in the persistent base script.')

    def test_loadnext_rebinds_after_swap(self):
        """_loadNext() must call _initQuestion() after writing the new innerHTML."""
        self.client.login(username='swapstudent', password='pass1234')
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
            'topic_id': self.topic.id,
        })
        content = self.client.get(url).content.decode()
        swap_idx = content.index("getElementById('question-container').innerHTML")
        after_swap = content[swap_idx:swap_idx + 400]
        self.assertIn(
            '_initQuestion()', after_swap,
            '_loadNext() must re-bind question listeners with _initQuestion() '
            'immediately after the innerHTML swap.',
        )


class QuizAttemptPersistenceTest(QuizAuditLoggingTestBase):
    """The real submit flows persist per-question review (questions_data) so an
    attempt can be reviewed later, and cap each series at the last 10."""

    def _bf_complete(self, level_number=100):
        url = reverse('basic_facts_quiz', kwargs={
            'subtopic': 'Addition', 'level_number': level_number,
        })
        self.client.get(url)
        session = self.client.session
        key = next(k for k in session.keys()
                   if k.startswith('bf_') and not k.startswith('bf_result_'))
        sid = key[3:]
        data = {'session_id': sid}
        for q in session[key]['questions']:
            data[f'answer_{q["id"]}'] = str(q['answer'])
        return self.client.post(url, data)

    def test_basic_facts_persists_questions_data(self):
        self.client.login(username='quizstudent', password='pass1234')
        self._bf_complete()
        result = BasicFactsResult.objects.filter(student=self.student).latest('completed_at')
        self.assertTrue(result.questions_data, 'questions_data not saved')
        first = result.questions_data[0]
        self.assertIn('question', first)
        self.assertIn('student_answer', first)
        self.assertIn('is_correct', first)

    def test_topic_quiz_persists_questions_data(self):
        self.client.login(username='quizstudent', password='pass1234')
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics', 'level_number': 4, 'topic_id': self.topic.id,
        })
        self.client.get(url)
        session = self.client.session
        key = next(k for k in session.keys()
                   if k.startswith('tq_') and not k.startswith('tq_result_'))
        sid = key[3:]
        questions = session[key]['questions']
        submit_url = reverse('api_submit_topic_answer')
        for q_data in questions:
            q = Question.objects.get(pk=q_data['id'])
            correct = q.answers.filter(is_correct=True).first()
            self.client.post(submit_url, data=json.dumps({
                'session_id': sid, 'question_id': q.id, 'answer_id': correct.id,
            }), content_type='application/json')

        sfa = StudentFinalAnswer.objects.filter(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
        ).latest('completed_at')
        self.assertEqual(len(sfa.questions_data), len(questions))
        item = sfa.questions_data[0]
        for field in ('question', 'student_answer', 'correct_answer', 'is_correct'):
            self.assertIn(field, item)
        # Answering all-correct → every review row is correct.
        self.assertTrue(all(row['is_correct'] for row in sfa.questions_data))

    def test_mixed_quiz_persists_questions_data(self):
        self.client.login(username='quizstudent', password='pass1234')
        url = reverse('mixed_quiz', kwargs={'subject': 'mathematics', 'level_number': 4})
        self.client.get(url)
        session = self.client.session
        key = next(k for k in session.keys()
                   if k.startswith('mq_') and not k.startswith('mq_result_'))
        sid = key[3:]
        data = {'session_id': sid}
        for qid in session[key]['question_ids']:
            q = Question.objects.get(pk=qid)
            correct = q.answers.filter(is_correct=True).first()
            data[f'answer_{q.id}'] = str(correct.id)
        self.client.post(url, data)

        sfa = StudentFinalAnswer.objects.filter(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_MIXED,
        ).latest('completed_at')
        self.assertTrue(sfa.questions_data)
        self.assertIn('correct_answer', sfa.questions_data[0])

    def _tt_session(self):
        """Build a finished times-tables session dict the submit view can read."""
        return {
            'table': 7, 'operation': 'multiplication', 'level_number': 4,
            'shuffled': False, 'thinking_time': 5, 'start_time': time.time(),
            'questions': [
                {'question': '7 × 1 = ?', 'answer': 7, 'student_answer': 7, 'is_correct': True},
                {'question': '7 × 2 = ?', 'answer': 14, 'student_answer': 10, 'is_correct': False},
            ],
        }

    def test_times_tables_persists_questions_data(self):
        self.client.login(username='quizstudent', password='pass1234')
        sid = str(uuid.uuid4())
        session = self.client.session
        session[f'tt_{sid}'] = self._tt_session()
        session.save()
        self.client.get(reverse('times_tables_submit', kwargs={'session_id': sid}))
        sfa = StudentFinalAnswer.objects.filter(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
        ).latest('completed_at')
        self.assertEqual(len(sfa.questions_data), 2)
        self.assertEqual(sfa.questions_data[1]['answer'], 14)

    def test_times_tables_flow_prunes_to_last_ten(self):
        self.client.login(username='quizstudent', password='pass1234')
        for _ in range(12):
            sid = str(uuid.uuid4())
            session = self.client.session
            session[f'tt_{sid}'] = self._tt_session()
            session.save()
            self.client.get(reverse('times_tables_submit', kwargs={'session_id': sid}))
        self.assertEqual(
            StudentFinalAnswer.objects.filter(
                student=self.student,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                table_number=7, operation='multiplication',
            ).count(),
            10,
        )

    def test_shuffled_and_ordered_times_tables_prune_independently(self):
        # Shuffled vs ordered runs of the same table are distinct series, so
        # pruning one must not eat into the other's last 10.
        base = dict(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=7, operation='multiplication', score=5, total_questions=5,
        )
        for _ in range(11):
            StudentFinalAnswer.objects.create(shuffled=False, **base)
        ordered_last = StudentFinalAnswer.objects.filter(
            student=self.student, shuffled=False).order_by('-id').first()
        StudentFinalAnswer.prune_old_attempts(ordered_last)
        # Now add a shuffled run and prune its series.
        shuffled = StudentFinalAnswer.objects.create(shuffled=True, **base)
        StudentFinalAnswer.prune_old_attempts(shuffled)
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student, shuffled=False).count(), 10,
        )
        self.assertTrue(
            StudentFinalAnswer.objects.filter(pk=shuffled.pk).exists(),
        )

    def test_topic_quiz_review_dedupes_replayed_answer(self):
        # A double-submitted question must not duplicate the saved review row.
        self.client.login(username='quizstudent', password='pass1234')
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics', 'level_number': 4, 'topic_id': self.topic.id,
        })
        self.client.get(url)
        session = self.client.session
        key = next(k for k in session.keys()
                   if k.startswith('tq_') and not k.startswith('tq_result_'))
        sid = key[3:]
        questions = session[key]['questions']
        submit_url = reverse('api_submit_topic_answer')

        def _answer(q_data):
            q = Question.objects.get(pk=q_data['id'])
            correct = q.answers.filter(is_correct=True).first()
            return self.client.post(submit_url, data=json.dumps({
                'session_id': sid, 'question_id': q.id, 'answer_id': correct.id,
            }), content_type='application/json')

        # Replay the first question, then answer the rest normally.
        _answer(questions[0])
        _answer(questions[0])
        for q_data in questions[1:]:
            _answer(q_data)

        sfa = StudentFinalAnswer.objects.filter(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
        ).latest('completed_at')
        ids = [row['id'] for row in sfa.questions_data]
        self.assertEqual(len(ids), len(set(ids)), 'duplicate review rows saved')


class QuizReviewHelperTest(TestCase):
    """Unit tests for the review normaliser + attempt-series label."""

    def test_normalize_handles_all_three_shapes(self):
        from quiz.views import _normalize_quiz_review
        out = _normalize_quiz_review([
            # topic/mixed shape
            {'question': 'a', 'student_answer': '4', 'correct_answer': '4', 'is_correct': True},
            # times-tables shape (correct answer under 'answer')
            {'question': 'b', 'student_answer': 10, 'answer': 14, 'is_correct': False},
            # basic-facts shape (correct answer under 'display_answer')
            {'question': 'c', 'student_answer': '', 'display_answer': '5', 'answer': 5, 'is_correct': False},
        ])
        self.assertEqual(out[0]['correct_answer'], '4')
        self.assertEqual(out[1]['correct_answer'], 14)
        self.assertEqual(out[2]['correct_answer'], '5')
        self.assertFalse(out[2]['is_correct'])

    def test_normalize_skips_non_dicts(self):
        from quiz.views import _normalize_quiz_review
        self.assertEqual(_normalize_quiz_review([None, 'x', 42]), [])
        self.assertEqual(_normalize_quiz_review(None), [])

    def test_sfa_label_variants(self):
        from quiz.views import _sfa_label
        from maths.models import StudentFinalAnswer as SFA
        tt = SFA(quiz_type=SFA.QUIZ_TYPE_TIMES_TABLE, table_number=7, operation='division')
        self.assertIn('7 times table', _sfa_label(tt))
        self.assertIn('Division', _sfa_label(tt))


class TestTopicQuizMeasureGrading(TestCase):
    """SubmitTopicAnswerView grades a `measure` question by tolerance.

    Regression guard: `measure` stores its target in numeric_answer (not an
    Answer row), so without a dedicated grading branch it falls through to the
    Answer-row path, finds nothing, and is marked wrong every time.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Measure School')
        cls.student = User.objects.create_user(
            username='measurestudent', password='pass1234', email='ms@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Angles', slug='angles', is_active=True,
        )
        cls.topic.levels.add(cls.level)
        # 135 degree angle, accept +/- 2.
        cls.q = Question.objects.create(
            question_text='Measure angle a.',
            question_type='measure',
            numeric_answer=Decimal('135'),
            answer_tolerance=Decimal('2'),
            answer_unit='°',
            topic=cls.topic,
            level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='measurestudent', password='pass1234')

    def _submit(self, text_answer):
        """Inject a topic-quiz session and POST one measure answer.

        Two questions in the list so this submission is never 'last' -- keeps the
        quiz-completion machinery (StudentFinalAnswer, stats) out of the way.
        """
        session_id = str(uuid.uuid4())
        session = self.client.session
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': [{'id': self.q.id}, {'id': self.q.id}],
            'correct': 0,
            'start_time': time.time(),
            'level_number': 4,
            'subject': 'mathematics',
        }
        session.save()
        resp = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({
                'session_id': session_id,
                'question_id': self.q.id,
                'text_answer': text_answer,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_within_tolerance_is_correct(self):
        # 134 is within 135 +/- 2.
        self.assertTrue(self._submit('134')['is_correct'])

    def test_on_tolerance_edge_is_correct(self):
        # 133 is exactly on the lower edge (135 - 2).
        self.assertTrue(self._submit('133')['is_correct'])

    def test_outside_tolerance_is_incorrect(self):
        # 120 is well outside the band.
        self.assertFalse(self._submit('120')['is_correct'])

    def test_unit_suffix_stripped_from_typed_value(self):
        # The grader strips the unit, so "135deg" reads as 135.
        self.assertTrue(self._submit('135°')['is_correct'])

    def test_correct_answer_text_reports_value_and_unit(self):
        data = self._submit('120')
        self.assertEqual(data['correct_answer_text'], '135°')

    def test_topic_question_partial_renders_protractor_stage(self):
        """The quiz render branch mounts the shared measure tool (protractor for
        degrees) with the figure + numeric input."""
        from django.template.loader import render_to_string

        html = render_to_string('quiz/partials/topic_question.html', {
            'question': self.q,
            'answers': [],
            'session_id': 'abc',
            'question_number': 1,
            'total_questions': 2,
        })
        self.assertIn('data-measure-tool="protractor"', html)
        self.assertIn('measure-figure', html)          # generated angle figure
        self.assertIn('id="text-answer-input"', html)  # numeric box for the reading

    def test_topic_question_partial_renders_ruler_for_length(self):
        """A length-unit measure question gets a ruler instead of a protractor."""
        from django.template.loader import render_to_string

        self.q.answer_unit = 'cm'
        self.q.save(update_fields=['answer_unit'])
        html = render_to_string('quiz/partials/topic_question.html', {
            'question': self.q,
            'answers': [],
            'session_id': 'abc',
            'question_number': 1,
            'total_questions': 2,
        })
        self.assertIn('data-measure-tool="ruler"', html)


class TimesTablesSelectViewTest(TestCase):
    """CPP-304: 'Pick Another Table' was rendering a blank page because
    TimesTablesSelectView didn't pass all_tables or year to the template."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Test School')
        cls.student = User.objects.create_user(
            username='ttstudent', password='pass1234', email='tt@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')

    def setUp(self):
        self.client = Client()
        self.client.login(username='ttstudent', password='pass1234')

    def test_multiplication_select_returns_200(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_division_select_returns_200(self):
        url = reverse('division_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_select_view_context_has_all_tables(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertIn('all_tables', resp.context)
        self.assertEqual(list(resp.context['all_tables']), list(range(1, 16)))

    def test_select_view_context_has_year(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertIn('year', resp.context)
        self.assertEqual(resp.context['year'], 4)
