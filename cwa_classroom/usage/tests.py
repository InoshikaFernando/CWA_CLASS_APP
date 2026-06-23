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


def _hit(path='/dashboard/', status=200, user=None, when=None, method='GET',
         client_key=''):
    """Create a PageHit, optionally back-dating created_at (auto_now_add)."""
    h = PageHit.objects.create(path=path, status_code=status, user=user,
                               method=method, client_key=client_key)
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

    def test_skips_static_admin_and_admin_dashboard(self):
        for path in ('/static/app.css', '/admin/', '/media/x.png',
                     '/stripe/webhook/', '/admin-dashboard/usage/overview/',
                     '/admin-dashboard/billing/overview/'):
            self._run(self.factory.get(path), HttpResponse('<html>x</html>'))
        self.assertEqual(PageHit.objects.count(), 0)

    def test_skips_redirects(self):
        from django.http import HttpResponseRedirect
        self._run(self.factory.get('/dashboard/'), HttpResponseRedirect('/login/'))
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

    def test_records_client_key(self):
        # Same IP+UA -> same key (counted as one guest); different IP -> different.
        r1 = self.factory.get('/dashboard/', REMOTE_ADDR='1.2.3.4',
                              HTTP_USER_AGENT='UA-x')
        r2 = self.factory.get('/dashboard/', REMOTE_ADDR='1.2.3.4',
                              HTTP_USER_AGENT='UA-x')
        r3 = self.factory.get('/dashboard/', REMOTE_ADDR='9.9.9.9',
                              HTTP_USER_AGENT='UA-x')
        for r in (r1, r2, r3):
            self._run(r, HttpResponse('<html>ok</html>'))
        keys = list(PageHit.objects.order_by('id').values_list('client_key', flat=True))
        self.assertTrue(all(keys), 'client_key should be populated')
        self.assertEqual(keys[0], keys[1])       # same IP+UA
        self.assertNotEqual(keys[0], keys[2])    # different IP
        self.assertEqual(len(keys[0]), 32)


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

    def test_top_pages_tie_break_is_stable(self):
        # All paths tie on 1 hit; the cutoff must select deterministically by
        # path name so lines don't flicker between refreshes.
        now = timezone.now()
        for p in ('/d/', '/b/', '/a/', '/c/', '/f/', '/e/', '/g/'):
            _hit(path=p, when=now)
        paths = [s['path'] for s in reporting.top_pages_daily(7, top_n=3)['series']]
        self.assertEqual(paths, ['/a/', '/b/', '/c/'])

    def test_active_now(self):
        now = timezone.now()
        # user_a active twice in the window (counts once), user_b just outside.
        _hit(user=self.user_a, when=now - timedelta(minutes=1))
        _hit(user=self.user_a, when=now - timedelta(minutes=2))
        _hit(user=self.user_b, when=now - timedelta(minutes=30))  # too old
        # Two distinct guests in-window (one repeats), one with no client_key
        # (not counted as a guest), and one stale guest outside the window.
        _hit(client_key='cli-1', when=now - timedelta(minutes=1))
        _hit(client_key='cli-2', when=now - timedelta(minutes=1))
        _hit(client_key='cli-1', when=now - timedelta(minutes=1))   # dup guest
        _hit(client_key='', when=now - timedelta(minutes=1))        # no key
        _hit(client_key='cli-3', when=now - timedelta(minutes=30))  # stale

        result = reporting.active_now(minutes=5)
        self.assertEqual(result['users'], 1)
        self.assertEqual(result['guests'], 2)   # cli-1 + cli-2, deduped
        self.assertEqual(result['views'], 6)    # 2 user_a + 4 in-window anon (incl. no-key)
        self.assertEqual(result['minutes'], 5)

    def test_combined_active_usage_matches_single_window(self):
        now = timezone.now()
        _hit(user=self.user_a, when=now)
        _hit(user=self.user_b, when=now)
        _hit(user=self.user_a, when=now - timedelta(days=10))
        usage = reporting.active_usage(30)
        self.assertEqual(len(usage['daily30']['labels']), 30)
        self.assertEqual(len(usage['daily7']['labels']), 7)
        self.assertEqual(len(usage['hourly24']['labels']), 24)
        # daily7 is the last 7 days of the 30-day series.
        self.assertEqual(usage['daily7']['views'], usage['daily30']['views'][-7:])
        self.assertEqual(usage['daily30']['views'][-1], 2)   # today
        self.assertEqual(usage['daily30']['users'][-1], 2)
        self.assertEqual(usage['hourly24']['views'][-1], 2)

    def test_combined_top_pages_recomputes_7day_window(self):
        now = timezone.now()
        # /old/ is big over 30d but absent this week; /new/ dominates this week.
        for _ in range(5):
            _hit(path='/old/', when=now - timedelta(days=20))
        for _ in range(3):
            _hit(path='/new/', when=now)
        pages = reporting.top_pages(30, top_n=2)
        self.assertEqual(pages['d30']['series'][0]['path'], '/old/')
        # 7-day window is recomputed, not sliced, so /new/ leads there.
        self.assertEqual(pages['d7']['series'][0]['path'], '/new/')

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

    def test_health_summary_excludes_noise(self):
        now = timezone.now()
        for _ in range(3):
            _hit(status=200, when=now)                       # ok page views
        _hit(path='/homework/13/take/', status=404, when=now)  # real 4xx
        _hit(path='/boom/', status=500, when=now)              # real 5xx
        _hit(path='/apple-touch-icon.png', status=404, when=now)  # noise
        _hit(path='/.well-known/x', status=404, when=now)         # noise
        h = reporting.health_summary(30)
        self.assertEqual(h['ok'], 3)
        self.assertEqual(h['client_4xx'], 1)   # /homework only; icon/.well-known excluded
        self.assertEqual(h['server_5xx'], 1)
        self.assertEqual(h['errors'], 2)
        self.assertEqual(h['noise'], 2)
        self.assertEqual(h['total'], 5)        # ok + real errors, noise excluded
        self.assertEqual(h['error_rate'], 40.0)
        self.assertEqual(h['band'], 'bad')

    def test_error_series_excludes_noise(self):
        now = timezone.now()
        _hit(path='/boom/', status=500, when=now)
        _hit(path='/favicon.ico', status=404, when=now)   # noise
        e = reporting.error_series_daily(30)
        self.assertEqual(e['server_5xx'][-1], 1)
        self.assertEqual(e['client_4xx'][-1], 0)          # favicon excluded
        paths = [t['path'] for t in e['top_errors']]
        self.assertIn('/boom/', paths)
        self.assertNotIn('/favicon.ico', paths)

    def test_recent_errors_newest_first_with_noise_flag(self):
        now = timezone.now()
        _hit(path='/boom/', status=500, when=now - timedelta(minutes=2))
        _hit(path='/apple-touch-icon.png', status=404, when=now - timedelta(minutes=1))
        rows = reporting.recent_errors(limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['path'], '/apple-touch-icon.png')  # newest first
        self.assertTrue(rows[0]['noise'])
        self.assertFalse(rows[1]['noise'])
        self.assertEqual(rows[1]['status'], 500)


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
        self.assertContains(resp, 'active')
        self.assertContains(resp, '5 min')

    def test_dashboard_renders_health_banner_and_drilldown(self):
        # One real 500 -> 100% error rate -> Critical banner; listed in drill-down.
        _hit(path='/boom/', status=500, when=timezone.now())
        self.client.login(username='super', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertContains(resp, 'Critical')          # health verdict banner
        self.assertContains(resp, 'error rate')
        self.assertContains(resp, 'chartActive')       # single toggled trend chart
        self.assertContains(resp, 'Most-visited pages')
        self.assertContains(resp, 'Recent errors')
        self.assertContains(resp, '/boom/')            # the real error is listed
        self.assertNotContains(resp, 'chartGauge')     # gauge/donut removed
        self.assertNotContains(resp, 'chartDonut')

    def test_healthy_banner_and_ranked_pages(self):
        # Mostly-2xx traffic -> Healthy banner + ranked top-pages bars.
        now = timezone.now()
        for _ in range(10):
            _hit(path='/dashboard/', status=200, when=now)
        for _ in range(4):
            _hit(path='/maths/', status=200, when=now)
        self.client.login(username='super', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertContains(resp, 'Healthy')
        self.assertContains(resp, '/dashboard/')       # top ranked page
        self.assertContains(resp, '/maths/')

    def test_ranked_pages_helper(self):
        from usage.views import _ranked_pages
        series = [
            {'path': '/a/', 'data': [1, 2, 3]},   # 6
            {'path': '/b/', 'data': [5, 5]},      # 10
            {'path': '/c/', 'data': [0, 1]},      # 1
        ]
        ranked = _ranked_pages(series)
        self.assertEqual([r['path'] for r in ranked], ['/b/', '/a/', '/c/'])
        self.assertEqual(ranked[0]['total'], 10)

    def test_normal_user_redirected(self):
        self.client.login(username='normal', password='pw')
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_redirected(self):
        resp = self.client.get(reverse('usage_admin_overview'))
        self.assertEqual(resp.status_code, 302)
