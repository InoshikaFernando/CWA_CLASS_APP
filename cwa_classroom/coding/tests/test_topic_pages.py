"""
test_topic_pages.py
~~~~~~~~~~~~~~~~~~~
Comprehensive unittest suite for Topic pages, Level pages, and Exercise list pages.

Screenshot reference:
  - Topic list: "X of Y topics started", "Z exercises completed", "N remaining"
  - Each topic card: title, description, progress "2 / 4", progress bar, "View levels →"
  - Level list: Beginner / Intermediate / Advanced with stars and progress
  - Exercise list: individual exercises with completion status

Views tested:
  - coding.views.topic_list       GET /coding/<lang>/
  - coding.views.level_list       GET /coding/<lang>/topics/<topic>/
  - coding.views.exercise_list    GET /coding/<lang>/topics/<topic>/<level>/

Covers:
  1. Authentication guard for all three views
  2. topic_list: hero stat pills (topics_started, exercises_total, exercises_completed, remaining, pct)
  3. topic_list: per-topic card data (total, completed, pct, is_started, is_complete, colour)
  4. topic_list: partial progress, zero-exercise topics, edge cases
  5. level_list: three levels present, correct metadata (stars, colour, hint)
  6. exercise_list: valid/invalid level, completion marking
  7. Log validation via assertLogs
  8. Data-consistency checks
"""
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    StudentExerciseSubmission,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------

def _lang(slug, name, order=1, active=True):
    lang, _ = CodingLanguage.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'color': '#000', 'order': order,
                  'is_active': active, 'description': f'{name} desc'},
    )
    return lang


def _topic(lang, name, slug, order=1, active=True):
    return CodingTopic.objects.create(
        language=lang, name=name, slug=slug,
        description=f'{name} topic description', order=order, is_active=active,
    )


def _exercise(topic, title, level=CodingExercise.BEGINNER, order=1, active=True):
    topic_level, _ = TopicLevel.get_or_create_for(topic, level)
    return CodingExercise.objects.create(
        topic_level=topic_level, title=title,
        description='Exercise instructions here.',
        starter_code='# start\n', hints='Use print()',
        order=order, is_active=active,
    )


def _complete(student, exercise):
    """Mark an exercise as completed by a student."""
    return StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise,
        code_submitted='print("done")', output_received='done',
        is_completed=True,
    )


def _incomplete(student, exercise):
    """Create an incomplete submission for a student."""
    return StudentExerciseSubmission.objects.create(
        student=student, exercise=exercise,
        code_submitted='# WIP', is_completed=False,
    )


# ===========================================================================
# 1. Authentication guard — all three views
# ===========================================================================

class TestTopicPagesAuth(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang = _lang('python', 'Python')
        topic = _topic(lang, 'Variables', 'auth-variables')
        _exercise(topic, 'Hello World')

    def test_topic_list_unauthenticated_redirects(self):
        resp = self.client.get(reverse('coding:topic_list', args=['python']))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'].lower())

    def test_level_list_unauthenticated_redirects(self):
        resp = self.client.get(reverse('coding:level_list', args=['python', 'auth-variables']))
        self.assertEqual(resp.status_code, 302)

    def test_exercise_list_unauthenticated_redirects(self):
        resp = self.client.get(
            reverse('coding:exercise_list', args=['python', 'auth-variables', 'beginner'])
        )
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# 2. topic_list — hero stat pills, no progress
# ===========================================================================

class TestTopicListNoProgress(TestCase):
    """
    Fresh student, no submissions.
    Expected: topics_started=0, exercises_completed=0, remaining=total.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('tl_fresh', password='pass', email='tl_fresh@test.com')
        cls.lang = _lang('python', 'Python')

        cls.t1 = _topic(cls.lang, 'Variables', 'py-variables-tp')   # 4 exercises
        cls.t2 = _topic(cls.lang, 'Loops', 'py-loops-tp')            # 3 exercises
        cls.t3 = _topic(cls.lang, 'Functions', 'py-functions-tp')    # 2 exercises

        for i in range(4):
            _exercise(cls.t1, f'Var Ex {i}', order=i)
        for i in range(3):
            _exercise(cls.t2, f'Loop Ex {i}', order=i)
        for i in range(2):
            _exercise(cls.t3, f'Func Ex {i}', order=i)

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:topic_list', args=['python'])

    def test_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_correct_template(self):
        self.assertTemplateUsed(self.client.get(self.url), 'coding/topic_list.html')

    def test_topics_started_is_zero(self):
        """Screenshot: '0 of 3 topics started'."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['topics_started'], 0)

    def test_exercises_total(self):
        """9 total active exercises."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['exercises_total'], 9)

    def test_exercises_completed_is_zero(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['exercises_completed'], 0)

    def test_exercises_remaining_equals_total(self):
        """Remaining = total - completed. With 0 completed → remaining == total."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['exercises_remaining'], 9)

    def test_completion_pct_is_zero(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['completion_pct'], 0)

    def test_topic_data_count(self):
        """topic_data list must contain one entry per active topic."""
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context['topic_data']), 3)

    def test_each_topic_pct_is_zero(self):
        resp = self.client.get(self.url)
        for td in resp.context['topic_data']:
            self.assertEqual(td['pct'], 0, f"{td['topic'].name} pct should be 0")
            self.assertFalse(td['is_started'])
            self.assertFalse(td['is_complete'])

    def test_topic_total_counts_correct(self):
        resp = self.client.get(self.url)
        totals = {td['topic'].slug: td['total'] for td in resp.context['topic_data']}
        self.assertEqual(totals['py-variables-tp'], 4)
        self.assertEqual(totals['py-loops-tp'], 3)
        self.assertEqual(totals['py-functions-tp'], 2)


