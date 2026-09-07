"""
Unit tests for WorksheetBuilderView, WorksheetBuilderQuestionsView,
and WorksheetBuilderSaveView — CPP-282 / CPP-284.

Run with:
    pytest worksheets/tests/test_views_builder.py -v
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolTeacher, Subject, Topic
from maths.models import Answer, Question
from worksheets.models import Worksheet, WorksheetQuestion


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class BuilderTestBase(TestCase):
    """School A + teacher + question bank fixtures."""

    @classmethod
    def setUpTestData(cls):
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER,
            defaults={'display_name': 'Teacher'},
        )
        student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT,
            defaults={'display_name': 'Student'},
        )
        parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT,
            defaults={'display_name': 'Parent'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'},
        )

        # School A owner + teacher
        cls.owner_a = CustomUser.objects.create_user(
            'builder_owner_a', 'builder_owner_a@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner_a.roles.add(owner_role)
        cls.school_a = School.objects.create(
            name='Builder School A', slug='builder-school-a', admin=cls.owner_a,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school_a, teacher=cls.owner_a)

        cls.teacher = CustomUser.objects.create_user(
            'builder_teacher', 'builder_teacher@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.teacher.roles.add(teacher_role)
        SchoolTeacher.objects.get_or_create(school=cls.school_a, teacher=cls.teacher)

        # Student (no builder access)
        cls.student = CustomUser.objects.create_user(
            'builder_student', 'builder_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(student_role)

        # Parent (no builder access)
        cls.parent = CustomUser.objects.create_user(
            'builder_parent', 'builder_parent@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.parent.roles.add(parent_role)

        # School B (for tenant isolation)
        cls.owner_b = CustomUser.objects.create_user(
            'builder_owner_b', 'builder_owner_b@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner_b.roles.add(owner_role)
        cls.school_b = School.objects.create(
            name='Builder School B', slug='builder-school-b', admin=cls.owner_b,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school_b, teacher=cls.owner_b)

        # Curriculum
        cls.subject_maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics'},
        )
        cls.level_y5, _ = Level.objects.get_or_create(
            level_number=5, defaults={'display_name': 'Year 5'},
        )
        cls.level_y6, _ = Level.objects.get_or_create(
            level_number=6, defaults={'display_name': 'Year 6'},
        )
        cls.topic_fractions, _ = Topic.objects.get_or_create(
            subject=cls.subject_maths, name='Fractions',
            defaults={'slug': 'fractions'},
        )
        cls.topic_algebra, _ = Topic.objects.get_or_create(
            subject=cls.subject_maths, name='Algebra',
            defaults={'slug': 'algebra'},
        )

        # Global question (school=None — visible to all)
        cls.q_global = Question.objects.create(
            level=cls.level_y5,
            topic=cls.topic_fractions,
            question_text='Global fraction question',
            question_type='multiple_choice',
            difficulty=1,
            points=1,
        )

        # School A's own question
        cls.q_school_a = Question.objects.create(
            school=cls.school_a,
            level=cls.level_y6,
            topic=cls.topic_algebra,
            question_text='School A algebra question',
            question_type='short_answer',
            difficulty=2,
            points=1,
        )

        # School B's question (should NOT appear for School A teacher)
        cls.q_school_b = Question.objects.create(
            school=cls.school_b,
            level=cls.level_y5,
            topic=cls.topic_fractions,
            question_text='School B private question',
            question_type='multiple_choice',
            difficulty=1,
            points=1,
        )

    def setUp(self):
        self.client.force_login(self.teacher)

    def _questions_url(self, **params):
        url = reverse('worksheets:builder_questions')
        if params:
            qs = '&'.join(f'{k}={v}' for k, v in params.items())
            return f'{url}?{qs}'
        return url


# ---------------------------------------------------------------------------
# WorksheetBuilderView — access control
# ---------------------------------------------------------------------------

class TestBuilderViewAccess(BuilderTestBase):

    def test_builder_view_teacher_can_access(self):
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertEqual(resp.status_code, 200)

    def test_builder_view_owner_can_access(self):
        self.client.force_login(self.owner_a)
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertEqual(resp.status_code, 200)

    def test_builder_view_student_gets_403(self):
        self.client.force_login(self.student)
        resp = self.client.get(reverse('worksheets:builder'))
        # RoleRequiredMixin returns 403; unauthenticated redirects to login
        self.assertIn(resp.status_code, [302, 403])

    def test_builder_view_parent_gets_403(self):
        self.client.force_login(self.parent)
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertIn(resp.status_code, [302, 403])

    def test_builder_view_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertIn(resp.status_code, [302, 403])

    def test_builder_view_context_has_subjects_topics_levels(self):
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertIn('subjects', resp.context)
        self.assertIn('maths_parent_topics', resp.context)
        self.assertIn('levels', resp.context)
        self.assertIn('coding_languages', resp.context)
        self.assertIn('coding_levels', resp.context)
        self.assertIn('question_types', resp.context)


# ---------------------------------------------------------------------------
# WorksheetBuilderQuestionsView — tenant isolation
# ---------------------------------------------------------------------------

class TestBuilderQuestionsViewTenantIsolation(BuilderTestBase):

    def test_global_questions_visible_to_school_a_teacher(self):
        resp = self.client.get(self._questions_url())
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)

    def test_school_a_questions_visible_to_school_a_teacher(self):
        resp = self.client.get(self._questions_url())
        content = resp.content.decode()
        self.assertIn('School A algebra question', content)

    def test_school_b_questions_not_visible_to_school_a_teacher(self):
        resp = self.client.get(self._questions_url())
        content = resp.content.decode()
        self.assertNotIn('School B private question', content)

    def test_school_b_teacher_cannot_see_school_a_questions(self):
        self.client.force_login(self.owner_b)
        resp = self.client.get(self._questions_url())
        content = resp.content.decode()
        self.assertNotIn('School A algebra question', content)
        self.assertIn('Global fraction question', content)


# ---------------------------------------------------------------------------
# WorksheetBuilderQuestionsView — filters
# ---------------------------------------------------------------------------

class TestBuilderQuestionsFilters(BuilderTestBase):

    def test_filter_by_topic(self):
        resp = self.client.get(self._questions_url(topic=self.topic_fractions.pk))
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)
        self.assertNotIn('School A algebra question', content)

    def test_filter_by_level(self):
        resp = self.client.get(self._questions_url(level=5))
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)
        self.assertNotIn('School A algebra question', content)

    def test_filter_by_subject_slug(self):
        resp = self.client.get(self._questions_url(subject='mathematics'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Both maths questions appear
        self.assertIn('Global fraction question', content)

    def test_search_filters_by_question_text(self):
        resp = self.client.get(self._questions_url(q='algebra'))
        content = resp.content.decode()
        self.assertIn('School A algebra question', content)
        self.assertNotIn('Global fraction question', content)

    def test_search_case_insensitive(self):
        resp = self.client.get(self._questions_url(q='FRACTION'))
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)

    def test_filter_by_question_type(self):
        # q_global is multiple_choice, q_school_a is short_answer.
        resp = self.client.get(self._questions_url(question_type='multiple_choice'))
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)
        self.assertNotIn('School A algebra question', content)

    def test_filter_by_question_type_short_answer(self):
        resp = self.client.get(self._questions_url(question_type='short_answer'))
        content = resp.content.decode()
        self.assertIn('School A algebra question', content)
        self.assertNotIn('Global fraction question', content)

    def test_unknown_question_type_yields_no_results(self):
        resp = self.client.get(self._questions_url(question_type='nonexistent'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Global fraction question', content)
        self.assertNotIn('School A algebra question', content)

    def test_invalid_topic_id_ignored(self):
        resp = self.client.get(self._questions_url(topic='not-a-number'))
        self.assertEqual(resp.status_code, 200)

    def test_invalid_level_ignored(self):
        resp = self.client.get(self._questions_url(level='abc'))
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# WorksheetBuilderCascadeView — question-type dropdown OOB swap
# ---------------------------------------------------------------------------

class TestBuilderCascadeQuestionType(BuilderTestBase):

    def _cascade_url(self, **params):
        url = reverse('worksheets:builder_cascade')
        qs = '&'.join(f'{k}={v}' for k, v in params.items())
        return f'{url}?{qs}'

    def test_subject_cascade_renders_maths_question_types(self):
        resp = self.client.get(self._cascade_url(subject='mathematics', step='subject'))
        content = resp.content.decode()
        self.assertIn('filter-qtype-wrapper', content)
        self.assertIn('Calculation', content)  # maths-only type

    def test_subject_cascade_renders_coding_question_types(self):
        resp = self.client.get(self._cascade_url(subject='coding', step='subject'))
        content = resp.content.decode()
        self.assertIn('filter-qtype-wrapper', content)
        self.assertIn('Write Code', content)  # coding-only type


# ---------------------------------------------------------------------------
# WorksheetBuilderQuestionsView — pagination
# ---------------------------------------------------------------------------

class TestBuilderQuestionsPagination(BuilderTestBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Create 30 extra questions to force multiple pages
        for i in range(30):
            Question.objects.create(
                level=cls.level_y5,
                topic=cls.topic_fractions,
                question_text=f'Paginated question {i:02d}',
                question_type='multiple_choice',
                difficulty=1,
                points=1,
            )

    def test_first_page_has_25_results(self):
        resp = self.client.get(self._questions_url())
        page_obj = resp.context['page_obj']
        self.assertEqual(len(page_obj.object_list), 25)

    def test_second_page_accessible(self):
        resp = self.client.get(self._questions_url(page=2))
        self.assertEqual(resp.status_code, 200)
        page_obj = resp.context['page_obj']
        self.assertEqual(page_obj.number, 2)

    def test_invalid_page_falls_back_to_last(self):
        resp = self.client.get(self._questions_url(page=9999))
        self.assertEqual(resp.status_code, 200)

    def test_pagination_links_target_questions_endpoint(self):
        # Regression: pagination must hit the questions endpoint (absolute
        # path) rather than a relative "?page=" that resolves against the
        # builder page URL — which returned the full page and reset filters.
        resp = self.client.get(self._questions_url(subject='mathematics'))
        content = resp.content.decode()
        questions_url = reverse('worksheets:builder_questions')
        self.assertIn(f'hx-get="{questions_url}?page=2', content)
        self.assertNotIn('hx-get="?page=', content)

    def test_pagination_links_preserve_filters(self):
        # Active filters (e.g. subject) must be carried into the pagination
        # link so the next page keeps the same subject/topic/subtopic.
        resp = self.client.get(self._questions_url(subject='mathematics'))
        content = resp.content.decode()
        self.assertIn('subject=mathematics', content)


# ---------------------------------------------------------------------------
# WorksheetBuilderSaveView — CPP-284
# ---------------------------------------------------------------------------

class TestBuilderSaveView(BuilderTestBase):
    """Tests for POST /worksheets/builder/save/"""

    def _save_url(self):
        return reverse('worksheets:builder_save')

    def _valid_payload(self, questions=None):
        if questions is None:
            questions = [{'subject_slug': 'mathematics', 'content_id': self.q_global.pk}]
        return {
            'name': 'Test Worksheet',
            'questions_json': json.dumps(questions),
        }

    # --- Happy path ---

    def test_builder_save_creates_worksheet_and_questions(self):
        payload = self._valid_payload([
            {'subject_slug': 'mathematics', 'content_id': self.q_global.pk},
            {'subject_slug': 'mathematics', 'content_id': self.q_school_a.pk},
        ])
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 200)
        worksheet = Worksheet.objects.get(name='Test Worksheet')
        self.assertEqual(worksheet.school, self.school_a)
        self.assertEqual(worksheet.created_by, self.teacher)
        wqs = WorksheetQuestion.objects.filter(worksheet=worksheet).order_by('order')
        self.assertEqual(wqs.count(), 2)
        self.assertEqual(wqs[0].content_id, self.q_global.pk)
        self.assertEqual(wqs[0].order, 1)
        self.assertEqual(wqs[1].content_id, self.q_school_a.pk)
        self.assertEqual(wqs[1].order, 2)

    def test_builder_save_question_count_refreshed(self):
        payload = self._valid_payload([
            {'subject_slug': 'mathematics', 'content_id': self.q_global.pk},
            {'subject_slug': 'mathematics', 'content_id': self.q_school_a.pk},
        ])
        self.client.post(self._save_url(), payload)
        worksheet = Worksheet.objects.get(name='Test Worksheet')
        self.assertEqual(worksheet.question_count, 2)

    def test_builder_save_redirects_to_detail_via_hx_redirect(self):
        resp = self.client.post(self._save_url(), self._valid_payload())
        self.assertEqual(resp.status_code, 200)
        worksheet = Worksheet.objects.get(name='Test Worksheet')
        expected = reverse('worksheets:detail', args=[worksheet.pk])
        self.assertEqual(resp['HX-Redirect'], expected)

    def test_builder_save_with_level(self):
        payload = self._valid_payload()
        payload['level_id'] = self.level_y5.level_number
        self.client.post(self._save_url(), payload)
        worksheet = Worksheet.objects.get(name='Test Worksheet')
        self.assertEqual(worksheet.level, self.level_y5)

    # --- Validation errors ---

    def test_builder_save_rejects_empty_name(self):
        payload = self._valid_payload()
        payload['name'] = ''
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Worksheet.objects.filter(name='').exists())

    def test_builder_save_rejects_whitespace_name(self):
        payload = self._valid_payload()
        payload['name'] = '   '
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)

    def test_builder_save_rejects_empty_question_list(self):
        payload = {'name': 'Empty', 'questions_json': '[]'}
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Worksheet.objects.filter(name='Empty').exists())

    def test_builder_save_rejects_malformed_json(self):
        payload = {'name': 'Bad JSON', 'questions_json': 'not-json'}
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)

    def test_builder_save_rejects_duplicate_question(self):
        payload = self._valid_payload([
            {'subject_slug': 'mathematics', 'content_id': self.q_global.pk},
            {'subject_slug': 'mathematics', 'content_id': self.q_global.pk},
        ])
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Worksheet.objects.filter(name='Test Worksheet').exists())

    def test_builder_save_rejects_cross_tenant_question(self):
        """Teacher from School A cannot include School B's question."""
        payload = self._valid_payload([
            {'subject_slug': 'mathematics', 'content_id': self.q_school_b.pk},
        ])
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Worksheet.objects.filter(name='Test Worksheet').exists())

    def test_builder_save_rejects_nonexistent_question(self):
        payload = self._valid_payload([
            {'subject_slug': 'mathematics', 'content_id': 999999},
        ])
        resp = self.client.post(self._save_url(), payload)
        self.assertEqual(resp.status_code, 400)

    # --- Access control ---

    def test_builder_save_student_gets_redirect_or_403(self):
        self.client.force_login(self.student)
        resp = self.client.post(self._save_url(), self._valid_payload())
        self.assertIn(resp.status_code, [302, 403])
        self.assertFalse(Worksheet.objects.filter(name='Test Worksheet').exists())

    def test_builder_save_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.post(self._save_url(), self._valid_payload())
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# WorksheetBuilderPreviewView — CPP-285
# ---------------------------------------------------------------------------

