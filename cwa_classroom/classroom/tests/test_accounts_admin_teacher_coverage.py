"""
Tests for accounts/views.py, classroom/views_admin.py, and classroom/views_teacher.py
to improve coverage (targeting uncovered ProfileView, SelectClassesView,
ChangePackageView, admin CRUD, teacher session management).
"""
import datetime
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, SchoolSubscription, ModuleSubscription, Package,
    Subscription,
)
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    ClassTeacher, ClassStudent, ClassSession, StudentAttendance,
    TeacherAttendance, AcademicYear, ParentInvite,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school(admin_role=Role.HEAD_OF_INSTITUTE, username='testhoi',
                  email='wlhtestmails+hoi@gmail.com'):
    """Create admin user + school + subscription. Returns (user, school)."""
    user = CustomUser.objects.create_user(
        username=username, password='password1!', email=email,
    )
    _assign_role(user, admin_role)
    school = School.objects.create(name='Test School', slug='test-school', admin=user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug='basic-test', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _setup_teacher(school, username='teacher1', email='wlhtestmails+teacher1@gmail.com',
                   role_name=Role.TEACHER, st_role='teacher'):
    """Create teacher user linked to school. Returns teacher user."""
    teacher = CustomUser.objects.create_user(
        username=username, password='password1!', email=email,
    )
    _assign_role(teacher, role_name)
    SchoolTeacher.objects.update_or_create(school=school, teacher=teacher, defaults={'role': st_role})
    return teacher


def _setup_classroom(school, teacher=None, name='Math 101'):
    """Create classroom + optionally assign teacher. Returns classroom."""
    classroom = ClassRoom.objects.create(
        name=name, school=school,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
    )
    if teacher:
        ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    return classroom


def _enable_module(school, module_slug):
    """Enable a module for the school's subscription."""
    sub = SchoolSubscription.objects.get(school=school)
    ModuleSubscription.objects.create(
        school_subscription=sub, module=module_slug, is_active=True,
    )


def _setup_student(school, username='student1', email='wlhtestmails+student1@gmail.com'):
    """Create student user linked to school. Returns student user."""
    student = CustomUser.objects.create_user(
        username=username, password='password1!', email=email,
        first_name='Test', last_name='Student',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)
    return student


# ===========================================================================
# accounts/views.py — ProfileView
# ===========================================================================

class ProfileViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username='profuser', password='password1!', email='wlhtestmails+prof@gmail.com',
            first_name='Old', last_name='Name',
        )
        self.client.login(username='profuser', password='password1!')

    def test_profile_get(self):
        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.status_code, 200)

    def test_update_profile(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'update_profile',
            'first_name': 'New',
            'last_name': 'Surname',
            'email': 'wlhtestmails+new@gmail.com',
            'username': 'profuser',  # unchanged
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'New')
        self.assertEqual(self.user.last_name, 'Surname')

    def test_update_profile_change_username(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'update_profile',
            'username': 'newuser123',
            'first_name': 'A',
            'last_name': 'B',
            'email': 'wlhtestmails+prof@gmail.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newuser123')

    def test_update_profile_invalid_username(self):
        # username too short
        resp = self.client.post(reverse('profile'), {
            'action': 'update_profile',
            'username': 'ab',
            'first_name': 'A',
            'last_name': 'B',
            'email': 'wlhtestmails+prof@gmail.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'profuser')  # unchanged

    def test_change_password_success(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'change_password',
            'current_password': 'password1!',
            'new_password': 'newpass123',
            'confirm_password': 'newpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass123'))

    def test_change_password_wrong_current(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'change_password',
            'current_password': 'wrongpass',
            'new_password': 'newpass123',
            'confirm_password': 'newpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('password1!'))

    def test_change_password_too_short(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'change_password',
            'current_password': 'password1!',
            'new_password': 'short',
            'confirm_password': 'short',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('password1!'))

    def test_change_password_mismatch(self):
        resp = self.client.post(reverse('profile'), {
            'action': 'change_password',
            'current_password': 'password1!',
            'new_password': 'newpass123',
            'confirm_password': 'different1',
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('password1!'))


# ===========================================================================
# accounts/views.py — SelectClassesView
# ===========================================================================

class SelectClassesViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username='indstudent', password='password1!', email='wlhtestmails+ind@gmail.com',
        )
        _assign_role(self.user, Role.INDIVIDUAL_STUDENT)
        self.pkg = Package.objects.create(
            name='Starter', price=Decimal('19.90'),
            class_limit=2, is_active=True, trial_days=14,
        )
        self.user.package = self.pkg
        self.user.save(update_fields=['package'])
        Subscription.objects.create(
            user=self.user, package=self.pkg, status=Subscription.STATUS_ACTIVE,
        )
        self.client.login(username='indstudent', password='password1!')
        # Create a classroom to join
        self.admin, self.school = _setup_school()
        self.classroom = _setup_classroom(self.school, name='Physics 101')

    def test_get_shows_page(self):
        resp = self.client.get(reverse('select_classes'))
        self.assertEqual(resp.status_code, 200)

    def test_non_individual_student_redirected(self):
        other = CustomUser.objects.create_user(
            username='other', password='password1!', email='wlhtestmails+other@gmail.com',
        )
        _assign_role(other, Role.STUDENT)
        self.client.login(username='other', password='password1!')
        resp = self.client.get(reverse('select_classes'))
        self.assertEqual(resp.status_code, 302)

    def test_join_by_code(self):
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
            'class_code': self.classroom.code,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.user
            ).exists()
        )

    def test_join_by_id(self):
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
            'classroom_id': self.classroom.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.user
            ).exists()
        )

    def test_join_already_enrolled(self):
        ClassStudent.objects.create(classroom=self.classroom, student=self.user)
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
            'class_code': self.classroom.code,
        })
        self.assertEqual(resp.status_code, 302)

    def test_join_invalid_code(self):
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
            'class_code': 'INVALID',
        })
        self.assertEqual(resp.status_code, 302)

    def test_join_no_code(self):
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
        })
        self.assertEqual(resp.status_code, 302)

    def test_leave_class(self):
        ClassStudent.objects.create(classroom=self.classroom, student=self.user)
        resp = self.client.post(reverse('select_classes'), {
            'action': 'leave',
            'classroom_id': self.classroom.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.user
            ).exists()
        )

    def test_join_exceeds_class_limit(self):
        # Fill up limit
        c1 = _setup_classroom(self.school, name='C1')
        c2 = _setup_classroom(self.school, name='C2')
        ClassStudent.objects.create(classroom=c1, student=self.user)
        ClassStudent.objects.create(classroom=c2, student=self.user)
        resp = self.client.post(reverse('select_classes'), {
            'action': 'join',
            'classroom_id': self.classroom.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.user
            ).exists()
        )


