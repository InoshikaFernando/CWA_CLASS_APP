"""
Tests for server-side search, ordering, and batch-save on the
admin student and teacher management pages.

Covers:
- Search across all pages (server-side ?q= parameter)
- Ordering via ?order_by= parameter
- Batch update (save) for students (nested-form fix)
- Batch update (save) for teachers
- Pagination preserves search/order params
- Total count accuracy
"""
import uuid
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, SchoolTeacher, SchoolStudent, ClassRoom, ClassStudent,
    ClassTeacher,
)


# ---------------------------------------------------------------------------
# Helpers (match project conventions)
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


def _setup_school(username='testhoi', email='hoi@test.com'):
    user = CustomUser.objects.create_user(
        username=username, password='pass12345', email=email,
        first_name='Admin', last_name='User',
    )
    _assign_role(user, Role.HEAD_OF_INSTITUTE)
    school = School.objects.create(
        name='Test School', slug=f'test-school-{uuid.uuid4().hex[:6]}',
        admin=user,
    )
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{uuid.uuid4().hex[:6]}',
        price=Decimal('89.00'), stripe_price_id='price_test',
        class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _make_teacher(school, first, last, role='teacher', **kw):
    uname = kw.pop('username', f'{first.lower()}.{last.lower()}')
    email = kw.pop('email', f'{uname}@test.com')
    user = CustomUser.objects.create_user(
        username=uname, password='pass12345', email=email,
        first_name=first, last_name=last,
    )
    _assign_role(user, Role.TEACHER)
    SchoolTeacher.objects.update_or_create(school=school, teacher=user, defaults={'role': role, **kw})
    return user


def _make_student(school, first, last, **kw):
    uname = kw.pop('username', f'{first.lower()}.{last.lower()}')
    email = kw.pop('email', f'{uname}@test.com')
    user = CustomUser.objects.create_user(
        username=uname, password='pass12345', email=email,
        first_name=first, last_name=last,
    )
    _assign_role(user, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=user, **kw)
    return user


# ---------------------------------------------------------------------------
# Teacher search & ordering tests
# ---------------------------------------------------------------------------

