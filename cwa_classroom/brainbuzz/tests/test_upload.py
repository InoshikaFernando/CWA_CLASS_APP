"""
Tests for question upload system with role-based access control.

Tests cover:
- Permission functions (role detection, visibility checks)
- File parsing utilities (JSON, CSV, Excel)
- Upload service (validation, deduplication, creation)
- API endpoints (visibility filtering)
- View access control
"""

import json
import io
import tempfile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from maths.models import Question, Answer
from classroom.models import School, Topic, Level, Subject, SchoolTeacher
from brainbuzz.permissions import (
    get_user_role, can_upload_questions, can_see_question, is_institute_admin,
    is_teacher, is_superuser,
)
from brainbuzz.upload_parsers import get_parser, JSONQuestionParser
from brainbuzz.upload_service import QuestionUploadService
from brainbuzz.managers import MathsQuestionsManager

User = get_user_model()


class RoleDetectionTests(TestCase):
    """Test user role detection and permission functions."""

    def setUp(self):
        """Create test users and schools."""
        self.superuser = User.objects.create_superuser(
            username='superuser', email='su@test.com', password='pass'
        )
        self.school = School.objects.create(name='Test School')
        self.admin = User.objects.create_user(
            username='admin', email='admin@test.com', password='pass'
        )
        self.admin.is_staff = True
        self.admin.school = self.school
        self.admin.save()

        self.guest = User.objects.create_user(
            username='guest', email='guest@test.com', password='pass'
        )

    def test_superuser_role_detection(self):
        """Test that superusers are identified correctly."""
        self.assertEqual(get_user_role(self.superuser), 'superuser')
        self.assertTrue(is_superuser(self.superuser))
        self.assertTrue(can_upload_questions(self.superuser))

    def test_admin_role_detection(self):
        """Test that institute admins are identified correctly."""
        self.assertEqual(get_user_role(self.admin), 'admin')
        self.assertTrue(is_institute_admin(self.admin))
        self.assertTrue(can_upload_questions(self.admin))

    def test_guest_role_detection(self):
        """Test that guests are identified correctly."""
        self.assertEqual(get_user_role(self.guest), 'guest')
        self.assertFalse(is_superuser(self.guest))
        self.assertFalse(is_institute_admin(self.guest))
        self.assertFalse(can_upload_questions(self.guest))

    def test_unauthenticated_user(self):
        """Test that unauthenticated users are guests."""
        anonymous = User()
        self.assertEqual(get_user_role(anonymous), 'guest')
        self.assertFalse(can_upload_questions(anonymous))


class QuestionVisibilityTests(TestCase):
    """Test question visibility and filtering."""

    def setUp(self):
        """Create test data."""
        self.superuser = User.objects.create_superuser(
            username='superuser', email='su@test.com', password='pass'
        )
        self.school = School.objects.create(name='Test School')
        self.admin = User.objects.create_user(
            username='admin', email='admin@test.com', password='pass'
        )
        self.admin.is_staff = True
        self.admin.school = self.school
        self.admin.save()

        # Create subject and topic
        self.subject = Subject.objects.create(
            name='Mathematics', slug='mathematics'
        )
        self.topic = Topic.objects.create(
            name='Fractions', slug='fractions', subject=self.subject
        )
        self.level = Level.objects.create(level_number=5, display_name='Year 5')

        # Create global question
        self.global_question = Question.objects.create(
            topic=self.topic,
            level=self.level,
            question_text='Global: What is 1/2?',
            question_type='multiple_choice',
            difficulty=1,
            school=None,  # Global
        )

        # Create school-local question
        self.local_question = Question.objects.create(
            topic=self.topic,
            level=self.level,
            question_text='Local: What is 1/4?',
            question_type='multiple_choice',
            difficulty=1,
            school=self.school,  # Local to school
        )

    def test_global_question_visible_to_superuser(self):
        """Test that superusers see global questions."""
        self.assertTrue(can_see_question(self.global_question, self.superuser))

    def test_global_question_visible_to_admin(self):
        """Test that admins see global questions."""
        self.assertTrue(can_see_question(self.global_question, self.admin))

    def test_local_question_visible_to_admin_in_school(self):
        """Test that admins see local questions in their school."""
        self.assertTrue(can_see_question(self.local_question, self.admin))

    def test_local_question_invisible_to_other_admin(self):
        """Test that admins don't see questions from other schools."""
        other_school = School.objects.create(name='Other School')
        other_admin = User.objects.create_user(
            username='other_admin', email='other@test.com', password='pass'
        )
        other_admin.is_staff = True
        other_admin.school = other_school
        other_admin.save()

        self.assertFalse(can_see_question(self.local_question, other_admin))

    def test_manager_filters_visible_questions(self):
        """Test that manager filters questions correctly."""
        # Superuser sees both
        qs = Question.objects.visible_to(self.superuser)
        self.assertEqual(qs.count(), 2)

        # Admin sees both (global + local to school)
        qs = Question.objects.visible_to(self.admin)
        self.assertEqual(qs.count(), 2)

        # Guest sees only global
        guest = User.objects.create_user(
            username='guest', password='pass'
        )
        qs = Question.objects.visible_to(guest)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), self.global_question)