# ===========================================================================
# accounts/views.py — ChangePackageView
# ===========================================================================

class ChangePackageViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username='indstudent2', password='password1!', email='wlhtestmails+ind2@gmail.com',
        )
        _assign_role(self.user, Role.INDIVIDUAL_STUDENT)
        self.pkg = Package.objects.create(
            name='Pro', price=Decimal('29.90'),
            class_limit=5, is_active=True, trial_days=14,
        )
        self.user.package = self.pkg
        self.user.save(update_fields=['package'])
        Subscription.objects.create(
            user=self.user, package=self.pkg, status=Subscription.STATUS_ACTIVE,
        )
        self.client.login(username='indstudent2', password='password1!')

    def test_get_shows_packages(self):
        resp = self.client.get(reverse('change_package'))
        self.assertEqual(resp.status_code, 200)

    def test_non_individual_student_redirected(self):
        other = CustomUser.objects.create_user(
            username='other2', password='password1!', email='wlhtestmails+other2@gmail.com',
        )
        _assign_role(other, Role.STUDENT)
        self.client.login(username='other2', password='password1!')
        resp = self.client.get(reverse('change_package'))
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# accounts/views.py — ParentRegisterView / ParentAcceptInviteView
# ===========================================================================

class ParentInviteViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school(
            username='parentadmin', email='wlhtestmails+padmin@gmail.com',
        )
        self.student = _setup_student(
            self.school, username='kidstudent', email='wlhtestmails+kid@gmail.com',
        )
        self.invite = ParentInvite.objects.create(
            school=self.school,
            student=self.student,
            parent_email='wlhtestmails+parent@gmail.com',
            relationship='Mother',
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_parent_register_get_valid_invite(self):
        resp = self.client.get(
            reverse('register_parent', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 200)

    def test_parent_register_get_expired_invite(self):
        self.invite.expires_at = timezone.now() - timedelta(days=1)
        self.invite.save(update_fields=['expires_at'])
        resp = self.client.get(
            reverse('register_parent', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 200)  # shows invalid page

    def test_parent_register_get_already_logged_in(self):
        user = CustomUser.objects.create_user(
            username='existinguser', password='password1!', email='wlhtestmails+existing@gmail.com',
        )
        self.client.login(username='existinguser', password='password1!')
        resp = self.client.get(
            reverse('register_parent', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 302)  # redirects to accept

    def test_parent_register_post_success(self):
        resp = self.client.post(
            reverse('register_parent', kwargs={'token': self.invite.token}),
            {
                'first_name': 'Jane',
                'last_name': 'Parent',
                'email': 'wlhtestmails+parent@gmail.com',
                'password': 'password1!',
                'confirm_password': 'password1!',
                'username': 'janeparent',
                'accept_terms': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, 'accepted')

    def test_parent_register_post_validation_errors(self):
        resp = self.client.post(
            reverse('register_parent', kwargs={'token': self.invite.token}),
            {
                'first_name': '',
                'last_name': '',
                'email': 'wlhtestmails+parent@gmail.com',
                'password': 'short',
                'confirm_password': 'mismatch',
            },
        )
        self.assertEqual(resp.status_code, 200)  # re-renders form

    def test_accept_invite_get(self):
        user = CustomUser.objects.create_user(
            username='existparent', password='password1!', email='wlhtestmails+ep@gmail.com',
        )
        self.client.login(username='existparent', password='password1!')
        resp = self.client.get(
            reverse('accept_parent_invite', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 200)

    def test_accept_invite_post_success(self):
        user = CustomUser.objects.create_user(
            username='existparent2', password='password1!', email='wlhtestmails+ep2@gmail.com',
        )
        self.client.login(username='existparent2', password='password1!')
        resp = self.client.post(
            reverse('accept_parent_invite', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 302)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.status, 'accepted')

    def test_accept_invite_invalid(self):
        self.invite.status = 'revoked'
        self.invite.save(update_fields=['status'])
        user = CustomUser.objects.create_user(
            username='existparent3', password='password1!', email='wlhtestmails+ep3@gmail.com',
        )
        self.client.login(username='existparent3', password='password1!')
        resp = self.client.get(
            reverse('accept_parent_invite', kwargs={'token': self.invite.token})
        )
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# classroom/views_admin.py — AdminDashboardView
# ===========================================================================

class AdminDashboardViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_dashboard(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('school_data', resp.context)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_wrong_role_forbidden(self):
        student = CustomUser.objects.create_user(
            username='stud', password='password1!', email='wlhtestmails+stud@gmail.com',
        )
        _assign_role(student, Role.STUDENT)
        self.client.login(username='stud', password='password1!')
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# classroom/views_admin.py — SchoolCreateView
# ===========================================================================

class SchoolCreateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_form(self):
        resp = self.client.get(reverse('admin_school_create'))
        self.assertEqual(resp.status_code, 200)

    def test_post_success(self):
        resp = self.client.post(reverse('admin_school_create'), {
            'name': 'New Academy',
            'address': '123 Main St',
            'phone': '555-1234',
            'email': 'new@academy.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(School.objects.filter(name='New Academy').exists())

    def test_post_missing_name(self):
        resp = self.client.post(reverse('admin_school_create'), {
            'name': '',
            'address': '123 Main St',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form

    def test_post_duplicate_slug_increments(self):
        School.objects.create(name='Dup School', slug='dup-school', admin=self.admin)
        resp = self.client.post(reverse('admin_school_create'), {
            'name': 'Dup School',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(School.objects.filter(slug='dup-school-1').exists())


# ===========================================================================
# classroom/views_admin.py — SchoolDetailView
# ===========================================================================

class SchoolDetailViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_detail(self):
        resp = self.client.get(
            reverse('admin_school_detail', kwargs={'school_id': self.school.id})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['school'], self.school)


# ===========================================================================
# classroom/views_admin.py — SchoolEditView
# ===========================================================================

class SchoolEditViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_edit_form(self):
        resp = self.client.get(
            reverse('admin_school_edit', kwargs={'school_id': self.school.id})
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_update(self):
        resp = self.client.post(
            reverse('admin_school_edit', kwargs={'school_id': self.school.id}),
            {'name': 'Updated School', 'address': 'New Addr', 'phone': '', 'email': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, 'Updated School')

    def test_post_missing_name(self):
        resp = self.client.post(
            reverse('admin_school_edit', kwargs={'school_id': self.school.id}),
            {'name': '', 'address': '', 'phone': '', 'email': ''},
        )
        self.assertEqual(resp.status_code, 200)  # re-renders


# ===========================================================================
# classroom/views_admin.py — SchoolTeacherManageView
# ===========================================================================

class SchoolTeacherManageViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_list(self):
        resp = self.client.get(
            reverse('admin_school_teachers', kwargs={'school_id': self.school.id})
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_post_create_teacher(self):
        resp = self.client.post(
            reverse('admin_school_teachers', kwargs={'school_id': self.school.id}),
            {
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'wlhtestmails+johndoe@gmail.com',
                'password': 'password1!',
                'username': 'johndoe',
                'role': 'teacher',
                'specialty': 'Math',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(username='johndoe').exists())
        self.assertTrue(
            SchoolTeacher.objects.filter(
                school=self.school,
                teacher__username='johndoe',
            ).exists()
        )

    def test_post_create_teacher_validation_errors(self):
        resp = self.client.post(
            reverse('admin_school_teachers', kwargs={'school_id': self.school.id}),
            {
                'first_name': '',
                'last_name': '',
                'email': 'invalid',
                'password': 'short',
                'username': '',
            },
        )
        self.assertEqual(resp.status_code, 200)  # re-renders with errors

    def test_post_create_teacher_duplicate_email(self):
        CustomUser.objects.create_user(
            username='existing', password='password1!', email='wlhtestmails+dup@gmail.com',
        )
        resp = self.client.post(
            reverse('admin_school_teachers', kwargs={'school_id': self.school.id}),
            {
                'first_name': 'Jane',
                'last_name': 'Doe',
                'email': 'wlhtestmails+dup@gmail.com',
                'password': 'password1!',
                'username': 'janedoe',
            },
        )
        self.assertEqual(resp.status_code, 200)  # validation error


# ===========================================================================
# classroom/views_admin.py — SchoolStudentManageView
# ===========================================================================

class SchoolStudentManageViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_list(self):
        resp = self.client.get(
            reverse('admin_school_students', kwargs={'school_id': self.school.id})
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_post_create_student(self):
        resp = self.client.post(
            reverse('admin_school_students', kwargs={'school_id': self.school.id}),
            {
                'first_name': 'Alice',
                'last_name': 'Smith',
                'email': 'wlhtestmails+alice@gmail.com',
                'password': 'password1!',
                'username': 'alicesmith',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(username='alicesmith').exists())

    def test_post_create_student_validation_errors(self):
        resp = self.client.post(
            reverse('admin_school_students', kwargs={'school_id': self.school.id}),
            {
                'first_name': '',
                'last_name': '',
                'email': 'bad',
                'password': 'short',
            },
        )
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# classroom/views_admin.py — SchoolStudentEditView
# ===========================================================================

class SchoolStudentEditViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.student = _setup_student(self.school)
        self.client.login(username='testhoi', password='password1!')

    def test_edit_student(self):
        resp = self.client.post(
            reverse('admin_school_student_edit', kwargs={
                'school_id': self.school.id,
                'student_id': self.student.id,
            }),
            {
                'first_name': 'Updated',
                'last_name': 'Name',
                'email': 'wlhtestmails+updated@gmail.com',
                'username': self.student.username,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Updated')


# ===========================================================================
# classroom/views_admin.py — SchoolTeacherBatchUpdateView
# ===========================================================================

class SchoolTeacherBatchUpdateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.client.login(username='testhoi', password='password1!')

    def test_batch_update_empty(self):
        resp = self.client.post(
            reverse('admin_school_teacher_batch_update', kwargs={
                'school_id': self.school.id,
            }),
            {'teacher_ids': ''},
        )
        self.assertEqual(resp.status_code, 302)

    def test_batch_update_single_teacher(self):
        tid = self.teacher.id
        resp = self.client.post(
            reverse('admin_school_teacher_batch_update', kwargs={
                'school_id': self.school.id,
            }),
            {
                'teacher_ids': str(tid),
                f'first_name_{tid}': 'BatchUpdated',
                f'last_name_{tid}': 'Teacher',
                f'email_{tid}': self.teacher.email,
                f'username_{tid}': self.teacher.username,
                f'role_{tid}': 'senior_teacher',
                f'specialty_{tid}': 'Science',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, 'BatchUpdated')


# ===========================================================================
# classroom/views_admin.py — AcademicYearCreateView
# ===========================================================================

class AcademicYearCreateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.client.login(username='testhoi', password='password1!')

    def test_get_form(self):
        resp = self.client.get(
            reverse('admin_academic_year_create', kwargs={
                'school_id': self.school.id,
            })
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_success(self):
        resp = self.client.post(
            reverse('admin_academic_year_create', kwargs={
                'school_id': self.school.id,
            }),
            {
                'year': '2026',
                'start_date': '2026-01-15',
                'end_date': '2026-12-15',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            AcademicYear.objects.filter(school=self.school, year=2026).exists()
        )

    def test_post_missing_fields(self):
        resp = self.client.post(
            reverse('admin_academic_year_create', kwargs={
                'school_id': self.school.id,
            }),
            {'year': '', 'start_date': '', 'end_date': ''},
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_invalid_year(self):
        resp = self.client.post(
            reverse('admin_academic_year_create', kwargs={
                'school_id': self.school.id,
            }),
            {'year': 'abc', 'start_date': '2026-01-01', 'end_date': '2026-12-31'},
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_duplicate_year(self):
        AcademicYear.objects.create(
            school=self.school, year=2026,
            start_date='2026-01-01', end_date='2026-12-31',
        )
        resp = self.client.post(
            reverse('admin_academic_year_create', kwargs={
                'school_id': self.school.id,
            }),
            {'year': '2026', 'start_date': '2026-02-01', 'end_date': '2026-11-30'},
        )
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# classroom/views_teacher.py — TeacherDashboardView
# ===========================================================================

class TeacherDashboardViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.client.login(username='teacher1', password='password1!')

    def test_get_dashboard_with_school(self):
        resp = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['current_school'], self.school)

    def test_get_dashboard_no_school(self):
        teacher2 = CustomUser.objects.create_user(
            username='loneteacher', password='password1!', email='wlhtestmails+lone@gmail.com',
        )
        _assign_role(teacher2, Role.TEACHER)
        self.client.login(username='loneteacher', password='password1!')
        resp = self.client.get(reverse('teacher_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['current_school'])


# ===========================================================================
# classroom/views_teacher.py — StartSessionView
# ===========================================================================

class StartSessionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        _enable_module(self.school, ModuleSubscription.MODULE_STUDENTS_ATTENDANCE)
        self.client.login(username='teacher1', password='password1!')

    def test_start_session_creates_session(self):
        resp = self.client.post(
            reverse('start_session', kwargs={'class_id': self.classroom.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassSession.objects.filter(
                classroom=self.classroom, date=timezone.localdate()
            ).exists()
        )

    def test_start_session_existing_scheduled(self):
        session = ClassSession.objects.create(
            classroom=self.classroom, date=timezone.localdate(),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        resp = self.client.post(
            reverse('start_session', kwargs={'class_id': self.classroom.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(str(session.id), resp.url)

    def test_start_session_no_access(self):
        teacher2 = _setup_teacher(
            self.school, username='teacher2', email='wlhtestmails+t2@gmail.com',
        )
        self.client.login(username='teacher2', password='password1!')
        resp = self.client.post(
            reverse('start_session', kwargs={'class_id': self.classroom.id})
        )
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# classroom/views_teacher.py — CreateSessionView
# ===========================================================================

class CreateSessionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.client.login(username='teacher1', password='password1!')

    def test_get_form(self):
        resp = self.client.get(
            reverse('create_session', kwargs={'class_id': self.classroom.id})
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_success(self):
        date_str = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(
            reverse('create_session', kwargs={'class_id': self.classroom.id}),
            {
                'date': date_str,
                'start_time': '09:00',
                'end_time': '10:00',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassSession.objects.filter(classroom=self.classroom).exists()
        )

    def test_post_invalid_date(self):
        resp = self.client.post(
            reverse('create_session', kwargs={'class_id': self.classroom.id}),
            {'date': 'not-a-date', 'start_time': '09:00', 'end_time': '10:00'},
        )
        self.assertEqual(resp.status_code, 302)  # redirects with error

    def test_post_duplicate_session(self):
        date_val = timezone.localdate() + timedelta(days=2)
        ClassSession.objects.create(
            classroom=self.classroom, date=date_val,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        resp = self.client.post(
            reverse('create_session', kwargs={'class_id': self.classroom.id}),
            {
                'date': date_val.isoformat(),
                'start_time': '09:00',
                'end_time': '10:00',
            },
        )
        self.assertEqual(resp.status_code, 302)

    def test_post_no_access(self):
        teacher2 = _setup_teacher(
            self.school, username='teacher2', email='wlhtestmails+t2@gmail.com',
        )
        self.client.login(username='teacher2', password='password1!')
        resp = self.client.post(
            reverse('create_session', kwargs={'class_id': self.classroom.id}),
            {
                'date': timezone.localdate().isoformat(),
                'start_time': '09:00',
                'end_time': '10:00',
            },
        )
        self.assertEqual(resp.status_code, 302)

    def test_post_with_go_to_attendance(self):
        date_str = (timezone.localdate() + timedelta(days=3)).isoformat()
        resp = self.client.post(
            reverse('create_session', kwargs={'class_id': self.classroom.id}),
            {
                'date': date_str,
                'start_time': '09:00',
                'end_time': '10:00',
                'go_to_attendance': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('attendance', resp.url)


# ===========================================================================
# classroom/views_teacher.py — CompleteSessionView
# ===========================================================================

class CompleteSessionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.session = ClassSession.objects.create(
            classroom=self.classroom, date=timezone.localdate(),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        self.client.login(username='teacher1', password='password1!')

    def test_complete_session(self):
        resp = self.client.post(
            reverse('complete_session', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')

    def test_complete_already_completed(self):
        self.session.status = 'completed'
        self.session.save(update_fields=['status'])
        resp = self.client.post(
            reverse('complete_session', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 302)

    def test_complete_no_access(self):
        teacher2 = _setup_teacher(
            self.school, username='teacher2', email='wlhtestmails+t2@gmail.com',
        )
        self.client.login(username='teacher2', password='password1!')
        resp = self.client.post(
            reverse('complete_session', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 302)


# ===========================================================================
# classroom/views_teacher.py — CancelSessionView
# ===========================================================================

class CancelSessionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.session = ClassSession.objects.create(
            classroom=self.classroom, date=timezone.localdate(),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        self.client.login(username='teacher1', password='password1!')

    def test_cancel_session(self):
        resp = self.client.post(
            reverse('cancel_session', kwargs={'session_id': self.session.id}),
            {'reason': 'Weather'},
        )
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'cancelled')
        self.assertEqual(self.session.cancellation_reason, 'Weather')

    def test_cancel_already_completed(self):
        self.session.status = 'completed'
        self.session.save(update_fields=['status'])
        resp = self.client.post(
            reverse('cancel_session', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')  # unchanged


# ===========================================================================
# classroom/views_teacher.py — DeleteSessionView
# ===========================================================================

class DeleteSessionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.session = ClassSession.objects.create(
            classroom=self.classroom, date=timezone.localdate(),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        self.client.login(username='teacher1', password='password1!')

    def test_delete_session(self):
        session_id = self.session.id
        resp = self.client.post(
            reverse('delete_session', kwargs={'session_id': session_id})
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ClassSession.objects.filter(id=session_id).exists())

    def test_delete_session_no_access(self):
        teacher2 = _setup_teacher(
            self.school, username='teacher2', email='wlhtestmails+t2@gmail.com',
        )
        self.client.login(username='teacher2', password='password1!')
        resp = self.client.post(
            reverse('delete_session', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassSession.objects.filter(id=self.session.id).exists())


# ===========================================================================
# classroom/views_teacher.py — SessionAttendanceView POST
# ===========================================================================

class SessionAttendancePostTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.classroom = _setup_classroom(self.school, teacher=self.teacher)
        self.student = _setup_student(self.school)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        _enable_module(self.school, ModuleSubscription.MODULE_STUDENTS_ATTENDANCE)
        self.session = ClassSession.objects.create(
            classroom=self.classroom, date=timezone.localdate(),
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.teacher,
        )
        self.client.login(username='teacher1', password='password1!')

    def test_get_attendance_page(self):
        resp = self.client.get(
            reverse('session_attendance', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_mark_attendance(self):
        resp = self.client.post(
            reverse('session_attendance', kwargs={'session_id': self.session.id}),
            {
                f'status_{self.student.id}': 'present',
                'teacher_status': 'present',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            StudentAttendance.objects.filter(
                session=self.session, student=self.student, status='present',
            ).exists()
        )

    def test_post_mark_attendance_and_complete(self):
        resp = self.client.post(
            reverse('session_attendance', kwargs={'session_id': self.session.id}),
            {
                f'status_{self.student.id}': 'present',
                'teacher_status': 'present',
                'complete_session': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')

    def test_post_no_access(self):
        teacher2 = _setup_teacher(
            self.school, username='teacher2', email='wlhtestmails+t2@gmail.com',
        )
        self.client.login(username='teacher2', password='password1!')
        resp = self.client.post(
            reverse('session_attendance', kwargs={'session_id': self.session.id}),
            {f'status_{self.student.id}': 'present'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            StudentAttendance.objects.filter(session=self.session).exists()
        )


# ===========================================================================
# classroom/views_admin.py — SchoolTeacherRemoveView
# ===========================================================================

class SchoolTeacherRemoveViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin, self.school = _setup_school()
        self.teacher = _setup_teacher(self.school)
        self.client.login(username='testhoi', password='password1!')

    def test_remove_teacher(self):
        resp = self.client.post(
            reverse('admin_school_teacher_remove', kwargs={
                'school_id': self.school.id,
                'teacher_id': self.teacher.id,
            })
        )
        self.assertEqual(resp.status_code, 302)
        st = SchoolTeacher.objects.get(school=self.school, teacher=self.teacher)
        self.assertFalse(st.is_active)

    def test_remove_nonexistent_teacher(self):
        resp = self.client.post(
            reverse('admin_school_teacher_remove', kwargs={
                'school_id': self.school.id,
                'teacher_id': 99999,
            })
        )
        self.assertEqual(resp.status_code, 302)
