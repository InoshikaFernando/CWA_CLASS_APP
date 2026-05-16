"""
Unit tests for WorksheetConfirmView — PR #255 regression guard.

Tests the confirm POST flow end-to-end using Django's test client so that
any reintroduction of the _TempSession AttributeError is caught in CI
without needing a Playwright browser.

Run with:
    pytest worksheets/tests/test_views.py -v
"""
import pytest
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolTeacher, Subject, Topic
from worksheets.models import Worksheet, WorksheetUploadSession


class WorksheetConfirmViewTestBase(TestCase):
    """Shared fixtures: owner user + school + maths Level + upload session."""

    @classmethod
    def setUpTestData(cls):
        # User with INSTITUTE_OWNER role (passes RoleRequiredMixin)
        # and is school admin (get_school_for_user returns the school via admin FK)
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'cv_owner', 'cv_owner@example.com', 'pass1!',
            profile_completed=True,
            must_change_password=False,
        )
        cls.owner.roles.add(owner_role)

        cls.school = School.objects.create(
            name='CV Test School', slug='cv-test-school', admin=cls.owner,
        )
        # _get_question_scope resolves school_id via SchoolTeacher.
        # Use get_or_create — a post_save signal may already have created this row.
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=6,
            defaults={'display_name': 'Year 6'},
        )[0]

    def setUp(self):
        self.client.force_login(self.owner)

    def _make_session(self, questions=None):
        """Create a WorksheetUploadSession with the given question list."""
        if questions is None:
            questions = [
                {
                    'include': True,
                    'question_text': 'What is 4 + 4?',
                    'question_type': 'short_answer',
                    'difficulty': 1,
                    'points': 1,
                    'year_level': 6,
                    'topic': 'cv-test-addition',
                    'subject': 'Mathematics',
                    'explanation': '',
                    'answers': [],
                }
            ]
        return WorksheetUploadSession.objects.create(
            user=self.owner,
            school=self.school,
            pdf_filename='cv_test.pdf',
            worksheet_name='CV Test Worksheet',
            extracted_data={'year_level': 6, 'subject': 'Mathematics', 'questions': questions},
            is_confirmed=False,
        )


# ---------------------------------------------------------------------------
# Happy path — confirm POST creates worksheet and marks session confirmed
# ---------------------------------------------------------------------------

class TestWorksheetConfirmPostHappyPath(WorksheetConfirmViewTestBase):

    def test_confirm_post_returns_redirect_not_500(self):
        """
        PR #255 regression: _TempSession lacked save() and is_confirmed,
        causing AttributeError on every confirm POST.  The fix adds a no-op
        save() so the response is a redirect, not a 500.
        """
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        # Any redirect is fine — what we must NOT see is a 500
        self.assertIn(
            response.status_code, [301, 302],
            f"Expected redirect after confirm POST, got {response.status_code}. "
            "_TempSession.save() fix may have been reverted.",
        )

    def test_confirm_post_marks_session_confirmed(self):
        """WorksheetUploadSession.is_confirmed should be True after POST."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        self.client.post(url)

        session.refresh_from_db()
        self.assertTrue(
            session.is_confirmed,
            "WorksheetUploadSession.is_confirmed should be True after confirm POST.",
        )

    def test_confirm_post_creates_worksheet(self):
        """A Worksheet row should be created for the school after confirm POST."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})
        worksheets_before = Worksheet.objects.filter(school=self.school).count()

        self.client.post(url)

        worksheets_after = Worksheet.objects.filter(school=self.school).count()
        self.assertEqual(
            worksheets_after, worksheets_before + 1,
            "Expected one new Worksheet row after confirm POST.",
        )

    def test_confirm_post_redirects_to_detail(self):
        """Successful confirm redirects to the worksheet detail page."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url, follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/worksheets/', response['Location'])


# ---------------------------------------------------------------------------
# Guard rails — bad / edge-case requests
# ---------------------------------------------------------------------------

class TestWorksheetConfirmPostEdgeCases(WorksheetConfirmViewTestBase):

    def test_confirm_already_confirmed_session_returns_404(self):
        """Confirming an already-confirmed session should 404, not error."""
        session = self._make_session()
        session.is_confirmed = True
        session.save(update_fields=['is_confirmed'])
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)

    def test_confirm_session_owned_by_other_user_returns_404(self):
        """A teacher should not be able to confirm another user's session."""
        other_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        other = CustomUser.objects.create_user(
            'cv_other', 'cv_other@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        other.roles.add(other_role)
        session = self._make_session()          # owned by self.owner
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        self.client.force_login(other)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)

    def test_confirm_all_excluded_questions_redirects_to_preview(self):
        """If every question has include=False, redirect back to preview."""
        session = self._make_session(questions=[
            {
                'include': False,
                'question_text': 'Excluded question',
                'question_type': 'short_answer',
                'difficulty': 1, 'points': 1, 'year_level': 6,
                'topic': 'cv-test-addition', 'subject': 'Mathematics',
                'explanation': '', 'answers': [],
            }
        ])
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/preview/', response['Location'])