class JSONParserTests(TestCase):
    """Test JSON question parser."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON format."""
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_text': 'What is 2+2?',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'topic': 'Arithmetic',
                    'level': 3,
                    'answers': [
                        {'text': '4', 'is_correct': True},
                        {'text': '5', 'is_correct': False},
                    ]
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        parser = JSONQuestionParser()
        questions = parser.parse(json_file)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['question_text'], 'What is 2+2?')
        self.assertEqual(len(questions[0]['answers']), 2)
        self.assertFalse(parser.errors)

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON."""
        json_file = io.StringIO('{invalid json}')

        parser = JSONQuestionParser()
        questions = parser.parse(json_file)

        self.assertEqual(len(questions), 0)
        self.assertTrue(parser.errors)

    def test_validate_missing_fields(self):
        """Test validation catches missing required fields."""
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    # Missing question_text, topic, level, answers
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        parser = JSONQuestionParser()
        questions = parser.parse(json_file)

        self.assertEqual(len(questions), 0)
        self.assertTrue(parser.errors)

    def test_validate_invalid_question_type(self):
        """Test validation catches invalid question type."""
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_text': 'Test?',
                    'question_type': 'invalid_type',
                    'difficulty': 1,
                    'topic': 'Test',
                    'level': 3,
                    'answers': [],
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        parser = JSONQuestionParser()
        questions = parser.parse(json_file)

        self.assertEqual(len(questions), 0)
        self.assertTrue(parser.errors)


class CSVParserTests(TestCase):
    """Test CSV question parser."""

    def test_parse_valid_csv(self):
        """Test parsing valid CSV format."""
        csv_content = """topic,level,question_text,question_type,difficulty,answer1,is_correct1,answer2,is_correct2
Fractions,5,What is 1/2 + 1/4?,multiple_choice,2,3/4,true,2/4,false"""

        csv_file = io.StringIO(csv_content)

        parser = get_parser('csv')
        questions = parser.parse(csv_file)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['question_text'], 'What is 1/2 + 1/4?')
        self.assertEqual(len(questions[0]['answers']), 2)
        self.assertFalse(parser.errors)

    def test_parse_multiple_questions(self):
        """Test parsing CSV with multiple questions."""
        csv_content = """topic,level,question_text,question_type,difficulty,answer1,is_correct1,answer2,is_correct2
Arithmetic,3,2+2=?,multiple_choice,1,4,true,5,false
Arithmetic,3,3+3=?,multiple_choice,1,6,true,7,false"""

        csv_file = io.StringIO(csv_content)

        parser = get_parser('csv')
        questions = parser.parse(csv_file)

        self.assertEqual(len(questions), 2)
        self.assertFalse(parser.errors)

    def test_validate_missing_headers(self):
        """Test validation catches missing required headers."""
        csv_content = """question_text,question_type
