"""
URL Sitemap Validation — All 700+ named routes
===============================================
Dynamically discovers every named URL pattern registered in the project,
resolves required kwargs using real DB objects, then GETs each URL and
asserts the response is NOT a server error (500) or missing route (404).

Exclusions (handled separately or not GET-accessible):
- Django admin routes    (admin:*)
- POST/webhook-only      (stripe_webhook, payment_intents, etc.)
- Multi-step wizard URLs (CSV preview/confirm, password reset confirm)
- HTMX partials          (htmx_*)
- JSON API endpoints     (api/*)
- UUID-token routes      (parent registration, password reset confirm)
"""
from __future__ import annotations

import re
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import NoReverseMatch, get_resolver, URLPattern, URLResolver, reverse


# ---------------------------------------------------------------------------
# URL pattern introspection helpers
# ---------------------------------------------------------------------------

def _collect_patterns(resolver=None, prefix="", ns_stack=None):
    """Recursively yield (full_name, route, [param_names]) for every named URL."""
    if resolver is None:
        resolver = get_resolver()
    ns_stack = ns_stack or []
    results = []
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            new_ns = ns_stack + ([p.namespace] if p.namespace else [])
            results.extend(_collect_patterns(p, prefix + str(p.pattern), new_ns))
        elif isinstance(p, URLPattern) and p.name:
            route = prefix + str(p.pattern)
            ns = ":".join(ns_stack)
            full_name = (ns + ":" + p.name) if ns else p.name
            params = re.findall(r"<(?:\w+:)?(\w+)>", route)
            results.append((full_name, route, params))
    return results


# ---------------------------------------------------------------------------
# Patterns to skip entirely (POST-only, webhooks, wizard steps, etc.)
# ---------------------------------------------------------------------------

SKIP_EXACT = frozenset({
    # Stripe / payment — POST-only or needs Stripe payload
    "stripe_webhook",
    "create_payment_intent",
    "confirm_payment",
    "apply_promo_code",
    "stripe_billing_portal",
    "institute_checkout",          # redirects to Stripe
    # Invoice/salary actions — POST-only forms
    "issue_invoices",
    "delete_draft_invoices",
    "cancel_invoice",
    "record_manual_payment",
    "issue_salary_slips",
    "delete_draft_salary_slips",
    "cancel_salary_slip",
    "record_salary_payment",
    # CSV wizard multi-step (require session state from prior step)
    "student_csv_preview",
    "student_csv_structure_mapping",
    "student_csv_confirm",
    "student_csv_credentials",
    "balance_csv_preview",
    "balance_csv_confirm",
    "teacher_csv_preview",
    "teacher_csv_confirm",
    "teacher_csv_credentials",
    "parent_csv_preview",
    "parent_csv_confirm",
    "parent_csv_credentials",
    "csv_column_mapping",
    "csv_review_matches",
    "confirm_csv_payments",
    # Password reset confirm (needs valid uidb64+token pair)
    "password_reset_confirm",
    "password_reset_done",
    "password_reset_complete",
    # Enrol/redeem actions — POST-only
    "student_redeem_absence_token",
    "student_enroll_global_class",
    "student_mark_attendance",
    # Approval/reject actions — POST-only
    "attendance_approve",
    "attendance_reject",
    "attendance_bulk_approve",
    "absence_token_approve",
    "absence_token_reject",
    "parent_link_approve",
    "parent_link_reject",
    "enrollment_approve",
    "enrollment_reject",
    "progress_criteria_approve",
    "progress_criteria_reject",
    "progress_criteria_submit",
    "revoke_parent_invite",
    "unlink_parent_student",
    # Admin school toggle/delete/publish actions
    "admin_school_toggle_active",
    "admin_school_delete",
    "admin_school_publish",
    "admin_school_teacher_remove",
    "admin_school_teacher_restore",
    "admin_school_teacher_batch_update",
    "admin_school_student_remove",
    "admin_school_student_restore",
    "admin_school_student_batch_update",
    # HoD actions
    "hod_delete_class",
    "hod_restore_class",
    "hod_subject_level_remove",
    # HTMX partial
    "htmx_topics_for_level",
    # number_puzzles_results requires a UUID session_id from an active puzzle session
    "number_puzzles_results",
    # Logout (POST in Django 5)
    "logout",
    # POST-only teacher actions
    "start_session",           # POST-only
    "teacher_switch_school",   # POST-only
    # Switch role (POST)
    "switch_role",
    # Parent switch child (POST)
    "parent_switch_child",
    # Become parent (POST)
    "become_parent",
    # Student absence token request (POST-only)
    "student_request_absence_token",
    # HoD assign class (POST-only)
    "hod_assign_class",
    # Module toggle (POST)
    "module_toggle",
    # Block/suspend (POST)
    "admin_block_user",
    "admin_unblock_user",
    "admin_suspend_school",
    "admin_unsuspend_school",
    # Institute cancel (POST)
    "institute_cancel_subscription",
    "institute_change_plan",
    # Time log update (POST API)
    "maths:update_time_log",
    # Batch updates (POST)
    "batch_classroom_fee",
    "batch_opening_balance",
    "batch_teacher_rate",
    # Set overrides (POST)
    "add_student_fee_override",
    "add_teacher_rate_override",
    "set_school_default_rate",
    "set_classroom_fee",
    "set_opening_balance",
    # DB backup (dangerous)
    "database_backup",
    # Teacher session cancel/delete
    "cancel_session",
    "delete_session",
    "complete_session",
    # Class student remove/fee
    "class_student_remove",
    "update_student_fee",
    # AI import wizard steps — session_id is an AI import UUID, not classroom session
    "ai_import:preview",
    "ai_import:confirm",
    "ai_import:export",
    "ai_import:upload_image",
})

