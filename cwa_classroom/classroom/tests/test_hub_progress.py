"""Unit tests for CPP-151: Multi-School Subject Progress in Student Hub.

Covers:
  - _compute_subject_progress(user, subject_ids, school=None)
  - _annotate_apps_with_progress(apps, user)
  - SubjectsHubView: multi-school display without enrollment filter,
    progress data on each card, shared global progress, scoped local progress.

Key invariants verified:
  1. Global question answers are shared across all LocalSubjects inheriting the same
     GlobalSubject — answering once does NOT double-count points.
  2. LocalQuestion answers are scoped to the specific school — they do NOT bleed
     into a different school's progress count.
  3. Progress denominator = total_global + total_local_for_this_school.
  4. SubjectsHubView shows ALL department subjects, not just enrolled ones.
"""
import uuid

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    Department, DepartmentSubject, Level, School, SchoolStudent, Subject,
    SubjectApp,
)
from classroom.views import (
    _annotate_apps_with_progress,
    _compute_subject_progress,
)
from maths.models import Answer, Question, StudentAnswer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def _make_user(username, role_name, **extra):
    user = CustomUser.objects.create_user(
        username=username,
        password='testpass',
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
        **extra,
    )
    role = _create_role(role_name)
    UserRole.objects.create(user=user, role=role)
    return user


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class HubProgressBase(TestCase):
    """Creates two schools, a global subject, and two local subjects.

    Level numbers 978-982 are reserved for this module to avoid colliding with
    other test classes that use the high-number ranges (e.g. 992-995).

    Global questions  : 3 (school=None, level=level_global)
    Local-A questions : 2 (school=school_a, level=level_local_a)
    Local-B questions : 2 (school=school_b, level=level_local_b)
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_superuser(
            'hub_prog_admin', 'hub_prog_admin@test.local', 'pass',
        )

        # ── Schools ────────────────────────────────────────────────────────
        cls.school_a = School.objects.create(
            name='Hub Prog School A', slug='hub-prog-school-a', admin=cls.admin,
        )
        cls.school_b = School.objects.create(
            name='Hub Prog School B', slug='hub-prog-school-b', admin=cls.admin,
        )

        # ── Global subject ─────────────────────────────────────────────────
        cls.global_subj, _ = Subject.objects.get_or_create(
            slug='hub-prog-global',
            defaults={'name': 'Hub Prog Global', 'is_active': True},
        )

        # ── Local subjects (linked to global via global_subject FK) ────────
        cls.local_a = Subject.objects.create(
            name='Hub Prog Local A', slug='hub-prog-local-a',
            school=cls.school_a, is_active=True,
            global_subject=cls.global_subj,
        )
        cls.local_b = Subject.objects.create(
            name='Hub Prog Local B', slug='hub-prog-local-b',
            school=cls.school_b, is_active=True,
            global_subject=cls.global_subj,
        )

        # ── Levels ────────────────────────────────────────────────────────
        cls.level_global, _ = Level.objects.get_or_create(
            level_number=982,
            defaults={'display_name': 'Hub Prog Level 982', 'subject': cls.global_subj},
        )
        cls._ensure_level_subject(cls.level_global, cls.global_subj)

        cls.level_local_a, _ = Level.objects.get_or_create(
            level_number=981,
            defaults={'display_name': 'Hub Prog Level 981', 'subject': cls.local_a},
        )
        cls._ensure_level_subject(cls.level_local_a, cls.local_a)

        cls.level_local_b, _ = Level.objects.get_or_create(
            level_number=980,
            defaults={'display_name': 'Hub Prog Level 980', 'subject': cls.local_b},
        )
        cls._ensure_level_subject(cls.level_local_b, cls.local_b)

        # ── Questions ─────────────────────────────────────────────────────
        cls.global_qs = [
            cls._make_question(cls.level_global, school=None, text=f'Global Q{i}')
            for i in range(3)
        ]
        cls.local_a_qs = [
            cls._make_question(cls.level_local_a, school=cls.school_a, text=f'Local A Q{i}')
            for i in range(2)
        ]
        cls.local_b_qs = [
            cls._make_question(cls.level_local_b, school=cls.school_b, text=f'Local B Q{i}')
            for i in range(2)
        ]

        # ── Student ───────────────────────────────────────────────────────
        cls.student = _make_user('hub_prog_student', Role.STUDENT, first_name='Hub')
        SchoolStudent.objects.create(school=cls.school_a, student=cls.student)
        SchoolStudent.objects.create(school=cls.school_b, student=cls.student)

    @classmethod
    def _ensure_level_subject(cls, level, subject):
        if level.subject_id != subject.id:
            Level.objects.filter(pk=level.pk).update(subject=subject)
            level.refresh_from_db()

    @classmethod
    def _make_question(cls, level, school, text):
        q = Question.objects.create(
            level=level, school=school,
            question_text=text,
            question_type='multiple_choice',
            difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text='Correct', is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text='Wrong', is_correct=False, order=2)
        return q

    def _answer(self, student, question, *, is_correct, attempt_id=None):
        """Create a StudentAnswer for (student, question)."""
        return StudentAnswer.objects.create(
            student=student,
            question=question,
            is_correct=is_correct,
            points_earned=question.points if is_correct else 0,
            attempt_id=attempt_id or uuid.uuid4(),
        )

    def tearDown(self):
        # Wipe all StudentAnswers created during each test
        StudentAnswer.objects.filter(student=self.student).delete()


# ===========================================================================
# _compute_subject_progress tests
# ===========================================================================

class ComputeSubjectProgressTests(HubProgressBase):
    """Tests for _compute_subject_progress(user, subject_ids, school=None)."""

    # ── Global-only scenarios ────────────────────────────────────────────

    def test_no_answers_global_returns_zero_progress(self):
        """No StudentAnswers → completed=0, total=3, pct=0."""
        result = _compute_subject_progress(self.student, [self.global_subj.id])
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['completed'], 0)
        self.assertEqual(result['pct'], 0)

    def test_global_progress_two_of_three_correct(self):
        """Answer 2 of 3 global questions correctly → completed=2, pct=67."""
        self._answer(self.student, self.global_qs[0], is_correct=True)
        self._answer(self.student, self.global_qs[1], is_correct=True)
        self._answer(self.student, self.global_qs[2], is_correct=False)

        result = _compute_subject_progress(self.student, [self.global_subj.id])
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['completed'], 2)
        self.assertEqual(result['pct'], 67)

    def test_full_global_completion_returns_100_pct(self):
        """Answer all 3 global questions correctly → pct=100."""
        for q in self.global_qs:
            self._answer(self.student, q, is_correct=True)

        result = _compute_subject_progress(self.student, [self.global_subj.id])
        self.assertEqual(result['pct'], 100)

    def test_only_incorrect_answers_returns_zero_completed(self):
        """All wrong answers → completed=0, regardless of total."""
        for q in self.global_qs:
            self._answer(self.student, q, is_correct=False)

        result = _compute_subject_progress(self.student, [self.global_subj.id])
        self.assertEqual(result['completed'], 0)

    def test_same_question_answered_multiple_times_counts_once(self):
        """Answering the same question correctly in two attempts → completed=1."""
        self._answer(self.student, self.global_qs[0], is_correct=True, attempt_id=uuid.uuid4())
        self._answer(self.student, self.global_qs[0], is_correct=True, attempt_id=uuid.uuid4())

        result = _compute_subject_progress(self.student, [self.global_subj.id])
        self.assertEqual(result['completed'], 1)

    def test_empty_subject_returns_zero_total(self):
        """Subject with no questions at all → total=0, completed=0, pct=0."""
        empty_subj, _ = Subject.objects.get_or_create(
            slug='hub-prog-empty',
            defaults={'name': 'Hub Prog Empty', 'is_active': True},
        )
        result = _compute_subject_progress(self.student, [empty_subj.id])
        self.assertEqual(result, {'completed': 0, 'total': 0, 'pct': 0})

    # ── Local-subject (mixed global + school-local) scenarios ─────────────

    def test_local_a_total_includes_global_plus_local_a(self):
        """For local_a/school_a: total = 3 global + 2 local-A = 5."""
        result = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        self.assertEqual(result['total'], 5)
        self.assertEqual(result['completed'], 0)

    def test_local_b_total_includes_global_plus_local_b(self):
        """For local_b/school_b: total = 3 global + 2 local-B = 5."""
        result = _compute_subject_progress(
            self.student,
            [self.local_b.id, self.global_subj.id],
            school=self.school_b,
        )
        self.assertEqual(result['total'], 5)

    # ── Shared global progress ────────────────────────────────────────────

    def test_global_answers_counted_in_school_a_progress(self):
        """Answering global questions appears in school_a's local progress."""
        self._answer(self.student, self.global_qs[0], is_correct=True)
        self._answer(self.student, self.global_qs[1], is_correct=True)

        result_a = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        self.assertEqual(result_a['completed'], 2)

    def test_global_answers_counted_in_school_b_progress(self):
        """Same global question answers also appear in school_b's local progress.

        This is the core 'shared global progress' behaviour from CPP-151:
        a GlobalQuestion is answered once but reflected in both schools.
        """
        self._answer(self.student, self.global_qs[0], is_correct=True)
        self._answer(self.student, self.global_qs[1], is_correct=True)

        result_b = _compute_subject_progress(
            self.student,
            [self.local_b.id, self.global_subj.id],
            school=self.school_b,
        )
        self.assertEqual(result_b['completed'], 2)  # same 2 global answers count here

    def test_global_progress_not_doubled_across_schools(self):
        """Answering all 3 global questions gives pct=60 (not 100) for a school
        with 5-question total, and completed stays at 3, not 6.
        """
        for q in self.global_qs:
            self._answer(self.student, q, is_correct=True)

        result_a = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        # 3 global correct / 5 total = 60 %
        self.assertEqual(result_a['completed'], 3)
        self.assertEqual(result_a['total'], 5)
        self.assertEqual(result_a['pct'], 60)

    # ── Scoped local progress ─────────────────────────────────────────────

    def test_local_a_questions_counted_for_school_a(self):
        """Answering local-A questions appears in school_a progress."""
        for q in self.local_a_qs:
            self._answer(self.student, q, is_correct=True)

        result_a = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        self.assertEqual(result_a['completed'], 2)

    def test_local_a_questions_not_counted_for_school_b(self):
        """Local-A question answers must NOT bleed into school_b's progress count."""
        for q in self.local_a_qs:
            self._answer(self.student, q, is_correct=True)

        result_b = _compute_subject_progress(
            self.student,
            [self.local_b.id, self.global_subj.id],
            school=self.school_b,
        )
        self.assertEqual(result_b['completed'], 0)  # local-A answers invisible to B

    def test_local_b_questions_not_counted_for_school_a(self):
        """Local-B question answers must NOT bleed into school_a's progress count."""
        for q in self.local_b_qs:
            self._answer(self.student, q, is_correct=True)

        result_a = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        self.assertEqual(result_a['completed'], 0)

    def test_full_progress_school_a_all_correct(self):
        """Answering all global + local-A questions → pct=100 for school_a."""
        for q in self.global_qs + self.local_a_qs:
            self._answer(self.student, q, is_correct=True)

        result_a = _compute_subject_progress(
            self.student,
            [self.local_a.id, self.global_subj.id],
            school=self.school_a,
        )
        self.assertEqual(result_a['pct'], 100)
        self.assertEqual(result_a['completed'], 5)


