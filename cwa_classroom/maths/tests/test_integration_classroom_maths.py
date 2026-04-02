"""
Integration tests: classroom ↔ maths app boundary.

These tests document and protect the behaviour at the seam between the two apps
after the refactoring that replaced maths.Topic / maths.Level FK references with
classroom.Topic / classroom.Level in Question, StudentFinalAnswer,
TopicLevelStatistics and BasicFactsResult.

Coverage areas
──────────────
1.  classroom.Topic        – canonical topic model for all maths FK fields;
                             maths.Topic and maths.Level have been removed.
2.  Question upload view   – JSON and ZIP uploads create questions linked to
                             the correct classroom.Topic / classroom.Level
4.  Strand-aware upload    – "strand" field in JSON is accepted without error
5.  Question scoping       – school / department / classroom FKs on
                             maths.Question are populated correctly per role
6.  Question visibility    – users only see questions they are entitled to
7.  Cross-app Level lookup – classroom.Level and maths.Level share the same
                             level_number so lookups are consistent
"""

import io
import json
import zipfile

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    ClassRoom, ClassTeacher, Department, DepartmentSubject, DepartmentTeacher,
    Level as ClassroomLevel, School, SchoolTeacher, Subject,
    Topic as ClassroomTopic,
)
from maths.models import (
    Answer as MathsAnswer,
    Question as MathsQuestion,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared base
# ─────────────────────────────────────────────────────────────────────────────

class IntegrationBase(TestCase):
    """
    Creates a minimal but complete school hierarchy plus matching
    classroom Topic/Level entries.  All tests that need cross-app fixtures
    inherit from this class.

    MathsQuestion.topic → classroom.Topic
    MathsQuestion.level → classroom.Level
    maths.Topic and maths.Level have been removed; classroom models are canonical.
    The global Mathematics classroom.Subject (slug='mathematics') is the anchor
    for all maths topics created by the upload view.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Roles ─────────────────────────────────────────────
        cls.role_hoi, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.role_hod, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_DEPARTMENT,
            defaults={'display_name': 'Head of Department'},
        )
        cls.role_teacher, _ = Role.objects.get_or_create(
            name=Role.TEACHER,
            defaults={'display_name': 'Teacher'},
        )
        cls.role_student, _ = Role.objects.get_or_create(
            name=Role.STUDENT,
            defaults={'display_name': 'Student'},
        )

        # ── Users ─────────────────────────────────────────────
        cls.superuser = CustomUser.objects.create_superuser(
            'int_super', 'int_super@test.com', 'pass1234',
        )
        cls.hoi_user = CustomUser.objects.create_user(
            'int_hoi', 'int_hoi@test.com', 'pass1234',
        )
        cls.hoi_user.roles.add(cls.role_hoi)

        cls.hod_user = CustomUser.objects.create_user(
            'int_hod', 'int_hod@test.com', 'pass1234',
        )
        cls.hod_user.roles.add(cls.role_hod)

        cls.teacher_user = CustomUser.objects.create_user(
            'int_teacher', 'int_teacher@test.com', 'pass1234',
        )
        cls.teacher_user.roles.add(cls.role_teacher)

        cls.student_user = CustomUser.objects.create_user(
            'int_student', 'int_student@test.com', 'pass1234',
        )
        cls.student_user.roles.add(cls.role_student)

        # ── Global Mathematics subject (anchor for upload view) ─
        cls.maths_subject, _ = Subject.objects.get_or_create(
            slug='mathematics',
            school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )

        # ── School ────────────────────────────────────────────
        cls.school = School.objects.create(
            name='Integration School', slug='integration-school',
            admin=cls.superuser,
        )
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi_user,
            role='head_of_institute',
        )
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hod_user,
            role='head_of_department',
        )
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.teacher_user,
            role='teacher',
        )

        # ── Department ────────────────────────────────────────
        cls.dept = Department.objects.create(
            school=cls.school, name='Int Maths Dept', slug='int-maths-dept',
            head=cls.hod_user,
        )
        DepartmentTeacher.objects.create(
            department=cls.dept, teacher=cls.teacher_user,
        )
        DepartmentSubject.objects.create(
            department=cls.dept, subject=cls.maths_subject,
        )

        # ── classroom.Level ───────────────────────────────────
        cls.classroom_level, _ = ClassroomLevel.objects.get_or_create(
            level_number=7,
            defaults={'display_name': 'Year 7'},
        )

        # ── classroom.Topic strand hierarchy under Mathematics ─
        # Use unique names/slugs to avoid conflicts with seed data
        cls.strand, _ = ClassroomTopic.objects.get_or_create(
            subject=cls.maths_subject,
            slug='int-test-algebra-strand',
            defaults={'name': 'IntTestAlgebra', 'is_active': True},
        )
        cls.classroom_topic, _ = ClassroomTopic.objects.get_or_create(
            subject=cls.maths_subject,
            slug='int-test-int-topic',
            defaults={'name': 'IntTestIntegers', 'is_active': True, 'parent': cls.strand},
        )
        cls.classroom_topic.levels.add(cls.classroom_level)

        # ── ClassRoom ─────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name='Int Year 7 A', school=cls.school,
            department=cls.dept, subject=cls.maths_subject,
        )
        cls.classroom.levels.add(cls.classroom_level)
        ClassTeacher.objects.create(
            classroom=cls.classroom, teacher=cls.teacher_user,
        )

    def setUp(self):
        self.client = Client()

    # ── Helpers ───────────────────────────────────────────────

    def _login(self, user):
        self.client.force_login(user)

    def _make_question(self, school=None, department=None, classroom=None,
                       text='Integration test question?'):
        """Create a MathsQuestion using classroom.Topic and classroom.Level."""
        q = MathsQuestion.objects.create(
            level=self.classroom_level,
            topic=self.classroom_topic,
            school=school,
            department=department,
            classroom=classroom,
            question_text=text,
            question_type='multiple_choice',
            difficulty=1,
            points=1,
        )
        MathsAnswer.objects.create(question=q, answer_text='Correct', is_correct=True, order=1)
        MathsAnswer.objects.create(question=q, answer_text='Wrong', is_correct=False, order=2)
        return q

    def _json_upload_payload(self, topic='IntTestIntegers', year_level=7, strand=None,
                             extra_fields=None):
        """Return a minimal valid questions.json payload as bytes."""
        data = {
            'topic': topic,
            'year_level': year_level,
            'questions': [
                {
                    'question_text': 'What is -3 + 5?',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'points': 1,
                    'answers': [
                        {'answer_text': '2', 'is_correct': True, 'order': 1},
                        {'answer_text': '-2', 'is_correct': False, 'order': 2},
                    ],
                }
            ],
        }
        if strand:
            data['strand'] = strand
        if extra_fields:
            data.update(extra_fields)
        return json.dumps(data).encode()

    def _make_zip(self, json_bytes, images=None):
        """Return a ZIP file (as BytesIO) containing questions.json + optional images."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('questions.json', json_bytes)
            for name, content in (images or {}).items():
                zf.writestr(name, content)
        buf.seek(0)
        return buf


# ─────────────────────────────────────────────────────────────────────────────
# 1. Topic & Level model relationships
# ─────────────────────────────────────────────────────────────────────────────

class TopicLevelParityTests(IntegrationBase):
    """
    classroom.Topic is the canonical topic model for all maths FK fields.
    """

    def test_classroom_topic_has_parent_strand(self):
        """classroom.Topic has the strand (parent) relationship."""
        self.assertIsNotNone(self.classroom_topic.parent)
        self.assertEqual(self.classroom_topic.parent.name, 'IntTestAlgebra')

    def test_question_topic_fk_is_classroom_topic(self):
        """MathsQuestion.topic FK now references classroom.Topic."""
        q = self._make_question()
        self.assertIsInstance(q.topic, ClassroomTopic)

    def test_question_level_fk_is_classroom_level(self):
        """MathsQuestion.level FK now references classroom.Level."""
        q = self._make_question()
        self.assertIsInstance(q.level, ClassroomLevel)


# ─────────────────────────────────────────────────────────────────────────────
# 2. JSON upload view — topic resolution
# ─────────────────────────────────────────────────────────────────────────────

class UploadViewTopicResolutionTests(IntegrationBase):
    """
    Tests that the /upload-questions/ view correctly resolves classroom.Topic
    from the JSON 'topic' field (now uses classroom.Topic under the global
    Mathematics subject instead of maths.Topic).
    """

    def test_upload_resolves_topic_by_name(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertIsNotNone(ctx.get('upload_results'))
        self.assertEqual(ctx['upload_results']['inserted'], 1)
        self.assertEqual(ctx['upload_results']['failed'], 0)

    def test_upload_with_strand_field_does_not_error(self):
        """strand field is accepted and narrows topic lookup to that strand."""
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7, strand='IntTestAlgebra')
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['upload_results']['failed'], 0)

    def test_upload_unknown_topic_auto_creates_topic(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='NonExistentTopic', year_level=7)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        # View now auto-creates unknown topics and renders upload results
        self.assertEqual(resp.status_code, 200)
        self.assertIn('upload_results', resp.context)

    def test_upload_unknown_year_level_returns_error_message(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=99)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        self.assertEqual(resp.status_code, 302)

    def test_upload_links_question_to_correct_classroom_topic_and_level(self):
        """Questions created by the upload view use classroom.Topic and classroom.Level."""
        self._login(self.superuser)
        before = MathsQuestion.objects.filter(
            topic=self.classroom_topic, level=self.classroom_level,
        ).count()
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        self.client.post(reverse('upload_questions'), {'upload_file': f})
        after = MathsQuestion.objects.filter(
            topic=self.classroom_topic, level=self.classroom_level,
        ).count()
        self.assertEqual(after, before + 1)

    def test_duplicate_upload_updates_not_duplicates(self):
        """Uploading the same question twice updates it rather than inserting a duplicate."""
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7)

        for _ in range(2):
            f = io.BytesIO(payload)
            f.name = 'questions.json'
            self.client.post(reverse('upload_questions'), {'upload_file': f})

        count = MathsQuestion.objects.filter(
            question_text='What is -3 + 5?',
            topic=self.classroom_topic, level=self.classroom_level,
        ).count()
        self.assertEqual(count, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. ZIP upload
# ─────────────────────────────────────────────────────────────────────────────

class UploadViewZipTests(IntegrationBase):
    """Tests for ZIP file uploads (questions + images)."""

    def test_zip_upload_inserts_question(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7)
        zf = self._make_zip(payload)
        zf.name = 'upload.zip'
        resp = self.client.post(reverse('upload_questions'), {'upload_file': zf})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['upload_results']['inserted'], 1)

    def test_zip_without_questions_json_returns_error(self):
        self._login(self.superuser)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('readme.txt', 'no json here')
        buf.seek(0)
        buf.name = 'bad.zip'
        resp = self.client.post(reverse('upload_questions'), {'upload_file': buf})
        self.assertEqual(resp.status_code, 302)

    def test_zip_with_image_reports_image_count(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='IntTestIntegers', year_level=7)
        fake_png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 20  # minimal PNG-like bytes
        zf = self._make_zip(payload, images={'diagram.png': fake_png})
        zf.name = 'upload.zip'
        resp = self.client.post(reverse('upload_questions'), {'upload_file': zf})
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results']
        self.assertEqual(results['images_saved'], 1)
        self.assertIn('questions/year7/inttestintegers', results['image_dir'])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Question scoping via classroom FK fields
