"""
test_language_dashboard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive unittest suite for the Language Dashboard (Coding Practice landing page).

Screenshot reference: "Coding Practice — 5 languages available — 4 of 5 started"
View: coding.views.language_selector  →  GET /coding/

Covers:
  1. Authentication guard
  2. Context variables: total_languages, started_count, per-language attributes
  3. Badge labels for all five languages
  4. Topic and exercise count accuracy
  5. "is_started" flag — set when student has at least one submission in that language
  6. Staff bypass — staff never count toward started_count
  7. Edge cases: no topics, no exercises, all started, none started
  8. Log validation via assertLogs (no silent failures)
  9. Data-consistency checks (context matches DB state)
  10. Navigation context (sidebar, template)
"""
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    StudentExerciseSubmission,
    StudentProblemSubmission,
)

User = get_user_model()

URL = reverse('coding:home')   # /coding/


# ===========================================================================
# Shared catalogue builders
# ===========================================================================

def _make_language(slug, name, order, active=True):
    lang, _ = CodingLanguage.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'color': '#000', 'order': order,
                  'is_active': active, 'description': f'{name} language description'},
    )
    return lang


def _make_topic(language, name, slug, order=1):
    return CodingTopic.objects.create(
        language=language, name=name, slug=slug, order=order, is_active=True,
    )


def _make_exercise(topic, title, level=CodingExercise.BEGINNER, order=1):
    return CodingExercise.objects.create(
        topic=topic, level=level, title=title,
        description='Description', starter_code='# code\n',
        order=order, is_active=True,
    )


def _start_language(student, exercise):
    """Create a submission that marks a language as 'started' for the student."""
    StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise,
        code_submitted='print("hi")', is_completed=False,
    )


# ===========================================================================
# 1. Authentication Guard
# ===========================================================================

class TestLanguageSelectorAuth(TestCase):

    def test_unauthenticated_redirects_to_login(self):
        """GET /coding/ without auth must redirect (302) to the login page."""
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'].lower())

    def test_authenticated_student_returns_200(self):
        """An authenticated student must receive a 200 response."""
        user = User.objects.create_user('auth_student', password='pass123', email='auth_student@test.com')
        self.client.force_login(user)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# 2. Context — no progress (fresh student)
# ===========================================================================

class TestLanguageSelectorNoProgress(TestCase):
    """
    Student has no submissions at all.
    Expected: started_count=0, all languages is_started=False.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('fresh_student', password='pass', email='fresh_student@test.com')
        cls.python = _make_language('python', 'Python', 1)
        cls.js = _make_language('javascript', 'JavaScript', 2)
        cls.html = _make_language('html', 'HTML', 3)
        cls.css = _make_language('css', 'CSS', 4)
        cls.scratch = _make_language('scratch', 'Scratch', 5)

        # Each language gets one topic and one exercise so counts are non-zero
        for lang in (cls.python, cls.js, cls.html, cls.css, cls.scratch):
            t = _make_topic(lang, f'{lang.name} Basics', f'{lang.slug}-basics')
            _make_exercise(t, f'{lang.name} Hello World')

    def setUp(self):
        self.client.force_login(self.student)

    def test_total_languages_is_five(self):
        """Dashboard header: '5 languages available'."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_languages'], 5)

    def test_started_count_is_zero(self):
        """With no submissions, started_count must be 0."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 0)

    def test_all_languages_not_started(self):
        """Every language card must have is_started=False for a fresh student."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            self.assertFalse(lang.is_started, f'{lang.slug} should not be started')

    def test_languages_list_length(self):
        """Context 'languages' must contain all five active languages."""
        resp = self.client.get(URL)
        self.assertEqual(len(resp.context['languages']), 5)

    def test_each_language_has_one_topic(self):
        """topic_count attached to each language object must equal 1."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            self.assertEqual(lang.topic_count, 1, f'{lang.slug} topic_count wrong')

    def test_each_language_has_one_exercise(self):
        """exercise_count attached to each language must equal 1."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            self.assertEqual(lang.exercise_count, 1, f'{lang.slug} exercise_count wrong')


