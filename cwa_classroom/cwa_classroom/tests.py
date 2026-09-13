"""Tests for project-level views (health check) and middleware."""

from importlib import import_module

from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import (
    DisallowedHost, SuspiciousOperation, TooManyFieldsSent,
)
from django.middleware.csrf import REASON_NO_CSRF_COOKIE

from cwa_classroom.middleware import SlowQueryLoggingMiddleware
from cwa_classroom.views import bad_request, csrf_failure


class HealthCheckTests(TestCase):
    def test_shallow_health_is_ok(self):
        resp = self.client.get(reverse("api_health"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["api"], "v1")
        self.assertIn("version", body)
        self.assertIn("timestamp", body)
        # Shallow probe must not run the deep checks.
        self.assertNotIn("checks", body)

    def test_deep_health_reports_checks_and_passes(self):
        resp = self.client.get(reverse("api_health"), {"deep": "1"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("checks", body)
        for probe in ("database", "migrations", "cache"):
            self.assertIn(probe, body["checks"])
            self.assertTrue(body["checks"][probe]["ok"], body["checks"][probe])

    def test_check_migrations_formats_pending(self):
        # Regression: a pending migration must be reported by app.name, not
        # crash on a missing attribute.
        from unittest import mock

        from cwa_classroom import views

        class FakeMigration:
            app_label = "billing"
            name = "0007_add_thing"

        class FakeExecutor:
            def __init__(self, connection):
                self.loader = mock.Mock()
                self.loader.graph.leaf_nodes.return_value = []

            def migration_plan(self, targets):
                return [(FakeMigration(), False)]

        with mock.patch.object(views, "MigrationExecutor", FakeExecutor):
            ok, detail = views._check_migrations()

        self.assertFalse(ok)
        self.assertIn("billing.0007_add_thing", detail)
        self.assertIn("1 unapplied", detail)

    def test_deep_health_degrades_to_503_on_failure(self):
        # A broken cache backend must surface as a 503 'degraded', not a
        # swallowed 200 — the whole point of the deep probe.
        from unittest import mock

        with mock.patch("cwa_classroom.views._check_cache", return_value=(False, "boom")):
            resp = self.client.get(reverse("api_health"), {"deep": "1"})
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body["status"], "degraded")
        self.assertFalse(body["checks"]["cache"]["ok"])
        self.assertEqual(body["checks"]["cache"]["detail"], "boom")


    def test_deep_health_carries_the_non_fatal_warnings(self):
        # Email backlog and unpaid access are real problems that must NOT 503:
        # scripts/deploy.sh gates on a 200 here, so failing the endpoint would
        # block the very deploy that fixes them. They ride in "warnings".
        resp = self.client.get(reverse("api_health"), {"deep": "1"})
        self.assertEqual(resp.status_code, 200)
        warnings = resp.json()["warnings"]
        self.assertEqual(warnings["email_queue"]["status"], "ok")
        unpaid = warnings["unpaid_access"]
        self.assertEqual(unpaid["status"], "ok")
        self.assertEqual(unpaid["leak_count"], 0)
        self.assertIn("window_days", unpaid)

    def test_unpaid_access_leak_warns_without_failing_the_endpoint(self):
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from billing.models import Subscription
        from usage.models import PageHit

        user = get_user_model().objects.create_user(
            username="leaky", email="leaky@test.local", password="Pass123!")
        Subscription.objects.create(
            user=user, status=Subscription.STATUS_PAST_DUE)
        hit = PageHit.objects.create(
            user=user, path="/maths/practice/", status_code=200)
        PageHit.objects.filter(pk=hit.pk).update(
            created_at=timezone.now() - timedelta(minutes=5))

        resp = self.client.get(reverse("api_health"), {"deep": "1"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        unpaid = body["warnings"]["unpaid_access"]
        self.assertEqual(unpaid["status"], "critical")
        self.assertEqual(unpaid["leak_count"], 1)
        self.assertTrue(unpaid["reasons"])

    def test_payment_delays_warn_without_failing_the_endpoint(self):
        """A backlog of un-notified failures rides in warnings, never a 503.

        scripts/deploy.sh gates on a 200 here, and the deploy most likely to
        be carrying a fix for the notifier is the one that would be blocked by
        its own backlog.
        """
        from django.contrib.auth import get_user_model

        from billing.models import Subscription

        user = get_user_model().objects.create_user(
            username="stranded", email="stranded@test.local", password="Pass123!")
        Subscription.objects.create(
            user=user, status=Subscription.STATUS_PAST_DUE)

        resp = self.client.get(reverse("api_health"), {"deep": "1"})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        delays = body["warnings"]["payment_delays"]
        self.assertEqual(delays["status"], "warning")
        self.assertEqual((delays["past_due"], delays["untold"]), (1, 1))
        self.assertTrue(delays["reasons"])

    def test_a_broken_payment_delay_probe_is_reported_not_swallowed(self):
        from unittest import mock

        with mock.patch(
            "billing.subscription_health.get_payment_delay_health",
            side_effect=RuntimeError("kaboom"),
        ):
            resp = self.client.get(reverse("api_health"), {"deep": "1"})

        delays = resp.json()["warnings"]["payment_delays"]
        self.assertEqual(delays["status"], "unknown")
        self.assertIn("kaboom", delays["detail"])

    def test_a_broken_warning_probe_is_reported_not_swallowed(self):
        from unittest import mock

        with mock.patch(
            "billing.subscription_health.get_unpaid_access_health",
            side_effect=RuntimeError("boom"),
        ):
            resp = self.client.get(reverse("api_health"), {"deep": "1"})
        unpaid = resp.json()["warnings"]["unpaid_access"]
        self.assertEqual(unpaid["status"], "unknown")
        self.assertIn("boom", unpaid["detail"])

class SlowQueryLoggingMiddlewareTests(TestCase):
    """The slow-query/N+1 diagnostic middleware."""

    def setUp(self):
        self.rf = RequestFactory()

    def _view_running(self, n_queries):
        """A fake view that issues n trivial queries then returns a response."""
        from django.http import HttpResponse

        def view(request):
            for _ in range(n_queries):
                with connection.cursor() as cur:
                    cur.execute('SELECT 1')
            return HttpResponse('ok')
        return view

    def test_logs_high_query_count(self):
        mw = SlowQueryLoggingMiddleware(self._view_running(6))
        mw.count_warn = 5          # trip the N+1 guard at 5 queries
        mw.slow_ms = 10_000        # don't trip the slow-query path
        req = self.rf.get('/some/path')
        with self.assertLogs('slow_queries', level='WARNING') as cm:
            mw(req)
        self.assertTrue(any('high query count' in m for m in cm.output))

    def test_logs_slow_query(self):
        mw = SlowQueryLoggingMiddleware(self._view_running(1))
        mw.slow_ms = -1            # every query counts as "slow" (>= -1 ms)
        mw.count_warn = 10_000     # don't trip the count path
        req = self.rf.get('/slow/path')
        with self.assertLogs('slow_queries', level='WARNING') as cm:
            mw(req)
        self.assertTrue(any('slow query' in m and 'SELECT 1' in m for m in cm.output))

    def test_quiet_request_logs_nothing(self):
        mw = SlowQueryLoggingMiddleware(self._view_running(2))
        mw.slow_ms = 10_000
        mw.count_warn = 50
        req = self.rf.get('/fast/path')
        with self.assertNoLogs('slow_queries', level='WARNING'):
            mw(req)

    def test_disabled_when_threshold_non_positive(self):
        from django.core.exceptions import MiddlewareNotUsed

        with self.settings(SLOW_QUERY_MS=0):
            with self.assertRaises(MiddlewareNotUsed):
                SlowQueryLoggingMiddleware(self._view_running(0))


class CsrfFailureViewTests(TestCase):
    """cwa_classroom.views.csrf_failure — the CSRF_FAILURE_VIEW (CPP-36)."""

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path, **post):
        """A request shaped like the ones that reach the failure view.

        CsrfViewMiddleware rejects from process_view, which runs after every
        middleware's request phase — so request.user is always populated by the
        time we render. RequestFactory skips that, hence the explicit user.
        """
        request = self.factory.post(path, post)
        request.user = AnonymousUser()
        return request

    def test_wired_up_in_settings(self):
        from django.conf import settings
        self.assertEqual(settings.CSRF_FAILURE_VIEW, 'cwa_classroom.views.csrf_failure')

    def test_login_failure_redirects_to_a_fresh_login_page(self):
        request = self._request(reverse('login'), username='someone')
        resp = csrf_failure(request, reason='CSRF token from POST incorrect.')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], f"{reverse('login')}?expired=1")

    def test_other_paths_get_the_branded_403(self):
        request = self._request('/hub/')
        resp = csrf_failure(request, reason='CSRF token from POST incorrect.')
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b'That page had expired', resp.content)
        self.assertNotIn(b'Cookies are switched off', resp.content)

    def test_a_missing_cookie_is_reported_never_retried(self):
        """Redirecting a cookie-less browser back to the form would just loop."""
        request = self._request(reverse('login'))
        resp = csrf_failure(request, reason=REASON_NO_CSRF_COOKIE)
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b'Cookies are switched off', resp.content)


