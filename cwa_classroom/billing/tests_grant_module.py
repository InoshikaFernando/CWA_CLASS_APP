"""grant_module — the grandfathering escape hatch for a closed entitlement leak.

Closing the progress-reports leak takes the feature away from schools that were
using it while it was ungated. This command exists so the generous answer is a
one-liner rather than a hand-edit per school in the admin.

The important test here is the one about ``--with-reports``: grandfathering
should follow *use*, not the customer list. A school that never generated a
report loses nothing when the gate goes up, and granting it a free module is
revenue given away for nothing.
"""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import CustomUser
from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
from classroom.models import School
from progress.models import PeriodReport

pytestmark = pytest.mark.django_db

MODULE = ModuleSubscription.MODULE_PROGRESS_REPORTS


def _plan():
    plan, _ = InstitutePlan.objects.get_or_create(
        slug='gm-standard',
        defaults={
            'name': 'Standard', 'price': Decimal('99.00'),
            'class_limit': 0, 'student_limit': 0,
            'invoice_limit_yearly': 100, 'extra_invoice_rate': Decimal('0.50'),
        },
    )
    return plan


def _school(slug, *, subscribed=True):
    admin = CustomUser.objects.create_user(
        f'gm-admin-{slug}', f'{slug}@gm.test', 'pass1234')
    school = School.objects.create(name=slug.title(), slug=slug, admin=admin)
    if subscribed:
        SchoolSubscription.objects.create(
            school=school, plan=_plan(),
            status=SchoolSubscription.STATUS_ACTIVE,
        )
    return school


def _report_for(school):
    student = CustomUser.objects.create_user(
        f'gm-stu-{school.slug}', f'stu-{school.slug}@gm.test', 'pass1234')
    return PeriodReport.objects.create(
        student=student, school=school, period_type='weekly',
        period_start=date.today() - timedelta(days=7),
        period_end=date.today(), data={},
    )


def _run(*args, **kwargs):
    out = StringIO()
    call_command('grant_module', *args, stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


def _has(school):
    return ModuleSubscription.objects.filter(
        school_subscription__school=school, module=MODULE, is_active=True,
    ).exists()


# ---------------------------------------------------------------------------
# --with-reports: grandfather use, not the customer list
# ---------------------------------------------------------------------------

def test_with_reports_selects_only_schools_that_generated_one():
    user = _school('gm-user')
    idle = _school('gm-idle')
    _report_for(user)

    output = _run(MODULE, '--all', '--with-reports', '--dry-run')

    assert 'Gm-User' in output
    assert 'Gm-Idle' not in output
    assert 'Would grant' in output


def test_with_reports_grants_only_to_the_school_that_used_it():
    user = _school('gm-real-user')
    idle = _school('gm-real-idle')
    _report_for(user)

    _run(MODULE, '--all', '--with-reports')

    assert _has(user) is True
    assert _has(idle) is False


def test_without_the_flag_every_subscribed_school_is_selected():
    """The blunt instrument still exists — it is just not the default advice."""
    user = _school('gm-broad-user')
    idle = _school('gm-broad-idle')
    _report_for(user)

    output = _run(MODULE, '--all', '--dry-run')

    assert 'Gm-Broad-User' in output
    assert 'Gm-Broad-Idle' in output


def test_a_report_with_no_school_does_not_drag_anyone_in():
    """An individual learner's report has school=None.

    Left in the subquery it would contribute a NULL and, depending on the
    backend, either match nothing or behave surprisingly. Excluded explicitly.
    """
    idle = _school('gm-null-idle')
    solo = CustomUser.objects.create_user('gm-solo', 'solo@gm.test', 'pass1234')
    PeriodReport.objects.create(
        student=solo, school=None, period_type='weekly',
        period_start=date.today() - timedelta(days=7),
        period_end=date.today(), data={},
    )

    output = _run(MODULE, '--all', '--with-reports', '--dry-run')
    assert 'nothing to do' in output
    assert _has(idle) is False


# ---------------------------------------------------------------------------
# The command's own guarantees
# ---------------------------------------------------------------------------

def test_a_dry_run_writes_nothing():
    school = _school('gm-dry')
    _report_for(school)

    _run(MODULE, '--all', '--with-reports', '--dry-run')

    assert _has(school) is False


def test_granting_twice_is_idempotent():
    school = _school('gm-twice')
    _report_for(school)

    _run(MODULE, '--all', '--with-reports')
    output = _run(MODULE, '--all', '--with-reports')

    assert ModuleSubscription.objects.filter(
        school_subscription__school=school, module=MODULE).count() == 1
    assert 'already had it' in output


def test_a_deactivated_row_is_reactivated_not_duplicated():
    school = _school('gm-reactivate')
    _report_for(school)
    _run(MODULE, '--all', '--with-reports')

    row = ModuleSubscription.objects.get(
        school_subscription__school=school, module=MODULE)
    row.is_active = False
    row.save(update_fields=['is_active'])

    _run(MODULE, '--all', '--with-reports')

    assert ModuleSubscription.objects.filter(
        school_subscription__school=school, module=MODULE).count() == 1
    assert _has(school) is True


def test_a_granted_row_is_not_billed():
    """The grant must never reach Stripe.

    A blank stripe_subscription_item_id is what "active but not billed" already
    means in this app — the sync reads that field. A grant that filled it in
    would start invoicing the school we just decided not to charge.
    """
    school = _school('gm-unbilled')
    _report_for(school)
    _run(MODULE, '--all', '--with-reports')

    row = ModuleSubscription.objects.get(
        school_subscription__school=school, module=MODULE)
    assert row.stripe_subscription_item_id == ''


def test_an_unknown_slug_is_refused():
    with pytest.raises(CommandError, match='Unknown module'):
        _run('not_a_module', '--all', '--dry-run')


def test_a_school_id_that_matches_nothing_is_an_error_not_a_partial_grant():
    """A typo'd id must not silently grant to the rest of the list."""
    school = _school('gm-typo')
    with pytest.raises(CommandError, match='No SchoolSubscription'):
        _run(MODULE, '--school', str(school.id), '--school', '999999')


def test_school_and_all_together_are_refused():
    with pytest.raises(CommandError, match='not both/neither'):
        _run(MODULE, '--school', '1', '--all')
