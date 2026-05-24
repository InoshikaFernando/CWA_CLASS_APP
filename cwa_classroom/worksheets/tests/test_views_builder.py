"""
Unit tests for WorksheetBuilderView, WorksheetBuilderQuestionsView,
and WorksheetBuilderSaveView — CPP-282 / CPP-284.

Run with:
    pytest worksheets/tests/test_views_builder.py -v
"""
import json

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

    def test_invalid_topic_id_ignored(self):
        resp = self.client.get(self._questions_url(topic='not-a-number'))
        self.assertEqual(resp.status_code, 200)

    def test_invalid_level_ignored(self):
        resp = self.client.get(self._questions_url(level='abc'))
        self.assertEqual(resp.status_code, 200)


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
