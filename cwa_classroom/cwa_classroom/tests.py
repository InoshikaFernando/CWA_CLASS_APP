"""Tests for project-level views (health check)."""

from django.test import TestCase
from django.urls import reverse


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