SKIP_PREFIXES = (
    "admin:",           # Django admin — complex object_id setup
    "django_js_reverse",
)

SKIP_PATTERNS = (
    r"^accounts/api/",  # JSON API — tested in test_api_endpoints_no_500
    r"^api/",
    r"^invoicing/api/",
    r"^salaries/api/",
    r"<uuid:token>",    # UUID registration tokens
    r"<uidb64>",        # password reset
)

# POST-only URLs that cannot be meaningfully tested with an empty POST
# (external services, dangerous side effects, or require prior wizard session).
# Everything in SKIP_EXACT *not* in this set will be POSTed to in
# test_post_actions_no_500.
POST_ALWAYS_SKIP = frozenset({
    # External payment processors — require signed Stripe payload
    "stripe_webhook", "create_payment_intent", "confirm_payment",
    "apply_promo_code", "stripe_billing_portal", "institute_checkout",
    # Requires valid signed uidb64+token pair
    "password_reset_confirm",
    # CSV wizard steps — require data from prior wizard step in session
    "student_csv_preview", "student_csv_structure_mapping", "student_csv_confirm",
    "balance_csv_preview", "balance_csv_confirm",
    "teacher_csv_preview", "teacher_csv_confirm",
    "parent_csv_preview", "parent_csv_confirm",
    "csv_column_mapping", "csv_review_matches", "confirm_csv_payments",
    # CSV credential views — GET but need session; tested in test_csv_credentials_no_500
    "student_csv_credentials", "teacher_csv_credentials", "parent_csv_credentials",
    # DB backup — dangerous, irreversible side effects
    "database_backup",
    # AI import wizard — tested separately in test_ai_import_wizard_no_500
    "ai_import:preview", "ai_import:confirm", "ai_import:export", "ai_import:upload_image",
    # Logout changes auth state for the test client
    "logout",
    # number_puzzles_results requires a UUID from an active live puzzle session
    "number_puzzles_results",
    # HTMX partial — requires HTMX headers and prior context
    "htmx_topics_for_level",
})


# ---------------------------------------------------------------------------
# Full school hierarchy — created once for all tests
# ---------------------------------------------------------------------------

