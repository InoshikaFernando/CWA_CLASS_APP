"""Tests for project-level views (health check) and middleware."""

from django.db import connection
from django.test import RequestFactory, TestCase
from django.urls import reverse

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import REASON_NO_CSRF_COOKIE

from cwa_classroom.middleware import SlowQueryLoggingMiddleware
from cwa_classroom.views import csrf_failure


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
