"""
Tests for CPP-165: term confirmation and force-confirm feature.

Covers:
- Term model fields (is_confirmed, confirmed_at)
- Standard confirm action (within 1-month window)
- Error when confirming outside the window via standard confirm
- Force confirm action (bypasses window)
- Force confirm is audit-logged with forced=True
- Non-authorised roles cannot access force confirm
- Unauthenticated requests are rejected
- Template shows correct badge and buttons per term state
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import School, Term
from audit.models import AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def _make_school(username, role_name):
    user = CustomUser.objects.create_user(
        username=username, password='password1!', email=f'wlhtestmails+{username}@gmail.com',
    )
    _assign_role(user, role_name)
    school = School.objects.create(name='Test School', slug=f'test-{username}', admin=user)
    plan = InstitutePlan.objects.create(
        name=f'Plan-{username}', slug=f'plan-{username}',
        price=Decimal('89.00'), stripe_price_id=f'price_{username}',
        class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return user, school


def _make_term(school, start_offset_days, end_offset_days=30):
    today = datetime.date.today()
    start = today + datetime.timedelta(days=start_offset_days)
    end = today + datetime.timedelta(days=end_offset_days + start_offset_days)
    return Term.objects.create(
        school=school,
        name='Term 1',
        start_date=start,
        end_date=end,
        order=1,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TermModelConfirmationFieldsTest(TestCase):
    def test_default_is_unconfirmed(self):
        user, school = _make_school('modeluser', Role.ADMIN)
        term = _make_term(school, start_offset_days=10)
        self.assertFalse(term.is_confirmed)
        self.assertIsNone(term.confirmed_at)

    def test_can_set_confirmed(self):
        user, school = _make_school('modeluser2', Role.ADMIN)
        term = _make_term(school, start_offset_days=10)
        now = timezone.now()
        term.is_confirmed = True
        term.confirmed_at = now
        term.save()
        term.refresh_from_db()
        self.assertTrue(term.is_confirmed)
        self.assertIsNotNone(term.confirmed_at)


# ---------------------------------------------------------------------------
# View tests — TermManageView confirm / force_confirm actions
# ---------------------------------------------------------------------------

class TermConfirmViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user, self.school = _make_school('hoi1', Role.HEAD_OF_INSTITUTE)
        self.client.login(username='hoi1', password='password1!')
        self.url = reverse('admin_school_terms', kwargs={'school_id': self.school.id})

    # --- GET renders page with context ---

    def test_get_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_get_context_includes_confirmation_keys(self):
        resp = self.client.get(self.url)
        self.assertIn('today', resp.context)
        self.assertIn('confirm_window_end', resp.context)
        self.assertIn('can_force_confirm', resp.context)
        self.assertTrue(resp.context['can_force_confirm'])

    # --- Standard confirm: within window ---

    def test_confirm_within_window_succeeds(self):
        term = _make_term(self.school, start_offset_days=15)
        resp = self.client.post(self.url, {
            'action': 'confirm',
            'term_id': term.id,
        })
        self.assertRedirects(resp, self.url)
        term.refresh_from_db()
        self.assertTrue(term.is_confirmed)
        self.assertIsNotNone(term.confirmed_at)

    def test_confirm_within_window_logs_audit(self):
        term = _make_term(self.school, start_offset_days=15)
        self.client.post(self.url, {'action': 'confirm', 'term_id': term.id})
        self.assertTrue(
            AuditLog.objects.filter(action='term_confirmed', school=self.school).exists()
        )

    # --- Standard confirm: outside window ---

    def test_confirm_too_far_out_fails(self):
        """Term starting in 60 days is outside the 30-day window."""
        term = _make_term(self.school, start_offset_days=60)
        resp = self.client.post(self.url, {
            'action': 'confirm',
            'term_id': term.id,
        })
        self.assertRedirects(resp, self.url)
        term.refresh_from_db()
        self.assertFalse(term.is_confirmed)

    def test_confirm_too_far_out_shows_error_message(self):
        term = _make_term(self.school, start_offset_days=60)
        self.client.post(self.url, {'action': 'confirm', 'term_id': term.id})
        # Follow redirect to check messages
        resp = self.client.get(self.url)
        messages = list(resp.context['messages'])
        self.assertTrue(
            any('Force Confirm' in str(m) for m in messages),
            'Expected error message mentioning Force Confirm',
        )

    def test_confirm_already_started_fails(self):
        """Term that started yesterday is outside the standard window."""
        term = _make_term(self.school, start_offset_days=-1)
        self.client.post(self.url, {'action': 'confirm', 'term_id': term.id})
        term.refresh_from_db()
        self.assertFalse(term.is_confirmed)

    # --- Force confirm ---

    def test_force_confirm_outside_window_succeeds(self):
        term = _make_term(self.school, start_offset_days=60)
        resp = self.client.post(self.url, {
            'action': 'force_confirm',
            'term_id': term.id,
        })
        self.assertRedirects(resp, self.url)
        term.refresh_from_db()
        self.assertTrue(term.is_confirmed)
        self.assertIsNotNone(term.confirmed_at)

    def test_force_confirm_logs_forced_in_audit(self):
        term = _make_term(self.school, start_offset_days=60)
        self.client.post(self.url, {'action': 'force_confirm', 'term_id': term.id})
        log = AuditLog.objects.filter(action='term_force_confirmed', school=self.school).first()
        self.assertIsNotNone(log)
        self.assertTrue(log.detail.get('forced'))

    def test_force_confirm_within_window_also_works(self):
        """Force confirm is not restricted to outside the window."""
        term = _make_term(self.school, start_offset_days=10)
        self.client.post(self.url, {'action': 'force_confirm', 'term_id': term.id})
        term.refresh_from_db()
        self.assertTrue(term.is_confirmed)

    # --- Permission: teacher cannot force-confirm ---

    def test_teacher_cannot_access_terms_page(self):
        teacher = CustomUser.objects.create_user(
            username='teacherx', password='password1!', email='wlhtestmails+teacherx@gmail.com',
        )
        _assign_role(teacher, Role.TEACHER)
        self.client.login(username='teacherx', password='password1!')
        resp = self.client.post(self.url, {
            'action': 'force_confirm',
            'term_id': 999,
        })
        # RoleRequiredMixin redirects non-authorised users
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(resp.status_code, 302)

    # --- Permission: can_force_confirm is False for non-admin roles ---

    def test_can_force_confirm_false_for_teacher_role(self):
        """A teacher who somehow gets to the page sees can_force_confirm=False."""
        # Access as admin first to get context, then test property directly
        teacher = CustomUser.objects.create_user(
            username='teachery', password='password1!', email='wlhtestmails+teachery@gmail.com',
        )
        _assign_role(teacher, Role.TEACHER)
        self.assertFalse(teacher.is_admin_user)
        self.assertFalse(teacher.is_institute_owner)
        self.assertFalse(teacher.is_head_of_institute)

    # --- Unauthenticated ---

    def test_unauthenticated_confirm_redirects(self):
        self.client.logout()
        term = _make_term(self.school, start_offset_days=15)
        resp = self.client.post(self.url, {'action': 'confirm', 'term_id': term.id})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_unauthenticated_force_confirm_redirects(self):
        self.client.logout()
        term = _make_term(self.school, start_offset_days=60)
        resp = self.client.post(self.url, {'action': 'force_confirm', 'term_id': term.id})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


# ---------------------------------------------------------------------------
# Template rendering tests
# ---------------------------------------------------------------------------

class TermConfirmTemplateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user, self.school = _make_school('hoi2', Role.HEAD_OF_INSTITUTE)
        self.client.login(username='hoi2', password='password1!')
        self.url = reverse('admin_school_terms', kwargs={'school_id': self.school.id})

    def test_unconfirmed_badge_shown(self):
        _make_term(self.school, start_offset_days=15)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Unconfirmed')

    def test_confirmed_badge_shown_after_confirmation(self):
        term = _make_term(self.school, start_offset_days=15)
        term.is_confirmed = True
        term.confirmed_at = timezone.now()
        term.save()
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Confirmed')

    def test_confirm_button_shown_within_window(self):
        _make_term(self.school, start_offset_days=15)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'value="confirm"')

    def test_force_confirm_button_shown_outside_window(self):
        _make_term(self.school, start_offset_days=60)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Force Confirm')

    def test_no_confirm_buttons_for_confirmed_term(self):
        term = _make_term(self.school, start_offset_days=15)
        term.is_confirmed = True
        term.confirmed_at = timezone.now()
        term.save()
        resp = self.client.get(self.url)
        # Standard confirm action button should not appear
        self.assertNotContains(resp, 'value="confirm"')
        # The Force Confirm trigger button ($dispatch call) should not appear in any term row
        self.assertNotContains(resp, "$dispatch('open-force-confirm'")

    def test_force_confirm_modal_present_for_hoi(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'forceConfirmModal')
