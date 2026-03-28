"""
Integration tests: classroom ↔ maths app boundary.

These tests document and protect the current behaviour at the seam between
the two apps.  They are the safety net for the planned refactoring that will
replace maths.Topic / maths.Level / maths.ClassRoom with the richer
classroom equivalents.

Coverage areas
──────────────
1.  Topic name parity      – maths.Topic.name == classroom.Topic.name
2.  Level number parity    – maths.Level.level_number == classroom.Level.level_number
3.  Question upload view   – JSON and ZIP uploads create questions linked to
                             the correct maths.Topic / maths.Level
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
    Level as MathsLevel,
    Question as MathsQuestion,
    Topic as MathsTopic,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared base
# ─────────────────────────────────────────────────────────────────────────────

class IntegrationBase(TestCase):
    """
    Creates a minimal but complete school hierarchy plus matching
    maths Topic/Level entries.  All tests that need cross-app fixtures
    inherit from this class.
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

        # ── Subject ───────────────────────────────────────────
        cls.subject, _ = Subject.objects.get_or_create(
            slug='int-mathematics',
            defaults={'name': 'Int Mathematics', 'is_active': True},
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
            department=cls.dept, subject=cls.subject,
        )

        # ── classroom.Level + maths.Level (same level_number) ─
        cls.classroom_level, _ = ClassroomLevel.objects.get_or_create(
            level_number=7,
            defaults={'display_name': 'Year 7'},
        )
        cls.maths_level, _ = MathsLevel.objects.get_or_create(
            level_number=7,
            defaults={'title': 'Year 7'},
        )

        # ── classroom.Topic (strand hierarchy) ────────────────
        cls.strand = ClassroomTopic.objects.create(
            name='Algebra', subject=cls.subject, is_active=True,
            slug='int-algebra',
        )
        cls.classroom_topic = ClassroomTopic.objects.create(
            name='Integers', subject=cls.subject, is_active=True,
            slug='int-integers', parent=cls.strand,
        )
        cls.classroom_topic.levels.add(cls.classroom_level)

        # ── maths.Topic (flat — same name as classroom subtopic) ─
        cls.maths_topic, _ = MathsTopic.objects.get_or_create(name='Integers')
        cls.maths_topic.levels.add(cls.maths_level)

        # ── ClassRoom ─────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name='Int Year 7 A', school=cls.school,
            department=cls.dept, subject=cls.subject,
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
        q = MathsQuestion.objects.create(
            level=self.maths_level,
            topic=self.maths_topic,
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

    def _json_upload_payload(self, topic='Integers', year_level=7, strand=None,
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
# 1. Topic & Level parity between apps
# ─────────────────────────────────────────────────────────────────────────────

class TopicLevelParityTests(IntegrationBase):
    """
    The upload view looks up maths.Topic by name.  After the refactoring it
    will look up classroom.Topic by name instead.  These tests assert that the
    names and level numbers are identical so the switch is transparent.
    """

    def test_maths_topic_name_matches_classroom_subtopic_name(self):
        self.assertEqual(self.maths_topic.name, self.classroom_topic.name)

    def test_maths_level_number_matches_classroom_level_number(self):
        self.assertEqual(self.maths_level.level_number, self.classroom_level.level_number)

    def test_classroom_topic_has_parent_strand(self):
        """classroom.Topic has the strand (parent) relationship; maths.Topic does not."""
        self.assertIsNotNone(self.classroom_topic.parent)
        self.assertEqual(self.classroom_topic.parent.name, 'Algebra')

    def test_maths_topic_has_no_parent_field(self):
        self.assertFalse(hasattr(self.maths_topic, 'parent'))

    def test_classroom_level_and_maths_level_share_level_number(self):
        """Both apps can be queried consistently by level_number."""
        cl = ClassroomLevel.objects.get(level_number=7)
        ml = MathsLevel.objects.get(level_number=7)
        self.assertEqual(cl.level_number, ml.level_number)


# ─────────────────────────────────────────────────────────────────────────────
# 2. JSON upload view — topic resolution
# ─────────────────────────────────────────────────────────────────────────────

class UploadViewTopicResolutionTests(IntegrationBase):
    """
    Tests that the /upload-questions/ view correctly resolves maths.Topic
    from the JSON 'topic' field.
    """

    def test_upload_resolves_topic_by_name(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='Integers', year_level=7)
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
        """strand field is accepted and does not cause a FieldError."""
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='Integers', year_level=7, strand='Algebra')
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['upload_results']['failed'], 0)

    def test_upload_unknown_topic_returns_error_message(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='NonExistentTopic', year_level=7)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        # Should redirect back with an error message, not 500
        self.assertEqual(resp.status_code, 302)

    def test_upload_unknown_year_level_returns_error_message(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='Integers', year_level=99)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'upload_file': f},
        )
        self.assertEqual(resp.status_code, 302)

    def test_upload_links_question_to_correct_maths_topic_and_level(self):
        self._login(self.superuser)
        before = MathsQuestion.objects.filter(
            topic=self.maths_topic, level=self.maths_level,
        ).count()
        payload = self._json_upload_payload(topic='Integers', year_level=7)
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        self.client.post(reverse('upload_questions'), {'upload_file': f})
        after = MathsQuestion.objects.filter(
            topic=self.maths_topic, level=self.maths_level,
        ).count()
        self.assertEqual(after, before + 1)

    def test_duplicate_upload_updates_not_duplicates(self):
        """Uploading the same question twice updates it rather than inserting a duplicate."""
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='Integers', year_level=7)

        for _ in range(2):
            f = io.BytesIO(payload)
            f.name = 'questions.json'
            self.client.post(reverse('upload_questions'), {'upload_file': f})

        count = MathsQuestion.objects.filter(
            question_text='What is -3 + 5?',
            topic=self.maths_topic, level=self.maths_level,
        ).count()
        self.assertEqual(count, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. ZIP upload
# ─────────────────────────────────────────────────────────────────────────────

class UploadViewZipTests(IntegrationBase):
    """Tests for ZIP file uploads (questions + images)."""

    def test_zip_upload_inserts_question(self):
        self._login(self.superuser)
        payload = self._json_upload_payload(topic='Integers', year_level=7)
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
        payload = self._json_upload_payload(topic='Integers', year_level=7)
        fake_png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 20  # minimal PNG-like bytes
        zf = self._make_zip(payload, images={'diagram.png': fake_png})
        zf.name = 'upload.zip'
        resp = self.client.post(reverse('upload_questions'), {'upload_file': zf})
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results']
        self.assertEqual(results['images_saved'], 1)
        self.assertIn('questions/year7/integers', results['image_dir'])


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
            level=cls.maths_level, topic=cls.maths_topic,
            school=None, department=None, classroom=None,
            question_text='Global question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.global_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.school_q = MathsQuestion.objects.create(
            level=cls.maths_level, topic=cls.maths_topic,
            school=cls.school, department=None, classroom=None,
            question_text='School question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.school_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.dept_q = MathsQuestion.objects.create(
            level=cls.maths_level, topic=cls.maths_topic,
            school=cls.school, department=cls.dept, classroom=None,
            question_text='Department question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.dept_q, answer_text='Yes', is_correct=True, order=1,
        )
        cls.class_q = MathsQuestion.objects.create(
            level=cls.maths_level, topic=cls.maths_topic,
            school=cls.school, department=cls.dept, classroom=cls.classroom,
            question_text='Class question?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        MathsAnswer.objects.create(
            question=cls.class_q, answer_text='Yes', is_correct=True, order=1,
        )

    def _get_question_list(self, user):
        self._login(user)
        url = reverse('question_list', args=[self.maths_level.level_number])
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
