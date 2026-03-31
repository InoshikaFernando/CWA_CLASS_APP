"""Tests for hub helper functions in classroom/views.py.

Covers:
  - _subject_has_questions(subj, school=None)
  - _annotate_apps_with_questions(apps)

Both helpers determine whether maths questions are accessible for a given
subject, used to decide whether hub app cards are clickable.
"""
from django.test import TestCase

from classroom.models import Level, School, Subject, SubjectApp
from classroom.views import _annotate_apps_with_questions, _subject_has_questions
from maths.models import Answer, Question


# ---------------------------------------------------------------------------
# Shared base fixture
# ---------------------------------------------------------------------------

class HubQuestionGateTestBase(TestCase):
    """Shared fixtures for hub question gate tests.

    Creates two schools, two subjects (one global, one school-local), and
    dedicated Level rows using high numbers (995-999) to avoid clashing with
    other test classes.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser

        # ── Admin user ─────────────────────────────────────────
        cls.admin = CustomUser.objects.create_superuser(
            'hubadmin', 'hubadmin@test.com', 'pass1234',
        )

        # ── Schools ────────────────────────────────────────────
        cls.school_a = School.objects.create(
            name='Hub School A', slug='hub-school-a', admin=cls.admin,
        )
        cls.school_b = School.objects.create(
            name='Hub School B', slug='hub-school-b', admin=cls.admin,
        )

        # ── Global subject (school=NULL) ───────────────────────
        cls.global_subject, _ = Subject.objects.get_or_create(
            slug='hub-maths-global',
            defaults={'name': 'Hub Maths Global', 'is_active': True},
        )

        # ── School-local subject (belongs to school_a) ─────────
        cls.local_subject = Subject.objects.create(
            name='Hub Maths Local', slug='hub-maths-local',
            school=cls.school_a, is_active=True,
        )

        # ── Levels ─────────────────────────────────────────────
        cls.level_global, _ = Level.objects.get_or_create(
            level_number=995,
            defaults={'display_name': 'Hub Level 995', 'subject': cls.global_subject},
        )
        # Ensure subject FK is set (get_or_create may have found an existing row)
        if cls.level_global.subject_id != cls.global_subject.id:
            Level.objects.filter(pk=cls.level_global.pk).update(subject=cls.global_subject)
            cls.level_global.refresh_from_db()

        cls.level_local, _ = Level.objects.get_or_create(
            level_number=994,
            defaults={'display_name': 'Hub Level 994', 'subject': cls.local_subject},
        )
        if cls.level_local.subject_id != cls.local_subject.id:
            Level.objects.filter(pk=cls.level_local.pk).update(subject=cls.local_subject)
            cls.level_local.refresh_from_db()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _create_question(self, level, school=None, text='Test?'):
        """Create a Question with one correct Answer. Returns the Question."""
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

    def _create_app(self, name, slug, subject=None):
        """Create a SubjectApp (is_active=False, is_coming_soon=True defaults)."""
        return SubjectApp.objects.create(
            name=name,
            slug=slug,
            subject=subject,
            is_active=False,
            is_coming_soon=True,
        )


# ---------------------------------------------------------------------------
# 2a. _subject_has_questions tests
# ---------------------------------------------------------------------------

class SubjectHasQuestionsTests(HubQuestionGateTestBase):
    """Tests for _subject_has_questions(subj, school=None)."""

    def test_global_subject_with_global_questions_and_no_school(self):
        """Global subject + global question, school=None → True."""
        self._create_question(self.level_global, school=None, text='SHQ global 1')

        result = _subject_has_questions(self.global_subject, school=None)
        self.assertTrue(result)

    def test_global_subject_with_no_questions_and_no_school(self):
        """Global subject with no questions at all, school=None → False."""
        # Use a fresh level with no questions
        fresh_subj, _ = Subject.objects.get_or_create(
            slug='shq-empty-global',
            defaults={'name': 'SHQ Empty Global', 'is_active': True},
        )
        result = _subject_has_questions(fresh_subj, school=None)
        self.assertFalse(result)

    def test_school_subject_with_local_questions_returns_true(self):
        """School subject with local (school-scoped) questions → True for that school."""
        self._create_question(
            self.level_local, school=self.school_a, text='SHQ local only',
        )

        result = _subject_has_questions(self.local_subject, school=self.school_a)
        self.assertTrue(result)

    def test_school_subject_with_global_questions_returns_true(self):
        """School subject with only global questions → True for school student (globals visible)."""
        # Create a level linked to local_subject but question is global (school=None)
        self._create_question(self.level_local, school=None, text='SHQ global visible')

        result = _subject_has_questions(self.local_subject, school=self.school_a)
        self.assertTrue(result)

    def test_school_subject_with_both_local_and_global_returns_true(self):
        """School subject with both local and global questions → True."""
        self._create_question(
            self.level_local, school=self.school_a, text='SHQ both local',
        )
        self._create_question(
            self.level_local, school=None, text='SHQ both global',
        )

        result = _subject_has_questions(self.local_subject, school=self.school_a)
        self.assertTrue(result)

    def test_school_subject_with_no_questions_returns_false(self):
        """School subject with no questions for this school → False."""
        fresh_subj = Subject.objects.create(
            name='SHQ No Qs Local', slug='shq-no-qs-local',
            school=self.school_a, is_active=True,
        )
        result = _subject_has_questions(fresh_subj, school=self.school_a)
        self.assertFalse(result)

    def test_school_subject_questions_for_different_school_returns_false(self):
        """Questions exist for School B only; school=school_a → False."""
        # Create a new subject + level scoped to school_b only
        subj_b = Subject.objects.create(
            name='SHQ School B', slug='shq-school-b',
            school=self.school_b, is_active=True,
        )
        level_b, _ = Level.objects.get_or_create(
            level_number=993,
            defaults={'display_name': 'Hub Level 993', 'subject': subj_b},
        )
        if level_b.subject_id != subj_b.id:
            Level.objects.filter(pk=level_b.pk).update(subject=subj_b)
            level_b.refresh_from_db()

        self._create_question(level_b, school=self.school_b, text='SHQ B only')

        # school_a student should not see these
        result = _subject_has_questions(subj_b, school=self.school_a)
        self.assertFalse(result)

    def test_school_subject_questions_for_different_school_but_global_visible(self):
        """Questions for School B + global question; school=school_a → True (global visible)."""
        subj_mixed = Subject.objects.create(
            name='SHQ Mixed', slug='shq-mixed',
            school=self.school_b, is_active=True,
        )
        level_mixed, _ = Level.objects.get_or_create(
            level_number=992,
            defaults={'display_name': 'Hub Level 992', 'subject': subj_mixed},
        )
        if level_mixed.subject_id != subj_mixed.id:
            Level.objects.filter(pk=level_mixed.pk).update(subject=subj_mixed)
            level_mixed.refresh_from_db()

        self._create_question(level_mixed, school=self.school_b, text='SHQ mixed B')
        self._create_question(level_mixed, school=None, text='SHQ mixed global')

        # school_a can see the global question
        result = _subject_has_questions(subj_mixed, school=self.school_a)
        self.assertTrue(result)

    def test_global_subject_id_expansion_finds_global_questions(self):
        """Subject with global_subject_id set — questions on global subject are found."""
        # Create a school subject that points to global_subject as its global counterpart
        school_variant = Subject.objects.create(
            name='SHQ Variant', slug='shq-variant',
            school=self.school_a, is_active=True,
            global_subject=self.global_subject,
        )
        # Add a global question to the global subject's level
        self._create_question(self.level_global, school=None, text='SHQ variant global')

        # The variant has no levels of its own, but global_subject_id expansion should
        # find questions through the global subject
        result = _subject_has_questions(school_variant, school=self.school_a)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# 2b. _annotate_apps_with_questions tests
# ---------------------------------------------------------------------------

class AnnotateAppsWithQuestionsTests(HubQuestionGateTestBase):
    """Tests for _annotate_apps_with_questions(apps)."""

    def test_app_with_global_questions_gets_has_questions_true(self):
        """App linked to a subject with global questions → has_questions=True."""
        self._create_question(self.level_global, school=None, text='AAQ global')

        app = self._create_app('AAQ Global App', 'aaq-global-app', subject=self.global_subject)
        result = _annotate_apps_with_questions([app])

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].has_questions)

    def test_app_with_no_questions_gets_has_questions_false(self):
        """App linked to subject with no questions → has_questions=False."""
        empty_subj, _ = Subject.objects.get_or_create(
            slug='aaq-empty-subj',
            defaults={'name': 'AAQ Empty Subject', 'is_active': True},
        )
        app = self._create_app('AAQ No Q App', 'aaq-no-q-app', subject=empty_subj)
        result = _annotate_apps_with_questions([app])

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].has_questions)

    def test_app_with_only_local_questions_gets_has_questions_false(self):
        """App linked to subject with ONLY school-scoped questions → has_questions=False.

        _annotate_apps_with_questions only checks global (school=None) questions.
        """
        self._create_question(
            self.level_local, school=self.school_a, text='AAQ local only',
        )

        app = self._create_app('AAQ Local App', 'aaq-local-app', subject=self.local_subject)
        result = _annotate_apps_with_questions([app])

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].has_questions)

    def test_app_with_no_subject_gets_has_questions_false(self):
        """App with subject_id=None → has_questions=False."""
        app = self._create_app('AAQ No Subject', 'aaq-no-subject', subject=None)
        result = _annotate_apps_with_questions([app])

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].has_questions)

    def test_multiple_apps_only_those_with_global_questions_get_true(self):
        """Multiple apps: only those with global questions receive has_questions=True."""
        self._create_question(self.level_global, school=None, text='AAQ multi global')

        empty_subj, _ = Subject.objects.get_or_create(
            slug='aaq-multi-empty',
            defaults={'name': 'AAQ Multi Empty', 'is_active': True},
        )

        app_with_q = self._create_app(
            'AAQ Multi With Q', 'aaq-multi-with-q', subject=self.global_subject,
        )
        app_without_q = self._create_app(
            'AAQ Multi Without Q', 'aaq-multi-without-q', subject=empty_subj,
        )
        app_no_subj = self._create_app('AAQ Multi No Subj', 'aaq-multi-no-subj', subject=None)

        result = _annotate_apps_with_questions([app_with_q, app_without_q, app_no_subj])

        self.assertEqual(len(result), 3)
        has_q_map = {app.id: app.has_questions for app in result}
        self.assertTrue(has_q_map[app_with_q.id])
        self.assertFalse(has_q_map[app_without_q.id])
        self.assertFalse(has_q_map[app_no_subj.id])

    def test_empty_list_returns_empty_list(self):
        """Empty input list → empty output list, no crash."""
        result = _annotate_apps_with_questions([])
        self.assertEqual(result, [])

    def test_single_query_used_for_multiple_apps(self):
        """_annotate_apps_with_questions uses exactly 1 DB query regardless of app count.

        Verifies there is no N+1 query problem.
        """
        self._create_question(self.level_global, school=None, text='AAQ n+1 global')

        subj2, _ = Subject.objects.get_or_create(
            slug='aaq-n1-subj2',
            defaults={'name': 'AAQ N+1 Subj2', 'is_active': True},
        )
        subj3, _ = Subject.objects.get_or_create(
            slug='aaq-n1-subj3',
            defaults={'name': 'AAQ N+1 Subj3', 'is_active': True},
        )

        apps = [
            self._create_app('AAQ N1 App1', 'aaq-n1-app1', subject=self.global_subject),
            self._create_app('AAQ N1 App2', 'aaq-n1-app2', subject=subj2),
            self._create_app('AAQ N1 App3', 'aaq-n1-app3', subject=subj3),
        ]

        with self.assertNumQueries(1):
            result = _annotate_apps_with_questions(apps)

        self.assertEqual(len(result), 3)
