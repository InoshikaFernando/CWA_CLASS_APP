"""
audit/tests_role_filtering.py — Tests for role-based audit log filtering (CPP-272).
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog
from audit.views import _get_role_activity_summary, _get_top_actions
from classroom.models import School


class RoleFilteringTestBase(TestCase):
    """Shared fixtures for role-based audit filtering tests."""

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        # Admin user (superuser for dashboard access)
        cls.admin_user = CustomUser.objects.create_superuser(
            'auditadmin', 'auditadmin@test.com', 'password1!',
        )
        cls.admin_user.roles.add(cls.admin_role)

        # School
        cls.school = School.objects.create(
            name='Filter School', slug='filter-school', admin=cls.admin_user,
        )

        # Teacher user
        cls.teacher = CustomUser.objects.create_user(
            'teacher1', 'teacher1@test.com', 'password1!',
        )
        cls.teacher.roles.add(cls.teacher_role)

        # Parent user
        cls.parent = CustomUser.objects.create_user(
            'parent1', 'parent1@test.com', 'password1!',
        )
        cls.parent.roles.add(cls.parent_role)

        # Student user
        cls.student = CustomUser.objects.create_user(
            'student1', 'student1@test.com', 'password1!',
        )
        cls.student.roles.add(cls.student_role)

        # Create audit events for each role
        now = timezone.now()
        for i in range(3):
            AuditLog.objects.create(
                user=cls.teacher, school=cls.school,
                category='data_change', action='homework_assigned',
                created_at=now - timedelta(hours=i),
            )
        for i in range(5):
            AuditLog.objects.create(
                user=cls.student, school=cls.school,
                category='data_change', action='maths_quiz_completed',
                created_at=now - timedelta(hours=i),
            )
        for i in range(2):
            AuditLog.objects.create(
                user=cls.student, school=cls.school,
                category='data_change', action='coding_problem_submitted',
                created_at=now - timedelta(hours=i),
            )
        for i in range(4):
            AuditLog.objects.create(
                user=cls.parent, school=cls.school,
                category='data_change', action='parent_viewed_homework',
                created_at=now - timedelta(hours=i),
            )

    def setUp(self):
        self.client = Client()


class TestDashboardRoleSummaryCards(RoleFilteringTestBase):

    def test_dashboard_shows_role_summary_cards(self):
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_dashboard'))
        self.assertEqual(resp.status_code, 200)

        role_summary = resp.context['role_summary']
        self.assertEqual(len(role_summary), 3)

        summary_dict = {r['role_name']: r['count'] for r in role_summary}
        self.assertEqual(summary_dict[Role.TEACHER], 3)
        self.assertEqual(summary_dict[Role.PARENT], 4)
        self.assertEqual(summary_dict[Role.STUDENT], 7)  # 5 quiz + 2 coding

    def test_dashboard_role_summary_zero_when_empty(self):
        """No events = zero counts, no crash."""
        AuditLog.objects.all().delete()
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_dashboard'))
        self.assertEqual(resp.status_code, 200)

        role_summary = resp.context['role_summary']
        for rs in role_summary:
            self.assertEqual(rs['count'], 0)


class TestEventsRoleFilter(RoleFilteringTestBase):

    def test_events_role_filter_returns_correct_users(self):
        """Filter by teacher shows only teacher events."""
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_events'), {'role': Role.TEACHER})
        self.assertEqual(resp.status_code, 200)

        page = resp.context['page']
        for event in page:
            self.assertEqual(event.user, self.teacher)

    def test_events_role_filter_combines_with_category(self):
        """Role + category combo works."""
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_events'), {
            'role': Role.STUDENT,
            'category': 'data_change',
        })
        self.assertEqual(resp.status_code, 200)

        page = resp.context['page']
        self.assertEqual(page.paginator.count, 7)  # 5 quiz + 2 coding
        for event in page:
            self.assertEqual(event.user, self.student)
            self.assertEqual(event.category, 'data_change')

    def test_events_role_filter_empty_result(self):
        """Filtering by a role with no events returns empty page."""
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_events'), {'role': Role.ADMIN})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page'].paginator.count, 0)


class TestTopActionsByRole(RoleFilteringTestBase):

    def test_top_actions_returns_ordered_counts(self):
        qs = AuditLog.objects.filter(user=self.student)
        top = _get_top_actions(qs)
        # maths_quiz_completed (5) should be first, coding_problem_submitted (2) second
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][0], 'maths_quiz_completed')
        self.assertEqual(top[0][1], 5)
        self.assertEqual(top[1][0], 'coding_problem_submitted')
        self.assertEqual(top[1][1], 2)

    def test_top_actions_in_events_context(self):
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_events'), {'role': Role.STUDENT})
        self.assertEqual(resp.status_code, 200)

        top_actions = resp.context['top_actions']
        self.assertTrue(len(top_actions) > 0)
        action_names = [a[0] for a in top_actions]
        self.assertIn('maths_quiz_completed', action_names)

    def test_top_actions_limit(self):
        """_get_top_actions respects the limit parameter."""
        qs = AuditLog.objects.all()
        top = _get_top_actions(qs, limit=2)
        self.assertLessEqual(len(top), 2)


class TestRoleActivitySummaryFunction(RoleFilteringTestBase):

    def test_role_summary_returns_all_summary_roles(self):
        summary = _get_role_activity_summary()
        role_names = [r['role_name'] for r in summary]
        self.assertIn(Role.TEACHER, role_names)
        self.assertIn(Role.PARENT, role_names)
        self.assertIn(Role.STUDENT, role_names)

    def test_role_summary_scoped_to_school(self):
        """When school_ids is provided, only events from those schools are counted."""
        other_school = School.objects.create(
            name='Other School', slug='other-school', admin=self.admin_user,
        )
        AuditLog.objects.create(
            user=self.teacher, school=other_school,
            category='data_change', action='homework_assigned',
        )

        # Scoped to original school only
        summary = _get_role_activity_summary(school_ids=[self.school.id])
        teacher_count = next(r['count'] for r in summary if r['role_name'] == Role.TEACHER)
        self.assertEqual(teacher_count, 3)  # Only the original 3, not the extra one


class TestAuditLogListRedirect(RoleFilteringTestBase):

    def test_legacy_log_list_redirects_to_events(self):
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_log_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/audit/events/', resp.url)

    def test_legacy_log_list_preserves_query_params(self):
        self.client.login(username='auditadmin', password='password1!')
        resp = self.client.get(reverse('audit_log_list'), {'category': 'auth', 'action': 'login'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('category=auth', resp.url)
        self.assertIn('action=login', resp.url)


class TestTenantIsolation(RoleFilteringTestBase):

    def test_hoi_cannot_see_other_school_events(self):
        """HoI user should only see events from their own school."""
        hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'},
        )
        hoi_user = CustomUser.objects.create_user(
            'hoi_user', 'hoi@test.com', 'password1!',
        )
        hoi_user.roles.add(hoi_role)

        # Create a school where this HoI is admin
        hoi_school = School.objects.create(
            name='HoI School', slug='hoi-school', admin=hoi_user,
        )
        AuditLog.objects.create(
            user=hoi_user, school=hoi_school,
            category='admin_action', action='student_added',
        )

        self.client.login(username='hoi_user', password='password1!')
        resp = self.client.get(reverse('audit_events'))
        self.assertEqual(resp.status_code, 200)

        page = resp.context['page']
        for event in page:
            self.assertEqual(event.school, hoi_school)