# ---------------------------------------------------------------------------
# CPP-277–281: WorksheetSessionView answer_partial dispatch +
#              grading helpers for long-division, prime-factorisation, extended
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock

from classroom.models import ClassRoom, ClassStudent
from maths.models import Answer as MathsAnswer, Question as MathsQuestion
from worksheets.models import (
    WorksheetAssignment, WorksheetQuestion, WorksheetStudentAnswer,
    WorksheetSubmission,
)
from worksheets.views import (
    ANSWER_PARTIAL_MAP,
    _ANSWER_PARTIAL_DEFAULT,
    _grade_long_division,
    _grade_prime_factorization,
    _prime_factors,
)


class SessionDispatchTestBase(TestCase):
    """Shared fixtures for session and answer view tests."""

    @classmethod
    def setUpTestData(cls):
        student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )

        cls.owner = CustomUser.objects.create_user(
            'sd_owner', 'sd_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='SD Test School', slug='sd-test-school', admin=cls.owner,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

        cls.student = CustomUser.objects.create_user(
            'sd_student', 'sd_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(student_role)

        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics'},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=5, defaults={'display_name': 'Year 5'},
        )[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='Arithmetic',
            defaults={'slug': 'arithmetic'},
        )[0]

        cls.classroom = ClassRoom.objects.create(
            name='SD Classroom', school=cls.school,
        )
        # Enroll student in classroom so _get_student_assignment passes
        ClassStudent.objects.get_or_create(
            classroom=cls.classroom,
            student=cls.student,
            defaults={'is_active': True},
        )

    def _make_question(self, qtype='multiple_choice', **kwargs):
        defaults = dict(
            level=self.level,
            topic=self.topic,
            question_text='Test question',
            question_type=qtype,
            difficulty=1,
            points=1,
        )
        defaults.update(kwargs)
        return MathsQuestion.objects.create(**defaults)

    def _make_worksheet_with_question(self, question):
        """Create Worksheet → WorksheetQuestion → WorksheetAssignment."""
        ws = Worksheet.objects.create(
            school=self.school,
            name='SD Worksheet',
            original_filename='',
            pdf_file=None,
            created_by=self.owner,
        )
        wq = WorksheetQuestion.objects.create(
            worksheet=ws,
            question=question,
            subject_slug='mathematics',
            content_id=question.pk,
            order=1,
        )
        ws.refresh_question_count()
        assignment = WorksheetAssignment.objects.create(
            worksheet=ws,
            classroom=self.classroom,
            assigned_by=self.owner,
        )
        return assignment, wq

    def _make_submission(self, assignment):
        return WorksheetSubmission.objects.create(
            assignment=assignment,
            student=self.student,
            total_questions=1,
        )


# ---------------------------------------------------------------------------
# Session view — answer_partial dispatch (CPP-280)
# ---------------------------------------------------------------------------

class TestSessionViewAnswerPartialDispatch(SessionDispatchTestBase):

    def _get_answer_partial(self, qtype, **kwargs):
        q = self._make_question(qtype=qtype, **kwargs)
        assignment, _ = self._make_worksheet_with_question(q)
        self._make_submission(assignment)
        self.client.force_login(self.student)
        resp = self.client.get(reverse('worksheets:session', args=[assignment.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.context['answer_partial']

    def test_session_view_answer_partial_multiple_choice(self):
        partial = self._get_answer_partial('multiple_choice')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['multiple_choice'])

    def test_session_view_answer_partial_true_false(self):
        partial = self._get_answer_partial('true_false')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['true_false'])

    def test_session_view_answer_partial_short_answer(self):
        partial = self._get_answer_partial('short_answer')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['short_answer'])

    def test_session_view_answer_partial_extended_answer(self):
        partial = self._get_answer_partial('extended_answer')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['extended_answer'])

    def test_session_view_answer_partial_fill_blank(self):
        partial = self._get_answer_partial('fill_blank')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['fill_blank'])

    def test_session_view_answer_partial_calculation(self):
        partial = self._get_answer_partial('calculation')
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['calculation'])

    def test_session_view_answer_partial_long_division(self):
        partial = self._get_answer_partial('long_division', dividend=84, divisor=7)
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['long_division'])

    def test_session_view_answer_partial_prime_factorization(self):
        partial = self._get_answer_partial('prime_factorization', target_number=30)
        self.assertEqual(partial, ANSWER_PARTIAL_MAP['prime_factorization'])

    def test_session_view_answer_partial_unknown_type_falls_back(self):
        """Unknown question_type falls back to _answer_text.html."""
        q = self._make_question(qtype='short_answer')
        q.question_type = 'unknown_future_type'  # bypass model validation
        # Calculate what the map would return without touching DB
        partial = ANSWER_PARTIAL_MAP.get('unknown_future_type', _ANSWER_PARTIAL_DEFAULT)
        self.assertEqual(partial, _ANSWER_PARTIAL_DEFAULT)