# ===========================================================================
# 3. Context — "4 of 5 started"
# ===========================================================================

class TestLanguageSelectorFourOfFiveStarted(TestCase):
    """
    Student has submissions in 4 out of 5 languages.
    Expected: started_count=4, four languages is_started=True, one False.
    Screenshot: "4 of 5 started"
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('prog_student', password='pass', email='prog_student@test.com')
        cls.python = _make_language('python', 'Python', 1)
        cls.js = _make_language('javascript', 'JavaScript', 2)
        cls.html = _make_language('html', 'HTML', 3)
        cls.css = _make_language('css', 'CSS', 4)
        cls.scratch = _make_language('scratch', 'Scratch', 5)

        # Exercises to trigger "started" state
        cls.py_ex = _make_exercise(_make_topic(cls.python, 'Vars', 'py-vars'), 'Hello')
        cls.js_ex = _make_exercise(_make_topic(cls.js, 'Basics', 'js-basics'), 'Intro')
        cls.html_ex = _make_exercise(_make_topic(cls.html, 'Tags', 'html-tags'), 'Page')
        cls.css_ex = _make_exercise(_make_topic(cls.css, 'Selectors', 'css-sel'), 'Style')
        # Scratch: topic exists but no submission → not started
        _make_exercise(_make_topic(cls.scratch, 'Blocks', 'sc-blocks'), 'Move')

        # Start 4 languages by creating a submission each
        for ex in (cls.py_ex, cls.js_ex, cls.html_ex, cls.css_ex):
            _start_language(cls.student, ex)

    def setUp(self):
        self.client.force_login(self.student)

    def test_started_count_is_four(self):
        """Header pill must show '4 of 5 started'."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 4)

    def test_four_languages_is_started_true(self):
        resp = self.client.get(URL)
        started = [l for l in resp.context['languages'] if l.is_started]
        self.assertEqual(len(started), 4)

    def test_scratch_is_not_started(self):
        """Scratch has no submission → is_started must be False."""
        resp = self.client.get(URL)
        scratch_lang = next(l for l in resp.context['languages'] if l.slug == 'scratch')
        self.assertFalse(scratch_lang.is_started)

    def test_python_is_started(self):
        resp = self.client.get(URL)
        py = next(l for l in resp.context['languages'] if l.slug == 'python')
        self.assertTrue(py.is_started)

    def test_total_languages_still_five(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_languages'], 5)


# ===========================================================================
# 4. Context — all languages started
# ===========================================================================

class TestLanguageSelectorAllStarted(TestCase):
    """All 5 languages started → started_count=5."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('all_student', password='pass', email='all_student@test.com')
        slugs = [('python', 'Python'), ('javascript', 'JavaScript'),
                 ('html', 'HTML'), ('css', 'CSS'), ('scratch', 'Scratch')]
        for i, (slug, name) in enumerate(slugs, start=1):
            lang = _make_language(slug, name, i)
            t = _make_topic(lang, f'{name} Basics', f'{slug}-basics-all')
            ex = _make_exercise(t, f'{name} First')
            _start_language(cls.student, ex)

    def setUp(self):
        self.client.force_login(self.student)

    def test_started_count_is_five(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 5)

    def test_all_languages_is_started_true(self):
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            self.assertTrue(lang.is_started, f'{lang.slug} should be started')


class TestLanguageSelectorProgressLinks(TestCase):
    """Landing page must link to each language dashboard from the Coding home screen."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('progress_links', password='pass', email='progress_links@test.com')
        cls.python = _make_language('python', 'Python', 1)
        cls.html = _make_language('html', 'HTML', 2)

    def setUp(self):
        self.client.force_login(self.student)

    def test_language_selector_has_dashboard_links(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('coding:dashboard', args=[self.python.slug]))
        self.assertContains(resp, reverse('coding:dashboard', args=[self.html.slug]))


class TestCodingDashboardView(TestCase):
    """Dashboard returns topic/level progress and problem-solving difficulty stats."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('dashboard_student', password='pass', email='dashboard_student@test.com')
        cls.python = _make_language('python', 'Python', 1)

        cls.topic_a = _make_topic(cls.python, 'Variables', 'variables')
        cls.topic_b = _make_topic(cls.python, 'Loops', 'loops')

        cls.beg_1 = _make_exercise(cls.topic_a, 'Vars 1', CodingExercise.BEGINNER)
        cls.int_1 = _make_exercise(cls.topic_a, 'Vars 2', CodingExercise.INTERMEDIATE)
        cls.adv_1 = _make_exercise(cls.topic_a, 'Vars 3', CodingExercise.ADVANCED)
        cls.beg_2 = _make_exercise(cls.topic_b, 'Loops 1', CodingExercise.BEGINNER)
        cls.int_2 = _make_exercise(cls.topic_b, 'Loops 2', CodingExercise.INTERMEDIATE)

        cls.problem_1 = CodingProblem.objects.create(
            title='Easy Sum', description='Add numbers', difficulty=1, is_active=True, language=cls.python,
        )
        cls.problem_5 = CodingProblem.objects.create(
            title='Tricky Loops', description='Loop puzzle', difficulty=5, is_active=True, language=cls.python,
        )

        StudentExerciseSubmission.objects.create(
            student=cls.student,
            exercise=cls.beg_1,
            code_submitted='print(1)',
            is_completed=True,
        )
        StudentExerciseSubmission.objects.create(
            student=cls.student,
            exercise=cls.int_1,
            code_submitted='print(2)',
            is_completed=False,
        )
        StudentExerciseSubmission.objects.create(
            student=cls.student,
            exercise=cls.beg_2,
            code_submitted='print(3)',
            is_completed=True,
        )

        StudentProblemSubmission.objects.create(
            student=cls.student,
            problem=cls.problem_1,
            code_submitted='print(1)',
            passed_all_tests=True,
            visible_passed=1,
            visible_total=1,
            hidden_passed=0,
            hidden_total=0,
            points=10.0,
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_dashboard_renders(self):
        url = reverse('coding:dashboard', args=[self.python.slug])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('topic_progress', resp.context)
        self.assertIn('difficulty_data', resp.context)

    def test_topic_progress_data_includes_levels(self):
        resp = self.client.get(reverse('coding:dashboard', args=[self.python.slug]))
        topic_data = resp.context['topic_progress']
        self.assertEqual(len(topic_data), 2)
        self.assertEqual(topic_data[0]['levels'][0]['label'], 'Beginner')
        self.assertEqual(topic_data[0]['levels'][0]['completed'], 1)
        self.assertEqual(topic_data[1]['levels'][0]['completed'], 1)

    def test_difficulty_data_counts_problems(self):
        resp = self.client.get(reverse('coding:dashboard', args=[self.python.slug]))
        difficulty_data = resp.context['difficulty_data']
        self.assertEqual(len(difficulty_data), 8)
        self.assertEqual(difficulty_data[0]['total'], 1)
        self.assertEqual(difficulty_data[0]['solved'], 1)
        self.assertEqual(difficulty_data[4]['total'], 1)
        self.assertEqual(difficulty_data[4]['solved'], 0)

class TestLanguageSelectorStaffBypass(TestCase):
    """
    Staff users bypass the started_lang_ids query.
    Their submissions must NOT increment started_count.
    """

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            'staff_dash', password='pass', is_staff=True, is_superuser=True,
            email='staff_dash@test.com',
        )
        lang = _make_language('python', 'Python', 1)
        t = _make_topic(lang, 'Staff Topic', 'staff-topic')
        ex = _make_exercise(t, 'Staff Exercise')
        # Create a submission as staff — must NOT be counted
        StudentExerciseSubmission.objects.create(
            student=cls.staff, exercise=ex,
            code_submitted='pass', is_completed=True,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_staff_started_count_is_zero(self):
        """Staff users always see started_count=0 (the query is skipped for staff)."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 0)

    def test_staff_is_started_all_false(self):
        """Staff users should see no language as 'started'."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            self.assertFalse(lang.is_started)


# ===========================================================================
# 6. Badge labels for all five languages
# ===========================================================================

class TestLanguageSelectorBadgeLabels(TestCase):
    """
    Each language card shows a badge label.
    Expected labels per BADGE_MAP in language_selector view.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('badge_student', password='pass', email='badge_student@test.com')
        _make_language('python', 'Python', 1)
        _make_language('javascript', 'JavaScript', 2)
        _make_language('html', 'HTML', 3)
        _make_language('css', 'CSS', 4)
        _make_language('scratch', 'Scratch', 5)

    def setUp(self):
        self.client.force_login(self.student)
        resp = self.client.get(URL)
        self.langs_by_slug = {l.slug: l for l in resp.context['languages']}

    def test_python_badge_is_beginner_friendly(self):
        self.assertEqual(self.langs_by_slug['python'].badge_label, 'Beginner friendly')
        self.assertEqual(self.langs_by_slug['python'].badge_type, 'starter')

    def test_javascript_badge_is_most_popular(self):
        self.assertEqual(self.langs_by_slug['javascript'].badge_label, 'Most popular')
        self.assertEqual(self.langs_by_slug['javascript'].badge_type, 'popular')

    def test_html_badge_is_great_first_step(self):
        """Screenshot shows 'Great first step' badge on the HTML card."""
        self.assertEqual(self.langs_by_slug['html'].badge_label, 'Great first step')
        self.assertEqual(self.langs_by_slug['html'].badge_type, 'starter')

    def test_css_badge_is_updated(self):
        self.assertEqual(self.langs_by_slug['css'].badge_label, 'Updated')
        self.assertEqual(self.langs_by_slug['css'].badge_type, 'new')

    def test_scratch_badge_is_visual_blocks(self):
        self.assertEqual(self.langs_by_slug['scratch'].badge_label, 'Visual blocks')
        self.assertEqual(self.langs_by_slug['scratch'].badge_type, 'visual')


# ===========================================================================
# 7. Topic and exercise count accuracy
# ===========================================================================

class TestLanguageSelectorCounts(TestCase):
    """
    Verify that topic_count and exercise_count on each language card
    exactly match the active objects in the database.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('count_student', password='pass', email='count_student@test.com')
        cls.python = _make_language('python', 'Python', 1)

        # 3 topics
        t1 = _make_topic(cls.python, 'Variables', 'py-variables-c')
        t2 = _make_topic(cls.python, 'Loops', 'py-loops-c')
        t3 = _make_topic(cls.python, 'Functions', 'py-functions-c')

        # t1: 4 exercises (3 active, 1 inactive)
        _make_exercise(t1, 'Ex1', order=1)
        _make_exercise(t1, 'Ex2', order=2)
        _make_exercise(t1, 'Ex3', order=3)
        CodingExercise.objects.create(
            topic=t1, level=CodingExercise.BEGINNER,
            title='Inactive Ex', description='x', is_active=False, order=4,
        )
        # t2: 2 exercises
        _make_exercise(t2, 'Loop1', order=1)
        _make_exercise(t2, 'Loop2', order=2)
        # t3: 0 exercises

        # One inactive topic (must NOT appear in counts)
        CodingTopic.objects.create(
            language=cls.python, name='Secret', slug='py-secret-c',
            order=99, is_active=False,
        )

    def setUp(self):
        self.client.force_login(self.student)

    def _get_python(self):
        resp = self.client.get(URL)
        return next(l for l in resp.context['languages'] if l.slug == 'python')

    def test_python_topic_count_is_three(self):
        """3 active topics → topic_count=3 (inactive topic excluded)."""
        self.assertEqual(self._get_python().topic_count, 3)

    def test_python_exercise_count_is_five(self):
        """5 active exercises across all topics (inactive excluded)."""
        self.assertEqual(self._get_python().exercise_count, 5)

    def test_inactive_topic_not_counted(self):
        """Inactive topics must not appear in topic_count."""
        total_topics = CodingTopic.objects.filter(language=self.python).count()
        active_topics = CodingTopic.objects.filter(language=self.python, is_active=True).count()
        self.assertGreater(total_topics, active_topics)   # confirm inactive exists
        self.assertEqual(self._get_python().topic_count, active_topics)

    def test_inactive_exercise_not_counted(self):
        """Inactive exercises must not appear in exercise_count."""
        self.assertEqual(self._get_python().exercise_count, 5)   # not 6

    def test_language_with_no_topics_shows_zero(self):
        """A language with zero topics must show topic_count=0 and exercise_count=0."""
        lang_no_topics = _make_language('scratch', 'Scratch', 5)
        resp = self.client.get(URL)
        scratch = next(l for l in resp.context['languages'] if l.slug == 'scratch')
        self.assertEqual(scratch.topic_count, 0)
        self.assertEqual(scratch.exercise_count, 0)


# ===========================================================================
# 8. Inactive language excluded
# ===========================================================================

class TestLanguageSelectorInactiveLanguage(TestCase):
    """Inactive languages must never appear on the dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('inactive_student', password='pass', email='inactive_student@test.com')
        _make_language('python', 'Python', 1, active=True)
        js_lang = _make_language('javascript', 'JavaScript', 2, active=False)
        js_lang.is_active = False
        js_lang.save()
        # Deactivate other seeded languages
        CodingLanguage.objects.filter(slug__in=['html', 'css', 'scratch']).update(is_active=False)

    def setUp(self):
        self.client.force_login(self.student)

    def test_inactive_language_excluded_from_list(self):
        resp = self.client.get(URL)
        slugs = [l.slug for l in resp.context['languages']]
        self.assertNotIn('javascript', slugs)

    def test_total_languages_excludes_inactive(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_languages'], 1)


# ===========================================================================
# 9. Student isolation — two students, independent started counts
# ===========================================================================

class TestLanguageSelectorStudentIsolation(TestCase):
    """Each student must see their own independent started_count."""

    @classmethod
    def setUpTestData(cls):
        cls.studentA = User.objects.create_user('isolate_A', password='pass', email='isolate_a@test.com')
        cls.studentB = User.objects.create_user('isolate_B', password='pass', email='isolate_b@test.com')

        py = _make_language('python', 'Python', 1)
        js = _make_language('javascript', 'JavaScript', 2)
        py_ex = _make_exercise(_make_topic(py, 'Vars', 'py-vars-iso'), 'Hello')
        js_ex = _make_exercise(_make_topic(js, 'Funcs', 'js-funcs-iso'), 'Intro')

        # A started both; B started only Python
        _start_language(cls.studentA, py_ex)
        _start_language(cls.studentA, js_ex)
        _start_language(cls.studentB, py_ex)

    def test_student_a_sees_two_started(self):
        self.client.force_login(self.studentA)
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 2)

    def test_student_b_sees_one_started(self):
        self.client.force_login(self.studentB)
        resp = self.client.get(URL)
        self.assertEqual(resp.context['started_count'], 1)


# ===========================================================================
# 10. Template and sidebar context
# ===========================================================================

class TestLanguageSelectorTemplate(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('tmpl_student', password='pass', email='tmpl_student@test.com')
        _make_language('python', 'Python', 1)

    def setUp(self):
        self.client.force_login(self.student)

    def test_correct_template_used(self):
        resp = self.client.get(URL)
        self.assertTemplateUsed(resp, 'coding/language_selector.html')

    def test_subject_sidebar_is_coding(self):
        """Sidebar context must be 'coding' to highlight the correct nav item."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['subject_sidebar'], 'coding')


# ===========================================================================
# 11. Log validation — no silent failures
# ===========================================================================

class TestLanguageSelectorLogging(TestCase):
    """
    The language_selector view must not emit WARNING or ERROR level logs
    during normal operation. Any errors should surface as exceptions, not
    swallowed silently.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('log_student', password='pass', email='log_student@test.com')
        py = _make_language('python', 'Python', 1)
        t = _make_topic(py, 'Variables', 'py-vars-log')
        _make_exercise(t, 'Hello')

    def setUp(self):
        self.client.force_login(self.student)

    def test_no_warning_logs_during_normal_load(self):
        """Normal load of the language selector must not trigger any WARNING logs."""
        # assertLogs requires at least one log to be emitted; use assertNoLogs (Django 4.1+)
        # Fall back to a manual check for older Django versions.
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                self.client.get(URL)
        else:
            # For older Django, just verify the response is healthy
            resp = self.client.get(URL)
            self.assertEqual(resp.status_code, 200)

    def test_no_error_logs_during_normal_load(self):
        """Normal dashboard load must not emit any ERROR level logs."""
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.ERROR):
                self.client.get(URL)
        else:
            resp = self.client.get(URL)
            self.assertEqual(resp.status_code, 200)

    def test_view_returns_200_with_empty_catalogue(self):
        """Even with no languages in the DB, the view must return 200, not crash."""
        CodingLanguage.objects.all().delete()
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_languages'], 0)
        self.assertEqual(resp.context['started_count'], 0)
        self.assertEqual(len(resp.context['languages']), 0)


# ===========================================================================
# 12. Data-consistency: started_count == len(is_started=True languages)
# ===========================================================================

class TestLanguageSelectorDataConsistency(TestCase):
    """Context values must be internally consistent."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('consist_student', password='pass', email='consist_student@test.com')
        py = _make_language('python', 'Python', 1)
        js = _make_language('javascript', 'JavaScript', 2)
        _make_language('html', 'HTML', 3)   # no submissions → not started

        py_ex = _make_exercise(_make_topic(py, 'Vars', 'py-vars-cons'), 'Hello')
        js_ex = _make_exercise(_make_topic(js, 'Funcs', 'js-funcs-cons'), 'Intro')

        _start_language(cls.student, py_ex)
        _start_language(cls.student, js_ex)

    def setUp(self):
        self.client.force_login(self.student)

    def test_started_count_equals_is_started_true_languages(self):
        """started_count must equal the count of language objects with is_started=True."""
        resp = self.client.get(URL)
        started_count = resp.context['started_count']
        is_started_count = sum(1 for l in resp.context['languages'] if l.is_started)
        self.assertEqual(started_count, is_started_count)

    def test_total_languages_equals_languages_list_length(self):
        """total_languages must equal len(context['languages'])."""
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_languages'], len(resp.context['languages']))

    def test_topic_count_matches_db_query(self):
        """topic_count on each language must match the DB count of active topics."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            db_count = CodingTopic.objects.filter(language=lang, is_active=True).count()
            self.assertEqual(lang.topic_count, db_count,
                             f'{lang.slug} topic_count {lang.topic_count} != DB {db_count}')

    def test_exercise_count_matches_db_query(self):
        """exercise_count on each language must match the DB count of active exercises."""
        resp = self.client.get(URL)
        for lang in resp.context['languages']:
            db_count = CodingExercise.objects.filter(
                topic__language=lang, is_active=True,
            ).count()
            self.assertEqual(lang.exercise_count, db_count,
                             f'{lang.slug} exercise_count mismatch')
