"""Super-admin "View as" — impersonating a real student, teacher or parent.

The behaviour that matters is not "a page rendered" but *whose* page rendered:
a super admin browsing as a student must be served the student's permissions
and the student's data, must not be able to change anything, and must leave a
truthful audit trail behind them.
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import impersonation
from accounts.models import CustomUser, Role, UserRole
from audit.models import AuditLog


def make_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def make_user(username, role_name=None, **kw):
    user = CustomUser.objects.create_user(
        username=username,
        password='password1!',
        email=f'{username}@example.com',
        first_name=username.title(),
        profile_completed=True,
        must_change_password=False,
        **kw,
    )
    if role_name:
        UserRole.objects.create(user=user, role=make_role(role_name))
    return user


class ImpersonationTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superadmin = make_user('rootadmin', is_staff=True, is_superuser=True)
        cls.student = make_user('amara', Role.STUDENT)
        cls.teacher = make_user('tinatchr', Role.TEACHER)
        cls.parent = make_user('parentp', Role.PARENT)

    def setUp(self):
        self.client = Client()

    def login_admin(self):
        self.client.force_login(self.superadmin)

    def start_impersonating(self, target):
        return self.client.post(reverse('impersonation_start', args=[target.pk]))


class PickerAccessTests(ImpersonationTestBase):
    """Only platform super admins get near the feature."""

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_school_admin_role_is_not_enough(self):
        # Role.ADMIN is a *school's* administrator, not a platform super admin.
        school_admin = make_user('schooladmin', Role.ADMIN)
        self.client.force_login(school_admin)
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertEqual(resp.status_code, 302)

    def test_teacher_cannot_start_impersonating(self):
        self.client.force_login(self.teacher)
        resp = self.start_impersonating(self.student)
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))

    def test_superuser_sees_picker(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'View as User')


class PickerSearchTests(ImpersonationTestBase):
    def test_no_search_lists_nobody(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertEqual(list(resp.context['results']), [])

    def test_search_by_name_finds_student(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'), {'q': 'amara'})
        self.assertIn(self.student, resp.context['results'])

    def test_search_by_email_finds_student(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'), {'q': 'amara@example.com'})
        self.assertIn(self.student, resp.context['results'])

    def test_role_filter_narrows_to_that_role(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'), {'role': Role.PARENT})
        self.assertIn(self.parent, resp.context['results'])
        self.assertNotIn(self.student, resp.context['results'])

    def test_staff_and_superusers_are_never_listed(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'), {'q': 'rootadmin'})
        self.assertEqual(list(resp.context['results']), [])

    def test_inactive_users_are_never_listed(self):
        gone = make_user('goneaway', Role.STUDENT, is_active=False)
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'), {'q': 'goneaway'})
        self.assertNotIn(gone, resp.context['results'])


class StartImpersonationTests(ImpersonationTestBase):
    def test_confirm_page_names_the_target(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_start', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Amara')

    def test_post_sets_session_keys(self):
        self.login_admin()
        self.start_impersonating(self.student)
        session = self.client.session
        self.assertEqual(session[impersonation.TARGET_KEY], self.student.pk)
        self.assertEqual(session[impersonation.IMPERSONATOR_KEY], self.superadmin.pk)
        self.assertIn(impersonation.STARTED_AT_KEY, session)

    def test_post_redirects_to_the_targets_own_dashboard(self):
        self.login_admin()
        resp = self.start_impersonating(self.student)
        self.assertRedirects(resp, reverse('subjects_hub'), fetch_redirect_response=False)

    def test_active_role_becomes_the_targets_role(self):
        self.login_admin()
        self.start_impersonating(self.parent)
        self.assertEqual(self.client.session['active_role'], Role.PARENT)

    def test_cannot_impersonate_another_superuser(self):
        other_admin = make_user('otheradmin', is_superuser=True)
        self.login_admin()
        resp = self.start_impersonating(other_admin)
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))

    def test_cannot_impersonate_staff(self):
        staffer = make_user('backoffice', Role.TEACHER, is_staff=True)
        self.login_admin()
        self.start_impersonating(staffer)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))

    def test_cannot_impersonate_an_inactive_account(self):
        gone = make_user('deadaccount', Role.STUDENT, is_active=False)
        self.login_admin()
        self.start_impersonating(gone)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))


class RequestUserSwapTests(ImpersonationTestBase):
    """The point of the feature: request.user really is the target."""

    def test_request_user_is_the_target(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.student)

    def test_impersonator_is_still_reachable_on_the_request(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.get(reverse('profile'))
        self.assertTrue(resp.wsgi_request.is_impersonating)
        self.assertEqual(resp.wsgi_request.impersonator, self.superadmin)

    def test_target_no_longer_carries_superuser_powers(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.get(reverse('profile'))
        self.assertFalse(resp.wsgi_request.user.is_superuser)

    def test_flags_are_false_when_not_impersonating(self):
        self.login_admin()
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertFalse(resp.wsgi_request.is_impersonating)
        self.assertIsNone(resp.wsgi_request.impersonator)

    def test_banner_is_rendered_while_impersonating(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.get(reverse('profile'))
        self.assertContains(resp, 'Viewing as')
        self.assertContains(resp, reverse('impersonation_stop'))


class ReadOnlyTests(ImpersonationTestBase):
    """Nothing may be written on the impersonated user's behalf."""

    def test_get_is_allowed(self):
        self.login_admin()
        self.start_impersonating(self.student)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)

    def test_post_is_refused(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.post(reverse('profile'), {
            'action': 'update_profile', 'first_name': 'Hacked',
        })
        self.assertEqual(resp.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Amara')

    def test_refusal_explains_itself(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.post(reverse('profile'), {'action': 'update_profile'})
        self.assertContains(resp, 'read-only', status_code=403)

    def test_htmx_write_gets_a_bare_403_not_a_whole_page(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.post(reverse('profile'), {}, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(b'<html', resp.content.lower())
        self.assertIn(b'Read-only', resp.content)

    def test_stop_is_still_reachable_by_post(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.post(reverse('impersonation_stop'))
        self.assertEqual(resp.status_code, 302)

    def test_switch_role_cannot_be_used_to_escape_read_only(self):
        self.login_admin()
        self.start_impersonating(self.student)
        resp = self.client.post(reverse('switch_role'), {'role': Role.STUDENT})
        self.assertEqual(resp.status_code, 403)


class StopImpersonationTests(ImpersonationTestBase):
    def test_stop_clears_the_session(self):
        self.login_admin()
        self.start_impersonating(self.student)
        self.client.post(reverse('impersonation_stop'))
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))
        self.assertIsNone(self.client.session.get(impersonation.IMPERSONATOR_KEY))

    def test_admin_is_themselves_again(self):
        self.login_admin()
        self.start_impersonating(self.student)
        self.client.post(reverse('impersonation_stop'))
        resp = self.client.get(reverse('impersonation_picker'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)
        self.assertEqual(resp.status_code, 200)

    def test_admins_own_active_role_is_restored(self):
        self.login_admin()
        session = self.client.session
        session['active_role'] = Role.ADMIN
        session.save()
        self.start_impersonating(self.student)
        self.assertEqual(self.client.session['active_role'], Role.STUDENT)
        self.client.post(reverse('impersonation_stop'))
        self.assertEqual(self.client.session['active_role'], Role.ADMIN)

    def test_stop_without_an_active_session_is_a_no_op(self):
        self.login_admin()
        resp = self.client.post(reverse('impersonation_stop'))
        self.assertEqual(resp.status_code, 302)


class SessionRevalidationTests(ImpersonationTestBase):
    """The session is never trusted on its own — it is re-checked every request."""

    def test_losing_superuser_ends_impersonation_immediately(self):
        self.login_admin()
        self.start_impersonating(self.student)

        self.superadmin.is_superuser = False
        self.superadmin.save(update_fields=['is_superuser'])

        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))

    def test_target_deactivated_mid_session_ends_impersonation(self):
        self.login_admin()
        self.start_impersonating(self.student)

        self.student.is_active = False
        self.student.save(update_fields=['is_active'])

        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)

    def test_target_promoted_to_staff_mid_session_ends_impersonation(self):
        self.login_admin()
        self.start_impersonating(self.student)

        self.student.is_staff = True
        self.student.save(update_fields=['is_staff'])

        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)

    def test_session_expires_after_the_time_limit(self):
        self.login_admin()
        self.start_impersonating(self.student)

        session = self.client.session
        stale = timezone.now() - timedelta(seconds=impersonation.max_seconds() + 60)
        session[impersonation.STARTED_AT_KEY] = stale.isoformat()
        session.save()

        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)
        self.assertIsNone(self.client.session.get(impersonation.TARGET_KEY))

    def test_a_session_without_the_impersonator_anchor_is_dropped(self):
        self.login_admin()
        self.start_impersonating(self.student)

        session = self.client.session
        del session[impersonation.IMPERSONATOR_KEY]
        session.save()

        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.wsgi_request.user, self.superadmin)


