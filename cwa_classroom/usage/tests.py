"""Tests for the Usage Analytics tracking + dashboard."""
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from usage.middleware import UsageTrackingMiddleware
from usage.models import PageHit
from usage import reporting


def _hit(path='/dashboard/', status=200, user=None, when=None, method='GET'):
    """Create a PageHit, optionally back-dating created_at (auto_now_add)."""
    h = PageHit.objects.create(path=path, status_code=status, user=user, method=method)
    if when is not None:
        PageHit.objects.filter(pk=h.pk).update(created_at=when)
    return h


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class MiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _run(self, request, response):
        request.user = getattr(request, 'user', AnonymousUser())
        if not hasattr(request, 'htmx'):
            request.htmx = False
        mw = UsageTrackingMiddleware(lambda r: response)
        return mw(request)

    def test_records_html_page_view(self):
        req = self.factory.get('/dashboard/')
        self._run(req, HttpResponse('<html>ok</html>'))
        self.assertEqual(PageHit.objects.count(), 1)
        hit = PageHit.objects.get()
        self.assertEqual(hit.path, '/dashboard/')
        self.assertEqual(hit.status_code, 200)

    def test_records_authenticated_user(self):
        user = CustomUser.objects.create_user(
            username='u1', password='x', email='u1@test.com')
        req = self.factory.get('/dashboard/')
        req.user = user
        self._run(req, HttpResponse('<html>ok</html>'))
        self.assertEqual(PageHit.objects.get().user, user)

    def test_skips_static_and_admin(self):
        for path in ('/static/app.css', '/admin/', '/media/x.png', '/stripe/webhook/'):
            self._run(self.factory.get(path), HttpResponse('<html>x</html>'))
        self.assertEqual(PageHit.objects.count(), 0)

    def test_skips_htmx_xhr_and_json(self):
        req_htmx = self.factory.get('/dashboard/')
        req_htmx.htmx = True
        self._run(req_htmx, HttpResponse('<html>x</html>'))

        req_xhr = self.factory.get('/dashboard/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self._run(req_xhr, HttpResponse('<html>x</html>'))

        req_json = self.factory.get('/api-ish/', HTTP_ACCEPT='application/json')
        self._run(req_json, JsonResponse({'ok': True}))

        self.assertEqual(PageHit.objects.count(), 0)

    def test_skips_non_get(self):
        self._run(self.factory.post('/dashboard/'), HttpResponse('<html>x</html>'))
        self.assertEqual(PageHit.objects.count(), 0)

    def test_records_error_response(self):
        self._run(self.factory.get('/missing/'), HttpResponse('nope', status=404))
        self._run(self.factory.get('/boom/'), HttpResponse('err', status=500))
        self.assertEqual(PageHit.objects.filter(status_code__gte=400).count(), 2)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

class ReportingTests(TestCase):
    def setUp(self):
        cache.clear()  # reporting caches per-window; isolate tests
        self.user_a = CustomUser.objects.create_user(
            username='a', password='x', email='a@test.com')
        self.user_b = CustomUser.objects.create_user(
            username='b', password='x', email='b@test.com')

    def test_daily_views_and_distinct_users(self):
        now = timezone.now()
        # Today: 2 hits from user_a (distinct users = 1, views = 2) + 1 anon
        _hit(user=self.user_a, when=now)
        _hit(user=self.user_a, when=now)
        _hit(user=None, when=now)
        d = reporting.active_usage_daily(7)
        self.assertEqual(len(d['labels']), 7)
        self.assertEqual(d['views'][-1], 3)
        self.assertEqual(d['users'][-1], 1)
        # Earlier days zero-filled.
        self.assertEqual(d['views'][0], 0)

    def test_daily_buckets_split_by_day(self):
        now = timezone.now()
        _hit(user=self.user_a, when=now)
        _hit(user=self.user_b, when=now - timedelta(days=1))
        d = reporting.active_usage_daily(7)
        self.assertEqual(d['views'][-1], 1)
        self.assertEqual(d['views'][-2], 1)
        self.assertEqual(d['users'][-1], 1)

    def test_hourly_window(self):
        h = reporting.active_usage_hourly(24)
        self.assertEqual(len(h['labels']), 24)
        self.assertEqual(sum(h['views']), 0)
        _hit(user=self.user_a, when=timezone.now())
        cache.clear()
        h = reporting.active_usage_hourly(24)
        self.assertEqual(h['views'][-1], 1)

    def test_top_pages_ordering_excludes_errors(self):
        now = timezone.now()
        for _ in range(3):
            _hit(path='/popular/', when=now)
        _hit(path='/rare/', when=now)
        _hit(path='/popular/', status=500, when=now)  # error excluded from top pages
        result = reporting.top_pages_daily(7)
        paths = [s['path'] for s in result['series']]
        self.assertEqual(paths[0], '/popular/')
        self.assertIn('/rare/', paths)
        # The 500 is not counted in the popular line.
        popular = next(s for s in result['series'] if s['path'] == '/popular/')
        self.assertEqual(popular['data'][-1], 3)

    def test_active_now(self):
        now = timezone.now()
        # user_a active twice in the window (counts once), user_b just outside.
        _hit(user=self.user_a, when=now - timedelta(minutes=1))
        _hit(user=self.user_a, when=now - timedelta(minutes=2))
        _hit(user=self.user_b, when=now - timedelta(minutes=30))  # too old
        # Two anonymous sessions in-window (distinct guests) + one with no
        # session_key (not counted as a guest) + one stale guest session.
        _g1 = PageHit.objects.create(path='/p/', session_key='sess-1')
        _g2 = PageHit.objects.create(path='/p/', session_key='sess-2')
        _gdup = PageHit.objects.create(path='/p/', session_key='sess-1')
        _gnokey = PageHit.objects.create(path='/p/', session_key='')
        PageHit.objects.filter(pk__in=[_g1.pk, _g2.pk, _gdup.pk, _gnokey.pk]).update(
            created_at=now - timedelta(minutes=1))
        _gold = _hit(user=None, when=now - timedelta(minutes=30))  # noqa: F841

        result = reporting.active_now(minutes=5)
        self.assertEqual(result['users'], 1)
        self.assertEqual(result['guests'], 2)   # sess-1 + sess-2, deduped
        self.assertEqual(result['views'], 6)    # 2 user_a + 4 in-window anon (incl. no-key)
        self.assertEqual(result['minutes'], 5)

    def test_error_series_split(self):
        now = timezone.now()
        _hit(path='/x/', status=404, when=now)
        _hit(path='/y/', status=500, when=now)
        _hit(path='/y/', status=500, when=now)
        e = reporting.error_series_daily(30)
        self.assertEqual(e['client_4xx'][-1], 1)
        self.assertEqual(e['server_5xx'][-1], 2)
        top = {(t['path'], t['status']): t['count'] for t in e['top_errors']}
        self.assertEqual(top[('/y/', 500)], 2)
        self.assertEqual(top[('/x/', 404)], 1)


# ---------------------------------------------------------------------------
# View access control
# ---------------------------------------------------------------------------

class ViewAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.superuser = CustomUser.objects.create_superuser(
            username='super', password='pw', email='super@test.com')
        self.normal = CustomUser.objects.create_user(
            username='normal', password='pw', email='normal@test.com')

    def test_superuser_gets_200(self):
        self.client.login(username='super', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertEqual(resp.status_code, 200)

    def test_active_now_badge_renders(self):
        _hit(user=self.superuser, when=timezone.now())
        self.client.login(username='super', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertContains(resp, 'active now')
        self.assertContains(resp, 'last 5 min')

    def test_normal_user_redirected(self):
        self.client.login(username='normal', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_redirected(self):
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertEqual(resp.status_code, 302)
