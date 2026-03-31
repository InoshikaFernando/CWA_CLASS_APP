"""Tests for _get_questions_for_level() in maths/views.py.

Verifies that the scoping rules correctly determine which questions a user
can access based on their school membership status:

  - Individual student (no active SchoolStudent) → global only
  - School student with no local questions       → global only
  - School student with local + global           → local ∪ global
  - School student with local only               → local only
  - Inactive membership                          → treated as individual (global only)
  - Cross-school isolation                       → School B questions not visible to School A student
  - Level filtering                              → questions from other levels not returned
"""
from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolStudent, Subject
from maths.models import Answer, Question
from maths.views import _get_questions_for_level


# ---------------------------------------------------------------------------
# Shared base fixture
# ---------------------------------------------------------------------------

class QuestionScopingTestBase(TestCase):
    """Shared fixtures for _get_questions_for_level tests.

    Uses high level_numbers (997-999) to avoid clashing with any existing
    Level rows created by other test classes or migrations.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Roles ──────────────────────────────────────────────
        cls.role_student, _ = Role.objects.get_or_create(
            name=Role.STUDENT,
            defaults={'display_name': 'Student'},
        )
        cls.role_individual, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student'},
        )

        # ── Admin user (needed as school admin) ────────────────
        cls.admin = CustomUser.objects.create_superuser(
            'scopeadmin', 'scopeadmin@test.com', 'pass1234',
        )

        # ── Students ───────────────────────────────────────────
        cls.individual_student = CustomUser.objects.create_user(
            'scope_individual', 'scope_ind@test.com', 'pass1234',
        )
        cls.individual_student.roles.add(cls.role_individual)

        cls.school_student_a = CustomUser.objects.create_user(
            'scope_school_a', 'scope_a@test.com', 'pass1234',
        )
        cls.school_student_a.roles.add(cls.role_student)

        cls.school_student_b = CustomUser.objects.create_user(
            'scope_school_b', 'scope_b@test.com', 'pass1234',
        )
        cls.school_student_b.roles.add(cls.role_student)

        cls.inactive_student = CustomUser.objects.create_user(
            'scope_inactive', 'scope_inactive@test.com', 'pass1234',
        )
        cls.inactive_student.roles.add(cls.role_student)

        # ── Schools ────────────────────────────────────────────
        cls.school_a = School.objects.create(
            name='Scope School A', slug='scope-school-a', admin=cls.admin,
        )
        cls.school_b = School.objects.create(
            name='Scope School B', slug='scope-school-b', admin=cls.admin,
        )

        # Active membership: school_student_a → school_a
        SchoolStudent.objects.create(
            school=cls.school_a, student=cls.school_student_a, is_active=True,
        )

        # Active membership: school_student_b → school_b
        SchoolStudent.objects.create(
            school=cls.school_b, student=cls.school_student_b, is_active=True,
        )

        # INACTIVE membership: inactive_student → school_a
        SchoolStudent.objects.create(
            school=cls.school_a, student=cls.inactive_student, is_active=False,
        )

        # ── Levels (high numbers to avoid collisions) ──────────
        cls.level_999, _ = Level.objects.get_or_create(
            level_number=999,
            defaults={'display_name': 'Scope Test Level 999'},
        )
        cls.level_998, _ = Level.objects.get_or_create(
            level_number=998,
            defaults={'display_name': 'Scope Test Level 998'},
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _create_question(self, level, school=None, text='Test question?'):
        """Create a Question with one correct Answer.  Returns the Question."""
        q = Question.objects.create(
            level=level,
            school=school,
            question_text=text,
            question_type='multiple_choice',
            difficulty=1,
            points=1,
        )
        Answer.objects.create(
            question=q, answer_text='Correct', is_correct=True, order=1,
        )
        return q


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class IndividualStudentScopingTests(QuestionScopingTestBase):
    """Individual students (no active SchoolStudent) see global questions only."""

    def test_individual_student_sees_only_global_questions(self):
        """Individual student: only school=NULL questions returned."""
        global_q = self._create_question(self.level_999, school=None, text='Global IND')
        local_q = self._create_question(self.level_999, school=self.school_a, text='Local IND')

        qs = _get_questions_for_level(self.individual_student, self.level_999)

        ids = list(qs.values_list('id', flat=True))
        self.assertIn(global_q.id, ids)
        self.assertNotIn(local_q.id, ids)

    def test_individual_student_empty_when_no_global_questions(self):
        """Individual student with no global questions → empty queryset."""
        # Only local question for school_a; no global question at level_998
        self._create_question(self.level_998, school=self.school_a, text='Local Only 998')

        qs = _get_questions_for_level(self.individual_student, self.level_998)
        self.assertEqual(qs.count(), 0)


class SchoolStudentScopingTests(QuestionScopingTestBase):
    """School students see questions based on local/global availability."""

    def test_school_student_no_local_gets_global_only(self):
        """School student whose school has no local questions → global only."""
        global_q = self._create_question(self.level_999, school=None, text='Global NoLocal')

        qs = _get_questions_for_level(self.school_student_a, self.level_999)
        ids = list(qs.values_list('id', flat=True))

        self.assertIn(global_q.id, ids)
        # No local questions were created, so the count should only include globals
        self.assertFalse(qs.filter(school__isnull=False).exists())

    def test_school_student_with_local_and_global_gets_both(self):
        """School student with local + global questions → union of both."""
        global_q = self._create_question(self.level_999, school=None, text='Global Both')
        local_q = self._create_question(self.level_999, school=self.school_a, text='Local Both')

        qs = _get_questions_for_level(self.school_student_a, self.level_999)
        ids = list(qs.values_list('id', flat=True))

        self.assertIn(global_q.id, ids)
        self.assertIn(local_q.id, ids)

    def test_school_student_with_local_only_gets_local_only(self):
        """School student whose school has local questions but no globals → local only."""
        local_q = self._create_question(self.level_999, school=self.school_a, text='Local Only Scoped')

        # Verify there are no global questions for this level at this point in test
        # (other tests may have added globals; use a dedicated level to isolate)
        level_997, _ = Level.objects.get_or_create(
            level_number=997,
            defaults={'display_name': 'Scope Test Level 997'},
        )
        local_only_q = self._create_question(level_997, school=self.school_a, text='Local Only L997')

        qs = _get_questions_for_level(self.school_student_a, level_997)
        ids = list(qs.values_list('id', flat=True))

        self.assertIn(local_only_q.id, ids)
        # No global questions exist for level_997, so none should be returned
        self.assertFalse(qs.filter(school__isnull=True).exists())

    def test_school_student_does_not_see_other_school_local_questions(self):
        """School A student does NOT see School B local questions."""
        school_b_q = self._create_question(
            self.level_999, school=self.school_b, text='School B Local',
        )

        qs = _get_questions_for_level(self.school_student_a, self.level_999)
        ids = list(qs.values_list('id', flat=True))

        self.assertNotIn(school_b_q.id, ids)

    def test_school_student_no_local_and_no_global_returns_empty(self):
        """School student with NO local AND NO global questions → empty queryset.

        This is the 'no questions at all' edge case. The hub card should
        already be 'Coming Soon' (not clickable) in this situation, but the
        quiz scoping helper must still return an empty queryset gracefully
        rather than crashing or leaking other schools' questions.
        """
        level_991, _ = Level.objects.get_or_create(
            level_number=991,
            defaults={'display_name': 'Scope Test Level 991'},
        )
        # No questions created for level_991 at all.
        qs = _get_questions_for_level(self.school_student_a, level_991)
        self.assertEqual(qs.count(), 0)


class InactiveMembershipScopingTests(QuestionScopingTestBase):
    """Students with inactive SchoolStudent records are treated as individual students."""

    def test_inactive_membership_treated_as_individual(self):
        """INACTIVE SchoolStudent → behaves like individual student (global only)."""
        global_q = self._create_question(self.level_999, school=None, text='Global Inactive')
        local_q = self._create_question(
            self.level_999, school=self.school_a, text='Local Inactive',
        )

        qs = _get_questions_for_level(self.inactive_student, self.level_999)
        ids = list(qs.values_list('id', flat=True))

        self.assertIn(global_q.id, ids)
        self.assertNotIn(local_q.id, ids)


class LevelIsolationScopingTests(QuestionScopingTestBase):
    """Questions from other levels are never returned."""

    def test_questions_from_other_levels_not_returned(self):
        """Questions belonging to a different level must not appear in results."""
        target_q = self._create_question(
            self.level_999, school=None, text='Correct Level',
        )
        wrong_level_q = self._create_question(
            self.level_998, school=None, text='Wrong Level',
        )

        qs = _get_questions_for_level(self.individual_student, self.level_999)
        ids = list(qs.values_list('id', flat=True))

        self.assertIn(target_q.id, ids)
        self.assertNotIn(wrong_level_q.id, ids)

    def test_empty_result_when_no_questions_of_any_kind(self):
        """No questions at all for the level → empty queryset, no crash."""
        level_996, _ = Level.objects.get_or_create(
            level_number=996,
            defaults={'display_name': 'Scope Test Level 996'},
        )

        qs = _get_questions_for_level(self.individual_student, level_996)
        self.assertEqual(qs.count(), 0)
