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
    DepartmentTeacher, Expense, School, SchoolStudent, SchoolTeacher, Subject,
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


def _enrol_student(school, username='stu1', **kwargs):
    stu = _user(username, Role.STUDENT, **kwargs)
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


# ---------------------------------------------------------------------------
# CSV export (CPP-347)
# ---------------------------------------------------------------------------

class TestStudentReportCSVExport(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('csv_hoi', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)

        self.stu1, self.ss1 = _enrol_student(self.school, 'csv_stu1',
                                              first_name='Alice', last_name='Anderson')
        self.stu2, self.ss2 = _enrol_student(self.school, 'csv_stu2',
                                              first_name='Bob', last_name='Brown')
        self.cls = _classroom(self.school)

    def _rows(self, resp):
        import csv
        import io
        content = resp.content.decode('utf-8')
        return list(csv.reader(io.StringIO(content)))

    def _dicts(self, resp):
        """Parse the CSV into header-keyed dicts (robust to column order)."""
        import csv
        import io
        content = resp.content.decode('utf-8')
        return list(csv.DictReader(io.StringIO(content)))

    def test_export_returns_csv_attachment(self):
        resp = self.client.get(URL, {'export': 'csv'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('student_report.csv', resp['Content-Disposition'])

    def test_export_has_header_and_all_rows(self):
        rows = self._rows(self.client.get(URL, {'export': 'csv'}))
        self.assertEqual(rows[0][0], 'Student Name')
        for col in ('Is Subscribed', 'Parent 1 Name', 'Parent 1 Email',
                    'Parent 1 Phone', 'Parent 1 Relationship', 'Parent 2 Name'):
            self.assertIn(col, rows[0])
        # header + 2 students
        self.assertEqual(len(rows), 3)

    def test_export_ignores_pagination(self):
        # Even with a page param, export returns every matching student
        for i in range(3, 8):
            _enrol_student(self.school, f'csv_extra{i}')
        rows = self._rows(self.client.get(URL, {'export': 'csv', 'page': '2'}))
        self.assertEqual(len(rows), 1 + 7)  # header + 7 students

    def test_export_respects_filters(self):
        ClassStudent.objects.create(classroom=self.cls, student=self.stu1, is_active=True)
        rows = self._rows(self.client.get(URL, {'export': 'csv', 'no_class': '1'}))
        names = [r[0] for r in rows[1:]]
        self.assertIn('Bob Brown', names)
        self.assertNotIn('Alice Anderson', names)

    def test_export_includes_parent_user_contact(self):
        from classroom.models import ParentStudent
        parent = _user('csv_parent1', Role.PARENT,
                       first_name='Pat', last_name='Parent', phone='021555111')
        ParentStudent.objects.create(
            parent=parent, student=self.stu1, school=self.school,
            relationship='mother', is_primary_contact=True, is_active=True,
        )
        alice = next(r for r in self._dicts(self.client.get(URL, {'export': 'csv'}))
                     if r['Student Name'] == 'Alice Anderson')
        self.assertEqual(alice['Parent 1 Name'], 'Pat Parent')
        self.assertEqual(alice['Parent 1 Email'], parent.email)
        self.assertEqual(alice['Parent 1 Phone'], '021555111')
        self.assertEqual(alice['Parent 1 Relationship'], 'Mother')

    def test_export_includes_guardian_contact(self):
        from classroom.models import Guardian, StudentGuardian
        guardian = Guardian.objects.create(
            school=self.school, first_name='Gina', last_name='Guardian',
            email='gina.guardian@example.com', phone='021555222',
            relationship='guardian',
        )
        StudentGuardian.objects.create(student=self.stu2, guardian=guardian, is_primary=True)
        bob = next(r for r in self._dicts(self.client.get(URL, {'export': 'csv'}))
                   if r['Student Name'] == 'Bob Brown')
        self.assertEqual(bob['Parent 1 Name'], 'Gina Guardian')
        self.assertEqual(bob['Parent 1 Email'], 'gina.guardian@example.com')
        self.assertEqual(bob['Parent 1 Phone'], '021555222')
        self.assertEqual(bob['Parent 1 Relationship'], 'Guardian')

    def test_export_lists_two_parents_with_primary_first(self):
        from classroom.models import Guardian, ParentStudent, StudentGuardian
        # Non-primary parent-user link + primary guardian → guardian must be Parent 1.
        parent = _user('csv_two_parent', Role.PARENT,
                       first_name='Sam', last_name='Secondary')
        ParentStudent.objects.create(
            parent=parent, student=self.stu1, school=self.school,
            is_primary_contact=False, is_active=True,
        )
        guardian = Guardian.objects.create(
            school=self.school, first_name='Prim', last_name='Primary',
            email='prim.primary@example.com',
        )
        StudentGuardian.objects.create(student=self.stu1, guardian=guardian, is_primary=True)
        alice = next(r for r in self._dicts(self.client.get(URL, {'export': 'csv'}))
                     if r['Student Name'] == 'Alice Anderson')
        self.assertEqual(alice['Parent 1 Name'], 'Prim Primary')   # primary first
        self.assertEqual(alice['Parent 2 Name'], 'Sam Secondary')  # non-primary second

    def test_export_is_subscribed_column(self):
        from billing.models import Subscription
        Subscription.objects.create(
            user=self.stu1, status=Subscription.STATUS_ACTIVE,
        )
        # stu2 deliberately has no subscription.
        dicts = self._dicts(self.client.get(URL, {'export': 'csv'}))
        alice = next(r for r in dicts if r['Student Name'] == 'Alice Anderson')
        bob = next(r for r in dicts if r['Student Name'] == 'Bob Brown')
        self.assertEqual(alice['Is Subscribed'], 'Yes')
        self.assertEqual(bob['Is Subscribed'], 'No')

    def test_export_tenant_isolation(self):
        other_hoi = _user('csv_other_hoi', Role.HEAD_OF_INSTITUTE)
        other_school = _school(other_hoi)
        _enrol_student(other_school, 'csv_other_stu')
        rows = self._rows(self.client.get(URL, {'export': 'csv'}))
        self.assertEqual(len(rows), 3)  # header + own 2 students only

    def test_export_does_not_leak_other_school_guardian(self):
        # stu1 also has a guardian belonging to a school this admin can't see.
        from classroom.models import Guardian, StudentGuardian
        other_hoi = _user('csv_leak_hoi', Role.HEAD_OF_INSTITUTE)
        other_school = _school(other_hoi)
        foreign_guardian = Guardian.objects.create(
            school=other_school, first_name='Foreign', last_name='Guardian',
            email='foreign.guardian@example.com',
        )
        StudentGuardian.objects.create(student=self.stu1, guardian=foreign_guardian)
        alice = next(r for r in self._dicts(self.client.get(URL, {'export': 'csv'}))
                     if r['Student Name'] == 'Alice Anderson')
        self.assertNotEqual(alice['Parent 1 Name'], 'Foreign Guardian')
        self.assertNotIn('foreign.guardian@example.com', alice.values())

    def test_export_requires_admin_role(self):
        stu = _user('csv_bad_stu', Role.STUDENT)
        self.client.force_login(stu)
        resp = self.client.get(URL, {'export': 'csv'})
        self.assertEqual(resp.status_code, 302)

    def test_export_neutralises_formula_injection(self):
        # A student whose name starts with '=' must not be exported as a formula
        self.stu1.first_name = '=cmd|calc'
        self.stu1.last_name = ''
        self.stu1.save()
        rows = self._rows(self.client.get(URL, {'export': 'csv'}))
        injected = next(r for r in rows[1:] if 'cmd|calc' in r[0])
        self.assertTrue(injected[0].startswith("'="))


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


# ===========================================================================
# Expense Report Tests (CPP-297)
# ===========================================================================

import datetime
from django.urls import reverse as _reverse

EXPENSE_URL = _reverse('reports_expenses')
EXPENSE_ADD_URL = _reverse('expense_add')


def _expense(school, created_by, **kwargs):
    defaults = {
        'category': 'rent',
        'description': 'Monthly rent',
        'amount': Decimal('1500.00'),
        'date': datetime.date(2026, 5, 1),
    }
    defaults.update(kwargs)
    return Expense.objects.create(school=school, created_by=created_by, **defaults)


class TestExpenseReportAccess(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('exp_hoi', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)

    def test_unauthenticated_redirects(self):
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_student_gets_403(self):
        stu = _user('exp_stu', Role.STUDENT)
        self.client.force_login(stu)
        resp = self.client.get(EXPENSE_URL)
        self.assertIn(resp.status_code, [302, 403])

    def test_teacher_gets_403(self):
        t = _user('exp_teacher', Role.TEACHER)
        self.client.force_login(t)
        resp = self.client.get(EXPENSE_URL)
        self.assertIn(resp.status_code, [302, 403])

    def test_hoi_can_access(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.status_code, 200)

    def test_hod_can_access(self):
        hod = _user('exp_hod', Role.HEAD_OF_DEPARTMENT)
        _dept(self.school, head=hod)
        self.client.force_login(hod)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.status_code, 200)


class TestExpenseReportScoping(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('scope_hoi', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.dept = _dept(self.school)
        self.e1 = _expense(self.school, self.hoi, description='Rent A')
        self.e2 = _expense(self.school, self.hoi, description='Supplies B',
                           category='supplies', department=self.dept)

    def test_hoi_sees_all_school_expenses(self):
        self.client.force_login(self.hoi)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.context['total_count'], 2)

    def test_tenant_isolation(self):
        other_hoi = _user('other_hoi_exp', Role.HEAD_OF_INSTITUTE)
        other_school = _school(other_hoi)
        _expense(other_school, other_hoi, description='Other school rent')
        self.client.force_login(self.hoi)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.context['total_count'], 2)

    def test_hod_sees_only_department_expenses(self):
        hod = _user('scope_hod', Role.HEAD_OF_DEPARTMENT)
        dept = _dept(self.school, head=hod)
        _expense(self.school, self.hoi, description='Dept expense',
                 category='utilities', department=dept)
        self.client.force_login(hod)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.context['total_count'], 1)
        self.assertEqual(resp.context['page_obj'][0].description, 'Dept expense')

    def test_hod_no_departments_sees_empty(self):
        hod = _user('scope_hod_empty', Role.HEAD_OF_DEPARTMENT)
        self.client.force_login(hod)
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.context['total_count'], 0)


class TestExpenseReportFilters(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('filt_hoi', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.dept = _dept(self.school)
        self.e1 = _expense(self.school, self.hoi, category='rent',
                           date=datetime.date(2026, 3, 1))
        self.e2 = _expense(self.school, self.hoi, category='supplies',
                           department=self.dept, date=datetime.date(2026, 5, 15))
        self.e3 = _expense(self.school, self.hoi, category='rent',
                           date=datetime.date(2026, 6, 1))
        self.client.force_login(self.hoi)

    def test_filter_by_category(self):
        resp = self.client.get(EXPENSE_URL, {'category': 'rent'})
        self.assertEqual(resp.context['total_count'], 2)

    def test_filter_by_department(self):
        resp = self.client.get(EXPENSE_URL, {'department_id': self.dept.pk})
        self.assertEqual(resp.context['total_count'], 1)

    def test_filter_by_date_range(self):
        resp = self.client.get(EXPENSE_URL, {
            'date_from': '2026-04-01', 'date_to': '2026-05-31',
        })
        self.assertEqual(resp.context['total_count'], 1)

    def test_combined_filters(self):
        resp = self.client.get(EXPENSE_URL, {
            'category': 'supplies', 'department_id': self.dept.pk,
        })
        self.assertEqual(resp.context['total_count'], 1)

    def test_total_amount_in_context(self):
        resp = self.client.get(EXPENSE_URL)
        self.assertEqual(resp.context['total_amount'], Decimal('4500.00'))

    def test_htmx_returns_partial(self):
        resp = self.client.get(EXPENSE_URL, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/_partials/expense_report_table.html')
        self.assertTemplateNotUsed(resp, 'reports/expenses.html')

    def test_full_request_returns_full_page(self):
        resp = self.client.get(EXPENSE_URL)
        self.assertTemplateUsed(resp, 'reports/expenses.html')
        self.assertTemplateUsed(resp, 'reports/_partials/expense_report_table.html')


class TestExpenseCRUD(TestCase):

    def setUp(self):
        self.client = Client()
        self.hoi = _user('crud_hoi', Role.HEAD_OF_INSTITUTE)
        self.school = _school(self.hoi)
        self.client.force_login(self.hoi)

    def test_create_expense(self):
        resp = self.client.post(EXPENSE_ADD_URL, {
            'category': 'utilities',
            'description': 'Electricity bill',
            'amount': '250.00',
            'date': '2026-05-10',
        })
        self.assertRedirects(resp, EXPENSE_URL)
        self.assertTrue(Expense.objects.filter(description='Electricity bill').exists())
        expense = Expense.objects.get(description='Electricity bill')
        self.assertEqual(expense.school, self.school)
        self.assertEqual(expense.created_by, self.hoi)

    def test_edit_expense(self):
        expense = _expense(self.school, self.hoi)
        url = _reverse('expense_edit', args=[expense.pk])
        resp = self.client.post(url, {
            'category': 'maintenance',
            'description': 'Updated description',
            'amount': '2000.00',
            'date': '2026-05-05',
        })
        self.assertRedirects(resp, EXPENSE_URL)
        expense.refresh_from_db()
        self.assertEqual(expense.description, 'Updated description')
        self.assertEqual(expense.category, 'maintenance')

    def test_delete_expense(self):
        expense = _expense(self.school, self.hoi)
        url = _reverse('expense_delete', args=[expense.pk])
        resp = self.client.post(url)
        self.assertRedirects(resp, EXPENSE_URL)
        self.assertFalse(Expense.objects.filter(pk=expense.pk).exists())

    def test_cannot_edit_other_school_expense(self):
        other_hoi = _user('other_crud_hoi', Role.HEAD_OF_INSTITUTE)
        other_school = _school(other_hoi)
        expense = _expense(other_school, other_hoi)
        url = _reverse('expense_edit', args=[expense.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_cannot_delete_other_school_expense(self):
        other_hoi = _user('other_crud_hoi2', Role.HEAD_OF_INSTITUTE)
        other_school = _school(other_hoi)
        expense = _expense(other_school, other_hoi)
        url = _reverse('expense_delete', args=[expense.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)

    def test_hod_cannot_create_expense(self):
        hod = _user('crud_hod', Role.HEAD_OF_DEPARTMENT)
        _dept(self.school, head=hod)
        self.client.force_login(hod)
        resp = self.client.get(EXPENSE_ADD_URL)
        self.assertIn(resp.status_code, [302, 403])

    def test_create_expense_get_renders_form(self):
        resp = self.client.get(EXPENSE_ADD_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'reports/expense_form.html')

    def test_edit_expense_get_renders_form(self):
        expense = _expense(self.school, self.hoi)
        url = _reverse('expense_edit', args=[expense.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Save Changes')
