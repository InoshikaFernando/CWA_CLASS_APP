from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, ParentStudent, ParentInvite,
)


class ParentRoleTest(TestCase):
    """Test the PARENT role constant and is_parent property."""

    @classmethod
    def setUpTestData(cls):
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.user = CustomUser.objects.create_user(
            'parentuser', 'wlhtestmails+parent@gmail.com', 'password1!',
        )

    def test_parent_role_constant(self):
        self.assertEqual(Role.PARENT, 'parent')

    def test_is_parent_false_by_default(self):
        self.assertFalse(self.user.is_parent)

    def test_is_parent_true_when_role_assigned(self):
        self.user.roles.add(self.parent_role)
        self.assertTrue(self.user.is_parent)

    def test_parent_in_role_priority(self):
        self.assertIn(Role.PARENT, CustomUser.ROLE_PRIORITY)

    def test_parent_priority_is_lowest(self):
        self.assertEqual(CustomUser.ROLE_PRIORITY[-1], Role.PARENT)

    def test_primary_role_is_parent(self):
        self.user.roles.add(self.parent_role)
        self.assertEqual(self.user.primary_role, Role.PARENT)

    def test_student_role_takes_priority_over_parent(self):
        """If a user has both STUDENT and PARENT roles, STUDENT wins."""
        self.user.roles.add(self.student_role)
        self.user.roles.add(self.parent_role)
        self.assertEqual(self.user.primary_role, Role.STUDENT)


class ParentStudentModelTest(TestCase):
    """Test the ParentStudent linking model."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'wlhtestmails+admin@gmail.com', 'password1!',
        )
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        cls.parent_a = CustomUser.objects.create_user(
            'parent_a', 'wlhtestmails+pa@gmail.com', 'password1!',
            first_name='Alice', last_name='Parent',
        )
        cls.parent_a.roles.add(cls.parent_role)

        cls.parent_b = CustomUser.objects.create_user(
            'parent_b', 'wlhtestmails+pb@gmail.com', 'password1!',
            first_name='Bob', last_name='Parent',
        )
        cls.parent_b.roles.add(cls.parent_role)

        cls.parent_c = CustomUser.objects.create_user(
            'parent_c', 'wlhtestmails+pc@gmail.com', 'password1!',
            first_name='Charlie', last_name='Parent',
        )
        cls.parent_c.roles.add(cls.parent_role)

        cls.student = CustomUser.objects.create_user(
            'student1', 'wlhtestmails+student1@gmail.com', 'password1!',
            first_name='Zara', last_name='Student',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        cls.student_b = CustomUser.objects.create_user(
            'student2', 'wlhtestmails+student2@gmail.com', 'password1!',
            first_name='Yuki', last_name='Student',
        )
        cls.student_b.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student_b)

    def test_create_parent_student_link(self):
        link = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school, relationship='mother',
        )
        self.assertEqual(link.parent, self.parent_a)
        self.assertEqual(link.student, self.student)
        self.assertEqual(link.school, self.school)
        self.assertTrue(link.is_active)

    def test_str(self):
        link = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        self.assertIn('parent_a', str(link))
        self.assertIn('student1', str(link))
        self.assertIn('Test School', str(link))

    def test_unique_together_constraint(self):
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ParentStudent.objects.create(
                parent=self.parent_a, student=self.student,
                school=self.school,
            )

    def test_max_two_parents_per_student(self):
        """Third parent link for the same student should fail validation."""
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        ParentStudent.objects.create(
            parent=self.parent_b, student=self.student,
            school=self.school,
        )
        link3 = ParentStudent(
            parent=self.parent_c, student=self.student,
            school=self.school,
        )
        with self.assertRaises(ValidationError):
            link3.clean()

    def test_inactive_link_does_not_count_toward_limit(self):
        """Deactivated links should not count toward the 2-parent limit."""
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school, is_active=False,
        )
        ParentStudent.objects.create(
            parent=self.parent_b, student=self.student,
            school=self.school,
        )
        link3 = ParentStudent(
            parent=self.parent_c, student=self.student,
            school=self.school,
        )
        # Should not raise — only 1 active link exists
        link3.clean()

    def test_parent_can_link_to_multiple_children(self):
        link1 = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        link2 = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student_b,
            school=self.school,
        )
        children = ParentStudent.objects.filter(
            parent=self.parent_a, is_active=True,
        )
        self.assertEqual(children.count(), 2)

    def test_is_primary_contact_default_false(self):
        link = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        self.assertFalse(link.is_primary_contact)

    def test_relationship_choices(self):
        for choice_val, _ in ParentStudent.RELATIONSHIP_CHOICES:
            link = ParentStudent(
                parent=self.parent_a, student=self.student,
                school=self.school, relationship=choice_val,
            )
            self.assertEqual(link.relationship, choice_val)

    def test_different_schools_allow_same_parent_student(self):
        """Same parent-student pair at different schools is allowed."""
        school_b = School.objects.create(
            name='School B', slug='school-b', admin=self.admin_user,
        )
        ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=self.school,
        )
        link2 = ParentStudent.objects.create(
            parent=self.parent_a, student=self.student,
            school=school_b,
        )
        self.assertEqual(link2.school, school_b)


class ParentInviteModelTest(TestCase):
    """Test the ParentInvite model."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'admin', 'wlhtestmails+admin@gmail.com', 'password1!',
        )
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.student = CustomUser.objects.create_user(
            'student1', 'wlhtestmails+student1@gmail.com', 'password1!',
        )
        cls.student.roles.add(cls.student_role)

    def _make_invite(self, **kwargs):
        defaults = {
            'school': self.school,
            'student': self.student,
            'parent_email': 'wlhtestmails+parent@gmail.com',
            'invited_by': self.admin_user,
            'expires_at': timezone.now() + timedelta(days=7),
        }
        defaults.update(kwargs)
        return ParentInvite.objects.create(**defaults)

    def test_create_invite(self):
        invite = self._make_invite()
        self.assertEqual(invite.status, 'pending')
        self.assertIsNotNone(invite.token)
        self.assertEqual(invite.parent_email, 'wlhtestmails+parent@gmail.com')

    def test_token_is_uuid(self):
        import uuid
        invite = self._make_invite()
        self.assertIsInstance(invite.token, uuid.UUID)

    def test_token_is_unique(self):
        invite1 = self._make_invite()
        invite2 = self._make_invite(parent_email='wlhtestmails+other@gmail.com')
        self.assertNotEqual(invite1.token, invite2.token)

    def test_is_valid_pending_and_not_expired(self):
        invite = self._make_invite()
        self.assertTrue(invite.is_valid)

    def test_is_valid_false_when_expired(self):
        invite = self._make_invite(
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(invite.is_valid)

    def test_is_valid_false_when_accepted(self):
        invite = self._make_invite(status='accepted')
        self.assertFalse(invite.is_valid)

    def test_is_valid_false_when_revoked(self):
        invite = self._make_invite(status='revoked')
        self.assertFalse(invite.is_valid)

    def test_str(self):
        invite = self._make_invite()
        s = str(invite)
        self.assertIn('wlhtestmails+parent@gmail.com', s)
        self.assertIn('student1', s)
        self.assertIn('pending', s)

    def test_default_ordering_is_newest_first(self):
        """Meta ordering is ['-created_at']."""
        self.assertEqual(
            ParentInvite._meta.ordering, ['-created_at'],
        )