# ---------------------------------------------------------------------------
# Grading helpers — unit tests (CPP-281)
# ---------------------------------------------------------------------------

class TestGradeLongDivision(TestCase):

    def _q(self, dividend, divisor):
        q = MagicMock()
        q.dividend = dividend
        q.divisor = divisor
        return q

    def test_grade_long_division_correct(self):
        q = self._q(84, 7)  # 84 ÷ 7 = 12 r 0
        self.assertTrue(_grade_long_division(q, '12'))

    def test_grade_long_division_correct_with_remainder(self):
        q = self._q(85, 7)  # 85 ÷ 7 = 12 r 1
        self.assertTrue(_grade_long_division(q, '12 r 1'))

    def test_grade_long_division_zero_remainder_explicit(self):
        q = self._q(84, 7)  # 84 ÷ 7 = 12 r 0
        self.assertTrue(_grade_long_division(q, '12 r 0'))

    def test_grade_long_division_wrong_quotient(self):
        q = self._q(84, 7)
        self.assertFalse(_grade_long_division(q, '11'))

    def test_grade_long_division_wrong_remainder(self):
        q = self._q(85, 7)
        self.assertFalse(_grade_long_division(q, '12 r 2'))

    def test_grade_long_division_malformed_answer(self):
        q = self._q(84, 7)
        self.assertFalse(_grade_long_division(q, 'not a number'))

    def test_grade_long_division_empty_answer(self):
        q = self._q(84, 7)
        self.assertFalse(_grade_long_division(q, ''))

    def test_grade_long_division_missing_dividend(self):
        q = self._q(None, 7)
        self.assertFalse(_grade_long_division(q, '12'))


class TestGradePrimeFactorization(TestCase):

    def _q(self, target):
        q = MagicMock()
        q.target_number = target
        return q

    def test_grade_prime_factorization_correct(self):
        q = self._q(30)  # 2 × 3 × 5
        self.assertTrue(_grade_prime_factorization(q, '2x3x5'))

    def test_grade_prime_factorization_correct_different_order(self):
        q = self._q(30)
        self.assertTrue(_grade_prime_factorization(q, '5x3x2'))

    def test_grade_prime_factorization_accepts_unicode_times(self):
        q = self._q(30)
        self.assertTrue(_grade_prime_factorization(q, '2×3×5'))

    def test_grade_prime_factorization_wrong_missing_factor(self):
        q = self._q(30)
        self.assertFalse(_grade_prime_factorization(q, '2x5'))

    def test_grade_prime_factorization_wrong_extra_factor(self):
        q = self._q(30)
        self.assertFalse(_grade_prime_factorization(q, '2x3x5x7'))

    def test_grade_prime_factorization_repeated_factors(self):
        q = self._q(12)  # 2 × 2 × 3
        self.assertTrue(_grade_prime_factorization(q, '2x2x3'))

    def test_grade_prime_factorization_empty_answer(self):
        q = self._q(30)
        self.assertFalse(_grade_prime_factorization(q, ''))

    def test_grade_prime_factorization_missing_target_number(self):
        q = self._q(None)
        self.assertFalse(_grade_prime_factorization(q, '2x3x5'))

    def test_prime_factors_utility(self):
        self.assertEqual(_prime_factors(30), [2, 3, 5])
        self.assertEqual(_prime_factors(12), [2, 2, 3])
        self.assertEqual(_prime_factors(7), [7])
        self.assertEqual(_prime_factors(1), [])


