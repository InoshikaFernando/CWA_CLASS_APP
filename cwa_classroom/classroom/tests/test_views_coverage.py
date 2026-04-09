"""
Comprehensive tests for classroom/views.py and classroom/views_admin.py
to increase coverage from ~33%/39% respectively.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, Package, Payment
from classroom.models import (
    School, Department, ClassRoom, SchoolTeacher, SchoolStudent,
    Subject, Level, ClassTeacher, ClassStudent, DepartmentSubject,
    DepartmentTeacher, DepartmentLevel, SubjectApp, ContactMessage,
    CONTACT_SUBJECT_CHOICES,
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


def _setup_school(admin_role=Role.HEAD_OF_INSTITUTE):
    """Create admin + school.  Returns (user, school)."""
    user = CustomUser.objects.create_user(
        username='testhoi', password='password1!', email='wlhtestmails+hoi@gmail.com',
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


def _setup_department(school, head=None):
    dept = Department.objects.create(
        school=school, name='Mathematics', slug='maths', head=head,
    )
    subj, _ = Subject.objects.get_or_create(
        slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)
    if head:
        DepartmentTeacher.objects.create(department=dept, teacher=head)
        SchoolTeacher.objects.update_or_create(
            school=school, teacher=head,
            defaults={'role': 'head_of_department'},
        )
    return dept, subj


def _setup_teacher(school, dept=None):
    teacher = CustomUser.objects.create_user(
        username='teacher1', password='password1!', email='wlhtestmails+teacher1@gmail.com',
    )
    _assign_role(teacher, Role.TEACHER)
    SchoolTeacher.objects.update_or_create(school=school, teacher=teacher, defaults={'role': 'teacher'})
    if dept:
        DepartmentTeacher.objects.create(department=dept, teacher=teacher)
    return teacher


def _setup_student(school):
    student = CustomUser.objects.create_user(
        username='student1', password='password1!', email='wlhtestmails+student1@gmail.com',
    )
    _assign_role(student, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=student)
    return student


def _setup_classroom(school, dept, teacher, subject=None):
    classroom = ClassRoom.objects.create(
        name='Test Class', school=school, department=dept, subject=subject,
    )
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    return classroom


# ============================================================================
# views.py Tests
# ============================================================================


class HomeViewTests(TestCase):
    """Test the HomeView (GET /app-home/)."""

    def setUp(self):
        self.client = Client()

    def test_redirect_unauthenticated(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_admin_redirect(self):
        user = CustomUser.objects.create_user('admin1', 'wlhtestmails+a@gmail.com', 'password1!')
        _assign_role(user, Role.ADMIN)
        self.client.login(username='admin1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('admin-dashboard', resp.url)

    def test_hoi_redirect(self):
        user = CustomUser.objects.create_user('hoi1', 'wlhtestmails+h@gmail.com', 'password1!')
        _assign_role(user, Role.HEAD_OF_INSTITUTE)
        self.client.login(username='hoi1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('dashboard', resp.url)

    def test_teacher_redirect(self):
        user = CustomUser.objects.create_user('teach1', 'wlhtestmails+t@gmail.com', 'password1!')
        _assign_role(user, Role.TEACHER)
        self.client.login(username='teach1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('teacher', resp.url)

    def test_accountant_redirect(self):
        user = CustomUser.objects.create_user('acc1', 'wlhtestmails+acc@gmail.com', 'password1!')
        _assign_role(user, Role.ACCOUNTANT)
        self.client.login(username='acc1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('accounting', resp.url)

    def test_parent_redirect(self):
        user = CustomUser.objects.create_user('parent1', 'wlhtestmails+p@gmail.com', 'password1!')
        _assign_role(user, Role.PARENT)
        self.client.login(username='parent1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('parent', resp.url)

    def test_institute_owner_redirect(self):
        user = CustomUser.objects.create_user('owner1', 'wlhtestmails+o@gmail.com', 'password1!')
        _assign_role(user, Role.INSTITUTE_OWNER)
        self.client.login(username='owner1', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('dashboard', resp.url)

    def test_superuser_no_role_redirects_to_django_admin(self):
        user = CustomUser.objects.create_superuser('su', 'wlhtestmails+su@gmail.com', 'password1!')
        self.client.login(username='su', password='password1!')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/', resp.url)


class PublicHomeViewTests(TestCase):
    """Test PublicHomeView (GET /)."""

    def test_anonymous_gets_public_page(self):
        resp = self.client.get(reverse('public_home'))
        self.assertEqual(resp.status_code, 200)

    def test_authenticated_admin_redirects(self):
        user = CustomUser.objects.create_user('a', 'wlhtestmails+a@gmail.com', 'password1!')
        _assign_role(user, Role.ADMIN)
        self.client.login(username='a', password='password1!')
        resp = self.client.get(reverse('public_home'))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_teacher_redirects(self):
        user = CustomUser.objects.create_user('t', 'wlhtestmails+t@gmail.com', 'password1!')
        _assign_role(user, Role.TEACHER)
        self.client.login(username='t', password='password1!')
        resp = self.client.get(reverse('public_home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('teacher', resp.url)


class SubjectsHubViewTests(TestCase):
    """Test SubjectsHubView (GET /hub/)."""

    def test_redirect_unauthenticated(self):
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_admin_redirects_to_dashboard(self):
        user = CustomUser.objects.create_user('a', 'wlhtestmails+a@gmail.com', 'password1!')
        _assign_role(user, Role.ADMIN)
        self.client.login(username='a', password='password1!')
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 302)

    def test_student_sees_hub(self):
        user = CustomUser.objects.create_user('s', 'wlhtestmails+s@gmail.com', 'password1!')
        user.profile_completed = True
        user.must_change_password = False
        user.save()
        _assign_role(user, Role.STUDENT)
        self.client.login(username='s', password='password1!')
        resp = self.client.get(reverse('subjects_hub'))
        # May redirect to student_dashboard or render 200
        self.assertIn(resp.status_code, [200, 302])

    def test_individual_student_sees_hub(self):
        from billing.models import Subscription
        user = CustomUser.objects.create_user('is', 'wlhtestmails+is@gmail.com', 'password1!')
        _assign_role(user, Role.INDIVIDUAL_STUDENT)
        Subscription.objects.create(user=user, status=Subscription.STATUS_ACTIVE)
        self.client.login(username='is', password='password1!')
        resp = self.client.get(reverse('subjects_hub'))
        self.assertEqual(resp.status_code, 200)


class TopicsViewTests(TestCase):
    def test_topics_requires_login(self):
        resp = self.client.get(reverse('topics'))
        self.assertEqual(resp.status_code, 302)

    def test_topics_returns_200(self):
        user = CustomUser.objects.create_user('u', 'wlhtestmails+u@gmail.com', 'password1!')
        self.client.login(username='u', password='password1!')
        resp = self.client.get(reverse('topics'))
        self.assertEqual(resp.status_code, 200)


class TopicLevelsViewTests(TestCase):
    def test_topic_levels(self):
        user = CustomUser.objects.create_user('u', 'wlhtestmails+u@gmail.com', 'password1!')
        subj = Subject.objects.create(name='Maths', slug='maths-tl')
        from classroom.models import Topic
        topic = Topic.objects.create(subject=subj, name='Addition', slug='addition')
        self.client.login(username='u', password='password1!')
        resp = self.client.get(reverse('topic_levels', args=[topic.id]))
        self.assertEqual(resp.status_code, 200)


class LevelDetailViewTests(TestCase):
    def test_level_detail(self):
        user = CustomUser.objects.create_user('u', 'wlhtestmails+u@gmail.com', 'password1!')
        lv, _ = Level.objects.get_or_create(level_number=1, defaults={'display_name': 'Year 1'})
        self.client.login(username='u', password='password1!')
        resp = self.client.get(reverse('level_detail', args=[lv.level_number]))
        self.assertEqual(resp.status_code, 200)


class RoleRequiredMixinTests(TestCase):
    """Test that role-gated views redirect unauthorized users."""

    def setUp(self):
        self.user = CustomUser.objects.create_user('u', 'wlhtestmails+u@gmail.com', 'password1!')
        _assign_role(self.user, Role.STUDENT)
        self.client.login(username='u', password='password1!')

    def test_student_cannot_access_admin_dashboard(self):
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_hod_overview(self):
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_accounting(self):
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 302)


class ClassDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_teacher_can_view_class(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classroom', resp.context)

    def test_hoi_can_view_class(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirect(self):
        resp = self.client.get(reverse('class_detail', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 302)


class CreateClassViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        # Map levels to dept
        for i in range(1, 4):
            lv, _ = Level.objects.get_or_create(
                level_number=i, defaults={'display_name': f'Year {i}', 'subject': cls.subj},
            )
            DepartmentLevel.objects.get_or_create(department=cls.dept, level=lv, defaults={'order': i})

    def test_get_create_class_form(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('create_class'))
        self.assertEqual(resp.status_code, 200)

    def test_post_create_class_success(self):
        self.client.login(username='testhoi', password='password1!')
        lv = Level.objects.get(level_number=1)
        resp = self.client.post(reverse('create_class'), {
            'name': 'New Class',
            'department': self.dept.id,
            'levels': [lv.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassRoom.objects.filter(name='New Class').exists())

    def test_post_create_class_no_name(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('create_class'), {
            'name': '',
            'department': self.dept.id,
        })
        self.assertEqual(resp.status_code, 302)  # redirect with error

    def test_post_create_class_no_department(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('create_class'), {
            'name': 'Test',
            'department': '',
        })
        self.assertEqual(resp.status_code, 302)


class EditClassViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_get_edit_class(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('edit_class', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classroom', resp.context)

    def test_post_edit_class(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('edit_class', args=[self.classroom.id]), {
            'name': 'Updated Name',
        })
        self.assertEqual(resp.status_code, 302)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.name, 'Updated Name')

    def test_post_edit_class_no_name(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('edit_class', args=[self.classroom.id]), {
            'name': '',
        })
        self.assertEqual(resp.status_code, 302)  # redirect with error


class AssignStudentsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)
        cls.student = _setup_student(cls.school)

    def test_get_assign_students(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('assign_students', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('all_students', resp.context)

    def test_post_assign_students(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('assign_students', args=[self.classroom.id]), {
            'students': [self.student.id],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassStudent.objects.filter(classroom=self.classroom, student=self.student).exists()
        )


class AssignTeachersViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_get_assign_teachers(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('assign_teachers', args=[self.classroom.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('all_teachers', resp.context)

    def test_post_assign_teachers(self):
        # Create another teacher
        teacher2 = CustomUser.objects.create_user('teacher2', 'wlhtestmails+t2@gmail.com', 'password1!')
        _assign_role(teacher2, Role.TEACHER)
        SchoolTeacher.objects.update_or_create(school=self.school, teacher=teacher2, defaults={'role': 'teacher'})

        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('assign_teachers', args=[self.classroom.id]), {
            'teachers': [self.teacher.id, teacher2.id],
        })
        self.assertEqual(resp.status_code, 302)


class HoDOverviewViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_hoi_can_access_dashboard(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access_dashboard(self):
        hod = CustomUser.objects.create_user('hod1', 'wlhtestmails+hod1@gmail.com', 'password1!')
        _assign_role(hod, Role.HEAD_OF_DEPARTMENT)
        self.dept.head = hod
        self.dept.save()
        DepartmentTeacher.objects.get_or_create(department=self.dept, teacher=hod)

        self.client.login(username='hod1', password='password1!')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 200)

    def test_student_cannot_access(self):
        student = CustomUser.objects.create_user('s', 'wlhtestmails+s@gmail.com', 'password1!')
        _assign_role(student, Role.STUDENT)
        self.client.login(username='s', password='password1!')
        resp = self.client.get(reverse('hod_overview'))
        self.assertEqual(resp.status_code, 302)


class HoDManageClassesViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_hoi_can_view_manage_classes(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classes', resp.context)


class HoDCreateClassViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_get_create_class_form(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('hod_create_class'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('departments', resp.context)

    def test_post_create_class_success(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('hod_create_class'), {
            'name': 'HoD Class',
            'department': self.dept.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClassRoom.objects.filter(name='HoD Class').exists())

    def test_post_create_class_missing_name(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('hod_create_class'), {
            'name': '',
            'department': self.dept.id,
        })
        self.assertEqual(resp.status_code, 302)


class HoDWorkloadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_workload_view(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('hod_workload'))
        self.assertEqual(resp.status_code, 200)


class HoDReportsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_reports_view(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('hod_reports'))
        self.assertEqual(resp.status_code, 200)


class AccountingDashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('acc', 'wlhtestmails+acc@gmail.com', 'password1!')
        _assign_role(cls.user, Role.ACCOUNTANT)
        # Create billing objects needed by accounting views
        cls.package = Package.objects.create(name='Test Pkg', price=Decimal('9.99'), is_active=True)

    def test_dashboard(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.get(reverse('accounting_dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_packages(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.get(reverse('accounting_packages'))
        self.assertEqual(resp.status_code, 200)

    def test_users(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.get(reverse('accounting_users'))
        self.assertEqual(resp.status_code, 200)

    def test_export(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.get(reverse('accounting_export'))
        self.assertEqual(resp.status_code, 200)

    def test_refunds(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.get(reverse('accounting_refunds'))
        self.assertEqual(resp.status_code, 200)


class ProcessRefundViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('acc', 'wlhtestmails+acc@gmail.com', 'password1!')
        _assign_role(cls.user, Role.ACCOUNTANT)
        cls.package = Package.objects.create(name='Pkg', price=Decimal('10.00'))
        cls.payment = Payment.objects.create(
            user=cls.user, package=cls.package,
            amount=Decimal('10.00'), status='succeeded',
        )

    def test_process_refund(self):
        self.client.login(username='acc', password='password1!')
        resp = self.client.post(reverse('process_refund', args=[self.payment.id]))
        self.assertEqual(resp.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')


class ManageTeachersViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_manage_teachers(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('manage_teachers'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('classes', resp.context)


class BulkStudentRegistrationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = CustomUser.objects.create_user('teacher', 'wlhtestmails+tc@gmail.com', 'password1!')
        _assign_role(cls.teacher, Role.TEACHER)

    def test_get_bulk_register(self):
        self.client.login(username='teacher', password='password1!')
        resp = self.client.get(reverse('bulk_student_registration'))
        self.assertEqual(resp.status_code, 200)

    def test_post_bulk_register(self):
        self.client.login(username='teacher', password='password1!')
        resp = self.client.post(reverse('bulk_student_registration'), {
            'students_data': 'bulkuser1,wlhtestmails+bulk1@gmail.com,password1!\nbulkuser2,wlhtestmails+bulk2@gmail.com,password1!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(CustomUser.objects.filter(username='bulkuser1').exists())
        self.assertTrue(CustomUser.objects.filter(username='bulkuser2').exists())


class ContactViewTests(TestCase):
    def test_get_contact_page(self):
        resp = self.client.get(reverse('contact'))
        self.assertEqual(resp.status_code, 200)

    def test_get_contact_page_sent(self):
        resp = self.client.get(reverse('contact') + '?sent=1')
        self.assertEqual(resp.status_code, 200)

    def test_post_contact_success(self):
        resp = self.client.post(reverse('contact'), {
            'name': 'Test User',
            'email': 'wlhtestmails+test@gmail.com',
            'subject': CONTACT_SUBJECT_CHOICES[0][0],
            'message': 'Hello, this is a test message.',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('sent=1', resp.url)

    def test_post_contact_missing_fields(self):
        resp = self.client.post(reverse('contact'), {
            'name': '',
            'email': '',
            'subject': '',
            'message': '',
        })
        self.assertEqual(resp.status_code, 200)  # re-render with errors

    def test_post_contact_honeypot_filled(self):
        """Bot detection: if honeypot 'website' field is filled, silently redirect."""
        resp = self.client.post(reverse('contact'), {
            'name': 'Bot',
            'email': 'bot@spam.com',
            'subject': 'general',
            'message': 'spam',
            'website': 'http://spam.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('sent=1', resp.url)
        # No ContactMessage should be saved
        self.assertEqual(ContactMessage.objects.count(), 0)


class ClassProgressListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)
        cls.teacher = _setup_teacher(cls.school, cls.dept)
        cls.classroom = _setup_classroom(cls.school, cls.dept, cls.teacher, cls.subj)

    def test_teacher_can_view(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('class_progress_list'))
        self.assertEqual(resp.status_code, 200)


# ============================================================================
# views_admin.py Tests
# ============================================================================


class AdminDashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_hoi_can_access(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('school_data', resp.context)
        self.assertEqual(resp.context['total_schools'], 1)

    def test_admin_can_access(self):
        admin = CustomUser.objects.create_user('admin2', 'wlhtestmails+admin2@gmail.com', 'password1!')
        _assign_role(admin, Role.ADMIN)
        School.objects.create(name='Admin School', slug='admin-school', admin=admin)
        self.client.login(username='admin2', password='password1!')
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)


class SchoolCreateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_create_form(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_create'))
        self.assertEqual(resp.status_code, 200)

    def test_post_create_school(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_create'), {
            'name': 'New School',
            'address': '123 Main St',
            'phone': '555-1234',
            'email': 'wlhtestmails+school@gmail.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(School.objects.filter(name='New School').exists())

    def test_post_create_school_no_name(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_create'), {'name': ''})
        self.assertEqual(resp.status_code, 200)  # re-render with error

    def test_post_create_duplicate_slug(self):
        """Slug uniqueness: second school with same name should get incremented slug."""
        self.client.login(username='testhoi', password='password1!')
        self.client.post(reverse('admin_school_create'), {'name': 'Slug Test'})
        self.client.post(reverse('admin_school_create'), {'name': 'Slug Test'})
        slugs = list(School.objects.filter(name='Slug Test').values_list('slug', flat=True))
        self.assertEqual(len(slugs), 2)
        self.assertNotEqual(slugs[0], slugs[1])


class SchoolDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.dept, cls.subj = _setup_department(cls.school, head=cls.hoi)

    def test_get_school_detail(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_detail', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['school'], self.school)

    def test_other_user_cannot_access(self):
        other = CustomUser.objects.create_user('other', 'wlhtestmails+other@gmail.com', 'password1!')
        _assign_role(other, Role.HEAD_OF_INSTITUTE)
        self.client.login(username='other', password='password1!')
        resp = self.client.get(reverse('admin_school_detail', args=[self.school.id]))
        self.assertEqual(resp.status_code, 404)


class SchoolEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_edit_form(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_edit', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['school'], self.school)

    def test_post_edit_school(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_edit', args=[self.school.id]), {
            'name': 'Renamed School',
            'address': '456 Other St',
            'phone': '555-9999',
            'email': 'wlhtestmails+new@gmail.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, 'Renamed School')

    def test_post_edit_school_no_name(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_edit', args=[self.school.id]), {
            'name': '',
        })
        self.assertEqual(resp.status_code, 200)  # re-render with error


class SchoolToggleActiveViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_toggle_deactivate(self):
        self.client.login(username='testhoi', password='password1!')
        self.assertTrue(self.school.is_active)
        resp = self.client.post(reverse('admin_school_toggle_active', args=[self.school.id]))
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertFalse(self.school.is_active)

    def test_toggle_get_redirects(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_toggle_active', args=[self.school.id]))
        self.assertEqual(resp.status_code, 302)


class SchoolDeleteViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_delete_redirects_to_toggle(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_delete', args=[self.school.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('toggle-active', resp.url)


class ManageRedirectViewTests(TestCase):
    """Test the admin redirect views: ManageTeachersRedirect, ManageStudentsRedirect, etc."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_manage_teachers_redirect(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_manage_teachers'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('teachers', resp.url)

    def test_manage_students_redirect(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_manage_students'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('students', resp.url)

    def test_manage_departments_redirect(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_manage_departments'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('departments', resp.url)

    def test_manage_subjects_redirect_no_dept(self):
        """Without a department, redirects to departments page."""
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_manage_subjects'))
        self.assertEqual(resp.status_code, 302)

    def test_manage_teachers_redirect_no_school(self):
        """User with no school redirects to create school."""
        user = CustomUser.objects.create_user('noschool', 'wlhtestmails+ns@gmail.com', 'password1!')
        _assign_role(user, Role.HEAD_OF_INSTITUTE)
        self.client.login(username='noschool', password='password1!')
        resp = self.client.get(reverse('admin_manage_teachers'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('create', resp.url)


class SchoolTeacherManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_teacher_list(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_teachers', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('school_teachers', resp.context)
        self.assertIn('role_choices', resp.context)

    def test_post_create_teacher(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_teachers', args=[self.school.id]), {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'wlhtestmails+jane@gmail.com',
            'password': 'securepass123',
            'role': 'teacher',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(email='wlhtestmails+jane@gmail.com').exists())
        self.assertTrue(
            SchoolTeacher.objects.filter(school=self.school, teacher__email='wlhtestmails+jane@gmail.com').exists()
        )

    def test_post_create_teacher_validation_errors(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_teachers', args=[self.school.id]), {
            'first_name': '',
            'last_name': '',
            'email': 'invalid',
            'password': 'short',
        })
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors


class SchoolTeacherRemoveViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.teacher = _setup_teacher(cls.school)

    def test_remove_teacher(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_school_teacher_remove', args=[self.school.id, self.teacher.id])
        )
        self.assertEqual(resp.status_code, 302)
        st = SchoolTeacher.objects.get(school=self.school, teacher=self.teacher)
        self.assertFalse(st.is_active)

    def test_remove_nonexistent_teacher(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_school_teacher_remove', args=[self.school.id, 99999])
        )
        self.assertEqual(resp.status_code, 302)  # redirect with warning


class SchoolStudentManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_student_list(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_students', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('school_students', resp.context)

    def test_post_create_student(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_students', args=[self.school.id]), {
            'first_name': 'Alice',
            'last_name': 'Smith',
            'email': 'wlhtestmails+alice@gmail.com',
            'password': 'securepass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CustomUser.objects.filter(email='wlhtestmails+alice@gmail.com').exists())
        self.assertTrue(
            SchoolStudent.objects.filter(school=self.school, student__email='wlhtestmails+alice@gmail.com').exists()
        )

    def test_post_create_student_validation_errors(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_students', args=[self.school.id]), {
            'first_name': '',
            'last_name': '',
            'email': 'bad',
            'password': 'short',
        })
        self.assertEqual(resp.status_code, 200)


class SchoolStudentEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.student = _setup_student(cls.school)

    def test_edit_student(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_school_student_edit', args=[self.school.id, self.student.id]),
            {
                'first_name': 'Updated',
                'last_name': 'Name',
                'email': 'wlhtestmails+updated@gmail.com',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Updated')


class SchoolStudentRemoveViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()
        cls.student = _setup_student(cls.school)

    def test_remove_student(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_school_student_remove', args=[self.school.id, self.student.id])
        )
        self.assertEqual(resp.status_code, 302)
        ss = SchoolStudent.objects.get(school=self.school, student=self.student)
        self.assertFalse(ss.is_active)

    def test_remove_nonexistent_student(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_school_student_remove', args=[self.school.id, 99999])
        )
        self.assertEqual(resp.status_code, 302)


class AcademicYearCreateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_form(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(
            reverse('admin_academic_year_create', args=[self.school.id])
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_create_academic_year(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_academic_year_create', args=[self.school.id]),
            {
                'year': '2026',
                'start_date': '2026-02-01',
                'end_date': '2026-12-15',
            },
        )
        self.assertEqual(resp.status_code, 302)
        from classroom.models import AcademicYear
        self.assertTrue(AcademicYear.objects.filter(school=self.school, year=2026).exists())

    def test_post_missing_fields(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_academic_year_create', args=[self.school.id]),
            {'year': '', 'start_date': '', 'end_date': ''},
        )
        self.assertEqual(resp.status_code, 200)  # re-render with error

    def test_post_invalid_year(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_academic_year_create', args=[self.school.id]),
            {'year': 'abc', 'start_date': '2026-01-01', 'end_date': '2026-12-01'},
        )
        self.assertEqual(resp.status_code, 200)

    def test_post_duplicate_year(self):
        from classroom.models import AcademicYear
        AcademicYear.objects.create(
            school=self.school, year=2025,
            start_date='2025-02-01', end_date='2025-12-15',
        )
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(
            reverse('admin_academic_year_create', args=[self.school.id]),
            {'year': '2025', 'start_date': '2025-02-01', 'end_date': '2025-12-15'},
        )
        self.assertEqual(resp.status_code, 200)


class SchoolSubjectManageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi, cls.school = _setup_school()

    def test_get_subjects(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.get(reverse('admin_school_subjects', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)

    def test_post_create_subject(self):
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_subjects', args=[self.school.id]), {
            'action': 'create',
            'name': 'Science',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(school=self.school, name='Science').exists())

    def test_post_edit_subject(self):
        subj = Subject.objects.create(name='Art', slug='art', school=self.school)
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_subjects', args=[self.school.id]), {
            'action': 'edit',
            'subject_id': subj.id,
            'name': 'Fine Art',
        })
        self.assertEqual(resp.status_code, 302)
        subj.refresh_from_db()
        self.assertEqual(subj.name, 'Fine Art')

    def test_post_delete_subject(self):
        subj = Subject.objects.create(name='Music', slug='music', school=self.school)
        self.client.login(username='testhoi', password='password1!')
        resp = self.client.post(reverse('admin_school_subjects', args=[self.school.id]), {
            'action': 'delete',
            'subject_id': subj.id,
        })
        self.assertEqual(resp.status_code, 302)
        subj.refresh_from_db()
        self.assertFalse(subj.is_active)


class HelperFunctionTests(TestCase):
    """Test utility functions in views.py."""

    def test_format_seconds_minutes(self):
        from classroom.views import _format_seconds
        self.assertEqual(_format_seconds(0), '0m')
        self.assertEqual(_format_seconds(120), '2m')
        self.assertEqual(_format_seconds(1620), '27m')

    def test_format_seconds_hours(self):
        from classroom.views import _format_seconds
        self.assertEqual(_format_seconds(3600), '1h 0m')
        self.assertEqual(_format_seconds(3900), '1h 5m')
        self.assertEqual(_format_seconds(7200), '2h 0m')

    def test_pct_colour(self):
        from classroom.views import _pct_colour
        self.assertIn('gray', _pct_colour(None))
        self.assertIn('green-600', _pct_colour(95))
        self.assertIn('green-400', _pct_colour(80))
        self.assertIn('green-200', _pct_colour(65))
        self.assertIn('yellow', _pct_colour(50))
        self.assertIn('orange', _pct_colour(35))
        self.assertIn('red', _pct_colour(20))