class BadRequestViewTests(TestCase):
    """handler400 — a 400 has to say what happened.

    Django converts a SuspiciousOperation raised while parsing a request into a
    400 before any view runs, and its stock page is the four words
    "Bad Request (400)". That was the entire message a teacher got when the PDF
    review form outgrew DATA_UPLOAD_MAX_NUMBER_FIELDS on submit; it took two
    production incidents to work out what it meant.
    """

    def test_an_oversized_form_says_so_and_offers_the_way_back(self):
        request = RequestFactory().post('/homework/pdf/preview/134/')
        response = bad_request(request, TooManyFieldsSent('too many'))

        self.assertEqual(response.status_code, 400)
        body = response.content.decode()
        self.assertNotEqual(body.strip(), '<h1>Bad Request (400)</h1>')
        self.assertIn('too big to send', body)
        # The review page posts to its own URL and the POST never reached the
        # view, so the questions are still there — send the teacher back to them.
        self.assertIn('/homework/pdf/preview/134/', body)

    def test_an_unparseable_request_gets_the_generic_page(self):
        request = RequestFactory().get('/anything/')
        response = bad_request(request, SuspiciousOperation('nope'))

        self.assertEqual(response.status_code, 400)
        body = response.content.decode()
        self.assertIn("couldn't read that request", body)
        self.assertNotIn('too big to send', body)

    def test_a_disallowed_host_renders_without_reaching_for_the_host(self):
        """DisallowedHost arrives here too. Rendering the page that reports it
        must not itself touch request.get_host()."""
        request = RequestFactory().get('/', HTTP_HOST='not-allowed.example.com')
        response = bad_request(request, DisallowedHost('bad host'))

        self.assertEqual(response.status_code, 400)

    def test_the_urlconf_actually_points_at_it(self):
        from django.urls import get_resolver

        self.assertIs(get_resolver().resolve_error_handler(400), bad_request)

