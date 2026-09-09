"""Making retirement reachable without a shell (CPP-410 follow-up).

``Question.retire()`` existed but only from a Django shell, which meant the
three unanswerable questions from CPP-406 still could not be withdrawn by
anyone but a developer. A lever nobody can pull is not a lever.

Two ways in, tested here: the admin actions (for one-off use by a super-admin)
and ``manage.py retire_question`` (for a real reason, several questions at
once, and a preview before anything is written).

The property both must keep is the one retirement exists for: **no answer row
is deleted and no mark moves.**
"""
from datetime import timedelta
from io import StringIO

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from classroom.models import ClassRoom, Level, School
from maths.admin import QuestionAdmin
from maths.models import Question

User = get_user_model()


def _request(user):
    """A request the admin's message_user can write onto."""
    request = RequestFactory().post('/admin/maths/question/')
    request.user = user
    request.session = 'session'
    from django.contrib.messages.storage.fallback import FallbackStorage
    request._messages = FallbackStorage(request)
    return request


class AdminActionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=958, defaults={'display_name': 'admin retire fixture'})
        cls.admin_user = User.objects.create_superuser(
            username='retireadmin', email='ra@test.com', password='p')

    def setUp(self):
        self.admin = QuestionAdmin(Question, AdminSite())

    def _q(self, text='Find the value of x.'):
        return Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)

    def test_the_action_withdraws_the_selected_questions(self):
        q = self._q()
        self.admin.retire_questions(
            _request(self.admin_user), Question.objects.filter(pk=q.pk))
        q.refresh_from_db()

        self.assertTrue(q.is_retired)
        self.assertNotEqual(q.retired_reason, '')

    def test_unretire_puts_them_back(self):
        q = self._q()
        q.retire('broken')
        self.admin.unretire_questions(
            _request(self.admin_user), Question.objects.filter(pk=q.pk))
        q.refresh_from_db()

        self.assertFalse(q.is_retired)
        self.assertEqual(q.retired_reason, '')

    def test_an_already_retired_question_is_reported_not_re_stamped(self):
        """Selecting a mixed batch must not silently rewrite the ones already done."""
        fresh, done = self._q('fresh'), self._q('already withdrawn')
        earlier = timezone.now() - timedelta(days=5)
        done.retire('withdrawn earlier', when=earlier)

        self.admin.retire_questions(
            _request(self.admin_user),
            Question.objects.filter(pk__in=[fresh.pk, done.pk]))

        done.refresh_from_db()
        fresh.refresh_from_db()
        self.assertTrue(fresh.is_retired)
        self.assertEqual(done.retired_reason, 'withdrawn earlier')
        self.assertEqual(done.retired_at.date(), earlier.date(),
                         'the original retirement date must survive')

    def test_the_changelist_says_which_are_withdrawn(self):
        live, gone = self._q('live'), self._q('gone')
        gone.retire('unanswerable')
        gone.refresh_from_db()

        self.assertEqual(self.admin.retirement_status(live), 'Live')
        self.assertIn('Withdrawn', self.admin.retirement_status(gone))
        self.assertIn('unanswerable', self.admin.retirement_status(gone))

    def test_both_actions_are_registered(self):
        self.assertIn('retire_questions', self.admin.actions)
        self.assertIn('unretire_questions', self.admin.actions)


class ManagementCommandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Cmd School')
        cls.level = Level.objects.create(level_number=957, display_name='Y-cmd')
        cls.classroom = ClassRoom.objects.create(name='C1', school=cls.school)
        cls.teacher = User.objects.create_user(
            username='cmdteacher', password='p', email='ct@test.com')
        cls.student = User.objects.create_user(
            username='cmdstudent', password='p', email='cs@test.com')

    def _q(self, text='Two straight lines intersect. Find x.'):
        return Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)

    def _run(self, *args):
        out = StringIO()
        call_command('retire_question', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        q = self._q()
        output = self._run('--question', str(q.pk), '--reason', 'no diagram')
        q.refresh_from_db()

        self.assertFalse(q.is_retired)
        self.assertIn('DRY RUN', output)

    def test_apply_withdraws_with_the_reason_given(self):
        q = self._q()
        self._run('--question', str(q.pk), '--reason',
                  'No diagram; unanswerable (CPP-406).', '--apply')
        q.refresh_from_db()

        self.assertTrue(q.is_retired)
        self.assertEqual(q.retired_reason, 'No diagram; unanswerable (CPP-406).')

    def test_several_questions_at_once(self):
        a, b = self._q('one'), self._q('two')
        self._run('--question', str(a.pk), '--question', str(b.pk),
                  '--reason', 'both broken', '--apply')

        a.refresh_from_db(); b.refresh_from_db()
        self.assertTrue(a.is_retired)
        self.assertTrue(b.is_retired)

    def test_it_reports_how_many_answers_it_is_keeping(self):
        """The number that makes the difference from deleting visible."""
        from homework.models import (
            Homework, HomeworkStudentAnswer, HomeworkSubmission)

        q = self._q()
        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='HW',
            homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=1))
        submission = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, score=0, total_questions=1)
        HomeworkStudentAnswer.objects.create(
            submission=submission, question=q, text_answer='37', is_correct=False)

        output = self._run('--question', str(q.pk), '--reason', 'x', '--apply')

        self.assertIn('1 recorded answer(s) KEPT', output)
        self.assertEqual(HomeworkStudentAnswer.objects.filter(question=q).count(), 1)
        submission.refresh_from_db()
        self.assertEqual(submission.score, 0)
        self.assertEqual(submission.total_questions, 1)

    def test_unretire_restores_it(self):
        q = self._q()
        q.retire('broken')
        self._run('--question', str(q.pk), '--unretire', '--apply')
        q.refresh_from_db()
        self.assertFalse(q.is_retired)

    def test_a_second_run_skips_rather_than_re_stamping(self):
        q = self._q()
        self._run('--question', str(q.pk), '--reason', 'first', '--apply')
        q.refresh_from_db()
        first_stamp = q.retired_at

        output = self._run('--question', str(q.pk), '--reason', 'second', '--apply')
        q.refresh_from_db()

        self.assertIn('already withdrawn', output)
        self.assertEqual(q.retired_at, first_stamp)
        self.assertEqual(q.retired_reason, 'first')

    def test_a_missing_question_is_reported_not_swallowed(self):
        output = self._run('--question', '99999999', '--reason', 'x', '--apply')
        self.assertIn('not found', output)

    def test_no_arguments_is_an_error_rather_than_a_no_op(self):
        with self.assertRaises(CommandError):
            self._run('--apply')

    def test_list_shows_what_is_withdrawn_and_why(self):
        q = self._q()
        q.retire('No table attached (CPP-406).')

        output = self._run('--list')

        self.assertIn(f'Q{q.pk}', output)
        self.assertIn('No table attached', output)

    def test_list_says_so_when_nothing_is_withdrawn(self):
        self.assertIn('No question is currently withdrawn', self._run('--list'))