# ===========================================================================
# 3. topic_list — partial progress ("2 of 3 topics started")
# ===========================================================================

class TestTopicListWithProgress(TestCase):
    """
    Student has completed 2 exercises in topic1, 1 in topic2, 0 in topic3.
    Screenshot reference: per-topic progress fractions "2 / 4", "1 / 3", "0 / 2".
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('tl_prog', password='pass', email='tl_prog@test.com')
        cls.lang = _lang('python', 'Python')

        cls.t1 = _topic(cls.lang, 'Variables', 'py-vars-prog')
        cls.t2 = _topic(cls.lang, 'Loops', 'py-loops-prog')
        cls.t3 = _topic(cls.lang, 'Functions', 'py-funcs-prog')

        cls.t1_exs = [_exercise(cls.t1, f'V{i}', order=i) for i in range(4)]
        cls.t2_exs = [_exercise(cls.t2, f'L{i}', order=i) for i in range(3)]
        cls.t3_exs = [_exercise(cls.t3, f'F{i}', order=i) for i in range(2)]

        # Student completes 2 from t1, 1 from t2
        _complete(cls.student, cls.t1_exs[0])
        _complete(cls.student, cls.t1_exs[1])
        _complete(cls.student, cls.t2_exs[0])
        # t3: incomplete (in-progress only, not completed)
        _incomplete(cls.student, cls.t3_exs[0])

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:topic_list', args=['python'])
        self.resp = self.client.get(self.url)
        self.td = {d['topic'].slug: d for d in self.resp.context['topic_data']}

    def test_topics_started_is_two(self):
        """2 topics have at least one completed exercise."""
        self.assertEqual(self.resp.context['topics_started'], 2)

    def test_exercises_completed_is_three(self):
        self.assertEqual(self.resp.context['exercises_completed'], 3)

    def test_exercises_remaining_is_six(self):
        self.assertEqual(self.resp.context['exercises_remaining'], 6)

    def test_completion_pct(self):
        """3 completed / 9 total → 33%."""
        self.assertEqual(self.resp.context['completion_pct'], 33)

    def test_t1_progress_fraction(self):
        """t1: 2 completed / 4 total → 50%."""
        self.assertEqual(self.td['py-vars-prog']['completed'], 2)
        self.assertEqual(self.td['py-vars-prog']['total'], 4)
        self.assertEqual(self.td['py-vars-prog']['pct'], 50)
        self.assertTrue(self.td['py-vars-prog']['is_started'])

    def test_t2_progress_fraction(self):
        """t2: 1 completed / 3 total → 33%."""
        self.assertEqual(self.td['py-loops-prog']['completed'], 1)
        self.assertEqual(self.td['py-loops-prog']['total'], 3)
        self.assertEqual(self.td['py-loops-prog']['pct'], 33)

    def test_t3_not_started(self):
        """t3: 0 completed → is_started=False even if an incomplete submission exists."""
        self.assertEqual(self.td['py-funcs-prog']['completed'], 0)
        self.assertFalse(self.td['py-funcs-prog']['is_started'])

    def test_is_complete_false_when_partial(self):
        """t1 is partially done (2/4) → is_complete must be False."""
        self.assertFalse(self.td['py-vars-prog']['is_complete'])

    def test_is_complete_true_when_all_done(self):
        """When all exercises are done, is_complete must be True."""
        # Complete the remaining t1 exercises
        _complete(self.student, self.t1_exs[2])
        _complete(self.student, self.t1_exs[3])
        resp = self.client.get(self.url)
        td = {d['topic'].slug: d for d in resp.context['topic_data']}
        self.assertTrue(td['py-vars-prog']['is_complete'])


# ===========================================================================
# 4. topic_list — edge cases
# ===========================================================================

class TestTopicListEdgeCases(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('tl_edge', password='pass', email='tl_edge@test.com')
        cls.lang = _lang('python', 'Python')

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:topic_list', args=['python'])

    def test_404_for_invalid_language_slug(self):
        resp = self.client.get(reverse('coding:topic_list', args=['cobol']))
        self.assertEqual(resp.status_code, 404)

    def test_404_for_inactive_language(self):
        lang = _lang('javascript', 'JavaScript', active=False)
        lang.is_active = False
        lang.save()
        resp = self.client.get(reverse('coding:topic_list', args=['javascript']))
        self.assertEqual(resp.status_code, 404)

    def test_empty_topic_list_returns_200(self):
        """Language with no topics must render without errors."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['exercises_total'], 0)
        self.assertEqual(resp.context['topics_started'], 0)
        self.assertEqual(resp.context['completion_pct'], 0)

    def test_topic_with_zero_exercises_shows_zero_pct(self):
        """Topic with no exercises: pct=0, is_complete=False, is_started=False."""
        _topic(self.lang, 'Empty Topic', 'py-empty-edge')
        resp = self.client.get(self.url)
        empty_td = next(
            td for td in resp.context['topic_data']
            if td['topic'].slug == 'py-empty-edge'
        )
        self.assertEqual(empty_td['total'], 0)
        self.assertEqual(empty_td['pct'], 0)
        self.assertFalse(empty_td['is_complete'])

    def test_inactive_topic_excluded_from_topic_data(self):
        """Inactive topics must not appear in topic_data."""
        _topic(self.lang, 'Active Topic', 'py-active-edge', active=True)
        _topic(self.lang, 'Inactive Topic', 'py-inactive-edge', active=False)
        resp = self.client.get(self.url)
        slugs = [td['topic'].slug for td in resp.context['topic_data']]
        self.assertIn('py-active-edge', slugs)
        self.assertNotIn('py-inactive-edge', slugs)

    def test_topic_colour_cycles_through_palette(self):
        """Colours are assigned by index modulo the palette size — none should be blank."""
        for i in range(8):   # more than the 7-colour palette
            _topic(self.lang, f'Topic {i}', f'py-colour-{i}', order=i)
        resp = self.client.get(self.url)
        for td in resp.context['topic_data']:
            self.assertTrue(td['colour'], f"Topic '{td['topic'].name}' has empty colour")

    def test_all_languages_have_topic_pages(self):
        """topic_list must respond 200 for every supported language slug."""
        for slug, name in [
            ('javascript', 'JavaScript'), ('html', 'HTML'),
            ('css', 'CSS'), ('scratch', 'Scratch'),
        ]:
            _lang(slug, name, order=2)
            resp = self.client.get(reverse('coding:topic_list', args=[slug]))
            self.assertEqual(resp.status_code, 200, f'{slug} topic_list returned non-200')


