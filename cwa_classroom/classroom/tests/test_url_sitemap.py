"""
URL Sitemap Validation Tests
============================
Every GET-accessible named URL in the project is exercised here.
Tests assert the response is NOT 404 or 500.

Strategy:
- Public URLs    → anonymous client (expect 200 or redirect)
- Auth URLs      → logged-in client with appropriate role + full school hierarchy
- POST-only URLs → skipped (they require CSRF / form data; tested elsewhere)
- HTMX partials  → skipped (require specific headers)
- Webhook / API  → skipped (require special payloads)
"""
from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.test import Client, TestCase
from django.urls import reverse


# ---------------------------------------------------------------------------
# Base: create entire school hierarchy once per class
# ---------------------------------------------------------------------------

class FullHierarchyMixin:
    """Set up a complete school hierarchy for URL testing."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser, Role, UserRole
        from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
        from classroom.models import (
            AcademicYear, ClassRoom, ClassStudent, ClassTeacher,
            Department, DepartmentSubject, DepartmentTeacher,
            Guardian, Invoice, InvoiceLineItem,
            Level, ParentStudent, School, SchoolStudent, SchoolTeacher,
            Subject, Term, Topic,
        )
        from attendance.models import ClassSession, StudentAttendance
        from maths.models import Answer, Question

        RUN = uuid.uuid4().hex[:6]

        def make_role(name):
            r, _ = Role.objects.get_or_create(
                name=name, defaults={"display_name": name.replace("_", " ").title()}
            )
            return r

        def make_user(username, role_name, **kw):
            u = CustomUser.objects.create_user(
                username=f"{username}_{RUN}",
                password="TestPass123!",
                email=f"{username}_{RUN}@test.local",
                first_name=username.title(),
                profile_completed=True,
                must_change_password=False,
                **kw,
            )
            r = make_role(role_name)
            UserRole.objects.create(user=u, role=r)
            return u

        # ── Users ──────────────────────────────────────────────────────────
        cls.admin      = make_user("url_admin",      Role.ADMIN, is_staff=True)
        cls.teacher    = make_user("url_teacher",    Role.TEACHER)
        cls.s_teacher  = make_user("url_steacher",   Role.SENIOR_TEACHER)
        cls.student    = make_user("url_student",    Role.STUDENT)
        cls.parent     = make_user("url_parent",     Role.PARENT)
        cls.hod        = make_user("url_hod",        Role.HEAD_OF_DEPARTMENT)
        cls.hoi        = make_user("url_hoi",        Role.INSTITUTE_OWNER)
        cls.accountant = make_user("url_accountant", Role.ACCOUNTANT)

        # ── School ─────────────────────────────────────────────────────────
        cls.school = School.objects.create(
            name=f"URL Test School {RUN}",
            slug=f"url-test-{RUN}",
            admin=cls.admin,
            is_active=True,
        )
        plan, _ = InstitutePlan.objects.get_or_create(
            slug=f"url-plan-{RUN}",
            defaults={
                "name": f"URL Plan {RUN}", "price": Decimal("89.00"),
                "stripe_price_id": "price_test", "class_limit": 50,
                "student_limit": 500, "invoice_limit_yearly": 500,
                "extra_invoice_rate": Decimal("0.30"),
            },
        )
        sub = SchoolSubscription.objects.create(school=cls.school, plan=plan, status="active")
        for module_key, _ in ModuleSubscription.MODULE_CHOICES:
            ModuleSubscription.objects.create(
                school_subscription=sub, module=module_key, is_active=True,
            )

        # ── School staff attachments ───────────────────────────────────────
        for user, role in [
            (cls.admin,      "head_of_institute"),
            (cls.teacher,    "teacher"),
            (cls.s_teacher,  "senior_teacher"),
            (cls.hod,        "head_of_department"),
            (cls.hoi,        "head_of_institute"),
            (cls.accountant, "accountant"),
        ]:
            SchoolTeacher.objects.get_or_create(
                school=cls.school, teacher=user, defaults={"role": role}
            )

        # ── Subject / Level / Topic ────────────────────────────────────────
        cls.subject, _ = Subject.objects.get_or_create(
            slug="mathematics", school=None,
            defaults={"name": "Mathematics", "is_active": True},
        )
        cls.level, _ = Level.objects.get_or_create(
            level_number=7, defaults={"display_name": "Level 7", "subject": cls.subject},
        )

        # ── Department ─────────────────────────────────────────────────────
        cls.dept = Department.objects.create(
            school=cls.school, name=f"Maths Dept {RUN}", slug=f"maths-{RUN}", head=cls.hod,
        )
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.subject)
        DepartmentTeacher.objects.get_or_create(department=cls.dept, teacher=cls.hod)
        DepartmentTeacher.objects.get_or_create(department=cls.dept, teacher=cls.s_teacher)
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.hod, defaults={"role": "head_of_department"}
        )

        # ── Topic ──────────────────────────────────────────────────────────
        strand = Topic.objects.create(
            subject=cls.subject, name=f"Number {RUN}", slug=f"number-{RUN}", order=1,
        )
        cls.topic = Topic.objects.create(
            subject=cls.subject, parent=strand,
            name=f"Addition {RUN}", slug=f"addition-{RUN}", order=1,
        )
        cls.topic.levels.add(cls.level)

        # ── Classroom ──────────────────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name=f"Year 7 Maths {RUN}", school=cls.school,
            department=cls.dept, subject=cls.subject,
            day="monday", start_time=time(9, 0), end_time=time(10, 0),
        )
        cls.classroom.levels.add(cls.level)
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        # ── Student enrollment ─────────────────────────────────────────────
        SchoolStudent.objects.get_or_create(school=cls.school, student=cls.student)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student, is_active=True)

        # ── Parent → student link ──────────────────────────────────────────
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student,
            school=cls.school, relationship="guardian",
        )

        # ── Guardian ───────────────────────────────────────────────────────
        from classroom.models import StudentGuardian
        cls.guardian = Guardian.objects.create(
            school=cls.school, first_name="Jane", last_name="Guardian",
            email=f"jane_{RUN}@test.local", phone="021-555-0100", relationship="guardian",
        )
        StudentGuardian.objects.create(student=cls.student, guardian=cls.guardian, is_primary=True)

        # ── Academic year / term ───────────────────────────────────────────
        today = date.today()
        cls.academic_year = AcademicYear.objects.create(
            school=cls.school, year=today.year,
            start_date=date(today.year, 1, 1), end_date=date(today.year, 12, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.academic_year,
            name="Term 1", start_date=today, end_date=today + timedelta(days=90), order=1,
        )

        # ── Class session ──────────────────────────────────────────────────
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom,
            date=date.today() - timedelta(days=1),
            start_time=time(9, 0), end_time=time(10, 0),
            status="completed", created_by=cls.teacher,
        )
        cls.attendance = StudentAttendance.objects.create(
            session=cls.session, student=cls.student, status="present",
        )

        # ── Questions ─────────────────────────────────────────────────────
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text="What is 2+2?", question_type="multiple_choice",
            difficulty=1, points=1,
        )
        for text, correct in [("4", True), ("3", False), ("5", False), ("6", False)]:
            Answer.objects.create(question=cls.question, answer_text=text, is_correct=correct)

        # ── Invoice ────────────────────────────────────────────────────────
        cls.invoice = Invoice.objects.create(
            student=cls.student, school=cls.school,
            invoice_number=f"INV-URL-{RUN}",
            billing_period_start=today - timedelta(days=30),
            billing_period_end=today,
            status="issued", amount=Decimal("120.00"),
            calculated_amount=Decimal("120.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice, classroom=cls.classroom,
            daily_rate=Decimal("10.00"), sessions_held=12,
            sessions_attended=12, sessions_charged=12,
            line_amount=Decimal("120.00"),
        )

    def _client(self, user):
        c = Client()
        c.login(username=user.username, password="TestPass123!")
        return c

    def assertURLOK(self, client, url, *, label=""):
        """GET url; assert NOT 404 or 500."""
        try:
            resp = client.get(url, follow=True)
        except Exception as e:
            self.fail(f"Exception fetching {label or url}: {e}")
        self.assertNotIn(
            resp.status_code, [404, 500],
            msg=f"URL {label or url!r} returned {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# Public URL Tests
# ---------------------------------------------------------------------------

class TestPublicURLs(FullHierarchyMixin, TestCase):
    """Anonymous access — expect 200 or redirect (not 404/500)."""

    def setUp(self):
        self.c = Client()  # anonymous

    def test_public_home(self):
        self.assertURLOK(self.c, reverse("public_home"))

    def test_subjects_hub(self):
        self.assertURLOK(self.c, reverse("subjects_hub"))

    def test_subjects_list(self):
        self.assertURLOK(self.c, reverse("subjects_list"))

    def test_contact(self):
        self.assertURLOK(self.c, reverse("contact"))

    def test_join_class(self):
        self.assertURLOK(self.c, reverse("join_class"))

    def test_privacy_policy(self):
        self.assertURLOK(self.c, reverse("privacy_policy"))

    def test_terms_conditions(self):
        self.assertURLOK(self.c, reverse("terms_conditions"))

    def test_robots_txt(self):
        self.assertURLOK(self.c, reverse("robots_txt"))

    def test_sitemap_xml(self):
        self.assertURLOK(self.c, "/sitemap.xml")

    def test_accounts_login(self):
        self.assertURLOK(self.c, reverse("login"))

    def test_accounts_password_reset(self):
        self.assertURLOK(self.c, reverse("password_reset"))

    def test_accounts_signup_teacher(self):
        self.assertURLOK(self.c, reverse("signup_teacher"))

    def test_accounts_register_teacher_center(self):
        self.assertURLOK(self.c, reverse("register_teacher_center"))

    def test_accounts_register_individual_student(self):
        self.assertURLOK(self.c, reverse("register_individual_student"))

    def test_accounts_register_school_student(self):
        self.assertURLOK(self.c, reverse("register_school_student"))

    def test_accounts_blocked(self):
        self.assertURLOK(self.c, reverse("account_blocked"))

    def test_help_centre(self):
        self.assertURLOK(self.c, reverse("help:help_centre"))

    def test_help_faq(self):
        self.assertURLOK(self.c, reverse("help:help_faq"))

    def test_help_search(self):
        self.assertURLOK(self.c, reverse("help:help_search"))


# ---------------------------------------------------------------------------
# Authenticated — Student URLs
# ---------------------------------------------------------------------------

class TestStudentURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.student)

    def test_maths_dashboard(self):
        self.assertURLOK(self.c, reverse("maths:dashboard"))

    def test_maths_dashboard_detail(self):
        self.assertURLOK(self.c, reverse("maths:dashboard_detail"))

    def test_maths_topics(self):
        self.assertURLOK(self.c, reverse("maths:topics"))

    def test_maths_level_detail(self):
        self.assertURLOK(self.c, reverse("maths:level_detail", kwargs={"level_number": self.level.level_number}))

    def test_maths_level_questions(self):
        self.assertURLOK(self.c, reverse("maths:level_questions", kwargs={"level_number": self.level.level_number}))

    def test_maths_user_profile(self):
        self.assertURLOK(self.c, reverse("maths:user_profile"))

    def test_student_dashboard(self):
        self.assertURLOK(self.c, reverse("student_dashboard"))

    def test_student_my_classes(self):
        self.assertURLOK(self.c, reverse("student_my_classes"))

    def test_student_class_detail(self):
        self.assertURLOK(self.c, reverse("student_class_detail", kwargs={"class_id": self.classroom.id}))

    def test_student_attendance_history(self):
        self.assertURLOK(self.c, reverse("student_attendance_history"))

    def test_student_absence_tokens(self):
        self.assertURLOK(self.c, reverse("student_absence_tokens"))

    def test_student_request_absence_token(self):
        self.assertURLOK(self.c, reverse("student_request_absence_token"))

    def test_homework_list(self):
        self.assertURLOK(self.c, reverse("homework:student_list"))

    def test_billing_history(self):
        self.assertURLOK(self.c, reverse("billing_history"))

    def test_billing_module_required(self):
        self.assertURLOK(self.c, reverse("module_required"))

    def test_accounts_profile(self):
        self.assertURLOK(self.c, reverse("profile"))

    def test_quiz_basic_facts_home(self):
        self.assertURLOK(self.c, reverse("basic_facts_home"))

    def test_quiz_basic_facts_subtopic(self):
        self.assertURLOK(self.c, reverse("basic_facts_select", kwargs={"subtopic": "addition"}))

    def test_quiz_times_tables_home(self):
        self.assertURLOK(self.c, reverse("times_tables_home"))

    def test_quiz_topic_quiz(self):
        self.assertURLOK(self.c, reverse("topic_quiz", kwargs={
            "subject": "maths", "level_number": self.level.level_number, "topic_id": self.topic.id,
        }))

    def test_quiz_mixed_quiz(self):
        self.assertURLOK(self.c, reverse("mixed_quiz", kwargs={
            "subject": "maths", "level_number": self.level.level_number,
        }))

    def test_progress_student_detail(self):
        self.assertURLOK(self.c, reverse("student_detail_progress", kwargs={"student_id": self.student.id}))

    def test_number_puzzles_home(self):
        self.assertURLOK(self.c, reverse("number_puzzles_home"))

    def test_parent_dashboard_redirects_for_student(self):
        """Student hitting parent page should redirect, not crash."""
        resp = self.c.get(reverse("parent_dashboard"))
        self.assertNotIn(resp.status_code, [404, 500])


# ---------------------------------------------------------------------------
# Authenticated — Teacher URLs
# ---------------------------------------------------------------------------

class TestTeacherURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.teacher)

    def test_class_detail(self):
        self.assertURLOK(self.c, reverse("class_detail", kwargs={"class_id": self.classroom.id}))

    def test_class_attendance(self):
        self.assertURLOK(self.c, reverse("class_attendance", kwargs={"class_id": self.classroom.id}))

    def test_class_assign_students(self):
        self.assertURLOK(self.c, reverse("assign_students", kwargs={"class_id": self.classroom.id}))

    def test_class_assign_teachers(self):
        self.assertURLOK(self.c, reverse("assign_teachers", kwargs={"class_id": self.classroom.id}))

    def test_class_settings(self):
        self.assertURLOK(self.c, reverse("class_settings", kwargs={"class_id": self.classroom.id}))

    def test_session_attendance(self):
        self.assertURLOK(self.c, reverse("session_attendance", kwargs={"session_id": self.session.id}))

    def test_attendance_approvals(self):
        self.assertURLOK(self.c, reverse("attendance_approvals"))

    def test_homework_monitor(self):
        self.assertURLOK(self.c, reverse("homework:teacher_monitor"))

    def test_homework_create(self):
        self.assertURLOK(self.c, reverse("homework:teacher_create", kwargs={"classroom_id": self.classroom.id}))

    def test_create_question(self):
        self.assertURLOK(self.c, reverse("create_question"))

    def test_question_list(self):
        self.assertURLOK(self.c, reverse("question_list", kwargs={"level_number": self.level.level_number}))

    def test_class_progress_list(self):
        self.assertURLOK(self.c, reverse("class_progress_list"))

    def test_record_progress(self):
        self.assertURLOK(self.c, reverse("record_progress", kwargs={"class_id": self.classroom.id}))

    def test_parent_link_requests(self):
        self.assertURLOK(self.c, reverse("parent_link_requests"))

    def test_absence_token_approvals(self):
        self.assertURLOK(self.c, reverse("absence_token_approvals"))

    def test_teacher_self_attendance(self):
        self.assertURLOK(self.c, reverse("teacher_self_attendance", kwargs={"session_id": self.session.id}))


# ---------------------------------------------------------------------------
# Authenticated — Admin / HoI / HoD URLs
# ---------------------------------------------------------------------------

class TestAdminURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.admin)

    def test_admin_dashboard(self):
        self.assertURLOK(self.c, reverse("admin_dashboard"))

    def test_admin_school_create(self):
        self.assertURLOK(self.c, reverse("admin_school_create"))

    def test_admin_school_detail(self):
        self.assertURLOK(self.c, reverse("admin_school_detail", kwargs={"school_id": self.school.id}))

    def test_admin_school_edit(self):
        self.assertURLOK(self.c, reverse("admin_school_edit", kwargs={"school_id": self.school.id}))

    def test_admin_school_settings(self):
        self.assertURLOK(self.c, reverse("admin_school_settings", kwargs={"school_id": self.school.id}))

    def test_admin_school_teachers(self):
        self.assertURLOK(self.c, reverse("admin_school_teachers", kwargs={"school_id": self.school.id}))

    def test_admin_school_students(self):
        self.assertURLOK(self.c, reverse("admin_school_students", kwargs={"school_id": self.school.id}))

    def test_admin_school_parents(self):
        self.assertURLOK(self.c, reverse("admin_school_parents", kwargs={"school_id": self.school.id}))

    def test_admin_school_departments(self):
        self.assertURLOK(self.c, reverse("admin_school_departments", kwargs={"school_id": self.school.id}))

    def test_admin_department_detail(self):
        self.assertURLOK(self.c, reverse("admin_department_detail", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_admin_department_edit(self):
        self.assertURLOK(self.c, reverse("admin_department_edit", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_admin_department_teachers(self):
        self.assertURLOK(self.c, reverse("admin_department_teachers", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_admin_department_assign_classes(self):
        self.assertURLOK(self.c, reverse("admin_department_assign_classes", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_admin_department_levels(self):
        self.assertURLOK(self.c, reverse("admin_department_levels", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_admin_school_subjects(self):
        self.assertURLOK(self.c, reverse("admin_school_subjects", kwargs={"school_id": self.school.id}))

    def test_admin_school_terms(self):
        self.assertURLOK(self.c, reverse("admin_school_terms", kwargs={"school_id": self.school.id}))

    def test_admin_academic_year_create(self):
        self.assertURLOK(self.c, reverse("admin_academic_year_create", kwargs={"school_id": self.school.id}))

    def test_admin_academic_year_edit(self):
        self.assertURLOK(self.c, reverse("admin_academic_year_edit", kwargs={
            "school_id": self.school.id, "academic_year_id": self.academic_year.id,
        }))

    def test_admin_parent_invites(self):
        self.assertURLOK(self.c, reverse("parent_invite_list", kwargs={"school_id": self.school.id}))

    def test_admin_school_teacher_edit(self):
        self.assertURLOK(self.c, reverse("admin_school_teacher_edit", kwargs={
            "school_id": self.school.id, "teacher_id": self.teacher.id,
        }))

    def test_admin_school_student_edit(self):
        self.assertURLOK(self.c, reverse("admin_school_student_edit", kwargs={
            "school_id": self.school.id, "student_id": self.student.id,
        }))

    def test_admin_guardian_update(self):
        self.assertURLOK(self.c, reverse("admin_guardian_update", kwargs={
            "school_id": self.school.id, "guardian_id": self.guardian.id,
        }))

    def test_admin_manage_settings(self):
        self.assertURLOK(self.c, reverse("admin_manage_settings"))

    def test_admin_manage_teachers(self):
        self.assertURLOK(self.c, reverse("admin_manage_teachers"))

    def test_admin_manage_students(self):
        self.assertURLOK(self.c, reverse("admin_manage_students"))

    def test_admin_manage_parents(self):
        self.assertURLOK(self.c, reverse("admin_manage_parents"))

    def test_admin_manage_departments(self):
        self.assertURLOK(self.c, reverse("admin_manage_departments"))

    def test_admin_subject_apps(self):
        self.assertURLOK(self.c, reverse("admin_subject_apps"))

    def test_create_class(self):
        self.assertURLOK(self.c, reverse("create_class"))

    def test_import_students(self):
        self.assertURLOK(self.c, reverse("student_csv_upload"))

    def test_import_teachers(self):
        self.assertURLOK(self.c, reverse("teacher_csv_upload"))

    def test_import_parents(self):
        self.assertURLOK(self.c, reverse("parent_csv_upload"))

    def test_import_balances(self):
        self.assertURLOK(self.c, reverse("balance_csv_upload"))

    def test_upload_questions(self):
        self.assertURLOK(self.c, reverse("upload_questions"))

    def test_audit_dashboard(self):
        self.assertURLOK(self.c, reverse("audit_dashboard"))

    def test_audit_log_list(self):
        self.assertURLOK(self.c, reverse("audit_log_list"))

    def test_school_hierarchy(self):
        self.assertURLOK(self.c, reverse("school_hierarchy", kwargs={"school_id": self.school.id}))

    def test_student_parent_links(self):
        self.assertURLOK(self.c, reverse("student_parent_links", kwargs={
            "school_id": self.school.id, "student_id": self.student.id,
        }))


# ---------------------------------------------------------------------------
# Authenticated — HoD URLs
# ---------------------------------------------------------------------------

class TestHoDURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.hod)

    def test_hod_overview(self):
        self.assertURLOK(self.c, reverse("hod_overview"))

    def test_hod_manage_classes(self):
        self.assertURLOK(self.c, reverse("hod_manage_classes"))

    def test_hod_create_class(self):
        self.assertURLOK(self.c, reverse("hod_create_class"))

    def test_hod_assign_class(self):
        self.assertURLOK(self.c, reverse("hod_assign_class"))

    def test_hod_workload(self):
        self.assertURLOK(self.c, reverse("hod_workload"))

    def test_hod_reports(self):
        self.assertURLOK(self.c, reverse("hod_reports"))

    def test_hod_attendance_report(self):
        self.assertURLOK(self.c, reverse("hod_attendance_report"))

    def test_hod_subject_levels(self):
        self.assertURLOK(self.c, reverse("hod_subject_levels"))

    def test_hod_subject_levels_dept(self):
        self.assertURLOK(self.c, reverse("hod_subject_levels_dept", kwargs={"dept_id": self.dept.id}))

    def test_department_subject_levels(self):
        self.assertURLOK(self.c, reverse("admin_department_subject_levels", kwargs={
            "school_id": self.school.id, "dept_id": self.dept.id,
        }))

    def test_manage_teachers(self):
        self.assertURLOK(self.c, reverse("manage_teachers"))


# ---------------------------------------------------------------------------
# Authenticated — Accountant / Invoicing URLs
# ---------------------------------------------------------------------------

class TestAccountantURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.accountant)

    def test_invoice_list(self):
        self.assertURLOK(self.c, reverse("invoice_list"))

    def test_invoice_detail(self):
        self.assertURLOK(self.c, reverse("invoice_detail", kwargs={"invoice_id": self.invoice.id}))

    def test_invoice_edit(self):
        self.assertURLOK(self.c, reverse("invoice_edit", kwargs={"invoice_id": self.invoice.id}))

    def test_generate_invoices(self):
        self.assertURLOK(self.c, reverse("generate_invoices"))

    def test_fee_configuration(self):
        self.assertURLOK(self.c, reverse("fee_configuration"))

    def test_csv_upload(self):
        self.assertURLOK(self.c, reverse("csv_upload"))

    def test_opening_balances(self):
        self.assertURLOK(self.c, reverse("opening_balances"))

    def test_salary_slip_list(self):
        self.assertURLOK(self.c, reverse("salary_slip_list"))

    def test_salary_rate_configuration(self):
        self.assertURLOK(self.c, reverse("salary_rate_configuration"))

    def test_generate_salary_slips(self):
        self.assertURLOK(self.c, reverse("generate_salary_slips"))

    def test_accounting_dashboard(self):
        self.assertURLOK(self.c, reverse("accounting_dashboard"))

    def test_accounting_packages(self):
        self.assertURLOK(self.c, reverse("accounting_packages"))

    def test_reference_mappings(self):
        self.assertURLOK(self.c, reverse("reference_mappings"))

    def test_billing_institute_dashboard(self):
        self.assertURLOK(self.c, reverse("institute_subscription_dashboard"))


# ---------------------------------------------------------------------------
# Authenticated — Parent URLs
# ---------------------------------------------------------------------------

class TestParentURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.parent)

    def test_parent_dashboard(self):
        self.assertURLOK(self.c, reverse("parent_dashboard"))

    def test_parent_add_child(self):
        self.assertURLOK(self.c, reverse("parent_add_child"))

    def test_parent_invoices(self):
        self.assertURLOK(self.c, reverse("parent_invoices"))

    def test_parent_invoice_detail(self):
        self.assertURLOK(self.c, reverse("parent_invoice_detail", kwargs={"invoice_id": self.invoice.id}))

    def test_parent_payment_history(self):
        self.assertURLOK(self.c, reverse("parent_payment_history"))

    def test_parent_attendance(self):
        self.assertURLOK(self.c, reverse("parent_attendance"))

    def test_parent_progress(self):
        self.assertURLOK(self.c, reverse("parent_progress"))

    def test_parent_classes(self):
        self.assertURLOK(self.c, reverse("parent_classes"))

    def test_my_children(self):
        self.assertURLOK(self.c, reverse("my_children"))


# ---------------------------------------------------------------------------
# Authenticated — Progress URLs
# ---------------------------------------------------------------------------

class TestProgressURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.teacher)

    def test_progress_criteria_list(self):
        self.assertURLOK(self.c, reverse("progress_criteria_list"))

    def test_progress_criteria_create(self):
        self.assertURLOK(self.c, reverse("progress_criteria_create"))

    def test_student_progress(self):
        self.assertURLOK(self.c, reverse("student_progress", kwargs={"student_id": self.student.id}))

    def test_student_progress_report(self):
        self.assertURLOK(self.c, reverse("student_progress_report"))


# ---------------------------------------------------------------------------
# Billing plan/subscription pages (school admin)
# ---------------------------------------------------------------------------

class TestBillingURLs(FullHierarchyMixin, TestCase):

    def setUp(self):
        self.c = self._client(self.admin)

    def test_institute_plan_select(self):
        self.assertURLOK(self.c, reverse("institute_plan_select"))

    def test_institute_trial_expired(self):
        self.assertURLOK(self.c, reverse("institute_trial_expired"))

    def test_billing_module_required(self):
        self.assertURLOK(self.c, reverse("module_required"))

    def test_billing_admin_dashboard(self):
        self.assertURLOK(self.c, reverse("billing_admin_dashboard"))

    def test_billing_history(self):
        self.assertURLOK(self.c, reverse("billing_history"))
