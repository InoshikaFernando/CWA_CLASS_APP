"""
test_inline_parent_student_onboarding.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for inline parent/student creation during the student-add and parent-add
flows (CPP-229).

Coverage:
  SchoolStudentManageView (POST — student add):
    - no parent action → student created, no parent (backward compat)
    - class_ids → student enrolled in chosen class
    - parent_action=new → new parent account created and linked
    - parent_action=new with duplicate parent email → warning, no parent created
    - parent_action=link → existing parent linked to new student
    - parent_action=link with invalid parent_id → student created, warning
    - GET returns add_student_classes and relationship_choices in context

  AddParentView (POST — parent add):
    - no inline_student_action → parent created, existing student linked (backward compat)
    - inline_student_action=new → student account created and linked to parent
    - inline_student_action=new + class enrollment → student enrolled in chosen class
    - inline_student_action=new, billing limit exceeded → 400-like response with error
    - inline_student_action=new, missing student fields → error, nothing created
    - GET returns classes in context
"""

from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, ClassRoom, ClassStudent, ParentStudent, Subject,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role(name, display_name=None):
    r, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return r


def _make_admin(username):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@test.com',
        first_name='Admin', last_name='User',
    )
    UserRole.objects.create(user=u, role=_role(Role.INSTITUTE_OWNER, 'Institute Owner'))
    return u


def _make_school(admin_user):
    return School.objects.create(
        name='Test School', admin=admin_user, is_active=True,
    )


def _make_class(school):
    subject, _ = Subject.objects.get_or_create(slug='cs', defaults={'name': 'CS'})
    return ClassRoom.objects.create(
        name='Year 10 CS', school=school, subject=subject, is_active=True,
    )


def _make_student(username, school):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@student.test',
        first_name='Test', last_name='Student',
    )
    UserRole.objects.create(user=u, role=_role(Role.STUDENT, 'Student'))
    SchoolStudent.objects.create(school=school, student=u)
    return u


# ---------------------------------------------------------------------------
# SchoolStudentManageView — Add Student inline parent/class tests
# ---------------------------------------------------------------------------