class TestBuilderPreviewView(BuilderTestBase):
    """Tests for GET /worksheets/builder/preview/<subject_slug>/<content_id>/"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Add answer options to the global question for preview testing
        cls.answer_correct = Answer.objects.create(
            question=cls.q_global, answer_text='1/2', is_correct=True, order=1,
        )
        cls.answer_wrong = Answer.objects.create(
            question=cls.q_global, answer_text='1/3', is_correct=False, order=2,
        )

    def _preview_url(self, subject_slug='mathematics', content_id=None):
        if content_id is None:
            content_id = self.q_global.pk
        return reverse('worksheets:builder_preview', kwargs={
            'subject_slug': subject_slug,
            'content_id': content_id,
        })

    # --- Happy path ---

    def test_preview_returns_partial(self):
        resp = self.client.get(self._preview_url())
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global fraction question', content)
        self.assertIn('1/2', content)
        self.assertIn('1/3', content)

    def test_preview_shows_correct_answer_highlighted(self):
        resp = self.client.get(self._preview_url())
        content = resp.content.decode()
        self.assertIn('bg-emerald-50', content)

    def test_preview_shows_explanation(self):
        self.q_global.explanation = 'Test explanation text'
        self.q_global.save()
        resp = self.client.get(self._preview_url())
        content = resp.content.decode()
        self.assertIn('Test explanation text', content)
        self.q_global.explanation = ''
        self.q_global.save()

    def test_preview_shows_question_type_badge(self):
        resp = self.client.get(self._preview_url())
        content = resp.content.decode()
        self.assertIn('Multiple Choice', content)

    def test_preview_school_a_question_accessible(self):
        resp = self.client.get(self._preview_url(content_id=self.q_school_a.pk))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('School A algebra question', content)

    # --- Tenant isolation ---

    def test_preview_rejects_cross_tenant_question(self):
        resp = self.client.get(self._preview_url(content_id=self.q_school_b.pk))
        self.assertEqual(resp.status_code, 404)

    def test_preview_nonexistent_question_returns_404(self):
        resp = self.client.get(self._preview_url(content_id=999999))
        self.assertEqual(resp.status_code, 404)

    # --- Access control ---

    def test_preview_student_gets_403(self):
        self.client.force_login(self.student)
        resp = self.client.get(self._preview_url())
        self.assertIn(resp.status_code, [302, 403])

    def test_preview_parent_gets_403(self):
        self.client.force_login(self.parent)
        resp = self.client.get(self._preview_url())
        self.assertIn(resp.status_code, [302, 403])

    def test_preview_owner_can_access(self):
        self.client.force_login(self.owner_a)
        resp = self.client.get(self._preview_url())
        self.assertEqual(resp.status_code, 200)

    def test_preview_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(self._preview_url())
        self.assertIn(resp.status_code, [302, 403])

    def test_preview_invalid_subject_slug_returns_404(self):
        resp = self.client.get(self._preview_url(subject_slug='science'))
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# WorksheetBuilderPreviewView — the live coding window
# ---------------------------------------------------------------------------

class TestBuilderPreviewCodingWindow(BuilderTestBase):
    """Previewing a coding exercise opens the editor-and-console window.

    A teacher building a coding worksheet used to see the starter code as a
    dead <pre>: no way to run the exercise and check it still produces the
    expected output before putting it in front of a class. The preview now
    renders the same window students get, wired to a teacher-only runner.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel

        python = CodingLanguage.objects.create(
            name='Python', slug=CodingLanguage.PYTHON, order=1, is_active=True,
        )
        scratch = CodingLanguage.objects.create(
            name='Scratch', slug=CodingLanguage.SCRATCH, order=2, is_active=True,
        )

        def _exercise(language, slug, **kwargs):
            topic = CodingTopic.objects.create(
                language=language, name=slug.title(), slug=slug, order=1, is_active=True,
            )
            level, _ = TopicLevel.get_or_create_for(topic, TopicLevel.BEGINNER)
            return CodingExercise.objects.create(
                topic_level=level, description='Do the thing.', is_active=True, **kwargs,
            )

        cls.coding_exercise = _exercise(
            python, 'variables',
            title='Print a greeting',
            starter_code='name = "world"\n',
            expected_output='hello world',
            solution_code='print("hello world")\n',
        )
        cls.quiz_exercise = _exercise(
            python, 'quiz-topic',
            title='Which is a list?',
            question_type=CodingExercise.MULTIPLE_CHOICE,
        )
        cls.scratch_exercise = _exercise(
            scratch, 'blocks', title='Move the cat', starter_code='(blocks)',
        )

    def _preview(self, exercise):
        return self.client.get(reverse('worksheets:builder_preview', kwargs={
            'subject_slug': 'coding', 'content_id': exercise.pk,
        }))

    def test_write_code_exercise_renders_the_window(self):
        resp = self._preview(self.coding_exercise)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['has_code_window'])
        content = resp.content.decode()
        self.assertIn('data-code-window', content)
        self.assertIn('cw-editor', content)
        self.assertIn('cw-stdout', content)

    def test_window_runs_against_the_teacher_endpoint(self):
        """Not api_run_code — that one is student-gated and scores submissions."""
        resp = self._preview(self.coding_exercise)
        self.assertEqual(
            resp.context['cw_run_url'], reverse('coding:api_preview_run'),
        )

    def test_window_is_seeded_with_the_starter_code(self):
        resp = self._preview(self.coding_exercise)
        self.assertEqual(resp.context['cw_starter'], 'name = "world"\n')
        self.assertEqual(resp.context['cw_expected_output'], 'hello world')

    def test_solution_is_offered_for_one_click_verification(self):
        resp = self._preview(self.coding_exercise)
        self.assertEqual(resp.context['cw_extra_code'], 'print("hello world")\n')
        self.assertIn('cw-load', resp.content.decode())

    def test_window_ids_are_unique_per_exercise(self):
        """Several previews can be open in one page session; ids must not clash."""
        first = self._preview(self.coding_exercise).context['cw_id']
        second = self._preview(self.quiz_exercise).context.get('cw_id')
        self.assertEqual(first, f'preview-{self.coding_exercise.pk}')
        self.assertIsNone(second)

    def test_quiz_exercise_keeps_the_static_preview(self):
        """Multiple choice has no code to run — an editor would be wrong."""
        resp = self._preview(self.quiz_exercise)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('has_code_window', resp.context.flatten())
        self.assertNotIn('data-code-window', resp.content.decode())

    def test_scratch_exercise_keeps_the_static_preview(self):
        resp = self._preview(self.scratch_exercise)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('data-code-window', content)
        # …and still shows what the exercise carries.
        self.assertIn('(blocks)', content)

    def test_maths_preview_is_unchanged(self):
        """The window is coding-only; a maths question keeps its narrow card."""
        resp = self.client.get(reverse('worksheets:builder_preview', kwargs={
            'subject_slug': 'mathematics', 'content_id': self.q_global.pk,
        }))
        content = resp.content.decode()
        self.assertNotIn('data-code-window', content)
        self.assertIn('max-w-lg', content)

    def test_no_template_comment_leaks_into_the_page(self):
        """Django's {# … #} is single-line only.

        A multi-line one does not comment anything out — it renders as a
        paragraph of prose in the middle of the preview, which is exactly how
        this shipped the first time.
        """
        for exercise in (self.coding_exercise, self.quiz_exercise, self.scratch_exercise):
            content = self._preview(exercise).content.decode()
            for leak in ('{#', '#}', '{%'):
                self.assertNotIn(
                    leak, content,
                    f'unrendered template syntax {leak!r} in the preview of '
                    f'{exercise.title!r}',
                )

    def test_student_cannot_open_the_coding_preview(self):
        self.client.force_login(self.student)
        resp = self._preview(self.coding_exercise)
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# WorksheetBuilderView — assets
# ---------------------------------------------------------------------------

