"""Reporting a problem with one specific question (CPP-398).

The global feedback button captures a description and the page URL. A topic
quiz page serves dozens of questions, so CPP-398 — "the answer in a quality
answer was 23 or 23 pencils but why" against a Year 7 topic quiz — reached the
Jira queue with no way to tell which question it was about. These tests pin the
missing link: the report carries the question the reporter was looking at.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolStudent, Subject, Topic
from feedback.models import Feedback
from maths.models import Answer, Question, QuestionReport


class QuestionReportTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'qr_owner', 'qr_owner@example.com', 'pass1!')
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})

        cls.student = CustomUser.objects.create_user(
            'qr_student', 'qr_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        cls.student.roles.add(cls.student_role)
        cls.school = School.objects.create(
            name='QR School', slug='qr-school', admin=cls.owner)
        SchoolStudent.objects.get_or_create(
            school=cls.school, student=cls.student)

        cls.other_admin = CustomUser.objects.create_superuser(
            'qr_other_admin', 'qr_other@example.com', 'pass1!')
        cls.other_school = School.objects.create(
            name='Other School', slug='qr-other', admin=cls.other_admin)

        cls.subject = Subject.objects.create(name='Maths', slug='qr-maths')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Fractions', slug='qr-fractions', subject=cls.subject)

    def _question(self, school=None, text='Ally has 23 pencils. How many?'):
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type='multiple_choice', school=school)
        Answer.objects.create(question=question, answer_text='23',
                              is_correct=True, order=0)
        return question

    def _submit(self, question_id, description='the answer was 23 or 23 pencils'):
        return self.client.post(reverse('feedback:submit'), {
            'category': Feedback.CATEGORY_BUG,
            'description': description,
            'question_id': question_id,
            'page_url': '/maths/level/7/topic/190/quiz/',
        })


class ScopedModalTests(QuestionReportTestBase):
    """Opening the modal from a question card."""

    def setUp(self):
        self.client.force_login(self.student)

    def test_the_modal_names_the_question_being_reported(self):
        question = self._question()
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reported-question')
        self.assertContains(response, f'Reporting question #{question.id}')
        self.assertContains(response, '23 pencils')

    def test_the_modal_carries_the_question_id_back(self):
        question = self._question()
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertContains(
            response,
            f'name="question_id" value="{question.id}"')

    def test_a_scoped_report_defaults_to_a_bug(self):
        """Nobody reaches this link to file a feature request."""
        question = self._question()
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertContains(response, 'value="bug" selected')

    def test_the_plain_modal_is_unchanged(self):
        response = self.client.get(reverse('feedback:submit'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'reported-question')

    def test_a_question_from_another_school_is_not_found(self):
        question = self._question(school=self.other_school)
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertEqual(response.status_code, 404)

    def test_a_question_that_does_not_exist_is_not_found(self):
        response = self.client.get(reverse('feedback:submit'), {'question': 99999})
        self.assertEqual(response.status_code, 404)

    def test_a_nonsense_question_id_is_not_found(self):
        response = self.client.get(
            reverse('feedback:submit'), {'question': 'or 1=1'})
        self.assertEqual(response.status_code, 404)

    def test_a_global_question_is_reportable_by_anyone(self):
        question = self._question(school=None)
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertEqual(response.status_code, 200)

    def test_a_school_question_is_reportable_inside_that_school(self):
        question = self._question(school=self.school)
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertEqual(response.status_code, 200)

    def test_anonymous_visitors_cannot_open_it(self):
        question = self._question()
        self.client.logout()
        response = self.client.get(
            reverse('feedback:submit'), {'question': question.id})
        self.assertNotEqual(response.status_code, 200)


class SubmittingAScopedReportTests(QuestionReportTestBase):

    def setUp(self):
        self.client.force_login(self.student)

    def test_a_report_row_is_created_against_the_question(self):
        question = self._question()
        response = self._submit(question.id)
        self.assertEqual(response.status_code, 200)

        report = QuestionReport.objects.get()
        self.assertEqual(report.question, question)
        self.assertEqual(report.reported_by, self.student)
        self.assertEqual(report.school, self.school)
        self.assertEqual(report.feedback, Feedback.objects.get())
        self.assertIn('23 pencils', report.note)

    def test_the_feedback_item_is_still_created_as_before(self):
        question = self._question()
        self._submit(question.id)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.submitted_by, self.student)
        self.assertEqual(feedback.category, Feedback.CATEGORY_BUG)
        self.assertEqual(feedback.status, Feedback.STATUS_NEW)

    def test_feedback_without_a_question_creates_no_report(self):
        response = self.client.post(reverse('feedback:submit'), {
            'category': Feedback.CATEGORY_IMPROVEMENT,
            'description': 'The dashboard could be brighter.',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertEqual(QuestionReport.objects.count(), 0)

    def test_an_unusable_question_id_still_saves_the_feedback(self):
        """Losing what somebody typed is worse than losing the link."""
        question = self._question(school=self.other_school)
        with self.assertLogs('feedback.views', level='WARNING') as logs:
            response = self._submit(question.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertEqual(QuestionReport.objects.count(), 0)
        self.assertIn('unusable question id', '\n'.join(logs.output))

    def test_a_cross_school_question_is_never_reported_against(self):
        question = self._question(school=self.other_school)
        with self.assertLogs('feedback.views', level='WARNING'):
            self._submit(question.id)
        self.assertFalse(
            QuestionReport.objects.filter(question=question).exists())

    def test_an_invalid_form_keeps_the_question_scope(self):
        """Re-rendering without it would lose the link on the second try."""
        question = self._question()
        response = self.client.post(reverse('feedback:submit'), {
            'category': Feedback.CATEGORY_BUG,
            'description': '',                     # required
            'question_id': question.id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, f'name="question_id" value="{question.id}"',
            status_code=400)

    def test_two_students_can_report_the_same_question(self):
        question = self._question()
        self._submit(question.id)
        self.client.logout()

        second = CustomUser.objects.create_user(
            'qr_student2', 'qr_student2@example.com', 'pass1!',
            profile_completed=True, must_change_password=False)
        second.roles.add(self.student_role)
        SchoolStudent.objects.get_or_create(school=self.school, student=second)
        self.client.force_login(second)
        self._submit(question.id, description='I got this wrong too')

        self.assertEqual(
            QuestionReport.objects.filter(question=question).count(), 2)

    def test_anonymous_visitors_cannot_report(self):
        question = self._question()
        self.client.logout()
        self._submit(question.id)
        self.assertEqual(QuestionReport.objects.count(), 0)


class JiraDescriptionTests(QuestionReportTestBase):
    """The Jira bug has to name the question, or triage guesses again."""

    def test_the_question_is_named_in_the_filed_bug(self):
        from unittest.mock import patch

        from feedback.services import report_feedback_bug

        question = self._question()
        self.client.force_login(self.student)
        self._submit(question.id)
        feedback = Feedback.objects.get()

        with patch('feedback.services.create_jira_bug',
                   return_value='') as create, \
                patch('feedback.services.post_discord'):
            report_feedback_bug(feedback)

        description = create.call_args.kwargs['description']
        self.assertIn(f'Question: #{question.id}', description)
        self.assertIn('23 pencils', description)

    def test_an_unscoped_bug_names_no_question(self):
        from unittest.mock import patch

        from feedback.services import report_feedback_bug

        feedback = Feedback.objects.create(
            submitted_by=self.student, category=Feedback.CATEGORY_BUG,
            description='Login is broken.')

        with patch('feedback.services.create_jira_bug',
                   return_value='') as create, \
                patch('feedback.services.post_discord'):
            report_feedback_bug(feedback)

        self.assertNotIn('Question: #',
                         create.call_args.kwargs['description'])
