"""
Shared fixtures for Playwright UI tests.

Every fixture defaults to function scope so the database is rolled back
after each test — no state leaks between tests.  pytest-django's
``live_server`` fixture already uses ``TransactionTestCase`` behaviour,
which truncates all tables after each test function.
"""

from __future__ import annotations

import os

# Force SQLite for UI tests unless DB_ENGINE was explicitly set before import
# (os.environ.setdefault won't work because load_dotenv hasn't run yet)
if "DB_ENGINE" not in os.environ:
    os.environ["DB_ENGINE"] = "sqlite"
# Allow synchronous DB operations in Playwright's async event loop
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import time as time_module
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.db import OperationalError, transaction
from django.utils import timezone
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Viewport — must be wide enough for the desktop sidebar (md: = 768px)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Set a desktop-sized viewport so the sidebar (hidden md:flex) is visible."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
    }


# ---------------------------------------------------------------------------
# Unique prefix for this test session — prevents slug/username collisions
# when running tests against a persistent database (--keepdb) or in parallel.
# ---------------------------------------------------------------------------
_RUN_ID = uuid.uuid4().hex[:6]

# ---------------------------------------------------------------------------
# Password used for every test user — kept simple for Playwright form-fill
# ---------------------------------------------------------------------------
TEST_PASSWORD = "TestPass123!"


# ---------------------------------------------------------------------------
# Helper: create / fetch a Role row
# ---------------------------------------------------------------------------
def _get_or_create_role(name: str):
    from accounts.models import Role

    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={"display_name": name.replace("_", " ").title()},
    )
    return role


def _assign_role(user, role_name: str):
    from accounts.models import UserRole

    role = _get_or_create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _make_user(username: str, role_name: str, **extra):
    from accounts.models import CustomUser

    unique_name = f"{username}_{_RUN_ID}"
    user = CustomUser.objects.create_user(
        username=unique_name,
        password=TEST_PASSWORD,
        email=f"{unique_name}@test.local",
        first_name=extra.pop("first_name", username.replace("_", " ").title()),
        profile_completed=True,
        must_change_password=False,
        **extra,
    )
    _assign_role(user, role_name)
    return user


# ---------------------------------------------------------------------------
# Login helper
# ---------------------------------------------------------------------------
def do_login(page: Page, live_server_url: str, user) -> None:
    """Navigate to login page, fill credentials, submit, and wait for redirect."""
    # Ensure desktop viewport so sidebar (hidden md:flex) is visible
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{live_server_url}/accounts/login/")
    # Wait for Tailwind CDN to finish generating styles
    page.wait_for_load_state("networkidle")
    page.locator("#id_username").fill(user.username)
    page.locator("#id_password").fill(TEST_PASSWORD)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    # Wait until we leave the login page
    page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)
    # Wait for DOM to be ready after redirect (networkidle can hang on CDN resources)
    page.wait_for_load_state("domcontentloaded")


def do_logout(page: Page, live_server_url: str) -> None:
    """POST to the logout URL (Django 5 removed GET-based logout support)."""
    with page.expect_navigation(timeout=10_000):
        page.evaluate(f"""() => {{
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '{live_server_url}/accounts/logout/';
            const csrf = document.createElement('input');
            csrf.type = 'hidden';
            csrf.name = 'csrfmiddlewaretoken';
            const match = document.cookie.match(/csrftoken=([^;]+)/);
            csrf.value = match ? match[1] : '';
            form.appendChild(csrf);
            document.body.appendChild(form);
            form.submit();
        }}""")
    page.wait_for_load_state("domcontentloaded")


# ═══════════════════════════════════════════════════════════════════════════
# Role fixtures  (function-scoped → cleaned up after each test)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def roles(db):
    """Ensure all standard roles exist."""
    from accounts.models import Role

    names = [
        Role.ADMIN,
        Role.TEACHER,
        Role.SENIOR_TEACHER,
        Role.STUDENT,
        Role.INDIVIDUAL_STUDENT,
        Role.ACCOUNTANT,
        Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
        Role.INSTITUTE_OWNER,
        Role.PARENT,
    ]
    return {n: _get_or_create_role(n) for n in names}


# ═══════════════════════════════════════════════════════════════════════════
# User fixtures — one per role
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def student_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_student", Role.STUDENT, first_name="Ui Student")


@pytest.fixture
def individual_student_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_individual", Role.INDIVIDUAL_STUDENT)


@pytest.fixture
def teacher_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_teacher", Role.TEACHER)


@pytest.fixture
def senior_teacher_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_senior_teacher", Role.SENIOR_TEACHER)


@pytest.fixture
def parent_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_parent", Role.PARENT)


@pytest.fixture
def admin_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_admin", Role.ADMIN, is_staff=True)


