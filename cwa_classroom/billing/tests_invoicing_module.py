"""Invoicing is a paid module, and the ways that could quietly stop being true.

Invoicing is the first module that lives *inside* a base app. Every other paid
module either owns its app outright (``brainbuzz``, ``worksheets``) or owns a
namespace (``progress:``), so a route nobody claimed fails the build. Invoicing
cannot: ``classroom`` holds enrolment and the timetable and can never leave
``BASE_APPS``, so an unclaimed invoicing route falls through to base, ships
free, and the registry test stays green because the route *is* accounted for.

That is why these tests exist and why they are shaped the way they are. The
build-time guard the other modules rely on does not protect this one.
"""

import pytest
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from billing import registry
from billing.catalogue import MODULE_CATALOGUE
from billing.models import ModuleSubscription

SLUG = 'invoicing'


def _classroom_routes():
    """Every route in the project, with its view module — same walk as the
    registry test, kept local so this file fails on its own terms."""
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
            found.append({
                'namespace': namespace,
                'name': pattern.name,
                'path': prefix + str(pattern.pattern),
                'module': view_module,
                'view_class': view_class,
            })

    walk(get_resolver())
    return found


def _owner(route):
    """Which module owns this route, by the same order the middleware uses."""
    declared = registry.module_for_view(route['view_class'])
    if declared:
        return declared
    by_name = registry.module_for_route(route['namespace'], route['name'])
    if by_name:
        return by_name
    return registry.module_for_view_module(route['module'])


def test_invoicing_is_sellable_and_enforceable():
    """A slug has to be in all three places or it is half a product."""
    assert SLUG in registry.slugs()
    assert SLUG in {s for s, _label in ModuleSubscription.MODULE_CHOICES}
    assert SLUG in MODULE_CATALOGUE


def test_every_staff_invoicing_route_is_owned():
    """The guard the registry test cannot provide for this module.

    ``classroom.views_invoicing`` is claimed as a whole view module rather than
    by url name, precisely so this stays true when somebody adds a view. If the
    claim is ever narrowed to a name list, this fails and says why.
    """
    staff = [r for r in _classroom_routes()
             if r['module'] == 'classroom.views_invoicing']

    assert staff, (
        'No routes resolved to classroom.views_invoicing — the walk is wrong, '
        'or the file moved. Either way this test is no longer guarding '
        'anything, which is worse than it failing.')

    unowned = [f"{r['name']} /{r['path']}" for r in staff if _owner(r) != SLUG]
    assert not unowned, (
        'These staff invoicing routes are not owned by the invoicing module, '
        'so they are free:\n  ' + '\n  '.join(sorted(unowned))
        + '\nThey live in a base app (classroom), so the registry test will '
          'NOT catch this — it sees them as accounted for.')


def test_the_parent_facing_routes_are_owned():
    """The family half. Named explicitly because they live in views_parent."""
    expected = {
        'parent_invoices', 'parent_invoice_detail',
        'parent_invoice_pay', 'parent_invoice_pay_success',
    }
    by_name = {r['name']: r for r in _classroom_routes() if r['name'] in expected}

    missing = expected - set(by_name)
    assert not missing, f'Parent invoice routes not found in the URL table: {sorted(missing)}'

    unowned = [name for name, r in by_name.items() if _owner(r) != SLUG]
    assert not unowned, (
        f'Parent-facing invoice routes not owned by {SLUG}: {sorted(unowned)}')


def test_the_fee_routes_are_owned():
    """Setting a fee is invoicing, even though the views live elsewhere.

    A school that can still edit fees but cannot issue an invoice has been
    sold half a feature and will report it as a bug.
    """
    expected = {'update_student_fee', 'admin_department_update_fee'}
    by_name = {r['name']: r for r in _classroom_routes() if r['name'] in expected}

    missing = expected - set(by_name)
    assert not missing, f'Fee routes not found in the URL table: {sorted(missing)}'

    unowned = [name for name, r in by_name.items() if _owner(r) != SLUG]
    assert not unowned, f'Fee routes not owned by {SLUG}: {sorted(unowned)}'


def test_claiming_a_view_module_does_not_leak_into_its_neighbours():
    """The claim is one file, not the whole app.

    ``classroom.views_parent`` also serves messaging and homework pages, and
    ``classroom.views`` serves most of the product. If the view-module claim
    were ever widened to ``classroom``, this catches it.
    """
    module = registry.REGISTRY[SLUG]
    assert module.view_modules == ('classroom.views_invoicing',), (
        f'invoicing claims {module.view_modules!r}. Claiming a broader module '
        'would make unrelated classroom pages paid.')

    neighbours = [r for r in _classroom_routes()
                  if r['module'] in ('classroom.views', 'classroom.views_parent')
                  and r['name'] not in {
                      'parent_invoices', 'parent_invoice_detail',
                      'parent_invoice_pay', 'parent_invoice_pay_success',
                      'update_student_fee',
                  }]
    captured = [r['name'] for r in neighbours if _owner(r) == SLUG]
    assert not captured, (
        f'These non-invoicing routes were captured by {SLUG}: {sorted(captured)}')