# ===========================================================================
# _annotate_apps_with_progress tests
# ===========================================================================

class AnnotateAppsWithProgressTests(HubProgressBase):
    """Tests for _annotate_apps_with_progress(apps, user)."""

    def _make_app(self, name, slug, subject):
        return SubjectApp.objects.create(
            name=name, slug=slug,
            subject=subject,
            is_active=True, is_coming_soon=False,
        )

    def test_app_gets_progress_dict_with_correct_keys(self):
        """Each annotated app receives a progress dict with completed/total/pct."""
        app = self._make_app('Prog App', 'prog-app-1', self.global_subj)
        result = _annotate_apps_with_progress([app], self.student)

        self.assertEqual(len(result), 1)
        prog = result[0].progress
        self.assertIn('completed', prog)
        self.assertIn('total', prog)
        self.assertIn('pct', prog)

    def test_app_total_reflects_global_questions(self):
        """App linked to global subject: total = 3 (the 3 global questions)."""
        app = self._make_app('Prog App Total', 'prog-app-total', self.global_subj)
        result = _annotate_apps_with_progress([app], self.student)
        self.assertEqual(result[0].progress['total'], 3)

    def test_app_completed_reflects_answered_questions(self):
        """Answered 1 of 3 global questions → progress.completed = 1."""
        self._answer(self.student, self.global_qs[0], is_correct=True)

        app = self._make_app('Prog App Completed', 'prog-app-comp', self.global_subj)
        result = _annotate_apps_with_progress([app], self.student)
        self.assertEqual(result[0].progress['completed'], 1)

    def test_app_with_no_subject_gets_zero_progress(self):
        """App without subject link → progress = {completed: 0, total: 0, pct: 0}."""
        app = self._make_app('No Subj App', 'prog-app-no-subj', None)
        app.subject = None
        app.subject_id = None
        result = _annotate_apps_with_progress([app], self.student)
        self.assertEqual(result[0].progress, {'completed': 0, 'total': 0, 'pct': 0})

    def test_uses_two_bulk_queries_for_multiple_apps(self):
        """Progress annotation uses exactly 2 DB queries for N apps (no N+1)."""
        apps = [
            self._make_app('Prog Bulk A', 'prog-bulk-a', self.global_subj),
            self._make_app('Prog Bulk B', 'prog-bulk-b', self.local_a),
        ]
        with self.assertNumQueries(2):
            _annotate_apps_with_progress(apps, self.student)

    def test_empty_list_returns_empty_list(self):
        """Empty input → empty output, no crash."""
        result = _annotate_apps_with_progress([], self.student)
        self.assertEqual(result, [])