# ===========================================================================
# 5. topic_list — student isolation
# ===========================================================================

class TestTopicListStudentIsolation(TestCase):
    """Student A's completions must not appear in Student B's topic progress."""

    @classmethod
    def setUpTestData(cls):
        cls.studentA = User.objects.create_user('tl_iso_A', password='pass', email='tl_iso_a@test.com')
        cls.studentB = User.objects.create_user('tl_iso_B', password='pass', email='tl_iso_b@test.com')
        lang = _lang('python', 'Python')
        t = _topic(lang, 'Isolation Topic', 'py-isolation')
        cls.ex1 = _exercise(t, 'Ex1', order=1)
        cls.ex2 = _exercise(t, 'Ex2', order=2)
        _complete(cls.studentA, cls.ex1)
        _complete(cls.studentA, cls.ex2)

    def test_student_b_sees_zero_completed(self):
        self.client.force_login(self.studentB)
        resp = self.client.get(reverse('coding:topic_list', args=['python']))
        self.assertEqual(resp.context['exercises_completed'], 0)

    def test_student_a_sees_two_completed(self):
        self.client.force_login(self.studentA)
        resp = self.client.get(reverse('coding:topic_list', args=['python']))
        self.assertEqual(resp.context['exercises_completed'], 2)


# ===========================================================================
# 6. level_list — Beginner / Intermediate / Advanced
# ===========================================================================

