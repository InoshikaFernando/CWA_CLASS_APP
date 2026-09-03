"""Every route makes an entitlement decision, and the build fails if one doesn't.

This is the test the whole registry exists for. A module gate is opt-in: it
only applies where somebody wrote ``required_module``. Forgetting it produces
no error, no 500 and no failing test — the paid feature simply becomes free,
and the first person to notice is whoever reads the invoice.

Two real leaks reached production that way, and the second is why this walks
the *resolved URL table* rather than reading source:

* the CPP-388 progress-report rebuild, ungated on pages and API;
* seven absence-token routes served out of ``attendance/`` — an app that is
  not in ``INSTALLED_APPS`` and whose urlconf is included nowhere, but whose
  view modules ``classroom/urls.py`` imports directly. Every check that looked
  at settings or at ``INSTALLED_APPS`` said that app was dormant. The URL
  table said otherwise.
"""

import pytest
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from billing import registry
from billing.models import ModuleSubscription

# Third-party and framework routes are not this project's to classify.
FOREIGN = ('django.', 'django_rq', 'drf_spectacular', 'rest_framework', 'debug_toolbar')


def _routes():
    """Every route the project itself serves: (namespace, name, path, module, view_class)."""
    found = []

    def walk(resolver, prefix='', namespace=None):
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern, prefix + str(pattern.pattern),
                     pattern.namespace or namespace)
                continue
            if not isinstance(pattern, URLPattern):
                continue
            callback = pattern.callback
            view_class = (getattr(callback, 'view_class', None)
                          or getattr(callback, 'cls', None))
            view_module = (view_class.__module__ if view_class is not None
                           else getattr(callback, '__module__', ''))
            if view_module.startswith(FOREIGN):
                continue
            found.append({
                'namespace': namespace,
                'name': pattern.name,
                'path': prefix + str(pattern.pattern),
                'module': view_module,
                'view_class': view_class,
            })

    walk(get_resolver())
    return found


def _decision(route):
    """The module this route needs, or None if it is base."""
    declared = registry.module_for_view(route['view_class'])
    if declared:
        return declared
    by_name = registry.module_for_route(route['namespace'], route['name'])
    if by_name:
        return by_name
    name = route['name'] or ''
    for suffix in ('-list', '-detail'):
        if name.endswith(suffix):
            found = registry.module_for_api_basename(name[: -len(suffix)])
            if found:
                return found
    return None


def test_every_route_makes_an_entitlement_decision():
    """A route claimed by neither a module nor the base product is a leak.

    Failing here is the point: it means somebody added a view and nobody
    decided whether it is paid for. The fix is one line in
    ``billing/registry.py`` — either add it to a module or confirm its app
    belongs to BASE_APPS.
    """
    unclassified = [
        f"{r['namespace'] or '-'}:{r['name']} ({r['module']}) /{r['path']}"
        for r in _routes()
        if _decision(r) is None and not registry.is_base(r['module'], r['namespace'])
    ]
    assert not unclassified, (
        'These routes are claimed by no module and are not in the declared '
        'base product, so nobody has decided whether they are paid for:\n  '
        + '\n  '.join(sorted(unclassified))
        + '\nAdd them to a module in billing/registry.py, or add their app to '
          'BASE_APPS to say plainly that they ship in every plan.')


def test_the_registry_and_the_catalogue_agree():
    """A slug you can enforce but not buy, or buy but not enforce.

    The first sells nothing; the second charges for nothing. Both look like
    working software.
    """
    catalogue = {slug for slug, _label in ModuleSubscription.MODULE_CHOICES}
    declared = registry.slugs()

    assert declared - catalogue == set(), (
        'In the registry but not sellable (no ModuleSubscription choice): '
        f'{sorted(declared - catalogue)}')
    assert catalogue - declared == set(), (
        'Sellable but not in the registry, so nothing knows what they own: '
        f'{sorted(catalogue - declared)}')


def test_the_absence_token_routes_are_gated():
    """The leak that only the URL table revealed.

    ``attendance/`` is in neither INSTALLED_APPS nor any urlconf, yet
    ``classroom/urls.py`` imports its view modules directly, so seven routes
    were live and ungated. Named explicitly because the general test above
    would go quiet the moment somebody added ``attendance`` to BASE_APPS.
    """
    routes = {r['name']: r for r in _routes()}
    expected = [
        'student_absence_tokens', 'student_request_absence_token',
        'student_available_makeup_sessions', 'student_redeem_absence_token',
        'absence_token_approvals', 'absence_token_approve',
        'absence_token_reject',
    ]
    for name in expected:
        assert name in routes, f'{name} is no longer routed — update this test'
        assert _decision(routes[name]) == ModuleSubscription.MODULE_STUDENTS_ATTENDANCE, (
            f'{name} is served by the attendance app and is a paid feature, '
            'but resolves to no module')


def test_a_service_only_module_declares_no_routes():
    """Modules with no request to gate must say so, or look enforced when they aren't.

    ``report_automation`` runs from the nightly command, ``ai_grading_*`` from
    the grading service, ``whatsapp_notifications`` from signals and RQ tasks.
    A route-only reading of any of them covers nothing at all.
    """
    for slug in ('report_automation', 'whatsapp_notifications',
                 'ai_grading_starter'):
        module = registry.REGISTRY[slug]
        assert registry.SERVICE in module.enforcement
        assert not module.namespaces and not module.route_names, (
            f'{slug} declares routes but is enforced in a service; either the '
            'routes are wrong or the enforcement kind is')


def test_rewards_is_api_only():
    """The rewards app has no urls.py at all — a route gate would cover nothing."""
    module = registry.REGISTRY['rewards']
    assert module.enforcement == (registry.API,)
    assert module.api_basenames