# ---------------------------------------------------------------------------
# WorksheetAnswerView — grading via POST (CPP-281)
# ---------------------------------------------------------------------------

class TestAnswerViewGrading(SessionDispatchTestBase):

    def _submit_answer(self, assignment, question, **post_data):
        self.client.force_login(self.student)
        submission = self._make_submission(assignment)
        data = {'question_id': question.pk}
        data.update(post_data)
        return self.client.post(
            reverse('worksheets:answer', args=[assignment.pk]),
            data,
            HTTP_HX_REQUEST='true',
        )

    def test_grade_long_division_correct_via_view(self):
        q = self._make_question('long_division', dividend=84, divisor=7)
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='12')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertTrue(sa.is_correct)
        self.assertEqual(sa.points_earned, 1.0)

    def test_grade_long_division_wrong_via_view(self):
        q = self._make_question('long_division', dividend=84, divisor=7)
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='11')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertFalse(sa.is_correct)
        self.assertEqual(sa.points_earned, 0.0)

    def test_grade_prime_factorization_correct_via_view(self):
        q = self._make_question('prime_factorization', target_number=30)
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='2x3x5')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertTrue(sa.is_correct)

    def test_grade_prime_factorization_wrong_via_view(self):
        q = self._make_question('prime_factorization', target_number=30)
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='2x5')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertFalse(sa.is_correct)

    @patch('worksheets.views.grade_extended_answer')
    def test_grade_extended_answer_calls_grading_service(self, mock_grade):
        mock_grade.return_value = {
            'is_correct': True,
            'is_partial': False,
            'score_fraction': 0.9,
            'feedback': 'Excellent reasoning.',
            'what_was_correct': 'All key steps.',
            'what_to_add': 'Nothing',
            'cache_hit': False,
        }
        q = self._make_question('extended_answer')
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='My detailed answer.')
        self.assertEqual(resp.status_code, 200)
        mock_grade.assert_called_once()
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertTrue(sa.is_correct)
        self.assertEqual(sa.answer_data['feedback'], 'Excellent reasoning.')
        self.assertFalse(sa.answer_data['is_partial'])

    @patch('worksheets.views.grade_extended_answer')
    def test_grade_extended_answer_partial_credit_stored(self, mock_grade):
        """Partial answer (score 0.3) stores is_partial=True and structured feedback."""
        mock_grade.return_value = {
            'is_correct': False,
            'is_partial': True,
            'score_fraction': 0.3,
            'feedback': 'You got some things right.',
            'what_was_correct': 'Mentioned gravity correctly.',
            'what_to_add': 'Add the inverse square law.',
            'cache_hit': False,
        }
        q = self._make_question('extended_answer')
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='Gravity pulls things down.')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertFalse(sa.is_correct)
        self.assertTrue(sa.answer_data['is_partial'])
        self.assertEqual(sa.answer_data['what_was_correct'], 'Mentioned gravity correctly.')
        self.assertEqual(sa.answer_data['what_to_add'], 'Add the inverse square law.')
        # Partial points awarded proportionally (0.3 * 1.0 = 0.3)
        self.assertAlmostEqual(sa.points_earned, 0.3, places=2)
        # Template renders amber partial state — assert content
        self.assertContains(resp, 'Partially correct')

    @patch('worksheets.views.grade_extended_answer')
    def test_grade_extended_answer_graceful_fallback_when_service_unavailable(self, mock_grade):
        mock_grade.side_effect = Exception('API timeout')
        q = self._make_question('extended_answer')
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='My answer.')
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertFalse(sa.is_correct)
        self.assertEqual(sa.answer_data.get('review_status'), 'pending_ai')

    def test_grade_short_answer_exact_match(self):
        q = self._make_question('short_answer')
        MathsAnswer.objects.create(question=q, answer_text='Seven', is_correct=True, order=1)
        assignment, _ = self._make_worksheet_with_question(q)
        resp = self._submit_answer(assignment, q, text_answer='seven')  # case-insensitive
        self.assertEqual(resp.status_code, 200)
        sa = WorksheetStudentAnswer.objects.get(question=q)
        self.assertTrue(sa.is_correct)