# ===========================================================================
# SubjectsHubView multi-school display and progress tests
# ===========================================================================

class HubViewMultiSchoolTests(HubProgressBase):
    """Integration tests for SubjectsHubView with multi-school setup.

    These tests verify:
    - All department subjects shown (not just class-enrolled ones).
    - Progress data present on every school subject card.
    - Global subjects not already covered by a school local subject appear in
      global_subjects.
    - Global question answers show in school sections for both schools.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # ── Departments with subjects ─────────────────────────────────────
        from classroom.models import Department, DepartmentSubject

        cls.dept_a = Department.objects.create(
            school=cls.school_a,
            name='Dept A',
            slug='dept-a-hub',
            head=cls.admin,
        )
        DepartmentSubject.objects.create(department=cls.dept_a, subject=cls.local_a)

        cls.dept_b = Department.objects.create(
            school=cls.school_b,
            name='Dept B',
            slug='dept-b-hub',
            head=cls.admin,
        )
        DepartmentSubject.objects.create(department=cls.dept_b, subject=cls.local_b)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student)
        # Clean up answers before each test
        StudentAnswer.objects.filter(student=self.student).delete()

    def _get_hub(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 200)
        return resp

    # ── Display rules ────────────────────────────────────────────────────

    def test_hub_shows_two_school_sections(self):
        """Student enrolled in two schools sees two school_sections."""
        resp = self._get_hub()
        self.assertEqual(len(resp.context['school_sections']), 2)

    def test_school_a_section_contains_local_a_subject(self):
        """local_a appears under school_a's section, not school_b's."""
        resp = self._get_hub()
        sections = {
            s['school'].id: [c['name'] for c in s['subjects']]
            for s in resp.context['school_sections']
        }
        self.assertIn(self.local_a.name, sections.get(self.school_a.id, []))

    def test_school_b_section_contains_local_b_subject(self):
        """local_b appears under school_b's section."""
        resp = self._get_hub()
        sections = {
            s['school'].id: [c['name'] for c in s['subjects']]
            for s in resp.context['school_sections']
        }
        self.assertIn(self.local_b.name, sections.get(self.school_b.id, []))

    def test_hub_subject_shown_without_class_enrollment(self):
        """Subject in a school's department appears in school_sections even if the
        student is not enrolled in any classroom for that subject.
        """
        # student has NO ClassStudent for these subjects — still shown
        resp = self._get_hub()
        all_names = [
            c['name']
            for s in resp.context['school_sections']
            for c in s['subjects']
        ]
        self.assertIn(self.local_a.name, all_names)
        self.assertIn(self.local_b.name, all_names)

    def test_is_enrolled_false_when_no_class_enrollment(self):
        """Cards for subjects without class enrollment have is_enrolled=False."""
        resp = self._get_hub()
        for section in resp.context['school_sections']:
            for card in section['subjects']:
                self.assertFalse(card['is_enrolled'])

    # ── Progress on cards ────────────────────────────────────────────────

    def test_school_subject_cards_have_progress_key(self):
        """Every school subject card carries a 'progress' dict."""
        resp = self._get_hub()
        for section in resp.context['school_sections']:
            for card in section['subjects']:
                self.assertIn('progress', card)
                prog = card['progress']
                self.assertIn('completed', prog)
                self.assertIn('total', prog)
                self.assertIn('pct', prog)

    def test_progress_zero_before_any_answers(self):
        """All cards show 0 completed before the student answers anything."""
        resp = self._get_hub()
        for section in resp.context['school_sections']:
            for card in section['subjects']:
                self.assertEqual(card['progress']['completed'], 0)

    def test_global_answer_appears_in_school_a_progress(self):
        """Answering a global question → school_a card shows completed=1."""
        self._answer(self.student, self.global_qs[0], is_correct=True)

        resp = self._get_hub()
        school_a_section = next(
            s for s in resp.context['school_sections']
            if s['school'].id == self.school_a.id
        )
        card_a = next(
            c for c in school_a_section['subjects']
            if c['name'] == self.local_a.name
        )
        self.assertEqual(card_a['progress']['completed'], 1)

    def test_global_answer_appears_in_school_b_progress(self):
        """Same global answer also reflected in school_b card — shared global progress."""
        self._answer(self.student, self.global_qs[0], is_correct=True)

        resp = self._get_hub()
        school_b_section = next(
            s for s in resp.context['school_sections']
            if s['school'].id == self.school_b.id
        )
        card_b = next(
            c for c in school_b_section['subjects']
            if c['name'] == self.local_b.name
        )
        self.assertEqual(card_b['progress']['completed'], 1)

    def test_global_answer_not_duplicated_in_completed_count(self):
        """Answering 1 global question → completed=1 in both schools, never 2."""
        self._answer(self.student, self.global_qs[0], is_correct=True)

        resp = self._get_hub()
        for section in resp.context['school_sections']:
            for card in section['subjects']:
                self.assertLessEqual(card['progress']['completed'], 1)

    def test_local_a_answer_only_in_school_a_progress(self):
        """Local-A question answered → school_a completed goes up, school_b does not."""
        self._answer(self.student, self.local_a_qs[0], is_correct=True)

        resp = self._get_hub()

        school_a_section = next(
            s for s in resp.context['school_sections']
            if s['school'].id == self.school_a.id
        )
        card_a = next(
            c for c in school_a_section['subjects']
            if c['name'] == self.local_a.name
        )

        school_b_section = next(
            s for s in resp.context['school_sections']
            if s['school'].id == self.school_b.id
        )
        card_b = next(
            c for c in school_b_section['subjects']
            if c['name'] == self.local_b.name
        )

        self.assertEqual(card_a['progress']['completed'], 1)  # local-A counted here
        self.assertEqual(card_b['progress']['completed'], 0)  # NOT here

    def test_global_subjects_context_present(self):
        """global_subjects key is present in context (may be empty list)."""
        resp = self._get_hub()
        self.assertIn('global_subjects', resp.context)

    def test_is_school_student_true(self):
        """Student with STUDENT role → is_school_student=True in context."""
        resp = self._get_hub()
        self.assertTrue(resp.context['is_school_student'])