class TeacherSearchTests(TestCase):
    """Server-side search for teachers via ?q= parameter."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_teacher(cls.school, 'Alice', 'Anderson')
        cls.bob = _make_teacher(cls.school, 'Bob', 'Brown')
        cls.charlie = _make_teacher(cls.school, 'Charlie', 'Clark')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_teachers', args=[self.school.id])

    def test_no_search_returns_all(self):
        """All teachers + admin (HoI auto-linked as teacher)."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        # 3 teachers + admin HoI auto-linked = 4
        self.assertEqual(resp.context['total_count'], 4)

    def test_search_by_first_name(self):
        resp = self.client.get(self.url, {'q': 'Alice'})
        self.assertEqual(resp.status_code, 200)
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)
        self.assertEqual(page.object_list[0].teacher.first_name, 'Alice')

    def test_search_by_last_name(self):
        resp = self.client.get(self.url, {'q': 'Brown'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)
        self.assertEqual(page.object_list[0].teacher.last_name, 'Brown')

    def test_search_by_email(self):
        resp = self.client.get(self.url, {'q': 'charlie.clark'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_by_username(self):
        resp = self.client.get(self.url, {'q': 'bob.brown'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_case_insensitive(self):
        resp = self.client.get(self.url, {'q': 'alice'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_no_results(self):
        resp = self.client.get(self.url, {'q': 'zzzznotfound'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 0)

    def test_search_partial_match(self):
        resp = self.client.get(self.url, {'q': 'ar'})
        page = resp.context['page']
        names = [st.teacher.last_name for st in page.object_list]
        self.assertIn('Clark', names)

    def test_q_preserved_in_context(self):
        resp = self.client.get(self.url, {'q': 'Alice'})
        self.assertEqual(resp.context['q'], 'Alice')

    def test_empty_q_treated_as_no_search(self):
        resp = self.client.get(self.url, {'q': '  '})
        self.assertEqual(resp.context['total_count'], 4)


class TeacherOrderingTests(TestCase):
    """Server-side ordering for teachers via ?order_by= parameter."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_teacher(cls.school, 'Alice', 'Zulu', role='teacher')
        cls.bob = _make_teacher(cls.school, 'Bob', 'Anderson', role='head_of_department')
        cls.charlie = _make_teacher(cls.school, 'Charlie', 'Middle', role='senior_teacher')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_teachers', args=[self.school.id])

    def test_order_name_asc(self):
        resp = self.client.get(self.url, {'order_by': 'name'})
        names = [st.teacher.first_name for st in resp.context['page']]
        # Admin (first_name='Admin') + Alice, Bob, Charlie
        self.assertEqual(names, ['Admin', 'Alice', 'Bob', 'Charlie'])

    def test_order_name_desc(self):
        resp = self.client.get(self.url, {'order_by': '-name'})
        names = [st.teacher.first_name for st in resp.context['page']]
        self.assertEqual(names, ['Charlie', 'Bob', 'Alice', 'Admin'])

    def test_order_email_asc(self):
        resp = self.client.get(self.url, {'order_by': 'email'})
        emails = [st.teacher.email for st in resp.context['page']]
        self.assertEqual(emails, sorted(emails))

    def test_order_email_desc(self):
        resp = self.client.get(self.url, {'order_by': '-email'})
        emails = [st.teacher.email for st in resp.context['page']]
        self.assertEqual(emails, sorted(emails, reverse=True))

    def test_order_role(self):
        resp = self.client.get(self.url, {'order_by': 'role'})
        roles = [st.role for st in resp.context['page']]
        self.assertEqual(roles, sorted(roles))

    def test_order_joined_asc(self):
        resp = self.client.get(self.url, {'order_by': 'joined'})
        dates = [st.joined_at for st in resp.context['page']]
        self.assertEqual(dates, sorted(dates))

    def test_order_joined_desc(self):
        resp = self.client.get(self.url, {'order_by': '-joined'})
        dates = [st.joined_at for st in resp.context['page']]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_invalid_order_defaults_to_name(self):
        resp = self.client.get(self.url, {'order_by': 'INVALID'})
        names = [st.teacher.first_name for st in resp.context['page']]
        self.assertEqual(names, ['Admin', 'Alice', 'Bob', 'Charlie'])

    def test_order_by_preserved_in_context(self):
        resp = self.client.get(self.url, {'order_by': '-email'})
        self.assertEqual(resp.context['order_by'], '-email')


class TeacherSearchWithOrderAndPaginationTests(TestCase):
    """Combined search + ordering + pagination for teachers."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        # Create 30 teachers (more than one page of 25) with common surname
        for i in range(30):
            _make_teacher(
                cls.school,
                f'Teacher{i:02d}',
                'Smith',
                username=f'teacher.smith.{i:02d}',
                email=f'teacher{i:02d}@test.com',
            )
        # One outlier with a different name
        _make_teacher(cls.school, 'Unique', 'Jones')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_teachers', args=[self.school.id])

    def test_search_smith_returns_30(self):
        resp = self.client.get(self.url, {'q': 'Smith'})
        self.assertEqual(resp.context['total_count'], 30)

    def test_search_smith_page1_has_25(self):
        resp = self.client.get(self.url, {'q': 'Smith'})
        self.assertEqual(len(resp.context['page'].object_list), 25)

    def test_search_smith_page2_has_5(self):
        resp = self.client.get(self.url, {'q': 'Smith', 'page': 2})
        self.assertEqual(len(resp.context['page'].object_list), 5)

    def test_search_jones_returns_1(self):
        resp = self.client.get(self.url, {'q': 'Jones'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_search_with_order(self):
        resp = self.client.get(self.url, {'q': 'Smith', 'order_by': '-name'})
        names = [st.teacher.first_name for st in resp.context['page']]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_search_with_show_inactive(self):
        resp = self.client.get(self.url, {'q': 'Smith', 'show_inactive': '1'})
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Student search & ordering tests
# ---------------------------------------------------------------------------

class StudentSearchTests(TestCase):
    """Server-side search for students via ?q= parameter."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_student(cls.school, 'Alice', 'Anderson')
        cls.bob = _make_student(cls.school, 'Bob', 'Brown')
        cls.charlie = _make_student(cls.school, 'Charlie', 'Clark')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_students', args=[self.school.id])

    def test_no_search_returns_all(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 3)

    def test_search_by_first_name(self):
        resp = self.client.get(self.url, {'q': 'Alice'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)
        self.assertEqual(page.object_list[0].student.first_name, 'Alice')

    def test_search_by_last_name(self):
        resp = self.client.get(self.url, {'q': 'Brown'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_by_email(self):
        resp = self.client.get(self.url, {'q': 'charlie.clark'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_by_username(self):
        resp = self.client.get(self.url, {'q': 'bob.brown'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_case_insensitive(self):
        resp = self.client.get(self.url, {'q': 'alice'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 1)

    def test_search_no_results(self):
        resp = self.client.get(self.url, {'q': 'zzzznotfound'})
        page = resp.context['page']
        self.assertEqual(len(page.object_list), 0)

    def test_q_preserved_in_context(self):
        resp = self.client.get(self.url, {'q': 'Bob'})
        self.assertEqual(resp.context['q'], 'Bob')


class StudentOrderingTests(TestCase):
    """Server-side ordering for students via ?order_by= parameter."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_student(cls.school, 'Alice', 'Zulu')
        cls.bob = _make_student(cls.school, 'Bob', 'Anderson')
        cls.charlie = _make_student(cls.school, 'Charlie', 'Middle')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_students', args=[self.school.id])

    def test_order_name_asc(self):
        resp = self.client.get(self.url, {'order_by': 'name'})
        names = [ss.student.first_name for ss in resp.context['page']]
        self.assertEqual(names, ['Alice', 'Bob', 'Charlie'])

    def test_order_name_desc(self):
        resp = self.client.get(self.url, {'order_by': '-name'})
        names = [ss.student.first_name for ss in resp.context['page']]
        self.assertEqual(names, ['Charlie', 'Bob', 'Alice'])

    def test_order_email_asc(self):
        resp = self.client.get(self.url, {'order_by': 'email'})
        emails = [ss.student.email for ss in resp.context['page']]
        self.assertEqual(emails, sorted(emails))

    def test_order_email_desc(self):
        resp = self.client.get(self.url, {'order_by': '-email'})
        emails = [ss.student.email for ss in resp.context['page']]
        self.assertEqual(emails, sorted(emails, reverse=True))

    def test_order_joined_asc(self):
        resp = self.client.get(self.url, {'order_by': 'joined'})
        dates = [ss.joined_at for ss in resp.context['page']]
        self.assertEqual(dates, sorted(dates))

    def test_order_joined_desc(self):
        resp = self.client.get(self.url, {'order_by': '-joined'})
        dates = [ss.joined_at for ss in resp.context['page']]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_order_by_classes(self):
        # Give Alice 2 classes, Bob 0
        import datetime
        c1 = ClassRoom.objects.create(
            name='Class1', school=self.school,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
        )
        c2 = ClassRoom.objects.create(
            name='Class2', school=self.school,
            start_time=datetime.time(10, 0), end_time=datetime.time(11, 0),
        )
        ClassStudent.objects.create(classroom=c1, student=self.alice)
        ClassStudent.objects.create(classroom=c2, student=self.alice)

        resp = self.client.get(self.url, {'order_by': '-classes'})
        first = resp.context['page'].object_list[0]
        self.assertEqual(first.student.first_name, 'Alice')

    def test_invalid_order_defaults_to_name(self):
        resp = self.client.get(self.url, {'order_by': 'BOGUS'})
        names = [ss.student.first_name for ss in resp.context['page']]
        self.assertEqual(names, ['Alice', 'Bob', 'Charlie'])

    def test_order_by_preserved_in_context(self):
        resp = self.client.get(self.url, {'order_by': '-email'})
        self.assertEqual(resp.context['order_by'], '-email')


class StudentSearchPaginationTests(TestCase):
    """Search across multiple pages for students."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        for i in range(30):
            _make_student(
                cls.school, f'Student{i:02d}', 'Smith',
                username=f'student.smith.{i:02d}',
                email=f'student{i:02d}@test.com',
            )
        _make_student(cls.school, 'Unique', 'Jones')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_students', args=[self.school.id])

    def test_search_across_pages(self):
        resp = self.client.get(self.url, {'q': 'Smith'})
        self.assertEqual(resp.context['total_count'], 30)

    def test_search_page2(self):
        resp = self.client.get(self.url, {'q': 'Smith', 'page': 2})
        self.assertEqual(len(resp.context['page'].object_list), 5)

    def test_search_jones(self):
        resp = self.client.get(self.url, {'q': 'Jones'})
        self.assertEqual(resp.context['total_count'], 1)


# ---------------------------------------------------------------------------
# Batch update (save) tests — verifies the nested-form fix
# ---------------------------------------------------------------------------

class StudentBatchUpdateTests(TestCase):
    """Test that batch saving students works (nested-form fix)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_student(cls.school, 'Alice', 'Anderson')
        cls.bob = _make_student(cls.school, 'Bob', 'Brown')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_student_batch_update', args=[self.school.id])

    def test_batch_update_first_name(self):
        resp = self.client.post(self.url, {
            'student_ids': str(self.alice.id),
            f'first_name_{self.alice.id}': 'Alicia',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': self.alice.email,
        })
        self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.first_name, 'Alicia')

    def test_batch_update_multiple_students(self):
        ids = f'{self.alice.id},{self.bob.id}'
        resp = self.client.post(self.url, {
            'student_ids': ids,
            f'first_name_{self.alice.id}': 'Alicia',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': self.alice.email,
            f'first_name_{self.bob.id}': 'Robert',
            f'last_name_{self.bob.id}': 'Brown',
            f'username_{self.bob.id}': self.bob.username,
            f'email_{self.bob.id}': self.bob.email,
        })
        self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.bob.refresh_from_db()
        self.assertEqual(self.alice.first_name, 'Alicia')
        self.assertEqual(self.bob.first_name, 'Robert')

    def test_batch_update_email(self):
        resp = self.client.post(self.url, {
            'student_ids': str(self.alice.id),
            f'first_name_{self.alice.id}': 'Alice',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': 'newemail@test.com',
        })
        self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, 'newemail@test.com')

    def test_batch_update_duplicate_email_rejected(self):
        resp = self.client.post(self.url, {
            'student_ids': str(self.alice.id),
            f'first_name_{self.alice.id}': 'Alice',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': self.bob.email,  # Bob's email
        })
        self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.assertNotEqual(self.alice.email, self.bob.email)

    def test_batch_update_empty_ids_redirects(self):
        resp = self.client.post(self.url, {'student_ids': ''})
        self.assertEqual(resp.status_code, 302)


class TeacherBatchUpdateTests(TestCase):
    """Test that batch saving teachers works."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.alice = _make_teacher(cls.school, 'Alice', 'Anderson')
        cls.bob = _make_teacher(cls.school, 'Bob', 'Brown')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_teacher_batch_update', args=[self.school.id])

    def test_batch_update_first_name(self):
        resp = self.client.post(self.url, {
            'teacher_ids': str(self.alice.id),
            f'first_name_{self.alice.id}': 'Alicia',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': self.alice.email,
            f'role_{self.alice.id}': 'teacher',
            f'specialty_{self.alice.id}': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.first_name, 'Alicia')

    def test_batch_update_role(self):
        resp = self.client.post(self.url, {
            'teacher_ids': str(self.alice.id),
            f'first_name_{self.alice.id}': 'Alice',
            f'last_name_{self.alice.id}': 'Anderson',
            f'username_{self.alice.id}': self.alice.username,
            f'email_{self.alice.id}': self.alice.email,
            f'role_{self.alice.id}': 'senior_teacher',
            f'specialty_{self.alice.id}': '',
        })
        self.assertEqual(resp.status_code, 302)
        st = SchoolTeacher.objects.get(teacher=self.alice, school=self.school)
        self.assertEqual(st.role, 'senior_teacher')

    def test_batch_update_empty_ids_redirects(self):
        resp = self.client.post(self.url, {'teacher_ids': ''})
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# Total count context variable tests
# ---------------------------------------------------------------------------

class TotalCountTests(TestCase):
    """Verify total_count is passed correctly in context."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        for i in range(5):
            _make_teacher(cls.school, f'T{i}', f'Last{i}',
                          username=f'teach{i}', email=f'teach{i}@test.com')
            _make_student(cls.school, f'S{i}', f'Last{i}',
                          username=f'stud{i}', email=f'stud{i}@test.com')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_teacher_total_count(self):
        resp = self.client.get(reverse('admin_school_teachers', args=[self.school.id]))
        # 5 teachers + admin HoI auto-linked = 6
        self.assertEqual(resp.context['total_count'], 6)

    def test_student_total_count(self):
        resp = self.client.get(reverse('admin_school_students', args=[self.school.id]))
        self.assertEqual(resp.context['total_count'], 5)

    def test_teacher_total_count_with_search(self):
        resp = self.client.get(
            reverse('admin_school_teachers', args=[self.school.id]),
            {'q': 'T0'},
        )
        self.assertEqual(resp.context['total_count'], 1)

    def test_student_total_count_with_search(self):
        resp = self.client.get(
            reverse('admin_school_students', args=[self.school.id]),
            {'q': 'S0'},
        )
        self.assertEqual(resp.context['total_count'], 1)


# ---------------------------------------------------------------------------
# Show inactive combined with search
# ---------------------------------------------------------------------------

class InactiveWithSearchTests(TestCase):
    """Verify search works with show_inactive toggle."""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.school = _setup_school()
        cls.active = _make_student(cls.school, 'Active', 'Student')
        cls.inactive_user = _make_student(
            cls.school, 'Inactive', 'Student',
            username='inactive.student', email='inactive@test.com',
        )
        ss = SchoolStudent.objects.get(student=cls.inactive_user)
        ss.is_active = False
        ss.save()

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse('admin_school_students', args=[self.school.id])

    def test_search_active_only(self):
        resp = self.client.get(self.url, {'q': 'Student'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_search_with_inactive(self):
        resp = self.client.get(self.url, {'q': 'Student', 'show_inactive': '1'})
        self.assertEqual(resp.context['total_count'], 2)

    def test_search_inactive_by_name(self):
        resp = self.client.get(self.url, {'q': 'Inactive', 'show_inactive': '1'})
        self.assertEqual(resp.context['total_count'], 1)

    def test_search_inactive_hidden_by_default(self):
        resp = self.client.get(self.url, {'q': 'Inactive'})
        self.assertEqual(resp.context['total_count'], 0)
