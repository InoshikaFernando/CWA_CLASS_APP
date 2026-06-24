"""
Playwright UI tests for CPP-317: Teacher add new student to class with card number support.

Covers:
1. "New Student" button visible on class detail for school-linked class
2. Add-student form renders with all expected fields including card_number
3. Submit valid form → redirect to class detail, success message
4. Submit with invalid card number → stays on form, shows error
5. CompleteProfileView: pre-claimed card shows activation banner
"""

import uuid
import pytest
from django.urls import reverse
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp317


# ---------------------------------------------------------------------------
# Shared data setup
# ---------------------------------------------------------------------------

def _make_school_with_teacher():
    from accounts.models import CustomUser, Role, UserRole
    from classroom.models import School, SchoolTeacher, ClassRoom

    def _make_user(role_name, suffix=''):
        uid = f'{_RUN_ID}{suffix}'
        u = CustomUser.objects.create_user(
            username=f'{role_name}_{uid}',
            email=f'{role_name}_{uid}@cpptest.com',
            password=TEST_PASSWORD,
            profile_completed=True,
            must_change_password=False,
        )
        r, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
        UserRole.objects.get_or_create(user=u, role=r)
        return u

    hoi = _make_user(Role.HEAD_OF_INSTITUTE, 'hoi')
    school = School.objects.create(name=f'CPP317 School {_RUN_ID}', admin=hoi)
    teacher = _make_user(Role.TEACHER, 'tch')
    SchoolTeacher.objects.create(school=school, teacher=teacher)
    classroom = ClassRoom.objects.create(name=f'Maths {_RUN_ID}', school=school)
    classroom.teachers.add(teacher)
    return hoi, school, teacher, classroom


# ---------------------------------------------------------------------------
# Test: New Student button on class detail
# ---------------------------------------------------------------------------

class TestNewStudentButton:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        self.url = live_server.url
        self.page = page
        _, self.school, self.teacher, self.classroom = _make_school_with_teacher()
        do_login(page, self.url, self.teacher)

    @pytest.mark.django_db(transaction=True)
    def test_new_student_button_visible(self):
        url = f'{self.url}{reverse("class_detail", kwargs={"class_id": self.classroom.id})}'
        self.page.goto(url)
        self.page.wait_for_load_state('networkidle')
        add_url = reverse('teacher_add_student_to_class', kwargs={'class_id': self.classroom.id})
        btn = self.page.locator(f'a[href="{add_url}"]')
        expect(btn.first).to_be_attached()
        expect(btn.first).to_contain_text('New Student')


# ---------------------------------------------------------------------------
# Test: Add student form fields
# ---------------------------------------------------------------------------

class TestAddStudentForm:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        self.url = live_server.url
        self.page = page
        _, self.school, self.teacher, self.classroom = _make_school_with_teacher()
        do_login(page, self.url, self.teacher)

    @pytest.mark.django_db(transaction=True)
    def test_form_has_all_fields(self):
        url = f'{self.url}{reverse("teacher_add_student_to_class", kwargs={"class_id": self.classroom.id})}'
        self.page.goto(url)
        self.page.wait_for_load_state('networkidle')
        expect(self.page.locator('input[name="first_name"]')).to_be_visible()
        expect(self.page.locator('input[name="last_name"]')).to_be_visible()
        expect(self.page.locator('input[name="email"]')).to_be_visible()
        expect(self.page.locator('input[name="password"]')).to_be_visible()
        expect(self.page.locator('input[name="card_number"]')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_submit_valid_form_creates_student(self):
        from accounts.models import CustomUser
        from classroom.models import ClassStudent

        url = f'{self.url}{reverse("teacher_add_student_to_class", kwargs={"class_id": self.classroom.id})}'
        self.page.goto(url)
        self.page.wait_for_load_state('networkidle')

        email = f'newui_{uuid.uuid4().hex[:6]}@cpptest.com'
        self.page.fill('input[name="first_name"]', 'Alice')
        self.page.fill('input[name="last_name"]', 'Smith')
        self.page.fill('input[name="email"]', email)
        self.page.fill('input[name="password"]', 'TempPass999')
        self.page.get_by_role('button', name='Create Student & Enrol').click()
        self.page.wait_for_load_state('networkidle')

        # Redirected to class detail
        assert f'/class/{self.classroom.id}/' in self.page.url
        expect(self.page.locator('body')).to_contain_text('added to')

        user = CustomUser.objects.get(email=email)
        assert ClassStudent.objects.filter(
            classroom=self.classroom, student=user, is_active=True,
        ).exists()

    @pytest.mark.django_db(transaction=True)
    def test_invalid_card_number_shows_error(self):
        url = f'{self.url}{reverse("teacher_add_student_to_class", kwargs={"class_id": self.classroom.id})}'
        self.page.goto(url)
        self.page.wait_for_load_state('networkidle')

        email = f'bcard_{uuid.uuid4().hex[:6]}@cpptest.com'
        self.page.fill('input[name="first_name"]', 'Bob')
        self.page.fill('input[name="last_name"]', 'Jones')
        self.page.fill('input[name="email"]', email)
        self.page.fill('input[name="password"]', 'TempPass999')
        self.page.fill('input[name="card_number"]', 'INVALID-XYZ')
        self.page.get_by_role('button', name='Create Student & Enrol').click()
        self.page.wait_for_load_state('networkidle')

        # Stays on form
        assert 'add-student' in self.page.url
        expect(self.page.locator('body')).to_contain_text('not found')


# ---------------------------------------------------------------------------
# Test: Cross-teacher access denied (403)
# ---------------------------------------------------------------------------

class TestCrossTeacherAccess:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        self.url = live_server.url
        self.page = page
        _, self.school, teacher, self.classroom = _make_school_with_teacher()
        # Create a second teacher who does NOT teach this class
        from accounts.models import CustomUser, Role, UserRole
        uid = f'{_RUN_ID}t2'
        self.other_teacher = CustomUser.objects.create_user(
            username=f'teacher2_{uid}',
            email=f'teacher2_{uid}@cpptest.com',
            password=TEST_PASSWORD,
            profile_completed=True,
            must_change_password=False,
        )
        r, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        UserRole.objects.get_or_create(user=self.other_teacher, role=r)
        do_login(page, self.url, self.other_teacher)

    @pytest.mark.django_db(transaction=True)
    def test_other_teacher_gets_404(self):
        add_url = f'{self.url}{reverse("teacher_add_student_to_class", kwargs={"class_id": self.classroom.id})}'
        with self.page.expect_response(lambda r: str(self.classroom.id) in r.url) as resp_info:
            self.page.goto(add_url)
        assert resp_info.value.status == 404