class TestStudentAddInlineParent(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _make_admin('io_student_add')
        cls.school = _make_school(cls.admin)
        cls.classroom = _make_class(cls.school)
        cls.url = reverse('admin_school_students', kwargs={'school_id': cls.school.id})

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        return c

    def _post(self, extra=None):
        data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane.doe@student.test',
            'username': 'janedoe',
            'password': 'securepass1',
        }
        if extra:
            data.update(extra)
        with patch('classroom.email_utils.send_staff_welcome_email'):
            resp = self._client().post(self.url, data, follow=True)
        return resp

    # --- backward compat ---

    def test_student_created_without_parent_by_default(self):
        resp = self._post()
        self.assertTrue(CustomUser.objects.filter(email='jane.doe@student.test').exists())
        self.assertEqual(ParentStudent.objects.filter(school=self.school).count(), 0)

    def test_student_is_enrolled_in_school(self):
        self._post()
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertTrue(SchoolStudent.objects.filter(school=self.school, student=student).exists())

    # --- class enrollment ---

    def test_student_enrolled_in_class_when_class_ids_provided(self):
        self._post(extra={'class_ids': [str(self.classroom.id)]})
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=student, is_active=True,
            ).exists()
        )

    def test_student_not_enrolled_when_no_class_ids(self):
        self._post()
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertEqual(ClassStudent.objects.filter(student=student).count(), 0)

    # --- inline new parent ---

    def test_new_parent_created_and_linked(self):
        with patch('classroom.views_parent_admin._send_parent_setup_email', return_value=True):
            self._post(extra={
                'parent_action': 'new',
                'parent_first_name': 'Mary',
                'parent_last_name': 'Doe',
                'parent_email': 'mary.doe@parent.test',
                'parent_relationship': 'mother',
            })
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertTrue(CustomUser.objects.filter(email='mary.doe@parent.test').exists())
        parent = CustomUser.objects.get(email='mary.doe@parent.test')
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=parent, student=student, school=self.school,
            ).exists()
        )

    def test_new_parent_has_parent_role(self):
        with patch('classroom.views_parent_admin._send_parent_setup_email', return_value=True):
            self._post(extra={
                'parent_action': 'new',
                'parent_first_name': 'Mary',
                'parent_last_name': 'Doe',
                'parent_email': 'mary2.doe@parent.test',
                'parent_relationship': 'mother',
            })
        parent = CustomUser.objects.get(email='mary2.doe@parent.test')
        self.assertTrue(parent.has_role(Role.PARENT))

    def test_new_parent_is_primary_contact(self):
        with patch('classroom.views_parent_admin._send_parent_setup_email', return_value=True):
            self._post(extra={
                'parent_action': 'new',
                'parent_first_name': 'Mary',
                'parent_last_name': 'Doe',
                'parent_email': 'mary3.doe@parent.test',
                'parent_relationship': 'mother',
            })
        student = CustomUser.objects.get(email='jane.doe@student.test')
        link = ParentStudent.objects.get(
            student=student, school=self.school,
        )
        self.assertTrue(link.is_primary_contact)

    def test_duplicate_parent_email_skips_parent_creation(self):
        # Pre-create a user with the parent email
        CustomUser.objects.create_user(
            username='existing_parent', password='pass1234!',
            email='existing@parent.test',
        )
        self._post(extra={
            'parent_action': 'new',
            'parent_first_name': 'Mary',
            'parent_last_name': 'Doe',
            'parent_email': 'existing@parent.test',
            'parent_relationship': 'mother',
        })
        # Student still created
        self.assertTrue(CustomUser.objects.filter(email='jane.doe@student.test').exists())
        # No parent linked
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertEqual(ParentStudent.objects.filter(student=student, school=self.school).count(), 0)

    def test_new_parent_missing_fields_skips_parent(self):
        # parent_email missing → no parent created, student still created
        self._post(extra={
            'parent_action': 'new',
            'parent_first_name': 'Mary',
            # no parent_email
            'parent_last_name': 'Doe',
            'parent_relationship': 'mother',
        })
        self.assertTrue(CustomUser.objects.filter(email='jane.doe@student.test').exists())
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertEqual(ParentStudent.objects.filter(student=student, school=self.school).count(), 0)

    # --- link existing parent ---

    def test_existing_parent_linked(self):
        parent = CustomUser.objects.create_user(
            username='linkable_parent', password='pass1234!',
            email='linkable@parent.test',
        )
        self._post(extra={
            'parent_action': 'link',
            'parent_id': str(parent.id),
            'parent_relationship': 'guardian',
        })
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=parent, student=student, school=self.school,
            ).exists()
        )

    def test_existing_parent_gets_parent_role_when_linked(self):
        parent = CustomUser.objects.create_user(
            username='linkable_parent2', password='pass1234!',
            email='linkable2@parent.test',
        )
        self._post(extra={
            'parent_action': 'link',
            'parent_id': str(parent.id),
            'parent_relationship': 'guardian',
        })
        parent.refresh_from_db()
        self.assertTrue(parent.has_role(Role.PARENT))

    def test_invalid_parent_id_student_still_created(self):
        self._post(extra={
            'parent_action': 'link',
            'parent_id': '999999',
            'parent_relationship': 'guardian',
        })
        self.assertTrue(CustomUser.objects.filter(email='jane.doe@student.test').exists())
        student = CustomUser.objects.get(email='jane.doe@student.test')
        self.assertEqual(ParentStudent.objects.filter(student=student, school=self.school).count(), 0)

    # --- GET context ---

    def test_get_includes_add_student_classes(self):
        resp = self._client().get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('add_student_classes', resp.context)

    def test_get_includes_relationship_choices(self):
        resp = self._client().get(self.url)
        self.assertIn('relationship_choices', resp.context)
        self.assertGreater(len(resp.context['relationship_choices']), 0)

    def test_classes_listed_in_template(self):
        resp = self._client().get(self.url)
        self.assertContains(resp, self.classroom.name)


# ---------------------------------------------------------------------------
# AddParentView — inline student creation tests
# ---------------------------------------------------------------------------

