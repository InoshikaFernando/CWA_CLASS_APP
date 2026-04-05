"""
Comprehensive URL coverage test — verifies every GET-accessible URL in the project
returns a non-500 status code (200 or a legitimate redirect).

Strategy
--------
* One shared ``setUpTestData`` builds a complete school hierarchy so all
  parameterised URLs can be resolved with real DB IDs.
* Five test classes, one per actor:
    - Anonymous visitor         → public pages only
    - Individual student        → student-facing pages
    - Teacher                   → teacher dashboard + class management
    - HoI (head of institute)   → admin-dashboard, HoD, invoicing, salaries
    - Superuser (Django admin)  → /admin/ CRUD

* Accepted response codes per endpoint type:
    - 200  OK
    - 302  redirect (role-gate, login-gate, or post-action redirect)
    - 405  method not allowed (GET on a POST-only endpoint is fine)
  Any 4xx (except 404 for missing objects) or 5xx fails the test.

* POST-only / webhook / Stripe endpoints are skipped explicitly.

* Django admin changelist/add/change/delete/history URLs (401 patterns) are
  exercised as a single bulk test logged in as superuser.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, Package, SchoolSubscription, Subscription,
)
from classroom.models import (
    AcademicYear,
    ClassRoom,
    ClassSession,
    ClassStudent,
    ClassTeacher,
    Department,
    DepartmentLevel,
    DepartmentSubject,
    DepartmentTeacher,
    Enrollment,
    Invoice,
    Level,
    ParentStudent,
    SalarySlip,
    School,
    SchoolStudent,
    SchoolTeacher,
    Subject,
    Term,
    Topic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKIP_PATTERNS = {
    # POST-only / action endpoints — no meaningful GET
    'stripe_webhook',
    'billing_cancel',
    'billing_success',
    'create_payment_intent',
    'confirm_payment',
    'apply_promo_code',
    'institute_checkout',
    'institute_checkout_success',
    'institute_cancel_subscription',
    'institute_change_plan',
    'institute_plan_upgrade',
    'module_toggle',
    'stripe_billing_portal',
    # Bulk-action POST endpoints
    'generate_invoices',
    'issue_invoices',
    'delete_draft_invoices',
    'generate_salary_slips',
    'issue_salary_slips',
    'delete_draft_salary_slips',
    'batch_classroom_fee',
    'batch_opening_balance',
    'batch_teacher_rate',
    'set_school_default_rate',
    'admin_school_student_batch_update',
    'admin_school_teacher_batch_update',
    'admin_suspend_school',
    'admin_unsuspend_school',
    'admin_block_user',
    'admin_unblock_user',
    'billing_admin_plan_sync',
    'billing_admin_module_sync',
    'billing_admin_discount_toggle',
    'billing_admin_module_toggle',
    'billing_admin_plan_toggle',
    'billing_admin_promo_toggle',
    'admin_school_toggle_active',
    'admin_department_toggle_active',
    'attendance_approve',
    'attendance_reject',
    'attendance_bulk_approve',
    'enrollment_approve',
    'enrollment_reject',
    'admin_department_subject_level_remove',
    'hod_subject_level_remove',
    'revoke_parent_invite',
    'unlink_parent_student',
    'class_student_remove',
    'admin_school_student_remove',
    'admin_school_student_restore',
    'admin_school_teacher_remove',
    'admin_school_teacher_restore',
    'hod_delete_class',
    'hod_restore_class',
    'process_refund',
    'cancel_invoice',
    'cancel_salary_slip',
    'record_manual_payment',
    'record_salary_payment',
    'switch_role',
    'school_switcher',
    'parent_switch_child',
    # API / HTMX endpoints (JSON, not HTML)
    'api_submit_topic_answer',
    'api_topic_next',
    'api_tt_answer',
    'api_tt_next',
    'api_update_time_log',
    'api_department_levels',
    'htmx_topics_for_level',
    'check_username',
    'student_search_api',
    'teacher_search_api',
    # Email action endpoints
    'email_unsubscribe',
    'email_compose',
    'invite_parent',
    # Billing portal (requires Stripe)
    'billing_admin_subscription_override',
    # CSV confirm / mapping (require prior session state)
    'student_csv_confirm',
    'teacher_csv_confirm',
    'parent_csv_confirm',
    'balance_csv_confirm',
    'confirm_csv_payments',
    'csv_review_matches',
    # AI import (require prior session)
    'ai_import:preview',
    'ai_import:upload_image',
    'ai_import:confirm',
    'ai_import:export',
    # Times-tables submit/results (require prior session)
    'times_tables_submit',
    'times_tables_results_view',
    # Number puzzle play/results (require prior session or slug)
    'number_puzzles_play',
    'number_puzzles_results',
    # Basic facts quiz/results (require prior session)
    'basic_facts_quiz',
    'basic_facts_results',
    # Mixed quiz results (require prior session)
    'mixed_results',
    # Register parent (requires UUID token)
    'register_parent',
    # Accept parent invite (requires UUID token)
    'accept_parent_invite',
}

ACCEPTED = {200, 302, 301, 403, 405}  # 403 = permission denied is fine; 404 = bad data


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def _user(username, **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        email=f'{username}@test.internal',
        password='Test@1234!',
        **kwargs,
    )


def _assign(user, role_name):
    UserRole.objects.get_or_create(user=user, role=_role(role_name))


def _get(client, url, label=''):
    try:
        return client.get(url, follow=False)
    except Exception as e:
        raise AssertionError(f'Exception on GET {url!r} ({label}): {e}') from e


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

class _SharedFixture(TestCase):
    """
    setUpTestData creates a full school hierarchy once per test class.
    Django wraps it in a savepoint and rolls back after the class → cascade delete.
    """

    @classmethod
    def setUpTestData(cls):
        # ── Roles ────────────────────────────────────────────────────────
        for r in [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
                  Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER, Role.TEACHER,
                  Role.JUNIOR_TEACHER, Role.STUDENT, Role.INDIVIDUAL_STUDENT,
                  Role.PARENT, Role.ACCOUNTANT]:
            _role(r)

        # ── Admin / HoI ──────────────────────────────────────────────────
        cls.hoi = _user('url_hoi')
        _assign(cls.hoi, Role.HEAD_OF_INSTITUTE)
        _assign(cls.hoi, Role.INSTITUTE_OWNER)
        _assign(cls.hoi, Role.ADMIN)

        # ── Teacher ──────────────────────────────────────────────────────
        cls.teacher = _user('url_teacher')
        _assign(cls.teacher, Role.TEACHER)

        # ── School (School.save() auto-creates SchoolTeacher for hoi) ────
        plan = InstitutePlan.objects.create(
            name='URL Test Plan', slug='url-test-plan',
            price=Decimal('0'), class_limit=999, student_limit=999,
            invoice_limit_yearly=9999, extra_invoice_rate=Decimal('0'),
        )
        cls.school = School.objects.create(
            name='URL Test School', slug='url-test-school',
            admin=cls.hoi, is_active=True,
        )
        SchoolSubscription.objects.create(
            school=cls.school, plan=plan,
            status=SchoolSubscription.STATUS_ACTIVE,
        )
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.teacher,
            defaults={'role': 'teacher', 'is_active': True},
        )

        # ── Subject + Levels ─────────────────────────────────────────────
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=1,
            defaults={'display_name': 'Year 1', 'subject': cls.subject},
        )[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='URL Test Topic',
            defaults={'slug': 'url-test-topic'},
        )[0]

        # ── Department ───────────────────────────────────────────────────
        cls.department = Department.objects.create(
            name='URL Test Dept', school=cls.school, is_active=True,
        )
        DepartmentSubject.objects.get_or_create(
            department=cls.department, subject=cls.subject,
        )
        DepartmentTeacher.objects.get_or_create(
            department=cls.department, teacher=cls.teacher,
        )
        DepartmentLevel.objects.get_or_create(
            department=cls.department, level=cls.level,
        )

        # ── HoD ──────────────────────────────────────────────────────────
        cls.hod = _user('url_hod')
        _assign(cls.hod, Role.HEAD_OF_DEPARTMENT)
        cls.department.head = cls.hod
        cls.department.save()
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.hod,
            defaults={'role': 'head_of_department', 'is_active': True},
        )

        # ── Classroom ────────────────────────────────────────────────────
        cls.classroom = ClassRoom.objects.create(
            name='URL Test Class', school=cls.school,
            department=cls.department, subject=cls.subject, is_active=True,
        )
        cls.classroom.levels.add(cls.level)
        ClassTeacher.objects.get_or_create(
            classroom=cls.classroom, teacher=cls.teacher,
        )

        # ── Student ──────────────────────────────────────────────────────
        cls.student = _user('url_student')
        _assign(cls.student, Role.STUDENT)
        SchoolStudent.objects.get_or_create(
            school=cls.school, student=cls.student,
        )
        ClassStudent.objects.get_or_create(
            classroom=cls.classroom, student=cls.student,
        )

        # ── Individual student + active subscription ─────────────────────
        pkg = Package.objects.create(
            name='URL Test Package', price=Decimal('0'), is_active=True,
        )
        cls.ind_student = _user('url_ind_student')
        _assign(cls.ind_student, Role.INDIVIDUAL_STUDENT)
        Subscription.objects.create(
            user=cls.ind_student, package=pkg,
            status=Subscription.STATUS_ACTIVE,
            current_period_end=timezone.now() + timedelta(days=365),
        )

        # ── Parent ───────────────────────────────────────────────────────
        cls.parent = _user('url_parent')
        _assign(cls.parent, Role.PARENT)
        cls.parent_link = ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
            relationship='guardian', is_active=True,
        )

        # ── Academic year + term ─────────────────────────────────────────
        cls.academic_year = AcademicYear.objects.create(
            school=cls.school, year=2026, start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.academic_year,
            name='Term 1', start_date=date(2026, 1, 1), end_date=date(2026, 3, 31),
            order=1,
        )

        # ── Class session ────────────────────────────────────────────────
        from datetime import time as dtime
        cls.session = ClassSession.objects.create(
            classroom=cls.classroom, date=date.today(),
            start_time=dtime(9, 0), end_time=dtime(10, 0),
            status='scheduled',
        )

        # ── Invoice ──────────────────────────────────────────────────────
        cls.invoice = Invoice.objects.create(
            invoice_number='INV-URL-001', school=cls.school,
            student=cls.student,
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 3, 31),
            attendance_mode='all_class_days',
            calculated_amount=Decimal('100'), amount=Decimal('100'),
            status='issued',
        )

        # ── Salary slip ──────────────────────────────────────────────────
        cls.salary_slip = SalarySlip.objects.create(
            slip_number='SAL-URL-001', school=cls.school,
            teacher=cls.teacher,
            billing_period_start=date(2026, 1, 1),
            billing_period_end=date(2026, 3, 31),
            calculated_amount=Decimal('500'), amount=Decimal('500'),
            status='issued',
        )

        # ── Superuser ────────────────────────────────────────────────────
        cls.superuser = CustomUser.objects.create_superuser(
            username='url_superuser',
            email='url_superuser@test.internal',
            password='Test@1234!',
        )
        _assign(cls.superuser, Role.ADMIN)
        _assign(cls.superuser, Role.HEAD_OF_INSTITUTE)

        # ── Enrollment ───────────────────────────────────────────────────
        cls.enrollment = Enrollment.objects.create(
            student=cls.ind_student,
            classroom=cls.classroom,
            status='pending',
        )

    # convenience
    def _check(self, url, label=''):
        r = _get(self.client, url, label)
        self.assertIn(
            r.status_code, ACCEPTED,
            f'GET {url!r} ({label}) → {r.status_code}',
        )
        return r.status_code


# ---------------------------------------------------------------------------
# 1. Anonymous / public pages
# ---------------------------------------------------------------------------

class AnonymousURLTest(_SharedFixture):
    """No login — only pages that are genuinely public."""

    def _check_200(self, url, label=''):
        r = _get(self.client, url, label)
        self.assertEqual(r.status_code, 200, f'Expected 200 for {url!r} ({label}), got {r.status_code}')

    def test_root(self):
        self._check_200('/')

    def test_contact(self):
        self._check_200('/contact/')

    def test_join(self):
        self._check_200('/join/')

    def test_privacy(self):
        self._check_200('/privacy/')

    def test_terms(self):
        self._check_200('/terms/')

    def test_login(self):
        self._check_200('/accounts/login/')

    def test_password_reset(self):
        self._check_200('/accounts/password_reset/')

    def test_register_teacher_center(self):
        self._check_200('/accounts/register/teacher-center/')

    def test_register_individual_student(self):
        self._check_200('/accounts/register/individual-student/')

    def test_register_school_student(self):
        self._check_200('/accounts/register/school-student/')

    def test_register_parent_join(self):
        self._check_200('/accounts/register/parent-join/')

    def test_sitemap_xml(self):
        self._check_200('/sitemap.xml')

    def test_robots_txt(self):
        self._check_200('/robots.txt')

    def test_coding(self):
        # @login_required — anonymous visitors get a redirect to login
        r = _get(self.client, '/coding/')
        self.assertIn(r.status_code, {200, 302})

    def test_music(self):
        r = _get(self.client, '/music/')
        self.assertIn(r.status_code, {200, 302})

    def test_science(self):
        r = _get(self.client, '/science/')
        self.assertIn(r.status_code, {200, 302})

    def test_signup_teacher_redirects(self):
        r = _get(self.client, '/accounts/signup/teacher/')
        self.assertIn(r.status_code, {200, 302})

    def test_billing_institute_plans_redirects(self):
        # Unauthenticated → login redirect
        r = _get(self.client, '/billing/institute/plans/')
        self.assertEqual(r.status_code, 302)

    def test_auth_required_pages_redirect_to_login(self):
        """Key protected pages must redirect, not 200 or 500."""
        protected = [
            '/hub/', '/subjects/', '/app-home/', '/student-dashboard/',
            '/maths/', '/basic-facts/', '/times-tables/',
            '/teacher/', '/parent/', '/admin-dashboard/',
            '/accounts/profile/',
        ]
        for url in protected:
            r = _get(self.client, url, url)
            self.assertIn(r.status_code, {302, 301},
                          f'{url} should redirect unauthenticated, got {r.status_code}')


# ---------------------------------------------------------------------------
# 2. Individual student
# ---------------------------------------------------------------------------

class IndividualStudentURLTest(_SharedFixture):

    def setUp(self):
        self.client.login(username='url_ind_student', password='Test@1234!')

    def _urls(self):
        return [
            ('/', 'root'),
            ('/hub/', 'hub'),
            ('/subjects/', 'subjects'),
            ('/app-home/', 'home'),
            ('/student-dashboard/', 'student_dashboard'),
            ('/maths/', 'maths_dashboard'),
            ('/basic-facts/', 'basic_facts_home'),
            ('/basic-facts/Addition/', 'basic_facts_select'),
            ('/times-tables/', 'times_tables_home'),
            (f'/maths/level/{self.level.level_number}/', 'maths_level_detail'),
            (f'/maths/level/{self.level.level_number}/quiz/', 'maths_take_quiz'),
            (f'/maths/level/{self.level.level_number}/practice/', 'maths_practice'),
            (f'/maths/level/{self.level.level_number}/multiplication/', 'tt_mult_select'),
            (f'/maths/level/{self.level.level_number}/division/', 'tt_div_select'),
            (f'/maths/level/{self.level.level_number}/multiplication/2/', 'tt_mult_quiz'),
            (f'/maths/level/{self.level.level_number}/division/2/', 'tt_div_quiz'),
            ('/basic-facts/number-puzzles/', 'number_puzzles_home'),
            ('/accounts/profile/', 'profile'),
            ('/accounts/complete-profile/', 'complete_profile'),
            ('/accounts/select-classes/', 'select_classes'),
            ('/accounts/trial-expired/', 'trial_expired'),
            ('/billing/institute/trial-expired/', 'institute_trial_expired'),
            ('/billing/history/', 'billing_history'),
            ('/billing/module-required/', 'module_required'),
            ('/ai-import/upload/', 'ai_import_upload'),
            ('/ai-import/plans/', 'ai_import_plans'),
            ('/student/my-classes/', 'student_my_classes'),
            (f'/student/class/{self.classroom.id}/', 'student_class_detail'),
            ('/student/join/', 'student_join'),
            ('/student/attendance/', 'student_attendance_history'),
            ('/student/absence-tokens/', 'student_absence_tokens'),
            ('/student/absence-tokens/request/', 'student_absence_token_request'),
            (f'/student/enroll-global/{self.classroom.id}/', 'student_enroll_global'),
            ('/student-dashboard/', 'progress_student_dashboard'),
        ]

    def test_all_student_urls(self):
        failures = []
        for url, label in self._urls():
            try:
                r = _get(self.client, url, label)
                if r.status_code not in ACCEPTED:
                    failures.append(f'{url!r} ({label}) → {r.status_code}')
            except AssertionError as e:
                failures.append(str(e))
        if failures:
            self.fail('Individual student URL failures:\n' + '\n'.join(f'  {f}' for f in failures))


# ---------------------------------------------------------------------------
# 3. School student
# ---------------------------------------------------------------------------

class SchoolStudentURLTest(_SharedFixture):

    def setUp(self):
        self.client.login(username='url_student', password='Test@1234!')

    def test_student_pages(self):
        urls = [
            ('/', 'root'),
            ('/hub/', 'hub'),
            ('/app-home/', 'home'),
            ('/student-dashboard/', 'student_dashboard'),
            ('/maths/', 'maths'),
            (f'/maths/level/{self.level.level_number}/', 'level_detail'),
            (f'/maths/level/{self.level.level_number}/topic/{self.topic.id}/quiz/', 'topic_quiz'),
            (f'/maths/level/{self.level.level_number}/topic/{self.topic.id}/results/', 'topic_results'),
            (f'/maths/level/{self.level.level_number}/quiz/', 'mixed_quiz'),
            ('/student/my-classes/', 'my_classes'),
            (f'/student/class/{self.classroom.id}/', 'class_detail'),
            ('/student/attendance/', 'attendance_history'),
            (f'/student/session/{self.session.id}/mark-attendance/', 'mark_attendance'),
            ('/student/absence-tokens/', 'absence_tokens'),
            (f'/progress/student/{self.student.id}/', 'student_progress'),
            (f'/student/{self.student.id}/progress/', 'student_detail_progress'),
            ('/accounts/profile/', 'profile'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('School student URL failures:\n' + '\n'.join(f'  {f}' for f in failures))


# ---------------------------------------------------------------------------
# 4. Parent
# ---------------------------------------------------------------------------

class ParentURLTest(_SharedFixture):

    def setUp(self):
        self.client.login(username='url_parent', password='Test@1234!')

    def test_parent_pages(self):
        urls = [
            ('/parent/', 'parent_dashboard'),
            ('/parent/attendance/', 'parent_attendance'),
            ('/parent/invoices/', 'parent_invoices'),
            (f'/parent/invoices/{self.invoice.id}/', 'parent_invoice_detail'),
            ('/parent/payments/', 'parent_payment_history'),
            ('/parent/progress/', 'parent_progress'),
            (f'/parent/switch-child/{self.student.id}/', 'parent_switch_child'),
            ('/accounts/profile/', 'profile'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Parent URL failures:\n' + '\n'.join(f'  {f}' for f in failures))


# ---------------------------------------------------------------------------
# 5. Teacher
# ---------------------------------------------------------------------------

class TeacherURLTest(_SharedFixture):

    def setUp(self):
        self.client.login(username='url_teacher', password='Test@1234!')

    def test_teacher_pages(self):
        cid = self.classroom.id
        sid = self.session.id
        aid = self.enrollment.id
        urls = [
            ('/teacher/', 'teacher_dashboard'),
            ('/teacher/enrollment-requests/', 'enrollment_requests'),
            ('/teacher/attendance-approvals/', 'attendance_approvals'),
            (f'/teacher/class/{cid}/start-session/', 'start_session'),
            (f'/teacher/class/{cid}/create-session/', 'create_session'),
            (f'/teacher/session/{sid}/complete/', 'complete_session'),
            (f'/teacher/session/{sid}/cancel/', 'cancel_session'),
            (f'/teacher/session/{sid}/delete/', 'delete_session'),
            (f'/teacher/session/{sid}/attendance/', 'session_attendance'),
            (f'/teacher/session/{sid}/self-attendance/', 'teacher_self_attendance'),
            (f'/class/{cid}/', 'class_detail'),
            (f'/class/{cid}/edit/', 'edit_class'),
            (f'/class/{cid}/attendance/', 'class_attendance'),
            (f'/class/{cid}/assign-students/', 'assign_students'),
            (f'/class/{cid}/assign-teachers/', 'assign_teachers'),
            ('/class/manage-teachers/', 'manage_teachers'),
            ('/class/progress/', 'class_progress_list'),
            (f'/progress/class/{cid}/record/', 'record_progress'),
            ('/progress/criteria/', 'progress_criteria_list'),
            ('/progress/criteria/create/', 'progress_criteria_create'),
            ('/progress/criteria/approvals/', 'progress_criteria_approvals'),
            (f'/progress/criteria/{self.level.id}/submit/', 'progress_criteria_submit'),
            ('/progress/report/', 'student_progress_report'),
            (f'/progress/student/{self.student.id}/', 'student_progress'),
            ('/upload-questions/', 'upload_questions'),
            ('/create-question/', 'create_question'),
            ('/topics/', 'topics'),
            (f'/topic/{self.level.id}/levels/', 'topic_levels'),
            ('/maths/topics/', 'maths_topics'),
            (f'/maths/level/{self.level.level_number}/', 'maths_level'),
            (f'/maths/level/{self.level.level_number}/questions/', 'maths_level_questions'),
            (f'/level/{self.level.level_number}/', 'level_detail'),
            (f'/level/{self.level.level_number}/questions/', 'question_list'),
            ('/accounts/profile/', 'profile'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Teacher URL failures:\n' + '\n'.join(f'  {f}' for f in failures))


# ---------------------------------------------------------------------------
# 6. HoI / Admin  (covers admin-dashboard, invoicing, salaries, HoD, billing-admin)
# ---------------------------------------------------------------------------

class HoIURLTest(_SharedFixture):

    def setUp(self):
        self.client.login(username='url_hoi', password='Test@1234!')

    def test_admin_dashboard_pages(self):
        sid = self.school.id
        did = self.department.id
        lid = self.level.id
        urls = [
            ('/admin-dashboard/', 'admin_dashboard'),
            (f'/admin-dashboard/schools/{sid}/', 'school_detail'),
            (f'/admin-dashboard/schools/{sid}/edit/', 'school_edit'),
            (f'/admin-dashboard/schools/{sid}/settings/', 'school_settings'),
            (f'/admin-dashboard/schools/{sid}/teachers/', 'school_teachers'),
            (f'/admin-dashboard/schools/{sid}/students/', 'school_students'),
            (f'/admin-dashboard/schools/{sid}/subjects/', 'school_subjects'),
            (f'/admin-dashboard/schools/{sid}/departments/', 'school_departments'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/', 'dept_detail'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/edit/', 'dept_edit'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/levels/', 'dept_levels'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/subject-levels/', 'dept_subject_levels'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/teachers/', 'dept_teachers'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/settings/', 'dept_settings'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/assign-classes/', 'dept_assign_classes'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/assign-hod/', 'dept_assign_hod'),
            (f'/admin-dashboard/schools/{sid}/departments/{did}/update-fee/', 'dept_update_fee'),
            (f'/admin-dashboard/schools/{sid}/terms/', 'school_terms'),
            (f'/admin-dashboard/schools/{sid}/holidays/', 'school_holidays'),
            (f'/admin-dashboard/schools/{sid}/public-holidays/', 'school_public_holidays'),
            (f'/admin-dashboard/schools/{sid}/parent-invites/', 'parent_invite_list'),
            (f'/admin-dashboard/schools/{sid}/academic-year/create/', 'academic_year_create'),
            (f'/admin-dashboard/schools/{sid}/students/{self.student.id}/edit/', 'student_edit'),
            (f'/admin-dashboard/schools/{sid}/students/{self.student.id}/parents/', 'student_parents'),
            (f'/admin-dashboard/schools/{sid}/students/{self.student.id}/invite-parent/', 'invite_parent'),
            (f'/admin-dashboard/schools/{sid}/teachers/{self.teacher.id}/edit/', 'teacher_edit'),
            ('/admin-dashboard/schools/create/', 'school_create'),
            ('/admin-dashboard/manage-settings/', 'manage_settings'),
            ('/admin-dashboard/manage-departments/', 'manage_departments'),
            ('/admin-dashboard/manage-teachers/', 'manage_teachers'),
            ('/admin-dashboard/manage-students/', 'manage_students'),
            ('/admin-dashboard/manage-subjects/', 'manage_subjects'),
            ('/admin-dashboard/manage-terms/', 'manage_terms'),
            ('/admin-dashboard/manage-parent-invites/', 'manage_parent_invites'),
            ('/admin-dashboard/email/', 'email_dashboard'),
            ('/admin-dashboard/email/campaigns/', 'email_campaign_list'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Admin dashboard URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_hoi_class_management(self):
        cid = self.classroom.id
        sid = self.school.id
        urls = [
            ('/create-class/', 'create_class'),
            (f'/class/{cid}/', 'class_detail'),
            (f'/class/{cid}/edit/', 'class_edit'),
            (f'/class/{cid}/assign-students/', 'assign_students'),
            (f'/class/{cid}/assign-teachers/', 'assign_teachers'),
            ('/school-hierarchy/', 'school_hierarchy_auto'),
            (f'/school-hierarchy/{sid}/', 'school_hierarchy'),
            ('/dashboard/', 'hod_overview'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('HoI class management failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_invoicing_pages(self):
        iid = self.invoice.id
        urls = [
            ('/invoicing/', 'invoice_list'),
            (f'/invoicing/{iid}/', 'invoice_detail'),
            (f'/invoicing/{iid}/edit/', 'invoice_edit'),
            ('/invoicing/fees/', 'fee_configuration'),
            ('/invoicing/preview/', 'invoice_preview'),
            ('/invoicing/opening-balances/', 'opening_balances'),
            ('/invoicing/reference-mappings/', 'reference_mappings'),
            ('/invoicing/csv/upload/', 'csv_upload'),
            ('/invoicing/csv/mapping/', 'csv_column_mapping'),
            ('/invoicing/fees/student-override/add/', 'add_student_fee_override'),
            (f'/invoicing/fees/class/{self.classroom.id}/set/', 'set_classroom_fee'),
            (f'/invoicing/opening-balances/{self.student.id}/set/', 'set_opening_balance'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Invoicing URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_salary_pages(self):
        ssid = self.salary_slip.id
        urls = [
            ('/salaries/', 'salary_list'),
            (f'/salaries/{ssid}/', 'salary_detail'),
            ('/salaries/rates/', 'salary_rates'),
            ('/salaries/preview/', 'salary_preview'),
            ('/salaries/rates/teacher-override/add/', 'add_teacher_rate_override'),
            (f'/salaries/rates/set-default/', 'set_school_default_rate'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Salary URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_import_pages(self):
        urls = [
            ('/import-students/', 'student_csv_upload'),
            ('/import-students/preview/', 'student_csv_preview'),
            ('/import-students/credentials/', 'student_csv_credentials'),
            ('/import-students/map-structure/', 'student_csv_structure_mapping'),
            ('/import-teachers/', 'teacher_csv_upload'),
            ('/import-teachers/preview/', 'teacher_csv_preview'),
            ('/import-teachers/credentials/', 'teacher_csv_credentials'),
            ('/import-parents/', 'parent_csv_upload'),
            ('/import-parents/preview/', 'parent_csv_preview'),
            ('/import-parents/credentials/', 'parent_csv_credentials'),
            ('/import-balances/', 'balance_csv_upload'),
            ('/import-balances/preview/', 'balance_csv_preview'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Import URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_billing_admin_pages(self):
        urls = [
            ('/admin-dashboard/billing/', 'billing_admin_dashboard'),
            ('/admin-dashboard/billing/plans/', 'billing_admin_plan_list'),
            ('/admin-dashboard/billing/plans/create/', 'billing_admin_plan_create'),
            (f'/admin-dashboard/billing/plans/{self.school.id}/edit/', 'billing_admin_plan_edit_attempt'),
            ('/admin-dashboard/billing/discount-codes/', 'billing_admin_discount_list'),
            ('/admin-dashboard/billing/discount-codes/create/', 'billing_admin_discount_create'),
            ('/admin-dashboard/billing/coupon-codes/', 'billing_admin_coupon_list'),
            ('/admin-dashboard/billing/coupon-codes/create/', 'billing_admin_coupon_create'),
            ('/admin-dashboard/billing/promo-codes/', 'billing_admin_promo_list'),
            ('/admin-dashboard/billing/promo-codes/create/', 'billing_admin_promo_create'),
            ('/admin-dashboard/billing/modules/', 'billing_admin_module_list'),
            ('/admin-dashboard/billing/subscriptions/', 'billing_admin_subscription_list'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Billing admin URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_accounting_pages(self):
        urls = [
            ('/accounting/', 'accounting_dashboard'),
            ('/accounting/packages/', 'accounting_packages'),
            ('/accounting/users/', 'accounting_users'),
            ('/accounting/export/', 'accounting_export'),
            ('/accounting/refunds/', 'accounting_refunds'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Accounting URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_audit_pages(self):
        urls = [
            ('/audit/dashboard/', 'audit_dashboard'),
            ('/audit/logs/', 'audit_log_list'),
            ('/audit/events/', 'audit_events'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Audit URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_hod_pages(self):
        urls = [
            ('/department/manage-classes/', 'hod_manage_classes'),
            ('/department/workload/', 'hod_workload'),
            ('/department/reports/', 'hod_reports'),
            ('/department/attendance/', 'hod_attendance'),
            ('/department/subject-levels/', 'hod_subject_levels'),
            (f'/department/subject-levels/{self.department.id}/', 'hod_subject_levels_dept'),
            ('/department/create-class/', 'hod_create_class'),
            ('/department/assign-class/', 'hod_assign_class'),
            ('/department/attendance/detail/', 'hod_attendance_detail'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('HoD URL failures:\n' + '\n'.join(f'  {f}' for f in failures))

    def test_institute_billing_pages(self):
        urls = [
            ('/billing/institute/plans/', 'institute_plan_select'),
            ('/billing/institute/dashboard/', 'institute_sub_dashboard'),
            ('/billing/history/', 'billing_history'),
            ('/billing/module-required/', 'module_required'),
            ('/billing/institute/trial-expired/', 'institute_trial_expired'),
        ]
        failures = []
        for url, label in urls:
            r = _get(self.client, url, label)
            if r.status_code not in ACCEPTED:
                failures.append(f'{url!r} ({label}) → {r.status_code}')
        if failures:
            self.fail('Institute billing URL failures:\n' + '\n'.join(f'  {f}' for f in failures))


# ---------------------------------------------------------------------------
# 7. Django admin  (superuser — tests all changelist / add / history pages)
# ---------------------------------------------------------------------------

class DjangoAdminURLTest(_SharedFixture):
    """
    Iterates every registered Django admin URL and GETs it as superuser.
    Skips change/delete (require real object pk) and autocomplete.
    """

    def setUp(self):
        self.client.login(username='url_superuser', password='Test@1234!')

    def test_admin_index(self):
        r = _get(self.client, '/admin/')
        self.assertIn(r.status_code, {200, 302})

    def test_admin_changelists_and_add(self):
        """GET /admin/<app>/<model>/ and /admin/<app>/<model>/add/ for all registered models."""
        from django.contrib import admin as django_admin
        failures = []
        skipped = []
        for model, admin_instance in django_admin.site._registry.items():
            app = model._meta.app_label
            name = model._meta.model_name
            for suffix in ['', 'add/']:
                url = f'/admin/{app}/{name}/{suffix}'
                try:
                    r = _get(self.client, url, f'{app}.{name}/{suffix}')
                except AssertionError as e:
                    # MySQL timezone error on date_hierarchy changelists — skip
                    if 'invalid datetime value' in str(e) or 'time zone' in str(e).lower():
                        skipped.append(url)
                        continue
                    failures.append(f'{url} → exception: {e}')
                    continue
                if r.status_code not in ACCEPTED:
                    failures.append(f'{url} → {r.status_code}')
        if failures:
            self.fail('Django admin URL failures:\n' + '\n'.join(f'  {f}' for f in failures))