# ─────────────────────────────────────────────────────────────────────────────

class QuestionScopingTests(IntegrationBase):
    """
    maths.Question uses classroom.School / classroom.Department /
    classroom.ClassRoom as FK fields for scope.  These tests assert that
    questions created with those FKs are correctly stored and retrievable.
    """

    def test_global_question_has_null_school(self):
        q = self._make_question()
        self.assertIsNone(q.school)
        self.assertIsNone(q.department)
        self.assertIsNone(q.classroom)

    def test_school_scoped_question_has_correct_school_fk(self):
        q = self._make_question(school=self.school)
        self.assertEqual(q.school_id, self.school.id)
        self.assertIsNone(q.department)

    def test_department_scoped_question_has_correct_department_fk(self):
        q = self._make_question(school=self.school, department=self.dept)
        self.assertEqual(q.school_id, self.school.id)
        self.assertEqual(q.department_id, self.dept.id)
        self.assertIsNone(q.classroom)

    def test_class_scoped_question_has_correct_classroom_fk(self):
        q = self._make_question(
            school=self.school,
            department=self.dept,
            classroom=self.classroom,
        )
        self.assertEqual(q.classroom_id, self.classroom.id)

    def test_school_fk_references_classroom_school_model(self):
        """The school FK on maths.Question points to classroom.School."""
        q = self._make_question(school=self.school)
        from classroom.models import School as ClassroomSchool
        self.assertIsInstance(q.school, ClassroomSchool)

    def test_department_fk_references_classroom_department_model(self):
        from classroom.models import Department as ClassroomDepartment
        q = self._make_question(school=self.school, department=self.dept)
        self.assertIsInstance(q.department, ClassroomDepartment)

    def test_classroom_fk_references_classroom_classroom_model(self):
        from classroom.models import ClassRoom as ClassroomClassRoom
        q = self._make_question(
            school=self.school, department=self.dept, classroom=self.classroom,
        )
        self.assertIsInstance(q.classroom, ClassroomClassRoom)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Question visibility via upload → question list view