class SubjectSubdomainTests(TestCase):
    """A subject subdomain must not take the whole site down.

    ``SubdomainURLRoutingMiddleware`` used to point four hostnames at urlconf
    modules — ``cwa_classroom.urls_maths`` and three siblings — that were never
    written and appear nowhere in git history. Django imports ``request.urlconf``
    to resolve a URL, so any request to one of those hosts raised
    ``ModuleNotFoundError``: a 500 on EVERY path of that subdomain, not a 404 and
    not a fallback to ``ROOT_URLCONF``. It went unnoticed because ``www`` and the
    apex domain are not keys in the map and so took the fallback.

    Subjects are served from paths now (/maths/, /coding/, …), so the middleware
    is gone rather than repaired. These tests pin the outcome, not the mechanism:
    whatever routing arrives later, a subject-shaped hostname must resolve like
    any other host.
    """

    SUBJECT_HOSTS = [
        'maths.wizardslearninghub.co.nz',
        'coding.wizardslearninghub.co.nz',
        'music.wizardslearninghub.co.nz',
        'science.wizardslearninghub.co.nz',
    ]

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_a_subject_subdomain_serves_the_normal_urlconf(self):
        for host in self.SUBJECT_HOSTS:
            with self.subTest(host=host):
                resp = self.client.get(reverse('api_health'), HTTP_HOST=host)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()['status'], 'ok')

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_no_middleware_rewrites_the_urlconf_per_host(self):
        """The specific regression: a host must not select a urlconf module.

        Asserted through ``request.urlconf`` rather than by grepping for the
        old class name, so a re-introduction under any name fails here.
        """
        for host in self.SUBJECT_HOSTS + ['www.wizardslearninghub.co.nz']:
            with self.subTest(host=host):
                request = RequestFactory().get('/', HTTP_HOST=host)
                for mw_path in settings.MIDDLEWARE:
                    module, _, name = mw_path.rpartition('.')
                    middleware = getattr(import_module(module), name)(
                        lambda req: HttpResponse('ok'))
                    middleware(request)
                self.assertFalse(
                    hasattr(request, 'urlconf'),
                    f'{host} had its urlconf rewritten to '
                    f'{getattr(request, "urlconf", None)!r} — an unimportable '
                    f'value here is a 500 on every URL of that host.')
