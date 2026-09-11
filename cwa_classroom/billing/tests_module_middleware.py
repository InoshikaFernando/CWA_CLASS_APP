"""The enforcement middleware: what it blocks, and what it must never block.

The middleware exists to cover the three surfaces a view mixin cannot reach
uniformly — function-based views, DRF viewsets, and whole namespaces. The
tests that matter most here are the negative ones: shadow mode must allow
everything it would deny, and the login/marketing surface must stay open,
because a billing gate that logs people out is far worse than one that leaks.
"""

from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing import registry
from billing.middleware import ModuleEnforcementMiddleware
from billing.models import (
    InstitutePlan, ModuleSubscription, SchoolSubscription,
)
from classroom.models import School, SchoolStudent

pytestmark = pytest.mark.django_db


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.title()})
    return role


@pytest.fixture
def school_student(db):
    """A student in a school that has bought nothing at all."""
    admin = CustomUser.objects.create_user('mw-admin', 'mw-admin@t.test', 'pass1234')
    school = School.objects.create(name='MW School', slug='mw-school', admin=admin)
    SchoolSubscription.objects.create(
        school=school,
        plan=InstitutePlan.objects.create(
            name='Basic', slug='mw-basic', price=Decimal('49.00'),
            class_limit=0, student_limit=0, invoice_limit_yearly=100,
            extra_invoice_rate=Decimal('0.50'),
        ),
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    student = CustomUser.objects.create_user('mw-student', 'mw-stu@t.test', 'pass1234')
    student.roles.add(_role('student'))
    SchoolStudent.objects.create(school=school, student=student, is_active=True)
    return student, school


def _grant(school, slug):
    return ModuleSubscription.objects.create(
        school_subscription=school.subscription, module=slug, is_active=True)


# ---------------------------------------------------------------------------
# Shadow mode — the default, and the one that must never block
# ---------------------------------------------------------------------------

@override_settings(MODULE_ENFORCEMENT='shadow')
def test_shadow_mode_allows_a_request_it_would_deny(client, school_student):
    """The whole point of shadow: measure the blast radius without causing it.

    A school with no brainbuzz module still reaches brainbuzz. If this ever
    returns a redirect, the safe rollout is not safe.
    """
    student, _school = school_student
    client.force_login(student)
    resp = client.get(reverse('brainbuzz:join'))
    assert resp.status_code != 302 or 'module-required' not in resp.get('Location', '')


@override_settings(MODULE_ENFORCEMENT='shadow')
def test_shadow_mode_records_the_would_be_denial(client, school_student):
    """Allowing silently would make shadow mode useless — the log IS the output."""
    from audit.models import AuditLog

    student, _school = school_student
    client.force_login(student)
    client.get(reverse('brainbuzz:join'))

    assert AuditLog.objects.filter(
        category='entitlement', action='module_access_would_deny',
    ).exists(), 'shadow mode allowed the request but recorded nothing'


@override_settings(MODULE_ENFORCEMENT='off')
def test_off_mode_does_nothing_at_all(client, school_student):
    from audit.models import AuditLog

    student, _school = school_student
    client.force_login(student)
    client.get(reverse('brainbuzz:join'))

    assert not AuditLog.objects.filter(
        category='entitlement',
        action__in=['module_access_would_deny', 'module_access_denied'],
    ).exists()


# ---------------------------------------------------------------------------
# Enforce mode
# ---------------------------------------------------------------------------

@override_settings(MODULE_ENFORCEMENT='enforce')
def test_enforce_blocks_a_namespace_the_school_has_not_bought(client, school_student):
    """brainbuzz is 29 function-based views — no mixin could have gated them."""
    student, _school = school_student
    client.force_login(student)
    resp = client.get(reverse('brainbuzz:join'))
    assert resp.status_code == 302
    assert 'module-required' in resp['Location']


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_enforce_allows_once_the_module_is_bought(client, school_student):
    student, school = school_student
    _grant(school, ModuleSubscription.MODULE_BRAINBUZZ)
    client.force_login(student)
    resp = client.get(reverse('brainbuzz:join'))
    assert not (resp.status_code == 302
                and 'module-required' in resp.get('Location', ''))


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_the_api_gets_402_not_a_redirect(client, school_student):
    """A 302 to an HTML page is unreadable to the mobile client.

    Worse, it looks like success — the client follows it, gets 200, and shows
    an empty screen. 402 names the module so the client can say what to buy.

    Uses a DRF viewset deliberately: a viewset is one of the two surfaces
    ``ModuleRequiredMixin`` cannot reach at all, which is why the middleware
    exists.
    """
    student, _school = school_student
    client.force_login(student)
    resp = client.get('/api/v1/worksheet-assignments/')
    assert resp.status_code == 402
    body = resp.json()
    assert body['code'] == 'module_required'
    assert body['module'] == 'worksheets'


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_the_leaderboard_api_is_never_gated(client, school_student):
    """Points and the leaderboard are free on every plan.

    A school that has bought nothing still reaches them. This is the API half
    of the rule ``tests_module_registry`` pins on the routes: the board is
    what makes a student do the next piece of work, so it is base product.
    """
    student, _school = school_student
    client.force_login(student)
    for path in ('/api/v1/points/', '/api/v1/points/total/', '/api/v1/leaderboard/'):
        assert client.get(path).status_code != 402, f'{path} was gated'


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_the_base_product_is_never_gated(client, school_student):
    """A school that has bought nothing still has a working app.

    If this fails, the registry has claimed something that belongs in the base
    plan and the next deploy locks every customer out of it.
    """
    student, _school = school_student
    client.force_login(student)
    resp = client.get(reverse('student_dashboard'))
    assert not (resp.status_code == 302
                and 'module-required' in resp.get('Location', ''))


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_anonymous_traffic_is_left_alone(client):
    """Whether a logged-out visitor may see a page is authentication's call.

    Billing must not turn a login redirect into a billing redirect, or the
    marketing site starts 402-ing strangers.
    """
    resp = client.get(reverse('brainbuzz:join'))
    assert 'module-required' not in resp.get('Location', '')


@override_settings(MODULE_ENFORCEMENT='enforce')
def test_a_superuser_is_not_gated(client, school_student):
    su = CustomUser.objects.create_superuser('mw-su', 'mw-su@t.test', 'pass1234')
    client.force_login(su)
    resp = client.get(reverse('brainbuzz:join'))
    assert not (resp.status_code == 302
                and 'module-required' in resp.get('Location', ''))


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_the_view_marker_wins_over_the_registry():
    """The 48 existing required_module markers stay authoritative.

    If the registry could override them the two would drift, and the drift
    would be silent — which is the failure mode this whole change exists to
    remove.
    """
    class FakeView:
        required_module = 'teachers_attendance'

    mw = ModuleEnforcementMiddleware(lambda r: None)

    class FakeCallback:
        view_class = FakeView

    class FakeMatch:
        namespace = 'brainbuzz'   # the registry would say 'brainbuzz'
        url_name = 'join'

    assert mw._module_for(None, FakeCallback, FakeMatch) == 'teachers_attendance'


def test_a_name_rule_beats_a_namespace_rule():
    """question_automation carves schedule_* out of the base homework namespace.

    Asserted as family membership rather than an exact slug: the route resolves
    to whichever tier the registry lists first, which is an implementation
    detail no caller should depend on. What must stay true is that the route is
    owned by question_automation and not by base.
    """
    owner = registry.module_for_route('homework', 'schedule_list')
    assert owner in registry.members_of('question_automation')
    assert registry.module_for_route('homework', 'homework_detail') is None
