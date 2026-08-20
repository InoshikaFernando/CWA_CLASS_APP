"""Every admin-dashboard route must refuse users who should not see it.

There is already a URL sweep (test_all_urls.py), but it accepts
``{200, 302, 301, 403, 405}`` for every actor — so a student hitting an admin
page passes whether the page REFUSED them or SERVED them. It catches 500s, not
privilege escalation: delete a role gate and that suite stays green while the
page starts handing a student the whole institute's data.

These tests assert the security property directly — an unprivileged actor must
never get a 200 — and they enumerate the routes FROM THE URLCONF rather than
from a hand-written list, so a route added tomorrow is covered without anyone
remembering to add it here. A checklist that must be maintained by hand is a
checklist that goes stale; that is how the question-health page shipped with no
link and full green tests.
"""
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from accounts.models import CustomUser, Role
from classroom.models import School

# Routes that legitimately answer 200 to any signed-in user, or that are not a
# dashboard at all. Kept deliberately tiny and explained — every entry here is a
# hole in the sweep.
EXEMPT_NAMES = set()

# Params filled with a real object id where the fixture has one, and an
# unused-but-plausible id otherwise. An unprivileged actor must be refused
# either way: if the object lookup runs BEFORE the permission check, a stranger
# learns which ids exist.
FALLBACK_ID = 987654


def _admin_dashboard_patterns():
    """Every named GET route mounted under admin-dashboard/, from the URLconf."""
    found = []

    def walk(patterns, prefix=''):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                route = prefix + str(entry.pattern)
                if route.startswith('admin-dashboard/') and entry.name:
                    found.append((entry.name, route))

    walk(get_resolver().url_patterns)
    return found


class AdminDashboardAuthorizationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'})
        student_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student'})

        cls.owner = CustomUser.objects.create_user(
            'authowner', 'authowner@test.internal', 'pass1234!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)

        cls.student = CustomUser.objects.create_user(
            'authstudent', 'authstudent@test.internal', 'pass1234!',
            profile_completed=True, must_change_password=False)
        cls.student.roles.add(student_role)

        cls.school = School.objects.create(
            name='Auth Sweep School', slug='auth-sweep-school', admin=cls.owner)

    def _urls(self):
        """Reversed URLs for every admin-dashboard route, with ids filled in."""
        known = {'school_id': self.school.id}
        urls = []
        for name, route in _admin_dashboard_patterns():
            if name in EXEMPT_NAMES:
                continue
            params = {}
            for token in route.split('/'):
                if token.startswith('<') and token.endswith('>'):
                    key = token.strip('<>').split(':')[-1]
                    params[key] = known.get(key, FALLBACK_ID)
            try:
                urls.append((name, reverse(name, kwargs=params) if params
                             else reverse(name)))
            except Exception:
                # A route this helper cannot address is reported by
                # test_every_route_is_covered rather than silently skipped.
                continue
        return urls

    def _assert_all_refused(self, label):
        served, crashed = [], []
        for name, url in self._urls():
            try:
                response = self.client.get(url)
            except Exception as exc:                              # noqa: BLE001
                # A view that raises on an unauthenticated request is running
                # DB code before its auth gate — a 500 to a stranger, and a
                # different bug from serving them the page. Reported apart so
                # neither hides the other.
                crashed.append(f'{name} ({url}) → {type(exc).__name__}: {exc}')
                continue
            if response.status_code == 200:
                served.append(f'{name} ({url})')

        problems = []
        if served:
            problems.append(
                f'{len(served)} route(s) SERVED a 200 to {label}:\n  '
                + '\n  '.join(sorted(served)))
        if crashed:
            problems.append(
                f'{len(crashed)} route(s) CRASHED for {label} (auth gate runs '
                f'after the query):\n  ' + '\n  '.join(sorted(crashed)))
        if problems:
            self.fail('\n\n'.join(problems))

    def test_the_sweep_actually_found_routes(self):
        # A sweep that silently enumerates nothing passes every assertion below
        # while testing precisely nothing.
        self.assertGreater(len(self._urls()), 50)

    def test_anonymous_is_refused_everywhere(self):
        self._assert_all_refused('an anonymous visitor')

    def test_a_student_is_refused_everywhere(self):
        self.client.login(username='authstudent', password='pass1234!')
        self._assert_all_refused('a student')

    def test_every_route_is_covered_or_explained(self):
        # Routes the helper cannot reverse are invisible to the sweep above, so
        # they are surfaced here instead of quietly reducing coverage.
        addressable = {name for name, _ in self._urls()}
        all_names = {name for name, _ in _admin_dashboard_patterns()
                     if name not in EXEMPT_NAMES}
        missed = all_names - addressable
        self.assertEqual(
            missed, set(),
            f'{len(missed)} admin-dashboard route(s) could not be addressed by '
            f'the authorization sweep, so nothing checks who may see them: '
            f'{sorted(missed)}')


class SuperuserOnlyDashboardTests(TestCase):
    """The superuser-only pages must refuse an institute owner too.

    These carry cross-tenant data — every school's finances, a full database
    dump, the whole question bank — so "signed in as an admin of one school" is
    not enough.
    """

    SUPERUSER_ONLY = [
        'database_backup',
        'question_health_admin_dashboard',
        'question_check_admin_dashboard',
    ]

    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'suowner', 'suowner@test.internal', 'pass1234!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='SU Sweep School', slug='su-sweep-school', admin=cls.owner)
        cls.superuser = CustomUser.objects.create_superuser(
            username='supersweep', email='supersweep@test.internal',
            password='pass1234!')

    def test_an_institute_owner_cannot_reach_them(self):
        self.client.login(username='suowner', password='pass1234!')
        served = [name for name in self.SUPERUSER_ONLY
                  if self.client.get(reverse(name)).status_code == 200]
        self.assertEqual(
            served, [],
            f'Institute owner was served superuser-only page(s): {served}')

    def test_a_superuser_can_reach_them(self):
        # The mirror of the test above: a gate that refuses everyone is not a
        # working gate, it is a broken page.
        self.client.login(username='supersweep', password='pass1234!')
        for name in self.SUPERUSER_ONLY:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