class TestLevelListView(TestCase):
    """
    GET /coding/<lang>/topics/<topic>/
    Must show three levels with correct metadata, stars, colours, and progress.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('ll_student', password='pass', email='ll_student@test.com')
        cls.lang = _lang('python', 'Python')
        cls.topic = _topic(cls.lang, 'Variables', 'py-variables-ll')

        # 3 beginner, 2 intermediate, 1 advanced exercises
        cls.beg_exs = [
            _exercise(cls.topic, f'Beg {i}', level=CodingExercise.BEGINNER, order=i)
            for i in range(3)
        ]
        cls.int_exs = [
            _exercise(cls.topic, f'Int {i}', level=CodingExercise.INTERMEDIATE, order=i)
            for i in range(2)
        ]
        cls.adv_exs = [
            _exercise(cls.topic, f'Adv 0', level=CodingExercise.ADVANCED, order=0)
        ]

        # Student completes 2 beginner exercises
        _complete(cls.student, cls.beg_exs[0])
        _complete(cls.student, cls.beg_exs[1])

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:level_list', args=['python', 'py-variables-ll'])
        self.resp = self.client.get(self.url)

    def test_returns_200(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_correct_template(self):
        self.assertTemplateUsed(self.resp, 'coding/level_list.html')

    def test_three_levels_in_context(self):
        """level_data must contain exactly 3 entries: Beginner, Intermediate, Advanced."""
        self.assertEqual(len(self.resp.context['level_data']), 3)

    def test_level_labels_present(self):
        labels = {ld['label'] for ld in self.resp.context['level_data']}
        self.assertEqual(labels, {'Beginner', 'Intermediate', 'Advanced'})

    def test_beginner_stars_is_one(self):
        beg = next(ld for ld in self.resp.context['level_data']
                   if ld['level'] == CodingExercise.BEGINNER)
        self.assertEqual(beg['stars'], 1)
        self.assertEqual(beg['colour'], 'green')

    def test_intermediate_stars_is_two(self):
        interm = next(ld for ld in self.resp.context['level_data']
                      if ld['level'] == CodingExercise.INTERMEDIATE)
        self.assertEqual(interm['stars'], 2)
        self.assertEqual(interm['colour'], 'amber')

    def test_advanced_stars_is_three(self):
        adv = next(ld for ld in self.resp.context['level_data']
                   if ld['level'] == CodingExercise.ADVANCED)
        self.assertEqual(adv['stars'], 3)
        self.assertEqual(adv['colour'], 'rose')

    def test_beginner_completion_count(self):
        beg = next(ld for ld in self.resp.context['level_data']
                   if ld['level'] == CodingExercise.BEGINNER)
        self.assertEqual(beg['completed'], 2)
        self.assertEqual(beg['total'], 3)
        self.assertEqual(beg['pct'], 67)   # round(2/3*100)

    def test_beginner_is_started_true(self):
        beg = next(ld for ld in self.resp.context['level_data']
                   if ld['level'] == CodingExercise.BEGINNER)
        self.assertTrue(beg['is_started'])
        self.assertFalse(beg['is_complete'])   # 2/3 done

    def test_advanced_is_started_false(self):
        adv = next(ld for ld in self.resp.context['level_data']
                   if ld['level'] == CodingExercise.ADVANCED)
        self.assertFalse(adv['is_started'])

    def test_topic_total_and_pct(self):
        """topic_total = 3+2+1=6, completed=2, pct=33."""
        ctx = self.resp.context
        self.assertEqual(ctx['topic_total'], 6)
        self.assertEqual(ctx['topic_completed'], 2)
        self.assertEqual(ctx['topic_pct'], 33)

    def test_level_hints_present(self):
        """Every level must have a non-empty hint string."""
        for ld in self.resp.context['level_data']:
            self.assertTrue(ld['hint'], f"Level {ld['level']} has empty hint")

    def test_404_for_invalid_topic(self):
        resp = self.client.get(
            reverse('coding:level_list', args=['python', 'nonexistent-topic'])
        )
        self.assertEqual(resp.status_code, 404)

    def test_404_for_invalid_language(self):
        resp = self.client.get(
            reverse('coding:level_list', args=['cobol', 'py-variables-ll'])
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# 7. exercise_list — exercises at a specific level
# ===========================================================================

class TestExerciseListView(TestCase):
    """
    GET /coding/<lang>/topics/<topic>/<level>/
    Shows all exercises at a given level with completion flags.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('el_student', password='pass', email='el_student@test.com')
        lang = _lang('python', 'Python')
        cls.topic = _topic(lang, 'Functions', 'py-functions-el')

        cls.beg1 = _exercise(cls.topic, 'Hello World',   level=CodingExercise.BEGINNER,  order=1)
        cls.beg2 = _exercise(cls.topic, 'Print Name',    level=CodingExercise.BEGINNER,  order=2)
        cls.beg3 = _exercise(cls.topic, 'Simple Calc',   level=CodingExercise.BEGINNER,  order=3)
        cls.int1 = _exercise(cls.topic, 'Nested Loops',  level=CodingExercise.INTERMEDIATE, order=1)
        # Inactive beginner — must not appear
        _beg_tl, _ = TopicLevel.get_or_create_for(cls.topic, CodingExercise.BEGINNER)
        CodingExercise.objects.create(
            topic_level=_beg_tl,
            title='Hidden', description='inactive', is_active=False, order=99,
        )
        # Student has completed beg1 only
        _complete(cls.student, cls.beg1)

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:exercise_list', args=['python', 'py-functions-el', 'beginner'])

    def test_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_correct_template(self):
        self.assertTemplateUsed(self.client.get(self.url), 'coding/exercise_list.html')

    def test_shows_three_active_beginner_exercises(self):
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context['exercise_data']), 3)

    def test_completed_exercise_flagged(self):
        """beg1 was completed → exercise_data entry must have completed=True."""
        resp = self.client.get(self.url)
        completed_titles = [
            ed['exercise'].title for ed in resp.context['exercise_data'] if ed['completed']
        ]
        self.assertIn('Hello World', completed_titles)

    def test_uncompleted_exercise_not_flagged(self):
        resp = self.client.get(self.url)
        incomplete = [
            ed['exercise'].title for ed in resp.context['exercise_data'] if not ed['completed']
        ]
        self.assertIn('Print Name', incomplete)
        self.assertIn('Simple Calc', incomplete)

    def test_inactive_exercise_excluded(self):
        resp = self.client.get(self.url)
        titles = [ed['exercise'].title for ed in resp.context['exercise_data']]
        self.assertNotIn('Hidden', titles)

    def test_intermediate_exercises_not_in_beginner_list(self):
        """Beginner endpoint must not serve intermediate exercises."""
        resp = self.client.get(self.url)
        for ed in resp.context['exercise_data']:
            self.assertEqual(ed['exercise'].level, CodingExercise.BEGINNER)

    def test_404_for_invalid_level(self):
        url = reverse('coding:exercise_list', args=['python', 'py-functions-el', 'expert'])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_context_contains_language_topic_level(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['level'], 'beginner')
        self.assertEqual(resp.context['level_label'], 'Beginner')
        self.assertEqual(resp.context['topic'].slug, 'py-functions-el')

    def test_intermediate_level_url_works(self):
        url = reverse('coding:exercise_list', args=['python', 'py-functions-el', 'intermediate'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        titles = [ed['exercise'].title for ed in resp.context['exercise_data']]
        self.assertIn('Nested Loops', titles)


# ===========================================================================
# 8. Scratch-language topic page
# ===========================================================================

class TestScratchTopicList(TestCase):
    """
    Scratch language must work identically to Python for the topic list view.
    Uses Blockly exercises (starter_code is XML, not Python).
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('sc_tl_student', password='pass', email='sc_tl_student@test.com')
        cls.lang = _lang('scratch', 'Scratch')

        cls.t1 = _topic(cls.lang, 'Motion & Looks', 'scratch-motion')
        cls.t2 = _topic(cls.lang, 'Events', 'scratch-events')

        cls.ex1 = _exercise(cls.t1, 'Say Hello')
        cls.ex2 = _exercise(cls.t1, 'Print Name')
        cls.ex3 = _exercise(cls.t2, 'Print a Message')

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('coding:topic_list', args=['scratch'])

    def test_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_scratch_topics_visible(self):
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context['topic_data']), 2)

    def test_scratch_exercises_total(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['exercises_total'], 3)

    def test_scratch_completion_after_submission(self):
        """Completing a Scratch exercise must update the topic progress."""
        _complete(self.student, self.ex1)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['exercises_completed'], 1)
        self.assertEqual(resp.context['topics_started'], 1)


# ===========================================================================
# 9. Log validation — topic_list normal operation
# ===========================================================================

class TestTopicListLogging(TestCase):
    """
    topic_list does not currently emit logs during normal operation.
    Validate that no WARNING/ERROR logs are emitted on happy-path requests,
    ensuring there are no silent failures in the view.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('log_tl', password='pass', email='log_tl@test.com')
        lang = _lang('python', 'Python')
        t = _topic(lang, 'Variables', 'py-vars-log-tl')
        _exercise(t, 'Hello')

    def setUp(self):
        self.client.force_login(self.student)

    def test_no_warning_on_normal_topic_list(self):
        """Happy path must produce no WARNING or above logs."""
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                self.client.get(reverse('coding:topic_list', args=['python']))
        else:
            resp = self.client.get(reverse('coding:topic_list', args=['python']))
            self.assertEqual(resp.status_code, 200)

    def test_no_warning_on_empty_topic_list(self):
        """Language with zero topics must load without warnings."""
        lang = _lang('javascript', 'JavaScript', order=2)
        import django
        if django.VERSION >= (4, 1):
            with self.assertNoLogs('coding.views', level=logging.WARNING):
                resp = self.client.get(reverse('coding:topic_list', args=['javascript']))
            self.assertEqual(resp.status_code, 200)


# ===========================================================================
# 10. Data-consistency checks
# ===========================================================================

class TestTopicListDataConsistency(TestCase):
    """Context values must be internally consistent."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('consist_tl', password='pass', email='consist_tl@test.com')
        lang = _lang('python', 'Python')
        t1 = _topic(lang, 'Variables', 'py-vars-consist')
        t2 = _topic(lang, 'Loops', 'py-loops-consist')
        cls.exs = [_exercise(t1, f'V{i}', order=i) for i in range(3)]
        cls.exs += [_exercise(t2, f'L{i}', order=i) for i in range(2)]
        _complete(cls.student, cls.exs[0])
        _complete(cls.student, cls.exs[1])

    def setUp(self):
        self.client.force_login(self.student)
        self.resp = self.client.get(reverse('coding:topic_list', args=['python']))

    def test_remaining_equals_total_minus_completed(self):
        ctx = self.resp.context
        self.assertEqual(
            ctx['exercises_remaining'],
            ctx['exercises_total'] - ctx['exercises_completed'],
        )

    def test_pct_matches_completed_over_total(self):
        ctx = self.resp.context
        expected = round(ctx['exercises_completed'] / ctx['exercises_total'] * 100)
        self.assertEqual(ctx['completion_pct'], expected)

    def test_topic_data_pct_matches_completed_over_total(self):
        for td in self.resp.context['topic_data']:
            if td['total'] > 0:
                expected = round(td['completed'] / td['total'] * 100)
                self.assertEqual(td['pct'], expected,
                                 f"{td['topic'].name} pct mismatch")

    def test_exercises_total_equals_sum_of_topic_totals(self):
        ctx = self.resp.context
        sum_totals = sum(td['total'] for td in ctx['topic_data'])
        self.assertEqual(ctx['exercises_total'], sum_totals)

    def test_exercises_completed_equals_sum_of_topic_completed(self):
        ctx = self.resp.context
        sum_completed = sum(td['completed'] for td in ctx['topic_data'])
        self.assertEqual(ctx['exercises_completed'], sum_completed)
