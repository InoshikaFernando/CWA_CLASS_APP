"""
Tests for the "Recently Added Students" audit view.

Covers:
- Newest-added students appear first, with their joined_at timestamp available.
- The time-window filter (?window=) narrows the list.
- Inactive (removed) students are still listed so a removal can be undone.
- Deactivate from this page soft-removes the student and returns here.
- Restore from this page reactivates and returns here.
- Permission: unauthorised roles cannot view the page.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import School, SchoolStudent


def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school():
    user = CustomUser.objects.create_user(
        username='testhoi', password='password1!', email='wlhtestmails+hoi@gmail.com',
    )
    _assign_role(user, Role.HEAD_OF_INSTITUTE)
    school = School.objects.create(name='Test School', slug='test-school', admin=user)
    plan = InstitutePlan.objects.create(
        name='Basic', slug='basic-recent', price=Decimal('89.00'),
        stripe_price_id='price_recent', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _add_student(school, username, joined_at=None):
    student = CustomUser.objects.create_user(
        username=username, password='password1!',
        email=f'wlhtestmails+{username}@gmail.com',
        first_name=username.title(), last_name='Test',
    )
    _assign_role(student, Role.STUDENT)
    ss = SchoolStudent.objects.create(school=school, student=student)
    if joined_at is not None:
        # joined_at uses auto_now_add, so overwrite explicitly.
        SchoolStudent.objects.filter(pk=ss.pk).update(joined_at=joined_at)
        ss.refresh_from_db()
    return student, ss


class RecentStudentsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()
        now = timezone.now()
        self.old_student, self.old_ss = _add_student(
            self.school, 'oldstudent', joined_at=now - timedelta(days=40),
        )
        self.week_student, self.week_ss = _add_student(
            self.school, 'weekstudent', joined_at=now - timedelta(days=3),
        )
        self.new_student, self.new_ss = _add_student(
            self.school, 'newstudent', joined_at=now - timedelta(hours=2),
        )
        self.client.login(username='testhoi', password='password1!')

    def _url(self, **params):
        url = reverse('admin_school_students_recent', kwargs={'school_id': self.school.id})
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return url

    def test_page_renders_and_orders_newest_first(self):
        resp = self.client.get(self._url(window='all'))
        self.assertEqual(resp.status_code, 200)
        rows = list(resp.context['school_students'])
        ids = [ss.student_id for ss in rows]
        self.assertEqual(
            ids, [self.new_student.id, self.week_student.id, self.old_student.id]
        )

    def test_default_window_excludes_old_students(self):
        # Default window is 7 days.
        resp = self.client.get(self._url())
        ids = [ss.student_id for ss in resp.context['school_students']]
        self.assertIn(self.new_student.id, ids)
        self.assertIn(self.week_student.id, ids)
        self.assertNotIn(self.old_student.id, ids)

    def test_24h_window_only_shows_newest(self):
        resp = self.client.get(self._url(window='1'))
        ids = [ss.student_id for ss in resp.context['school_students']]
        self.assertEqual(ids, [self.new_student.id])

    def test_joined_at_timestamp_present(self):
        resp = self.client.get(self._url(window='all'))
        first = list(resp.context['school_students'])[0]
        self.assertIsNotNone(first.joined_at)

    def test_deactivate_from_recent_page_removes_and_returns_here(self):
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.new_student.id,
        })
        resp = self.client.post(url, {'next': 'admin_school_students_recent'})
        self.assertRedirects(
            resp, self._url(), fetch_redirect_response=False,
        )
        self.new_ss.refresh_from_db()
        self.assertFalse(self.new_ss.is_active)

    def test_inactive_student_still_listed(self):
        self.new_ss.is_active = False
        self.new_ss.save(update_fields=['is_active'])
        resp = self.client.get(self._url(window='all'))
        ids = [ss.student_id for ss in resp.context['school_students']]
        self.assertIn(self.new_student.id, ids)

    def test_restore_from_recent_page_reactivates_and_returns_here(self):
        self.new_ss.is_active = False
        self.new_ss.save(update_fields=['is_active'])
        url = reverse('admin_school_student_restore', kwargs={
            'school_id': self.school.id, 'student_id': self.new_student.id,
        })
        resp = self.client.post(url, {'next': 'admin_school_students_recent'})
        self.assertRedirects(
            resp, self._url(), fetch_redirect_response=False,
        )
        self.new_ss.refresh_from_db()
        self.assertTrue(self.new_ss.is_active)

    def test_remove_without_next_still_redirects_to_manage_page(self):
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.new_student.id,
        })
        resp = self.client.post(url)
        self.assertRedirects(
            resp,
            reverse('admin_school_students', kwargs={'school_id': self.school.id}),
            fetch_redirect_response=False,
        )

    def test_next_param_ignores_external_url(self):
        """An arbitrary next value must not be honoured (no open redirect)."""
        url = reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.new_student.id,
        })
        resp = self.client.post(url, {'next': 'https://evil.example.com'})
        self.assertRedirects(
            resp,
            reverse('admin_school_students', kwargs={'school_id': self.school.id}),
            fetch_redirect_response=False,
        )


class RecentStudentsPermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi, self.school = _setup_school()

    def test_student_cannot_view_recent_page(self):
        student = CustomUser.objects.create_user(
            username='justastudent', password='password1!',
            email='wlhtestmails+justastudent@gmail.com',
        )
        _assign_role(student, Role.STUDENT)
        self.client.login(username='justastudent', password='password1!')
        resp = self.client.get(
            reverse('admin_school_students_recent', kwargs={'school_id': self.school.id})
        )
        self.assertIn(resp.status_code, (302, 403, 404))