class TestBuilderAssetsAreSelfHosted(BuilderTestBase):
    """The builder must not depend on a third-party CDN to function.

    SortableJS used to be loaded from cdn.jsdelivr.net, and ``Sortable.create``
    runs at the top of the page's IIFE — so any failure to fetch it (blocked
    network, CDN outage) threw before a single handler was bound and the whole
    builder went dead: no adding questions, no search, no save, no error the
    teacher could see. The library is vendored in static/js/ like htmx, Alpine
    and Tailwind already are; this keeps it that way.
    """

    SCRIPT_SRC_RE = re.compile(rb'<script[^>]+src=["\']([^"\']+)["\']')

    def test_builder_page_loads_no_external_scripts(self):
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertEqual(resp.status_code, 200)
        external = [
            src.decode() for src in self.SCRIPT_SRC_RE.findall(resp.content)
            if src.startswith((b'http://', b'https://', b'//'))
        ]
        self.assertEqual(
            external, [],
            'The worksheet builder must serve its JS from static/, not a CDN: '
            + ', '.join(external),
        )

    def test_builder_page_loads_sortable_from_static(self):
        resp = self.client.get(reverse('worksheets:builder'))
        self.assertIn(b'js/sortable.min.js', resp.content)

    def test_vendored_sortable_file_exists_and_is_the_library(self):
        path = Path(settings.BASE_DIR) / 'static' / 'js' / 'sortable.min.js'
        self.assertTrue(path.exists(), f'missing vendored library: {path}')
        head = path.read_text(encoding='utf-8')[:200]
        self.assertIn('Sortable', head)