class AuditTrailTests(ImpersonationTestBase):
    def test_start_is_logged_against_the_admin(self):
        self.login_admin()
        self.start_impersonating(self.student)
        entry = AuditLog.objects.get(action='impersonation_started')
        self.assertEqual(entry.user, self.superadmin)
        self.assertEqual(entry.detail['target_username'], 'amara')

    def test_stop_is_logged_against_the_admin(self):
        self.login_admin()
        self.start_impersonating(self.student)
        self.client.post(reverse('impersonation_stop'))
        entry = AuditLog.objects.get(action='impersonation_stopped')
        self.assertEqual(entry.user, self.superadmin)
        self.assertEqual(entry.detail['target_username'], 'amara')
        # The stop event is about the admin ending it, not about them acting as
        # the student — it must not be tagged as an impersonated action.
        self.assertNotIn('impersonating', entry.detail)

    def test_expiry_is_logged(self):
        self.login_admin()
        self.start_impersonating(self.student)

        session = self.client.session
        stale = timezone.now() - timedelta(seconds=impersonation.max_seconds() + 60)
        session[impersonation.STARTED_AT_KEY] = stale.isoformat()
        session.save()
        self.client.get(reverse('profile'))

        entry = AuditLog.objects.get(action='impersonation_expired')
        self.assertEqual(entry.user, self.superadmin)
        self.assertEqual(entry.detail['target_user_id'], self.student.pk)

    def test_events_during_impersonation_name_the_real_actor(self):
        from audit.services import log_event

        self.login_admin()
        self.start_impersonating(self.student)
        request = self.client.get(reverse('profile')).wsgi_request

        log_event(user=request.user, category='auth', action='some_event', request=request)

        entry = AuditLog.objects.get(action='some_event')
        self.assertEqual(entry.user, self.superadmin)
        self.assertTrue(entry.detail['impersonating'])
        self.assertEqual(entry.detail['impersonated_username'], 'amara')