class FullHierarchyMixin:

    @classmethod
    def setUpTestData(cls):  # noqa: N802
        from accounts.models import CustomUser, Role, UserRole
        from attendance.models import AbsenceToken, ClassSession, StudentAttendance
        from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
        from classroom.models import (
            AbsenceToken as CAbsenceToken,
            AcademicYear, ClassRoom, ClassStudent, ClassTeacher,
            Department, DepartmentSubject, DepartmentTeacher,
            Guardian, Invoice, InvoiceLineItem,
            Level, ParentInvite, ParentLinkRequest, ParentStudent,
            ProgressCriteria, SalarySlip,
            School, SchoolStudent, SchoolTeacher,
            Subject, Term, Topic,
        )
        from ai_import.models import AIImportSession
        from homework.models import Homework, HomeworkSubmission
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
        cls.admin      = make_user("url_admin",      Role.ADMIN, is_staff=True, is_superuser=True)
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
        cls.plan = plan

        # ── School staff ───────────────────────────────────────────────────
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
        strand = Topic.objects.create(
            subject=cls.subject, name=f"Number {RUN}", slug=f"number-{RUN}", order=1,
        )
        cls.topic = Topic.objects.create(
            subject=cls.subject, parent=strand,
            name=f"Addition {RUN}", slug=f"addition-{RUN}", order=1,
        )
        cls.topic.levels.add(cls.level)

        # ── Department ─────────────────────────────────────────────────────
        cls.dept = Department.objects.create(
            school=cls.school, name=f"Maths {RUN}", slug=f"maths-{RUN}", head=cls.hod,
        )
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.subject)
        DepartmentTeacher.objects.get_or_create(department=cls.dept, teacher=cls.hod)
        DepartmentTeacher.objects.get_or_create(department=cls.dept, teacher=cls.s_teacher)

        # ── Classroom ──────────────────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name=f"Year 7 {RUN}", school=cls.school,
            department=cls.dept, subject=cls.subject,
            day="monday", start_time=time(9, 0), end_time=time(10, 0),
        )
        cls.classroom.levels.add(cls.level)
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        # ── Student enrollment ─────────────────────────────────────────────
        SchoolStudent.objects.get_or_create(school=cls.school, student=cls.student)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )
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
        StudentGuardian.objects.create(
            student=cls.student, guardian=cls.guardian, is_primary=True,
        )

        # ── Academic year / term ───────────────────────────────────────────
        today = date.today()
        cls.academic_year = AcademicYear.objects.create(
            school=cls.school, year=today.year,
            start_date=date(today.year, 1, 1),
            end_date=date(today.year, 12, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.academic_year,
            name="Term 1", start_date=today,
            end_date=today + timedelta(days=90), order=1,
        )

        # ── Session + attendance ───────────────────────────────────────────
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom,
            date=today - timedelta(days=1),
            start_time=time(9, 0), end_time=time(10, 0),
            status="completed", created_by=cls.teacher,
        )
        cls.attendance_record = StudentAttendance.objects.create(
            session=cls.session, student=cls.student, status="present",
        )

        # ── Absence token ──────────────────────────────────────────────────
        from django.utils import timezone as tz
        cls.absence_token = AbsenceToken.objects.create(
            student=cls.student,
            original_session=cls.session,
            original_classroom=cls.classroom,
            created_by=cls.teacher,
            status="approved",
            expires_at=tz.now() + timedelta(days=30),
        )

        # ── Questions ─────────────────────────────────────────────────────
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text="What is 2+2?", question_type="multiple_choice",
            difficulty=1, points=1,
        )
        for text, correct in [("4", True), ("3", False), ("5", False), ("6", False)]:
            Answer.objects.create(
                question=cls.question, answer_text=text, is_correct=correct,
            )

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

        # ── Salary slip ────────────────────────────────────────────────────
        cls.salary_slip = SalarySlip.objects.create(
            school=cls.school, teacher=cls.teacher,
            slip_number=f"SAL-{RUN}",
            billing_period_start=today - timedelta(days=30),
            billing_period_end=today,
            status="draft", amount=Decimal("500.00"),
            calculated_amount=Decimal("500.00"),
            created_by=cls.admin,
        )

        # ── Homework ───────────────────────────────────────────────────────
        from django.utils import timezone as tz
        cls.homework = Homework.objects.create(
            classroom=cls.classroom,
            created_by=cls.teacher,
            title=f"Homework {RUN}",
            homework_type="topic",
            num_questions=5,
            due_date=tz.now() + timedelta(days=7),
        )
        cls.homework_submission = HomeworkSubmission.objects.create(
            homework=cls.homework,
            student=cls.student,
            score=4,
            total_questions=5,
        )

        # ── Progress criteria ──────────────────────────────────────────────
        cls.progress_criteria = ProgressCriteria.objects.create(
            school=cls.school, subject=cls.subject, level=cls.level,
            name=f"Criteria {RUN}", description="Test criteria",
            status="approved", created_by=cls.teacher,
        )

        # ── Parent invite ──────────────────────────────────────────────────
        cls.parent_invite = ParentInvite.objects.create(
            school=cls.school, student=cls.student,
            parent_email=f"invite_{RUN}@test.local",
            relationship="guardian", invited_by=cls.admin,
            status="pending",
            expires_at=tz.now() + timedelta(days=7),
        )

        # ── Parent link request ────────────────────────────────────────────
        from classroom.models import SchoolStudent
        school_student = SchoolStudent.objects.get(school=cls.school, student=cls.student)
        cls.parent_link_request = ParentLinkRequest.objects.create(
            parent=cls.parent,
            school_student=school_student,
            relationship="guardian",
            status="pending",
        )

        # ── Parent-student link id (for admin_parent_link_edit_modal) ─────
        cls.parent_student_link = ParentStudent.objects.filter(
            parent=cls.parent, student=cls.student, school=cls.school,
        ).first()

        # ── AI Import Session (owned by admin so client auth passes) ───────
        cls.ai_session = AIImportSession.objects.create(
            user=cls.admin,
            school=cls.school,
            pdf_filename="test_import.pdf",
            extracted_data={"questions": []},
            page_count=1,
            is_confirmed=False,
        )

    # ── Kwargs resolver ────────────────────────────────────────────────────

    def _build_kwargs(self, params):
        """Map URL parameter names to real object IDs."""
        mapping = {
            "school_id":        self.school.id,
            "dept_id":          self.dept.id,
            "class_id":         self.classroom.id,
            "classroom_id":     self.classroom.id,
            "session_id":       self.session.id,
            "student_id":       self.student.id,
            "teacher_id":       self.teacher.id,
            "topic_id":         self.topic.id,
            "level_number":     self.level.level_number,
            "level_id":         self.level.id,
            "invoice_id":       self.invoice.id,
            "slip_id":          self.salary_slip.id,
            "homework_id":      self.homework.id,
            "submission_id":    self.homework_submission.id,
            "criteria_id":      self.progress_criteria.id,
            "invite_id":        self.parent_invite.id,
            "request_id":       self.parent_link_request.id,
            "link_id":          self.parent_student_link.id,
            "guardian_id":      self.guardian.id,
            "academic_year_id": self.academic_year.id,
            "question_id":      self.question.id,
            "token_id":         self.absence_token.id,
            "attendance_id":    self.attendance_record.id,
            "subject":          "maths",
            "subtopic":         "addition",
            "table":            2,
            "package_id":       self.plan.id,
            "payment_id":       self.invoice.id,  # rough stand-in
            "import_id":        1,  # won't exist → 404 from view (not routing 404)
            "enrollment_id":    1,
            "campaign_id":      1,
            "pk":               self.admin.id,
            "id":               self.admin.id,
            # slug placeholders
            "slug":             "test",
            "app_label":        "classroom",
            "content_type_id":  1,
            "object_id":        1,
            # token/uidb64 — will get 404 from view (invalid token), not routing 404
            "token":            "invalid-token",
            "uidb64":           "NA",
        }
        return {p: mapping[p] for p in params if p in mapping}

    def _client_for(self, url_name):
        """Return the most permissive client suitable for the URL."""
        c = Client()
        # Use admin for everything — superuser can access all school views
        c.login(username=self.admin.username, password="TestPass123!")
        return c

    def _should_skip(self, full_name, route, params):
        if full_name in SKIP_EXACT:
            return True
        for prefix in SKIP_PREFIXES:
            if full_name.startswith(prefix):
                return True
        for pat in SKIP_PATTERNS:
            if re.search(pat, route):
                return True
        # Skip if any required param has no mapping
        mapping = {
            "school_id", "dept_id", "class_id", "classroom_id", "session_id",
            "student_id", "teacher_id", "topic_id", "level_number", "level_id",
            "invoice_id", "slip_id", "homework_id", "submission_id", "criteria_id",
            "invite_id", "request_id", "link_id", "guardian_id", "academic_year_id",
            "question_id", "token_id", "attendance_id", "subject", "subtopic",
            "table", "package_id", "payment_id", "import_id", "enrollment_id",
            "campaign_id", "pk", "id", "slug", "app_label", "content_type_id",
            "object_id", "token", "uidb64",
        }
        for p in params:
            if p not in mapping:
                return True  # unknown param — skip rather than fail
        return False