What is 1+1?,multiple_choice"""

        csv_file = io.StringIO(csv_content)

        parser = get_parser('csv')
        questions = parser.parse(csv_file)

        self.assertEqual(len(questions), 0)
        self.assertTrue(parser.errors)


class UploadServiceTests(TestCase):
    """Test the upload service."""

    def setUp(self):
        """Create test data."""
        self.superuser = User.objects.create_superuser(
            username='superuser', email='su@test.com', password='pass'
        )
        self.school = School.objects.create(name='Test School')
        self.admin = User.objects.create_user(
            username='admin', email='admin@test.com', password='pass'
        )
        self.admin.is_staff = True
        self.admin.school = self.school
        self.admin.save()

        # Create subject and topic
        self.subject = Subject.objects.create(
            name='Mathematics', slug='mathematics'
        )
        self.topic = Topic.objects.create(
            name='Fractions', slug='fractions', subject=self.subject
        )
        self.level = Level.objects.create(level_number=5, display_name='Year 5')

    def test_upload_service_creates_questions(self):
        """Test that upload service creates questions correctly."""
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_text': 'What is 1/2?',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'topic': 'Fractions',
                    'level': 5,
                    'answers': [
                        {'text': 'One half', 'is_correct': True},
                    ]
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        service = QuestionUploadService(self.superuser, 'maths')
        result = service.upload_file(json_file, 'json')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created'], 1)
        self.assertEqual(Question.objects.count(), 1)

        # Check question was created with correct scope
        q = Question.objects.first()
        self.assertEqual(q.question_text, 'What is 1/2?')
        self.assertIsNone(q.school)  # Superuser uploads are global

    def test_upload_service_respects_user_scope(self):
        """Test that upload service respects user scope."""
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_text': 'Local question',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'topic': 'Fractions',
                    'level': 5,
                    'answers': [
                        {'text': 'Answer', 'is_correct': True},
                    ]
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        service = QuestionUploadService(self.admin, 'maths')
        result = service.upload_file(json_file, 'json')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created'], 1)

        # Check question was scoped to admin's school
        q = Question.objects.first()
        self.assertEqual(q.school, self.school)

    def test_upload_service_detects_duplicates(self):
        """Test that upload service detects duplicates."""
        # Create initial question
        Question.objects.create(
            topic=self.topic,
            level=self.level,
            question_text='Duplicate question',
            question_type='multiple_choice',
            difficulty=1,
            school=None,
        )

        # Try to upload the same question
        json_data = {
            'subject': 'maths',
            'questions': [
                {
                    'question_text': 'Duplicate question',
                    'question_type': 'multiple_choice',
                    'difficulty': 1,
                    'topic': 'Fractions',
                    'level': 5,
                    'answers': [
                        {'text': 'Answer', 'is_correct': True},
                    ]
                }
            ]
        }
        json_file = io.StringIO(json.dumps(json_data))

        service = QuestionUploadService(self.superuser, 'maths')
        result = service.upload_file(json_file, 'json')

        self.assertEqual(result['skipped'], 1)
        self.assertEqual(Question.objects.count(), 1)  # No new questions created


class APIEndpointTests(TestCase):
    """Test API endpoints with visibility filtering."""

    def setUp(self):
        """Create test data."""
        self.client = Client()

        self.superuser = User.objects.create_superuser(
            username='superuser', email='su@test.com', password='pass123'
        )
        self.school = School.objects.create(name='Test School')
        self.admin = User.objects.create_user(
            username='admin', email='admin@test.com', password='pass123'
        )
        self.admin.is_staff = True
        self.admin.save()
        SchoolTeacher.objects.create(school=self.school, teacher=self.admin, is_active=True)

        # Create subject and topic
        self.subject = Subject.objects.create(
            name='Mathematics', slug='mathematics'
        )
        self.topic = Topic.objects.create(
            name='Fractions', slug='fractions', subject=self.subject
        )
        self.level = Level.objects.create(level_number=5, display_name='Year 5')

        # Create global question
        self.global_q = Question.objects.create(
            topic=self.topic,
            level=self.level,
            question_text='Global question',
            question_type='multiple_choice',
            difficulty=1,
            school=None,
        )
        Answer.objects.create(
            question=self.global_q,
            answer_text='Answer 1',
            is_correct=True,
        )

        # Create local question
        self.local_q = Question.objects.create(
            topic=self.topic,
            level=self.level,
            question_text='Local question',
            question_type='multiple_choice',
            difficulty=1,
            school=self.school,
        )
        Answer.objects.create(
            question=self.local_q,
            answer_text='Answer 2',
            is_correct=True,
        )

    def test_api_list_superuser_sees_all(self):
        """Test that superuser sees all questions via API."""
        self.client.login(username='superuser', password='pass123')
        response = self.client.get(reverse('brainbuzz:api_questions_list'), {
            'subject': 'maths'
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total'], 2)

    def test_api_list_admin_sees_relevant(self):
        """Test that admin sees global and local questions via API."""
        self.client.login(username='admin', password='pass123')
        response = self.client.get(reverse('brainbuzz:api_questions_list'), {
            'subject': 'maths'
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total'], 2)
        texts = [q['question_text'] for q in data['questions']]
        self.assertIn('Global question', texts)
        self.assertIn('Local question', texts)

    def test_api_list_filtering(self):
        """Test API filtering by topic."""
        self.client.login(username='superuser', password='pass123')
        response = self.client.get(reverse('brainbuzz:api_questions_list'), {
            'subject': 'maths',
            'topic': 'Fractions'
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total'], 2)

    def test_api_upload_requires_permission(self):
        """Test that upload API requires permission."""
        guest = User.objects.create_user(
            username='guest', password='pass123'
        )
        self.client.login(username='guest', password='pass123')

        response = self.client.post(reverse('brainbuzz:api_upload'))
        self.assertEqual(response.status_code, 403)


class ViewAccessControlTests(TestCase):
    """Test view access control."""

    def setUp(self):
        """Create test users."""
        self.client = Client()

        self.superuser = User.objects.create_superuser(
            username='superuser', email='su@test.com', password='pass123'
        )
        self.admin = User.objects.create_user(
            username='admin', email='admin@test.com', password='pass123'
        )
        self.admin.is_staff = True
        self.admin.save()
        _school = School.objects.create(name='Test School')
        SchoolTeacher.objects.create(school=_school, teacher=self.admin, is_active=True)

        self.guest = User.objects.create_user(
            username='guest', password='pass123'
        )

    def test_upload_view_requires_login(self):
        """Test that upload view requires login."""
        response = self.client.get(reverse('brainbuzz:upload_questions'))
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_upload_view_requires_permission(self):
        """Test that upload view requires upload permission."""
        self.client.login(username='guest', password='pass123')
        response = self.client.get(reverse('brainbuzz:upload_questions'))
        self.assertEqual(response.status_code, 403)

    def test_upload_view_accessible_to_admin(self):
        """Test that upload view is accessible to admins."""
        self.client.login(username='admin', password='pass123')
        response = self.client.get(reverse('brainbuzz:upload_questions'))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_accessible_to_superuser(self):
        """Test that upload view is accessible to superusers."""
        self.client.login(username='superuser', password='pass123')
        response = self.client.get(reverse('brainbuzz:upload_questions'))
        self.assertEqual(response.status_code, 200)