class UsageTrackingTests(ImpersonationTestBase):
    def test_page_views_are_not_credited_to_the_impersonated_user(self):
        from usage.models import PageHit

        self.login_admin()
        self.start_impersonating(self.student)
        before = PageHit.objects.count()
        self.client.get(reverse('profile'))
        self.assertEqual(PageHit.objects.count(), before)


class MiddlewareOrderTests(TestCase):
    """The slot the middleware occupies is part of its contract."""

    def test_impersonation_runs_before_the_apps_own_gates(self):
        from django.conf import settings

        order = settings.MIDDLEWARE.index
        impersonation_at = order('accounts.impersonation.ImpersonationMiddleware')

        # After: it needs a verified login, a message store, and request.htmx.
        for earlier in (
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'django.contrib.messages.middleware.MessageMiddleware',
            'django_htmx.middleware.HtmxMiddleware',
        ):
            self.assertLess(order(earlier), impersonation_at, earlier)

        # Before: each of these must act on the impersonated user, not the admin.
        for later in (
            'cwa_classroom.middleware.TrialExpiryMiddleware',
            'cwa_classroom.middleware.AccountBlockMiddleware',
            'cwa_classroom.middleware.ProfileCompletionMiddleware',
            'usage.middleware.UsageTrackingMiddleware',
        ):
            self.assertGreater(order(later), impersonation_at, later)
