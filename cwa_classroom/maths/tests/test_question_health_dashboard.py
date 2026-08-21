"""Tests for the question-bank health snapshot and super-admin dashboard."""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question, QuestionHealthSnapshot

User = get_user_model()


def _question(level, topic, text, options):
    q = Question.objects.create(
        level=level, topic=topic, question_text=text,
        question_type=Question.MULTIPLE_CHOICE, difficulty=1,
    )
    for order, (answer_text, correct) in enumerate(options):
        Answer.objects.create(question=q, answer_text=answer_text,
                              is_correct=correct, order=order)
    return q


class RecordQuestionHealthTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=988, display_name='Health')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Health Fractions',
            slug='health-fractions', is_active=True)

    def test_records_blocking_and_advisory_separately(self):
        # Blocking: a distractor equal to the correct answer.
        _question(self.level, self.topic, 'Calculate: 11/12 - 2/3',
                  [('1/4', True), ('3/12', False), ('1/2', False)])
        # Advisory: two distractors worth the same, neither correct.
        _question(self.level, self.topic, '5/6 kg less 1/2 kg?',
                  [('1/3', True), ('1/2', False), ('3/6', False)])
        # Clean.
        _question(self.level, self.topic, 'Calculate: 9/10 - 3/5',
                  [('3/10', True), ('2/5', False), ('1/2', False)])

        call_command('record_question_health', '--level', 988, '--quiet')

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.choice_questions, 3)
        self.assertEqual(snapshot.questions_blocking, 1)
        self.assertEqual(snapshot.questions_advisory, 1)
        self.assertIn('EQUIVALENT-OPTION', snapshot.issue_counts)
        self.assertIn('DUPLICATE-VALUE', snapshot.issue_counts)

    def test_health_and_coverage_are_reported_separately(self):
        # A word problem cannot be machine-verified but is structurally sound:
        # it must count as healthy and NOT as verified. Collapsing the two
        # would overstate what is actually known.
        _question(self.level, self.topic,
                  'A bag holds 5/6 kg. 1/2 kg is removed. How much is left?',
                  [('1/3', True), ('1/2', False), ('1/6', False)])

        call_command('record_question_health', '--level', 988, '--quiet')

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.health_percent, 100)
        self.assertEqual(snapshot.coverage_percent, 0)
        self.assertEqual(snapshot.unverifiable, 1)

    def test_flagged_list_is_capped_but_counts_stay_complete(self):
        for index in range(4):
            _question(self.level, self.topic, f'Calculate: 11/12 - 2/3 #{index}',
                      [('1/4', True), ('3/12', False)])

        call_command('record_question_health', '--level', 988,
                     '--max-flagged', 2, '--quiet')

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.questions_blocking, 4)      # complete
        self.assertEqual(len(snapshot.flagged_questions), 2)  # capped

    def test_empty_bank_is_not_reported_as_unhealthy(self):
        call_command('record_question_health', '--level', 988, '--quiet')
        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.choice_questions, 0)
        self.assertEqual(snapshot.health_percent, 100)
        self.assertEqual(snapshot.status, 'ok')


class QuestionHealthDashboardViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='healthadmin', email='health@test.com', password='pass1234')
        cls.student = User.objects.create_user(
            username='healthstudent', email='hs@test.com', password='pass1234')

    def setUp(self):
        self.client = Client()
        self.url = reverse('question_health_admin_dashboard')

    def test_superuser_can_view(self):
        self.client.login(username='healthadmin', password='pass1234')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Question Bank Health')

    def test_non_superuser_is_refused(self):
        self.client.login(username='healthstudent', password='pass1234')
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_anonymous_is_refused(self):
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_renders_before_any_snapshot_exists(self):
        # The dashboard must be usable on day one, before the cron has run.
        self.client.login(username='healthadmin', password='pass1234')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'record_question_health')

    def test_shows_the_latest_snapshot(self):
        QuestionHealthSnapshot.objects.create(
            choice_questions=57, questions_blocking=14, questions_advisory=3,
            arithmetic_verified=9, unverifiable=48,
            issue_counts={'EQUIVALENT-OPTION': 17},
            flagged_questions=[{'id': 6017, 'codes': ['EQUIVALENT-OPTION'],
                                'detail': "'9/3 kg' == '3 kg'",
                                'text': 'A baker uses 1/3 kg...',
                                'level': 7, 'topic': 'Fractions'}],
        )
        self.client.login(username='healthadmin', password='pass1234')
        response = self.client.get(self.url)
        self.assertContains(response, 'Distractor equals the answer')
        self.assertContains(response, 'Q6017')


class QuestionHealthReachabilityTests(TestCase):
    """The dashboard must be reachable by clicking, not only by typing the URL.

    This page shipped with no link to it anywhere in the UI — the view, the URL
    and the template all existed and were tested, so every test passed while the
    feature was, in practice, undiscoverable. Testing that a page renders says
    nothing about whether a user can get to it; that gap is what these tests
    close.
    """

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='navadmin', email='nav@test.com', password='pass1234')
        cls.teacher = User.objects.create_user(
            username='navteacher', email='navt@test.com', password='pass1234')

    def test_admin_sidebar_links_to_the_dashboard(self):
        from django.template.loader import render_to_string

        html = render_to_string(
            'partials/sidebar_admin.html',
            {'request': _FakeRequest(self.superuser)},
        )
        self.assertIn(reverse('question_health_admin_dashboard'), html)
        self.assertIn('Question Health', html)

    def test_sidebar_hides_the_link_from_non_superusers(self):
        # The view is superuser-only, so a link a teacher can see is a link that
        # only leads to a 403.
        from django.template.loader import render_to_string

        html = render_to_string(
            'partials/sidebar_admin.html',
            {'request': _FakeRequest(self.teacher)},
        )
        self.assertNotIn(reverse('question_health_admin_dashboard'), html)


class _FakeRequest:
    """Minimal stand-in for the request the sidebar reads (user + path)."""

    def __init__(self, user, path='/admin-dashboard/'):
        self.user = user
        self.path = path