class TestParentAddInlineStudent(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _make_admin('io_parent_add')
        cls.school = _make_school(cls.admin)
        cls.classroom = _make_class(cls.school)
        cls.existing_student = _make_student('existing_stud', cls.school)
        cls.url = reverse('admin_school_add_parent', kwargs={'school_id': cls.school.id})

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        return c

    def _post(self, extra=None):
        data = {
            'first_name': 'Parent',
            'last_name': 'Test',
            'email': 'parent.test@parent.test',
            'phone': '',
            'relationship': 'guardian',
            'student_ids': [str(self.existing_student.id)],
        }
        if extra:
            data.update(extra)
        with patch('classroom.views_parent_admin._send_parent_setup_email', return_value=True), \
             patch('classroom.email_utils.send_staff_welcome_email'):
            resp = self._client().post(self.url, data, follow=True)
        return resp

    # --- backward compat ---

    def test_parent_created_without_inline_student(self):
        self._post()
        self.assertTrue(CustomUser.objects.filter(email='parent.test@parent.test').exists())

    def test_existing_student_linked_to_parent(self):
        self._post()
        parent = CustomUser.objects.get(email='parent.test@parent.test')
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=parent, student=self.existing_student, school=self.school,
            ).exists()
        )

    # --- inline student creation ---

    def test_inline_student_created(self):
        self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'newstudent@student.test',
            'inline_student_password': 'securepass1',
        })
        self.assertTrue(CustomUser.objects.filter(email='newstudent@student.test').exists())

    def test_inline_student_enrolled_in_school(self):
        self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'newstudent2@student.test',
            'inline_student_password': 'securepass1',
        })
        student = CustomUser.objects.get(email='newstudent2@student.test')
        self.assertTrue(SchoolStudent.objects.filter(school=self.school, student=student).exists())

    def test_inline_student_linked_to_parent(self):
        self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'newstudent3@student.test',
            'inline_student_password': 'securepass1',
        })
        parent = CustomUser.objects.get(email='parent.test@parent.test')
        student = CustomUser.objects.get(email='newstudent3@student.test')
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=parent, student=student, school=self.school,
            ).exists()
        )

    def test_inline_student_has_student_role(self):
        self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'newstudent4@student.test',
            'inline_student_password': 'securepass1',
        })
        student = CustomUser.objects.get(email='newstudent4@student.test')
        self.assertTrue(student.has_role(Role.STUDENT))

    def test_inline_student_enrolled_in_class(self):
        self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'newstudent5@student.test',
            'inline_student_password': 'securepass1',
            'inline_student_class_ids': [str(self.classroom.id)],
        })
        student = CustomUser.objects.get(email='newstudent5@student.test')
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=student, is_active=True,
            ).exists()
        )

    def test_inline_student_missing_email_shows_error(self):
        resp = self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            # missing inline_student_email
            'inline_student_password': 'securepass1',
        })
        self.assertFalse(CustomUser.objects.filter(email='parent.test@parent.test').exists())
        # Check error message present
        messages_list = [str(m) for m in resp.context['messages']] if 'messages' in resp.context else []
        self.assertTrue(any('email' in m.lower() for m in messages_list))

    def test_inline_student_short_password_shows_error(self):
        resp = self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'short_pw@student.test',
            'inline_student_password': 'short',
        })
        self.assertFalse(CustomUser.objects.filter(email='parent.test@parent.test').exists())
        self.assertFalse(CustomUser.objects.filter(email='short_pw@student.test').exists())

    def test_inline_student_duplicate_email_shows_error(self):
        # Pre-create a user with the student email
        CustomUser.objects.create_user(
            username='dup_stud_check', password='pass1234!',
            email='duplicate_stud@student.test',
        )
        resp = self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'duplicate_stud@student.test',
            'inline_student_password': 'securepass1',
        })
        # Parent should NOT be created if inline student validation fails
        self.assertFalse(CustomUser.objects.filter(email='parent.test@parent.test').exists())

    def test_billing_limit_blocks_inline_student(self):
        from datetime import timedelta
        from django.utils import timezone
        from billing.models import InstitutePlan, SchoolSubscription

        plan = InstitutePlan.objects.filter(slug='limit1').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Limit1', slug='limit1', price=0,
                class_limit=10, student_limit=1,
                invoice_limit_yearly=0, extra_invoice_rate=0,
            )
        SchoolSubscription.objects.create(
            school=self.school, plan=plan, status='active',
            trial_end=timezone.now() + timedelta(days=30),
        )
        resp = self._post(extra={
            'inline_student_action': 'new',
            'inline_student_first_name': 'New',
            'inline_student_last_name': 'Student',
            'inline_student_email': 'overlimit@student.test',
            'inline_student_password': 'securepass1',
        })
        self.assertFalse(CustomUser.objects.filter(email='overlimit@student.test').exists())
        self.assertFalse(CustomUser.objects.filter(email='parent.test@parent.test').exists())
        # Clean up subscription to avoid affecting other tests
        SchoolSubscription.objects.filter(school=self.school, plan=plan).delete()

    # --- GET context ---

    def test_get_includes_classes(self):
        resp = self._client().get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classes', resp.context)

    def test_get_class_listed_in_template(self):
        resp = self._client().get(self.url)
        self.assertContains(resp, self.classroom.name)