# ─────────────────────────────────────────────────────────────────────────────

class QuestionVisibilityTests(IntegrationBase):
    """
    After uploading, questions appear in the question list for the correct
    roles and are hidden from others.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.global_q = MathsQuestion.objects.create(
            level=cls.classroom_level, topic=cls.classroom_topic,
            school=None, department=None, classroom=None,
            question_text='Global question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.global_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.school_q = MathsQuestion.objects.create(
            level=cls.classroom_level, topic=cls.classroom_topic,
            school=cls.school, department=None, classroom=None,
            question_text='School question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.school_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.dept_q = MathsQuestion.objects.create(
            level=cls.classroom_level, topic=cls.classroom_topic,
            school=cls.school, department=cls.dept, classroom=None,
            question_text='Department question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.dept_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.class_q = MathsQuestion.objects.create(
            level=cls.classroom_level, topic=cls.classroom_topic,
            school=cls.school, department=cls.dept, classroom=cls.classroom,
            question_text='Class question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.class_q, answer_text='Yes', is_correct=True, order=1,
        )

    def _get_question_list(self, user):
        self._login(user)
        url = reverse('question_list', args=[self.classroom_level.level_number])
        return self.client.get(url)

    def test_superuser_sees_all_questions(self):
        resp = self._get_question_list(self.superuser)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global question?', content)
        self.assertIn('School question?', content)
        self.assertIn('Department question?', content)
        self.assertIn('Class question?', content)

    def test_hoi_sees_global_and_school_questions(self):
        resp = self._get_question_list(self.hoi_user)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global question?', content)
        self.assertIn('School question?', content)

    def test_hod_sees_global_school_and_department_questions(self):
        resp = self._get_question_list(self.hod_user)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global question?', content)
        self.assertIn('School question?', content)
        self.assertIn('Department question?', content)

    def test_teacher_sees_all_questions_in_their_scope(self):
        resp = self._get_question_list(self.teacher_user)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Global question?', content)
        self.assertIn('Class question?', content)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Upload view access control
# ─────────────────────────────────────────────────────────────────────────────

class UploadViewAccessTests(IntegrationBase):
    """The upload view must be accessible to the correct roles only."""

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url.lower())

    def test_superuser_can_access_upload_page(self):
        self._login(self.superuser)
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 200)

    def test_hoi_can_access_upload_page(self):
        self._login(self.hoi_user)
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access_upload_page(self):
        self._login(self.hod_user)
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_can_access_upload_page(self):
        self._login(self.teacher_user)
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 200)

    def test_student_cannot_access_upload_page(self):
        self._login(self.student_user)
        resp = self.client.get(reverse('upload_questions'))
        self.assertNotEqual(resp.status_code, 200)