@pytest.fixture
def superuser(db, roles):
    from accounts.models import CustomUser, Role
    user = CustomUser.objects.create_superuser(
        username="ui_superuser",
        password=TEST_PASSWORD,
        email="ui_superuser@test.local",
        profile_completed=True,
        must_change_password=False,
    )
    _assign_role(user, Role.ADMIN)
    return user


@pytest.fixture
def hod_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_hod", Role.HEAD_OF_DEPARTMENT)


@pytest.fixture
def hoi_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_hoi", Role.INSTITUTE_OWNER)


@pytest.fixture
def accountant_user(db, roles):
    from accounts.models import Role
    return _make_user("ui_accountant", Role.ACCOUNTANT)


# ═══════════════════════════════════════════════════════════════════════════
# School / hierarchy fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def school(db, admin_user):
    """Create a school with unique slug, active subscription, modules enabled.

    Uses _RUN_ID for unique slugs so tests can run against a persistent DB
    (--keepdb) without collisions. School.delete() cascades to all related data.
    """
    from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
    from classroom.models import School, SchoolTeacher

    school = School.objects.create(
        name=f"Test School {_RUN_ID}",
        slug=f"ui-test-school-{_RUN_ID}",
        admin=admin_user,
        is_active=True,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f"basic-ui-{_RUN_ID}",
        defaults={
            "name": f"Basic {_RUN_ID}",
            "price": Decimal("89.00"),
            "stripe_price_id": "price_test",
            "class_limit": 50,
            "student_limit": 500,
            "invoice_limit_yearly": 500,
            "extra_invoice_rate": Decimal("0.30"),
        },
    )
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status="active",
    )
    # Enable all modules so module-gated views work in tests
    for module_key, _ in ModuleSubscription.MODULE_CHOICES:
        ModuleSubscription.objects.create(
            school_subscription=sub,
            module=module_key,
            is_active=True,
        )
    # Admin must also be a SchoolTeacher for sidebar views to work
    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=admin_user,
        defaults={"role": "head_of_institute"},
    )

    yield school

    # Cascade cleanup — deletes departments, classes, sessions, attendance, etc.
    # With parallel tests (-n auto), SQLite can have locking issues, so retry with backoff
    def delete_with_retry(obj, max_retries=5):
        """Delete an object with exponential backoff retry for SQLite locking."""
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    obj.delete()
                return
            except OperationalError as e:
                if "database table is locked" not in str(e):
                    raise
                if attempt == max_retries - 1:
                    raise
                wait_time = (2 ** attempt) * 0.1  # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                time_module.sleep(wait_time)
    
    delete_with_retry(school)
    # Clean up the test user accounts too
    from accounts.models import CustomUser
    CustomUser.objects.filter(username__endswith=f"_{_RUN_ID}").delete()
    delete_with_retry(plan)


@pytest.fixture
def subject(db):
    """A global Mathematics subject."""
    from classroom.models import Subject

    subj, _ = Subject.objects.get_or_create(
        slug="mathematics",
        school=None,
        defaults={"name": "Mathematics", "is_active": True},
    )
    return subj


@pytest.fixture
def department(db, school, hod_user, subject):
    """Department linked to school, with subject and HoD."""
    from classroom.models import (
        Department,
        DepartmentSubject,
        DepartmentTeacher,
        SchoolTeacher,
    )

    dept = Department.objects.create(
        school=school,
        name=f"Mathematics {_RUN_ID}",
        slug=f"maths-{_RUN_ID}",
        head=hod_user,
    )
    DepartmentSubject.objects.create(department=dept, subject=subject)
    DepartmentTeacher.objects.create(department=dept, teacher=hod_user)
    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=hod_user,
        defaults={"role": "head_of_department"},
    )
    return dept


@pytest.fixture
def level(db, subject):
    """A Level 7 for mathematics."""
    from classroom.models import Level

    lvl, _ = Level.objects.get_or_create(
        level_number=7,
        defaults={"display_name": "Level 7", "subject": subject},
    )
    return lvl


@pytest.fixture
def topic(db, subject, level):
    """A parent strand + child subtopic for quizzes."""
    from classroom.models import Topic

    strand = Topic.objects.create(
        subject=subject,
        name=f"Number {_RUN_ID}",
        slug=f"number-{_RUN_ID}",
        order=1,
    )
    subtopic = Topic.objects.create(
        subject=subject,
        parent=strand,
        name=f"Addition {_RUN_ID}",
        slug=f"addition-{_RUN_ID}",
        order=1,
    )
    subtopic.levels.add(level)
    return subtopic


