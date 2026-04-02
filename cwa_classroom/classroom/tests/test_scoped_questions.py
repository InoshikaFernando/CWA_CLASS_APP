"""Tests for scoped question bank — role-based question creation, listing,
editing, and deletion with scope hierarchy:
  global (superuser) ⊃ school (HoI) ⊃ department (HoD) ⊃ class (teacher).
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentTeacher,
    Subject, Level, ClassRoom, ClassTeacher, Topic as ClassroomTopic,
)
from maths.models import Question as MathsQuestion, Answer as MathsAnswer
from classroom.models import Level as MathsLevel, Topic as MathsTopic
from classroom.views import _get_question_scope, _can_edit_question


class ScopedQuestionTestBase(TestCase):
    """Shared fixtures for scoped-question tests."""

    @classmethod
    def setUpTestData(cls):
        # ── Roles ────────────────────────────────────────────
        cls.role_hoi, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.role_hod, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_DEPARTMENT,
            defaults={'display_name': 'Head of Department'},
        )
        cls.role_teacher, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.role_student, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        # ── Users ────────────────────────────────────────────
        cls.superuser = CustomUser.objects.create_superuser(
            'superadmin', 'super@test.com', 'pass1234',
        )

        cls.hoi_user = CustomUser.objects.create_user(
            'hoi', 'hoi@test.com', 'pass1234',
        )
        cls.hoi_user.roles.add(cls.role_hoi)

        cls.hod_user = CustomUser.objects.create_user(
            'hod', 'hod@test.com', 'pass1234',
        )
        cls.hod_user.roles.add(cls.role_hod)

        cls.teacher_user = CustomUser.objects.create_user(
            'teacher', 'teacher@test.com', 'pass1234',
        )
        cls.teacher_user.roles.add(cls.role_teacher)

        cls.student_user = CustomUser.objects.create_user(
            'student', 'student@test.com', 'pass1234',
        )
        cls.student_user.roles.add(cls.role_student)

        # ── School ───────────────────────────────────────────
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.superuser,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hoi_user, defaults={'role': 'head_of_institute'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hod_user, defaults={'role': 'head_of_department'})
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.teacher_user, defaults={'role': 'teacher'})

        # ── Subject & Department ─────────────────────────────
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.dept = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths',
            head=cls.hod_user,
        )
        DepartmentTeacher.objects.create(
            department=cls.dept, teacher=cls.teacher_user,
        )

        # ── Level (classroom + maths) ────────────────────────
        cls.level, _ = Level.objects.get_or_create(
            level_number=4,
            defaults={'display_name': 'Year 4'},
        )
        cls.maths_level = cls.level  # Same model after unification

        # ── Topic (classroom + maths) ────────────────────────
        cls.classroom_topic = ClassroomTopic.objects.create(
            name='Fractions', subject=cls.subject, is_active=True,
        )
        cls.classroom_topic.levels.add(cls.level)
        cls.maths_topic = cls.classroom_topic  # Same model after unification
        cls.maths_topic.levels.add(cls.maths_level)

        # ── Classroom ────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name='Year 4 Mon', school=cls.school,
            department=cls.dept, subject=cls.subject,
        )
        cls.classroom.levels.add(cls.level)
        ClassTeacher.objects.create(
            classroom=cls.classroom, teacher=cls.teacher_user,
        )

    # ── Helpers ──────────────────────────────────────────────

    def _create_question(self, school=None, department=None, classroom=None,
                         text='Test question?'):
        q = MathsQuestion.objects.create(
            level=self.maths_level, topic=self.maths_topic,
            school=school, department=department, classroom=classroom,
            question_text=text, question_type='multiple_choice',
            difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=q, answer_text='A', is_correct=True, order=1,
        )
        MathsAnswer.objects.create(
            question=q, answer_text='B', is_correct=False, order=2,
        )
        return q

    def _post_question_data(self, extra=None):
        data = {
            'topic': self.classroom_topic.id,
            'question_text': 'What is 1/2 + 1/4?',
            'question_type': 'multiple_choice',
            'difficulty': '1',
            'points': '1',
            'explanation': '',
            'answer_text_1': '3/4',
            'answer_correct_1': 'true',
            'answer_order_1': '1',
            'answer_text_2': '1/2',
            'answer_correct_2': 'false',
            'answer_order_2': '2',
            'answer_text_3': '',
            'answer_correct_3': 'false',
            'answer_order_3': '3',
            'answer_text_4': '',
            'answer_correct_4': 'false',
            'answer_order_4': '4',
        }
        if extra:
            data.update(extra)
        return data


# ─────────────────────────────────────────────────────────────
# 1. _get_question_scope helper
# ─────────────────────────────────────────────────────────────

class GetQuestionScopeTests(ScopedQuestionTestBase):

    def test_superuser_gets_global_scope(self):
        school_id, dept_id, cls_ids = _get_question_scope(self.superuser)
        self.assertIsNone(school_id)
        self.assertIsNone(dept_id)
        self.assertEqual(cls_ids, [])

    def test_hoi_gets_school_scope(self):
        school_id, dept_id, cls_ids = _get_question_scope(self.hoi_user)
        self.assertEqual(school_id, self.school.id)
        self.assertIsNone(dept_id)
        self.assertEqual(cls_ids, [])

    def test_hod_gets_department_scope(self):
        school_id, dept_id, cls_ids = _get_question_scope(self.hod_user)
        self.assertEqual(school_id, self.school.id)
        self.assertEqual(dept_id, self.dept.id)
        self.assertEqual(cls_ids, [])

    def test_teacher_gets_class_scope(self):
        school_id, dept_id, cls_ids = _get_question_scope(self.teacher_user)
        self.assertEqual(school_id, self.school.id)
        self.assertEqual(dept_id, self.dept.id)
        self.assertIn(self.classroom.id, cls_ids)


# ─────────────────────────────────────────────────────────────
# 2. _can_edit_question helper
# ─────────────────────────────────────────────────────────────

class CanEditQuestionTests(ScopedQuestionTestBase):

    def test_superuser_can_edit_global(self):
        q = self._create_question()
        self.assertTrue(_can_edit_question(self.superuser, q))

    def test_superuser_can_edit_any_scope(self):
        q = self._create_question(school=self.school, department=self.dept,
                                  classroom=self.classroom)
        self.assertTrue(_can_edit_question(self.superuser, q))

    def test_hoi_can_edit_school_scoped(self):
        q = self._create_question(school=self.school)
        self.assertTrue(_can_edit_question(self.hoi_user, q))

    def test_hoi_cannot_edit_global(self):
        q = self._create_question()
        self.assertFalse(_can_edit_question(self.hoi_user, q))

    def test_hod_can_edit_department_scoped(self):
        q = self._create_question(school=self.school, department=self.dept)
        self.assertTrue(_can_edit_question(self.hod_user, q))

    def test_hod_cannot_edit_school_scoped(self):
        q = self._create_question(school=self.school)
        self.assertFalse(_can_edit_question(self.hod_user, q))

    def test_teacher_can_edit_class_scoped(self):
        q = self._create_question(school=self.school, department=self.dept,
                                  classroom=self.classroom)
        self.assertTrue(_can_edit_question(self.teacher_user, q))

    def test_teacher_cannot_edit_department_scoped(self):
        q = self._create_question(school=self.school, department=self.dept)
        self.assertFalse(_can_edit_question(self.teacher_user, q))

    def test_teacher_cannot_edit_global(self):
        q = self._create_question()
        self.assertFalse(_can_edit_question(self.teacher_user, q))


# ─────────────────────────────────────────────────────────────
# 3. AddQuestionView — access & scope assignment
# ─────────────────────────────────────────────────────────────

class AddQuestionAccessTests(ScopedQuestionTestBase):

    def test_student_cannot_access(self):
        self.client.login(username='student', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertEqual(resp.status_code, 302)

    def test_teacher_can_access(self):
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        self.client.login(username='hod', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_hoi_can_access(self):
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertEqual(resp.status_code, 200)

    def test_form_shows_classroom_selector_for_teacher(self):
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertContains(resp, 'name="classroom"')
        self.assertContains(resp, self.classroom.name)

    def test_form_hides_classroom_selector_for_hod(self):
        self.client.login(username='hod', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertNotContains(resp, 'name="classroom"')

    def test_form_shows_scope_badge(self):
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(
            reverse('add_question', args=[self.level.level_number]),
        )
        self.assertContains(resp, 'School')


class AddQuestionScopeTests(ScopedQuestionTestBase):

    def test_superuser_creates_global_question(self):
        self.client.login(username='superadmin', password='pass1234')
        self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data(),
        )
        q = MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').first()
        self.assertIsNotNone(q)
        self.assertIsNone(q.school_id)
        self.assertIsNone(q.department_id)
        self.assertIsNone(q.classroom_id)

    def test_hoi_creates_school_scoped_question(self):
        self.client.login(username='hoi', password='pass1234')
        self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data(),
        )
        q = MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.school_id, self.school.id)
        self.assertIsNone(q.department_id)
        self.assertIsNone(q.classroom_id)

    def test_hod_creates_department_scoped_question(self):
        self.client.login(username='hod', password='pass1234')
        self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data(),
        )
        q = MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.school_id, self.school.id)
        self.assertEqual(q.department_id, self.dept.id)
        self.assertIsNone(q.classroom_id)

    def test_teacher_creates_class_scoped_question(self):
        self.client.login(username='teacher', password='pass1234')
        self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data({'classroom': self.classroom.id}),
        )
        q = MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.school_id, self.school.id)
        self.assertEqual(q.department_id, self.dept.id)
        self.assertEqual(q.classroom_id, self.classroom.id)

    def test_teacher_must_select_classroom(self):
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data(),  # no classroom
        )
        # Should re-render form with error, not redirect
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').count(),
            0,
        )

    def test_teacher_cannot_use_invalid_classroom(self):
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data({'classroom': 99999}),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').count(),
            0,
        )

    def test_answers_are_created(self):
        self.client.login(username='hoi', password='pass1234')
        self.client.post(
            reverse('add_question', args=[self.level.level_number]),
            self._post_question_data(),
        )
        q = MathsQuestion.objects.filter(question_text='What is 1/2 + 1/4?').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.answers.count(), 2)
        self.assertTrue(q.answers.filter(answer_text='3/4', is_correct=True).exists())


# ─────────────────────────────────────────────────────────────
# 4. QuestionListView — scoped filtering
# ─────────────────────────────────────────────────────────────

class QuestionListScopeTests(ScopedQuestionTestBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.q_global = cls._create_question_cls(text='Global Q')
        cls.q_school = cls._create_question_cls(
            school=cls.school, text='School Q',
        )
        cls.q_dept = cls._create_question_cls(
            school=cls.school, department=cls.dept, text='Dept Q',
        )
        cls.q_class = cls._create_question_cls(
            school=cls.school, department=cls.dept,
            classroom=cls.classroom, text='Class Q',
        )

    @classmethod
    def _create_question_cls(cls, school=None, department=None,
                             classroom=None, text='Q'):
        q = MathsQuestion.objects.create(
            level=cls.maths_level, topic=cls.maths_topic,
            school=school, department=department, classroom=classroom,
            question_text=text, question_type='multiple_choice',
            difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=q, answer_text='A', is_correct=True, order=1,
        )
        return q

    def test_hoi_sees_global_and_all_school_questions(self):
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(
            reverse('question_list', args=[self.level.level_number]),
        )
        self.assertContains(resp, 'Global Q')
        self.assertContains(resp, 'School Q')
        self.assertContains(resp, 'Dept Q')
        self.assertContains(resp, 'Class Q')

    def test_hod_sees_global_school_and_dept_questions(self):
        self.client.login(username='hod', password='pass1234')
        resp = self.client.get(
            reverse('question_list', args=[self.level.level_number]),
        )
        self.assertContains(resp, 'Global Q')
        self.assertContains(resp, 'School Q')
        self.assertContains(resp, 'Dept Q')
        # HoD should NOT see class-scoped questions
        self.assertNotContains(resp, 'Class Q')

    def test_teacher_sees_global_school_dept_and_class_questions(self):
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.get(
            reverse('question_list', args=[self.level.level_number]),
        )
        self.assertContains(resp, 'Global Q')
        self.assertContains(resp, 'School Q')
        self.assertContains(resp, 'Dept Q')
        self.assertContains(resp, 'Class Q')

    def test_scope_badges_render(self):
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(
            reverse('question_list', args=[self.level.level_number]),
        )
        content = resp.content.decode()
        self.assertIn('Global', content)
        self.assertIn('School', content)
        self.assertIn('Dept', content)
        self.assertIn('Class', content)


# ─────────────────────────────────────────────────────────────
# 5. EditQuestionView — scope-based permissions
# ─────────────────────────────────────────────────────────────

class EditQuestionPermissionTests(ScopedQuestionTestBase):

    def test_hoi_can_edit_school_question(self):
        q = self._create_question(school=self.school, text='School edit me')
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(reverse('edit_question', args=[q.id]))
        self.assertEqual(resp.status_code, 200)

    def test_hoi_cannot_edit_global_question(self):
        q = self._create_question(text='Global no edit')
        self.client.login(username='hoi', password='pass1234')
        resp = self.client.get(reverse('edit_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)

    def test_teacher_can_edit_class_question(self):
        q = self._create_question(
            school=self.school, department=self.dept,
            classroom=self.classroom, text='Class edit me',
        )
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.get(reverse('edit_question', args=[q.id]))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_cannot_edit_dept_question(self):
        q = self._create_question(
            school=self.school, department=self.dept,
            text='Dept no edit',
        )
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.get(reverse('edit_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)


# ─────────────────────────────────────────────────────────────
# 6. DeleteQuestionView — scope-based permissions
# ─────────────────────────────────────────────────────────────

class DeleteQuestionPermissionTests(ScopedQuestionTestBase):

    def test_hod_can_delete_dept_question(self):
        q = self._create_question(
            school=self.school, department=self.dept, text='Dept del me',
        )
        self.client.login(username='hod', password='pass1234')
        resp = self.client.post(reverse('delete_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(MathsQuestion.objects.filter(id=q.id).exists())

    def test_teacher_cannot_delete_dept_question(self):
        q = self._create_question(
            school=self.school, department=self.dept, text='Dept no del',
        )
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.post(reverse('delete_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(MathsQuestion.objects.filter(id=q.id).exists())

    def test_teacher_can_delete_own_class_question(self):
        q = self._create_question(
            school=self.school, department=self.dept,
            classroom=self.classroom, text='Class del me',
        )
        self.client.login(username='teacher', password='pass1234')
        resp = self.client.post(reverse('delete_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(MathsQuestion.objects.filter(id=q.id).exists())

    def test_student_cannot_delete(self):
        q = self._create_question(school=self.school, text='No del')
        self.client.login(username='student', password='pass1234')
        resp = self.client.post(reverse('delete_question', args=[q.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(MathsQuestion.objects.filter(id=q.id).exists())