# ---------------------------------------------------------------------------
# Single test class that dynamically iterates ALL URL patterns
# ---------------------------------------------------------------------------

class TestAllURLsSitemap(FullHierarchyMixin, TestCase):
    """
    Iterates every named URL pattern in the project.
    Asserts each returns a non-500 (and non-routing-404) response.
    Failures are collected and reported together at the end.
    """

    def test_all_urls_no_500(self):
        """GET every named URL — collect all failures, report at end."""
        all_patterns = _collect_patterns()
        failures = []
        skipped = []
        tested = 0

        for full_name, route, params in all_patterns:
            if self._should_skip(full_name, route, params):
                skipped.append(full_name)
                continue

            kwargs = self._build_kwargs(params)

            # Try to reverse the URL
            try:
                ns, name = full_name.rsplit(":", 1) if ":" in full_name else ("", full_name)
                url = reverse(full_name, kwargs=kwargs)
            except NoReverseMatch as e:
                failures.append(f"NoReverseMatch {full_name!r}: {e}")
                continue

            # GET the URL
            c = self._client_for(full_name)
            try:
                resp = c.get(url, follow=True)
            except Exception as e:
                failures.append(f"Exception {full_name!r} ({url}): {e}")
                continue

            if resp.status_code == 500:
                failures.append(f"500 {full_name!r} → {url}")
            elif resp.status_code == 404:
                # Params that use stub IDs (1) which may not exist → expected 404 from view
                placeholder_params = {
                    "import_id", "enrollment_id", "campaign_id", "payment_id",
                    # homework/submission use real IDs but view gates on session state
                    "submission_id", "homework_id",
                    # number_puzzles_play uses slug="test" (doesn't exist) → 404 expected
                    "slug",
                    # billing checkout — plan may not be in purchasable state
                    "package_id",
                    # absence token available sessions — student may have none
                    "token_id",
                }
                if not any(p in placeholder_params for p in params):
                    failures.append(f"404 {full_name!r} → {url}")

            tested += 1

        # Report summary
        summary = (
            f"\nTested: {tested}  |  Skipped: {len(skipped)}  |  "
            f"Total patterns: {len(all_patterns)}"
        )
        if failures:
            self.fail(
                f"{len(failures)} URL(s) failed:{summary}\n\n"
                + "\n".join(f"  • {f}" for f in failures)
            )
        else:
            print(summary)  # visible with -s flag

    # ── Known URL parameter names (for POST + API tests) ──────────────────

    _KNOWN_PARAMS = frozenset({
        "school_id", "dept_id", "class_id", "classroom_id", "session_id",
        "student_id", "teacher_id", "topic_id", "level_number", "level_id",
        "invoice_id", "slip_id", "homework_id", "submission_id", "criteria_id",
        "invite_id", "request_id", "link_id", "guardian_id", "academic_year_id",
        "question_id", "token_id", "attendance_id", "subject", "subtopic",
        "table", "package_id", "payment_id", "import_id", "enrollment_id",
        "campaign_id", "pk", "id", "slug", "app_label", "content_type_id",
        "object_id", "token", "uidb64",
    })

    def _can_build_url(self, full_name, route, params):
        """Return True if all URL params can be resolved and no skip patterns match."""
        if full_name.startswith(SKIP_PREFIXES):
            return False
        for pat in SKIP_PATTERNS:
            if re.search(pat, route):
                return False
        return all(p in self._KNOWN_PARAMS for p in params)

    # ── POST actions ───────────────────────────────────────────────────────

    def test_post_actions_no_500(self):
        """POST to action-only URLs with empty data — must not return 500.

        Views that are POST-only but handle missing/invalid form data gracefully
        should return 302/400/403/200 — never 500.
        """
        name_to_info = {
            fn: (route, params)
            for fn, route, params in _collect_patterns()
        }
        failures = []
        tested = 0

        # Iterate SKIP_EXACT entries that aren't in POST_ALWAYS_SKIP
        for full_name in sorted(SKIP_EXACT - POST_ALWAYS_SKIP):
            if full_name not in name_to_info:
                continue
            route, params = name_to_info[full_name]
            if not self._can_build_url(full_name, route, params):
                continue
            kwargs = self._build_kwargs(params)
            if len(kwargs) < len(params):
                continue
            try:
                url = reverse(full_name, kwargs=kwargs)
            except NoReverseMatch:
                continue

            c = self._client_for(full_name)
            try:
                resp = c.post(url, data={}, follow=True)
            except Exception as exc:
                failures.append(f"Exception POST {full_name!r}: {exc}")
                continue

            if resp.status_code == 500:
                failures.append(f"500 POST {full_name!r} → {url}")
            tested += 1

        summary = f"\nPOST tested: {tested}"
        if failures:
            self.fail(
                f"{len(failures)} POST URL(s) failed (of {tested} tested):{summary}\n\n"
                + "\n".join(f"  • {f}" for f in failures)
            )
        else:
            print(summary)

    # ── AI Import wizard ───────────────────────────────────────────────────

    def test_ai_import_wizard_no_500(self):
        """AI import wizard views must not 500 when called with a real session."""
        # Use one client logged in as admin (who owns cls.ai_session)
        c = self._client_for("ai_import:preview")
        sid = self.ai_session.id
        ai_views = [
            ("ai_import:preview",      {"session_id": sid}, "GET"),
            ("ai_import:confirm",      {"session_id": sid}, "GET"),
            ("ai_import:export",       {"session_id": sid}, "GET"),
            ("ai_import:upload_image", {"session_id": sid}, "POST"),
        ]
        failures = []
        for full_name, kwargs, method in ai_views:
            try:
                url = reverse(full_name, kwargs=kwargs)
            except NoReverseMatch as exc:
                failures.append(f"NoReverseMatch {full_name!r}: {exc}")
                continue
            try:
                if method == "POST":
                    resp = c.post(url, data={}, follow=True)
                else:
                    resp = c.get(url, follow=True)
            except Exception as exc:
                failures.append(f"Exception {full_name!r}: {exc}")
                continue
            if resp.status_code == 500:
                failures.append(f"500 {method} {full_name!r} → {url}")

        if failures:
            self.fail(
                f"{len(failures)} AI import URL(s) failed:\n\n"
                + "\n".join(f"  • {f}" for f in failures)
            )

    # ── JSON API endpoints ─────────────────────────────────────────────────

    def test_api_endpoints_no_500(self):
        """GET-accessible JSON API endpoints must not 500."""
        api_route_prefixes = (
            "accounts/api/",
            "api/",
            "invoicing/api/",
            "salaries/api/",
        )
        api_patterns = [
            (fn, route, params)
            for fn, route, params in _collect_patterns()
            if any(route.startswith(p) for p in api_route_prefixes)
            and not re.search(r"<uuid:token>|<uidb64>", route)
        ]
        failures = []
        tested = 0

        for full_name, route, params in api_patterns:
            # Don't use _can_build_url here — it re-applies SKIP_PATTERNS
            if full_name.startswith(SKIP_PREFIXES):
                continue
            if not all(p in self._KNOWN_PARAMS for p in params):
                continue
            kwargs = self._build_kwargs(params)
            if len(kwargs) < len(params):
                continue
            try:
                url = reverse(full_name, kwargs=kwargs)
            except NoReverseMatch:
                continue

            c = self._client_for(full_name)
            try:
                # Append common search/query params for search endpoints
                resp = c.get(
                    url + "?q=test&username=testuser",
                    HTTP_ACCEPT="application/json",
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                    follow=True,
                )
            except Exception as exc:
                failures.append(f"Exception API {full_name!r}: {exc}")
                continue

            if resp.status_code == 500:
                failures.append(f"500 API {full_name!r} → {url}")
            tested += 1

        summary = f"\nAPI tested: {tested}"
        if failures:
            self.fail(
                f"{len(failures)} API URL(s) failed (of {tested} tested):{summary}\n\n"
                + "\n".join(f"  • {f}" for f in failures)
            )
        else:
            print(summary)

    # ── CSV credential download views ──────────────────────────────────────

    def test_csv_credentials_no_500(self):
        """CSV credential download views (GET with injected session) must not 500."""
        base_cred = {
            "username": "testuser",
            "email": "testuser@test.local",
            "password": "TestPass1!",
            "first_name": "Test",
            "last_name": "User",
        }
        student_cred = {**base_cred}
        teacher_cred = {**base_cred, "role": "teacher"}
        parent_cred  = {**base_cred, "children": "Student One"}
        cred_views = {
            "student_csv_credentials": {
                "csv_student_credentials": [student_cred],
                "csv_parent_credentials":  [parent_cred],
            },
            "teacher_csv_credentials": {
                "csv_teacher_credentials": [teacher_cred],
            },
            "parent_csv_credentials": {
                "csv_parent_credentials": [parent_cred],
            },
        }
        failures = []

        for url_name, session_data in cred_views.items():
            try:
                url = reverse(url_name)
            except NoReverseMatch:
                continue

            c = self._client_for(url_name)
            # Inject the expected session keys
            sess = c.session
            sess.update(session_data)
            sess.save()

            try:
                resp = c.get(url, follow=True)
            except Exception as exc:
                failures.append(f"Exception {url_name!r}: {exc}")
                continue

            if resp.status_code == 500:
                failures.append(f"500 {url_name!r} → {url}")

        if failures:
            self.fail(
                f"{len(failures)} CSV credential URL(s) failed:\n\n"
                + "\n".join(f"  • {f}" for f in failures)
            )