@pytest.fixture
def classroom(db, school, department, subject, level, teacher_user):
    """A classroom with a teacher assigned."""
    from classroom.models import ClassRoom, ClassTeacher, SchoolTeacher

    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=teacher_user,
        defaults={"role": "teacher"},
    )
    room = ClassRoom.objects.create(
        name=f"Year 7 Maths {_RUN_ID}",
        school=school,
        department=department,
        subject=subject,
        day="monday",
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    room.levels.add(level)
    ClassTeacher.objects.create(classroom=room, teacher=teacher_user)
    return room


@pytest.fixture
def enrolled_student(db, classroom, student_user, school):
    """Enrol the student user in a classroom."""
    from classroom.models import ClassStudent, SchoolStudent

    SchoolStudent.objects.get_or_create(
        school=school, student=student_user,
    )
    ClassStudent.objects.create(
        classroom=classroom, student=student_user, is_active=True,
    )
    return student_user


@pytest.fixture
def guardian(db, school, enrolled_student):
    """A Guardian contact linked to the enrolled student."""
    from classroom.models import Guardian, StudentGuardian

    g = Guardian.objects.create(
        school=school,
        first_name="Jane",
        last_name="Guardian",
        email=f"jane.guardian.{_RUN_ID}@test.local",
        phone="021-555-0100",
        relationship="guardian",
    )
    StudentGuardian.objects.create(
        student=enrolled_student,
        guardian=g,
        is_primary=True,
    )
    return g


@pytest.fixture
def parent_with_child(db, parent_user, enrolled_student, school):
    """Link parent to student."""
    from classroom.models import ParentStudent

    ParentStudent.objects.create(
        parent=parent_user,
        student=enrolled_student,
        school=school,
        relationship="guardian",
    )
    return parent_user


# ═══════════════════════════════════════════════════════════════════════════
# Guardian / bulk-student fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def guardian(db, enrolled_student, school):
    """A guardian contact linked to the enrolled student."""
    from classroom.models import Guardian, StudentGuardian

    g = Guardian.objects.create(
        school=school,
        first_name="Jane",
        last_name="Guardian",
        email=f"jane.guardian.{_RUN_ID}@test.local",
        phone="021-555-1234",
        relationship="mother",
    )
    StudentGuardian.objects.create(student=enrolled_student, guardian=g)
    return g


@pytest.fixture
def many_students(db, school):
    """Create 30 students for pagination testing."""
    from classroom.models import SchoolStudent
    from accounts.models import CustomUser

    students = []
    for i in range(30):
        user = CustomUser.objects.create_user(
            username=f"pag_{_RUN_ID}_{i:03d}",
            password=TEST_PASSWORD,
            email=f"pag_{_RUN_ID}_{i:03d}@test.local",
            first_name=f"Student{i:03d}",
            last_name=f"Pag{_RUN_ID}",
            profile_completed=True,
            must_change_password=False,
        )
        _assign_role(user, "student")
        SchoolStudent.objects.create(school=school, student=user)
        students.append(user)
    return students


# ═══════════════════════════════════════════════════════════════════════════
# Attendance fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def completed_session(db, classroom, teacher_user):
    """A completed class session with attendance data."""
    from attendance.models import ClassSession

    session = ClassSession.objects.create(
        classroom=classroom,
        date=date.today() - timedelta(days=1),
        start_time=time(9, 0),
        end_time=time(10, 0),
        status="completed",
        created_by=teacher_user,
    )
    return session


@pytest.fixture
def student_attendance(db, completed_session, enrolled_student):
    """Attendance record for student — marked present."""
    from attendance.models import StudentAttendance

    return StudentAttendance.objects.create(
        session=completed_session,
        student=enrolled_student,
        status="present",
    )


@pytest.fixture
def future_session(db, classroom, teacher_user):
    """An upcoming (scheduled) class session."""
    from attendance.models import ClassSession

    return ClassSession.objects.create(
        classroom=classroom,
        date=date.today() + timedelta(days=3),
        start_time=time(9, 0),
        end_time=time(10, 0),
        status="scheduled",
        created_by=teacher_user,
    )


@pytest.fixture
def self_reported_attendance(db, completed_session, enrolled_student):
    """Self-reported attendance pending approval."""
    from attendance.models import StudentAttendance

    return StudentAttendance.objects.create(
        session=completed_session,
        student=enrolled_student,
        status="present",
        self_reported=True,
        approved_by=None,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Quiz / question fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def questions(db, level, topic):
    """5 multiple-choice questions with 4 answers each."""
    from maths.models import Answer, Question

    qs = []
    for i in range(1, 6):
        q = Question.objects.create(
            level=level,
            topic=topic,
            question_text=f"What is {i} + {i}?",
            question_type="multiple_choice",
            difficulty=1,
            points=1,
        )
        for j, (text, correct) in enumerate([
            (str(i * 2), True),
            (str(i * 2 + 1), False),
            (str(i * 2 - 1), False),
            (str(i * 3), False),
        ]):
            Answer.objects.create(
                question=q, answer_text=text, is_correct=correct, order=j,
            )
        qs.append(q)
    return qs


# ═══════════════════════════════════════════════════════════════════════════
# Progress / TimeLog fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def timelog(db, enrolled_student):
    """TimeLog with 45 min today and 3 hours this week."""
    from maths.models import TimeLog

    return TimeLog.objects.create(
        student=enrolled_student,
        daily_total_seconds=2700,   # 45 min
        weekly_total_seconds=10800, # 3 hrs
    )


@pytest.fixture
def progress_data(db, enrolled_student, level, topic):
    """StudentFinalAnswer + TopicLevelStatistics for colour-banded progress grid."""
    from maths.models import StudentFinalAnswer, TopicLevelStatistics

    StudentFinalAnswer.objects.create(
        student=enrolled_student,
        session_id=str(uuid.uuid4()),
        topic=topic,
        level=level,
        quiz_type="topic",
        score=8,
        total_questions=10,
        points=75.0,
        time_taken_seconds=120,
    )
    stats, _ = TopicLevelStatistics.objects.get_or_create(
        level=level,
        topic=topic,
        defaults={
            "average_points": Decimal("60.00"),
            "sigma": Decimal("15.00"),
            "student_count": 10,
        },
    )
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# Academic Year / Term fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def academic_year(db, school):
    """Current academic year."""
    from classroom.models import AcademicYear

    today = date.today()
    return AcademicYear.objects.create(
        school=school,
        year=today.year,
        start_date=date(today.year, 1, 1),
        end_date=date(today.year, 12, 31),
        is_current=True,
    )


@pytest.fixture
def future_term(db, school, academic_year):
    """A term starting in the future (next month onwards)."""
    from classroom.models import Term

    today = date.today()
    # Start 30 days from now, end 90 days from now
    start = today + timedelta(days=30)
    end = today + timedelta(days=90)
    return Term.objects.create(
        school=school,
        academic_year=academic_year,
        name="Term 2",
        start_date=start,
        end_date=end,
        order=2,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Invoice fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def invoice(db, enrolled_student, school, classroom):
    """A draft invoice for the enrolled student."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=enrolled_student,
        school=school,
        invoice_number=f"INV-{_RUN_ID}",
        billing_period_start=date.today() - timedelta(days=30),
        billing_period_end=date.today(),
        status="draft",
        amount=Decimal("120.00"),
        calculated_amount=Decimal("120.00"),
    )
    InvoiceLineItem.objects.create(
        invoice=inv,
        classroom=classroom,
        daily_rate=Decimal("10.00"),
        sessions_held=12,
        sessions_attended=12,
        sessions_charged=12,
        line_amount=Decimal("120.00"),
    )
    return inv


@pytest.fixture
def issued_invoice(db, enrolled_student, school, classroom):
    """An issued invoice for the enrolled student (payment form is visible)."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=enrolled_student,
        school=school,
        invoice_number="INV-0002",
        billing_period_start=date.today() - timedelta(days=30),
        billing_period_end=date.today(),
        status="issued",
        amount=Decimal("120.00"),
        calculated_amount=Decimal("120.00"),
    )
    InvoiceLineItem.objects.create(
        invoice=inv,
        classroom=classroom,
        daily_rate=Decimal("10.00"),
        sessions_held=12,
        sessions_attended=12,
        sessions_charged=12,
        line_amount=Decimal("120.00"),
    )
    return inv


# ═══════════════════════════════════════════════════════════════════════════
# HoI setup  (requires full hierarchy for sidebar access)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def hoi_school_setup(db, hoi_user, school, department):
    """Attach HoI user to the school so sidebar renders correctly."""
    from classroom.models import SchoolTeacher

    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=hoi_user,
        defaults={"role": "head_of_institute"},
    )
    return school


@pytest.fixture
def accountant_school_setup(db, accountant_user, school):
    """Attach accountant to school."""
    from classroom.models import SchoolTeacher

    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=accountant_user,
        defaults={"role": "accountant"},
    )
    return school


@pytest.fixture
def senior_teacher_school_setup(db, senior_teacher_user, school, department):
    """Attach senior teacher to school and department."""
    from classroom.models import DepartmentTeacher, SchoolTeacher

    SchoolTeacher.objects.get_or_create(
        school=school,
        teacher=senior_teacher_user,
        defaults={"role": "senior_teacher"},
    )
    DepartmentTeacher.objects.get_or_create(
        department=department,
        teacher=senior_teacher_user,
    )
    return school
