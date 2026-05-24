"""
Unit tests for classroom/views_reports.py — StudentReportView.

Coverage:
- Authentication & role gating
- Tenant isolation
- HoI vs HoD scoping
- All filter combinations
- Edge cases (empty school, duplicate class enrolments)
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentSubject,
    DepartmentTeacher, School, SchoolStudent, SchoolTeacher, Subject,
)

URL = reverse('reports_students')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role(name):
    r, _ = Role.objects.get_or_create(name=name, defaults={'display_name': name})
    return r


def _user(username, role_name, **kwargs):
    u = CustomUser.objects.create_user(
        username=username,
        password='password1!',
        email=f'wlhtestmails+{username}@gmail.com',
        **kwargs,
    )
    UserRole.objects.get_or_create(user=u, role=_role(role_name))
    return u


def _school(admin):
    school = School.objects.create(name='Test School', slug=f'ts-{admin.pk}', admin=admin)
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{admin.pk}', price=Decimal('89.00'),
        stripe_price_id='price_test', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=admin, defaults={'role': 'head_of_institute'},
    )
    return school


def _enrol_student(school, username='stu1'):
    stu = _user(username, Role.STUDENT)
    ss = SchoolStudent.objects.create(school=school, student=stu)
    return stu, ss


def _subject():
    subj, _ = Subject.objects.get_or_create(
        slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
    )
    return subj


_dept_seq = 0


def _dept(school, head=None):
    global _dept_seq
    _dept_seq += 1
    dept = Department.objects.create(
        school=school, name=f'Dept {_dept_seq}', slug=f'dept-{school.pk}-{_dept_seq}',
    )
    DepartmentSubject.objects.create(department=dept, subject=_subject())
    if head:
        dept.head = head
        dept.save()
        DepartmentTeacher.objects.create(department=dept, teacher=head)
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=head, defaults={'role': 'head_of_department'},
        )
    return dept


def _classroom(school, dept=None):
    return ClassRoom.objects.create(
        name='Class A', school=school, department=dept, is_active=True,
    )


# ---------------------------------------------------------------------------
# Authentication & role gating
# ---------------------------------------------------------------------------

class TestStudentReportAccess(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('hoi1', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)

    def test_student_report_requires_login(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_student_report_requires_admin_role_student(self):
        stu = _user('stu_bad', Role.STUDENT)
        self.client.force_login(stu)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_student_report_requires_admin_role_teacher(self):
        teacher = _user('teach_bad', Role.TEACHER)
        self.client.force_login(teacher)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_student_report_requires_admin_role_parent(self):
        parent = _user('parent_bad', Role.PARENT)
        self.client.force_login(parent)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)

    def test_hoi_can_access(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)

    def test_institute_owner_can_access(self):
        owner = _user('owner1', Role.INSTITUTE_OWNER)
        school = _school(owner)
        self.client.force_login(owner)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        hod = _user('hod1', Role.HEAD_OF_DEPARTMENT)
        _dept(self.school, head=hod)
        self.client.force_login(hod)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# HoI sees all school students
# ---------------------------------------------------------------------------

class TestHoiScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('hoi2', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)

    def test_hoi_sees_all_school_students(self):
        stu1, _ = _enrol_student(self.school, 's1')
        stu2, _ = _enrol_student(self.school, 's2')
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 2)

    def test_empty_school_returns_empty_list(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 0)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi_a = _user('hoi_a', Role.HEAD_OF_INSTITUTE)
        self.school_a = _school(self.hoi_a)

        self.hoi_b = _user('hoi_b', Role.HEAD_OF_INSTITUTE)
        self.school_b = _school(self.hoi_b)

    def test_school_a_hoi_cannot_see_school_b_students(self):
        stu_b, _ = _enrol_student(self.school_b, 'stu_b1')
        self.client.force_login(self.hoi_a)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        # School A has no students — School B's student must not appear
        self.assertEqual(resp.context['total_count'], 0)


# ---------------------------------------------------------------------------
# HoD scoping
# ---------------------------------------------------------------------------

class TestHodScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('hoi3', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.hod = _user('hod2', Role.HEAD_OF_DEPARTMENT)
        self.dept = _dept(self.school, head=self.hod)
        self.other_dept = _dept(self.school)

    def test_hod_sees_only_department_students(self):
        # Student in HoD's class
        stu_in, _ = _enrol_student(self.school, 'stu_in')
        cls = _classroom(self.school, dept=self.dept)
        ClassStudent.objects.create(classroom=cls, student=stu_in, is_active=True)

        # Student in another department's class
        stu_out, _ = _enrol_student(self.school, 'stu_out')
        cls2 = _classroom(self.school, dept=self.other_dept)
        ClassStudent.objects.create(classroom=cls2, student=stu_out, is_active=True)

        self.client.force_login(self.hod)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 1)
        student_ids = [ss.student_id for ss in resp.context['page_obj']]
        self.assertIn(stu_in.pk, student_ids)
        self.assertNotIn(stu_out.pk, student_ids)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestFilters(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('hoi4', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)

        self.stu1, self.ss1 = _enrol_student(self.school, 'f_stu1')
        self.stu2, self.ss2 = _enrol_student(self.school, 'f_stu2')
        self.cls = _classroom(self.school)

    def test_filter_by_class(self):
        ClassStudent.objects.create(classroom=self.cls, student=self.stu1, is_active=True)
        resp = self.client.get(URL, {'class_id': self.cls.pk})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_status_active(self):
        self.ss2.is_active = False
        self.ss2.save()
        resp = self.client.get(URL, {'status': 'active'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_status_inactive(self):
        self.ss2.is_active = False
        self.ss2.save()
        resp = self.client.get(URL, {'status': 'inactive'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_payment_blocked(self):
        self.stu1.is_blocked = True
        self.stu1.save()
        resp = self.client.get(URL, {'payment': 'blocked'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_not_in_class(self):
        # Only stu1 is in a class
        ClassStudent.objects.create(classroom=self.cls, student=self.stu1, is_active=True)
        resp = self.client.get(URL, {'no_class': '1'})
        self.assertEqual(resp.context['total_count'], 1)
        student_ids = [ss.student_id for ss in resp.context['page_obj']]
        self.assertIn(self.stu2.pk, student_ids)
        self.assertNotIn(self.stu1.pk, student_ids)

    def test_combined_filters(self):
        ClassStudent.objects.create(classroom=self.cls, student=self.stu1, is_active=True)
        self.stu2.is_blocked = True
        self.stu2.save()
        # Active + in class → only stu1
        resp = self.client.get(URL, {'status': 'active', 'class_id': self.cls.pk})
        self.assertEqual(resp.context['total_count'], 1)

    def test_student_in_multiple_classes_appears_once(self):
        cls2 = ClassRoom.objects.create(name='Class B', school=self.school, is_active=True)
        ClassStudent.objects.create(classroom=self.cls, student=self.stu1, is_active=True)
        ClassStudent.objects.create(classroom=cls2, student=self.stu1, is_active=True)
        resp = self.client.get(URL)
        self.assertEqual(resp.context['total_count'], 2)  # 2 students, not 3 rows

    def test_htmx_request_returns_partial(self):
        resp = self.client.get(URL, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/_partials/student_report_table.html')
        self.assertTemplateNotUsed(resp, 'reports/students.html')

    def test_full_request_returns_full_page(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/students.html')
        self.assertTemplateUsed(resp, 'reports/_partials/student_report_table.html')


# ===========================================================================
# Teacher Report Tests (CPP-295)
# ===========================================================================

TEACHER_URL = reverse('reports_teachers')


def _add_teacher(school, username='teacher1', role='teacher', dept=None, is_active=True):
    teacher = _user(username, Role.TEACHER)
    st = SchoolTeacher.objects.create(
        school=school, teacher=teacher, role=role, is_active=is_active,
    )
    if dept:
        DepartmentTeacher.objects.create(department=dept, teacher=teacher)
    return teacher, st


class TestTeacherReportAccess(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('tr_hoi1', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)

    def test_requires_login(self):
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_student_denied(self):
        stu = _user('tr_stu', Role.STUDENT)
        self.client.force_login(stu)
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 302)

    def test_regular_teacher_denied(self):
        teacher = _user('tr_teach', Role.TEACHER)
        self.client.force_login(teacher)
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 302)

    def test_hoi_can_access(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        hod = _user('tr_hod1', Role.HEAD_OF_DEPARTMENT)
        _dept(self.school, head=hod)
        self.client.force_login(hod)
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 200)


class TestTeacherReportHoiScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('tr_hoi2', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)

    def test_hoi_sees_all_teachers(self):
        _add_teacher(self.school, 'tr_t1')
        _add_teacher(self.school, 'tr_t2')
        resp = self.client.get(TEACHER_URL)
        # +1 for the HoI who is also a SchoolTeacher
        self.assertEqual(resp.context['total_count'], 3)

    def test_empty_school_only_shows_hoi(self):
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.context['total_count'], 1)


class TestTeacherReportTenantIsolation(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi_a = _user('tr_hoi_a', Role.HEAD_OF_INSTITUTE)
        self.school_a = _school(self.hoi_a)
        self.hoi_b = _user('tr_hoi_b', Role.HEAD_OF_INSTITUTE)
        self.school_b = _school(self.hoi_b)

    def test_cannot_see_other_school_teachers(self):
        _add_teacher(self.school_b, 'tr_other')
        self.client.force_login(self.hoi_a)
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.context['total_count'], 1)  # only self


class TestTeacherReportHodScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('tr_hoi3', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.hod = _user('tr_hod2', Role.HEAD_OF_DEPARTMENT)
        self.dept = _dept(self.school, head=self.hod)
        self.other_dept = _dept(self.school)

    def test_hod_sees_own_dept_teachers(self):
        t1, _ = _add_teacher(self.school, 'tr_dt1', dept=self.dept)
        t2, _ = _add_teacher(self.school, 'tr_dt2', dept=self.other_dept)
        self.client.force_login(self.hod)
        resp = self.client.get(TEACHER_URL)
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(t1.pk, teacher_ids)
        self.assertNotIn(t2.pk, teacher_ids)


class TestTeacherReportFilters(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('tr_hoi4', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)
        self.dept = _dept(self.school)
        self.t1, self.st1 = _add_teacher(self.school, 'tr_ft1', dept=self.dept)
        self.t2, self.st2 = _add_teacher(self.school, 'tr_ft2')

    def test_filter_by_status_active(self):
        self.st2.is_active = False
        self.st2.save()
        resp = self.client.get(TEACHER_URL, {'status': 'active'})
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t1.pk, teacher_ids)
        self.assertNotIn(self.t2.pk, teacher_ids)

    def test_filter_by_status_inactive(self):
        self.st2.is_active = False
        self.st2.save()
        resp = self.client.get(TEACHER_URL, {'status': 'inactive'})
        self.assertEqual(resp.context['total_count'], 1)
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t2.pk, teacher_ids)

    def test_filter_by_class(self):
        cls = _classroom(self.school, dept=self.dept)
        ClassTeacher.objects.create(classroom=cls, teacher=self.t1)
        resp = self.client.get(TEACHER_URL, {'class_id': cls.pk})
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t1.pk, teacher_ids)
        self.assertNotIn(self.t2.pk, teacher_ids)

    def test_filter_by_subject(self):
        subj = _subject()
        cls = ClassRoom.objects.create(
            name='Maths A', school=self.school, subject=subj, is_active=True,
        )
        ClassTeacher.objects.create(classroom=cls, teacher=self.t1)
        resp = self.client.get(TEACHER_URL, {'subject_id': subj.pk})
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t1.pk, teacher_ids)
        self.assertNotIn(self.t2.pk, teacher_ids)

    def test_filter_by_department(self):
        resp = self.client.get(TEACHER_URL, {'department_id': self.dept.pk})
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t1.pk, teacher_ids)
        self.assertNotIn(self.t2.pk, teacher_ids)

    def test_filter_by_role(self):
        self.st1.role = 'senior_teacher'
        self.st1.save()
        resp = self.client.get(TEACHER_URL, {'role': 'senior_teacher'})
        self.assertEqual(resp.context['total_count'], 1)
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertIn(self.t1.pk, teacher_ids)

    def test_filter_no_class(self):
        cls = _classroom(self.school)
        ClassTeacher.objects.create(classroom=cls, teacher=self.t1)
        resp = self.client.get(TEACHER_URL, {'no_class': '1'})
        teacher_ids = [st.teacher_id for st in resp.context['page_obj']]
        self.assertNotIn(self.t1.pk, teacher_ids)
        self.assertIn(self.t2.pk, teacher_ids)

    def test_htmx_returns_partial(self):
        resp = self.client.get(TEACHER_URL, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/_partials/teacher_report_table.html')
        self.assertTemplateNotUsed(resp, 'reports/teachers.html')

    def test_full_request_returns_full_page(self):
        resp = self.client.get(TEACHER_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/teachers.html')
        self.assertTemplateUsed(resp, 'reports/_partials/teacher_report_table.html')

    def test_annotations_departments_and_subjects(self):
        subj = _subject()
        cls = ClassRoom.objects.create(
            name='Anno Class', school=self.school, department=self.dept,
            subject=subj, is_active=True,
        )
        ClassTeacher.objects.create(classroom=cls, teacher=self.t1)
        resp = self.client.get(TEACHER_URL)
        for st in resp.context['page_obj']:
            if st.teacher_id == self.t1.pk:
                self.assertIn(self.dept.name, st.departments_list)
                self.assertIn(subj.name, st.subjects_list)
                self.assertGreaterEqual(st.active_class_count, 1)
                break
        else:
            self.fail('t1 not found in page_obj')
