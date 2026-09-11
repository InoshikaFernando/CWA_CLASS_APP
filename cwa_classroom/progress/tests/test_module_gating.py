"""Period reports are a paid add-on — everywhere, not just in classroom/.

The reports capability exists twice: the original views in
``classroom/views_progress.py``, which require MODULE_PROGRESS_REPORTS in 17
places, and the CPP-388 rebuild in this app, which shipped without the gate.
A school on any plan could read the pages, download the PDF and pull the whole
lot over ``/api/v1/`` without ever buying the module.

These tests pin the rule at each of the three doors, and pin the two cases a
naive gate gets wrong: a parent (who belongs to no school and would be denied
by a check on the *viewer's* school) and an individual learner (who has no
school at all and is not part of the institute module economy).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from billing.models import (
    InstitutePlan, ModuleSubscription, SchoolSubscription,
)
from classroom.models import ParentStudent, SchoolStudent
from progress.models import PeriodReport
from progress.tests.factories import make_school, make_user, role

pytestmark = pytest.mark.django_db


def _plan():
    return InstitutePlan.objects.create(
        name='Standard', slug='standard', price=Decimal('99.00'),
        class_limit=0, student_limit=0, invoice_limit_yearly=100,
        extra_invoice_rate=Decimal('0.50'),
    )


def _subscribe(school, *, with_module=False):
    sub = SchoolSubscription.objects.create(
        school=school, plan=_plan(), status=SchoolSubscription.STATUS_ACTIVE,
    )
    if with_module:
        ModuleSubscription.objects.create(
            school_subscription=sub,
            module=ModuleSubscription.MODULE_PROGRESS_REPORTS,
            is_active=True,
        )
    return sub


def _report(student, school):
    return PeriodReport.objects.create(
        student=student, school=school,
        period_type='weekly',
        period_start=date.today() - timedelta(days=7),
        period_end=date.today(),
        data={},
    )


def _school_student(school, username):
    student = make_user(username, 'student')
    SchoolStudent.objects.create(school=school, student=student, is_active=True)
    return student


# ---------------------------------------------------------------------------
# The three doors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('with_module,expected', [(False, 404), (True, 200)])
def test_report_list_requires_the_module(client, with_module, expected):
    school = make_school(slug='list-school', modules=[])
    _subscribe(school, with_module=with_module)
    student = _school_student(school, 'list-student')

    client.force_login(student)
    assert client.get(reverse('progress:period_report_list')).status_code == expected


@pytest.mark.parametrize('with_module,expected', [(False, 404), (True, 200)])
def test_report_detail_requires_the_module(client, with_module, expected):
    school = make_school(slug='detail-school', modules=[])
    _subscribe(school, with_module=with_module)
    student = _school_student(school, 'detail-student')
    report = _report(student, school)

    client.force_login(student)
    url = reverse('progress:period_report_detail', kwargs={'report_id': report.id})
    assert client.get(url).status_code == expected


def test_report_pdf_requires_the_module(client):
    """The download is its own view, so it needs its own gate.

    A gate on the page that renders the report and not on the file it links to
    is the leak with the report still in it.
    """
    school = make_school(slug='pdf-school', modules=[])
    _subscribe(school, with_module=False)
    student = _school_student(school, 'pdf-student')
    report = _report(student, school)

    client.force_login(student)
    url = reverse('progress:period_report_pdf', kwargs={'report_id': report.id})
    assert client.get(url).status_code == 404


def test_the_api_does_not_return_reports_the_school_has_not_bought(client):
    """The /api/v1/ surface is a second copy of the product, gated separately.

    A mixin on a Django view does nothing for a DRF viewset, so this is the
    door that stays open when only the pages are fixed.
    """
    school = make_school(slug='api-school', modules=[])
    _subscribe(school, with_module=False)
    student = _school_student(school, 'api-student')
    _report(student, school)

    client.force_login(student)
    resp = client.get('/api/v1/reports/')
    if resp.status_code == 404:
        pytest.skip('reports route not registered under this basename')
    assert resp.status_code == 200
    payload = resp.json()
    rows = payload['results'] if isinstance(payload, dict) else payload
    assert rows == [], 'A school without the module got report rows from the API'


# ---------------------------------------------------------------------------
# The two cases a gate on the *viewer's* school gets wrong
# ---------------------------------------------------------------------------

def test_a_parent_reads_the_report_their_child_s_school_paid_for(client):
    """Parents belong to no school of their own.

    Checking the module against the requesting user — which is what
    has_module_any_school does — resolves to no schools for a parent and
    denies them a report the school has bought. The rule has to follow the
    student, so this test fails on the obvious wrong implementation.
    """
    school = make_school(slug='parent-school', modules=[])
    _subscribe(school, with_module=True)
    student = _school_student(school, 'parent-child')
    report = _report(student, school)

    parent = make_user('report-parent', 'parent')
    parent.roles.add(role('parent'))
    ParentStudent.objects.create(parent=parent, student=student, is_active=True)

    client.force_login(parent)
    url = reverse('progress:period_report_detail', kwargs={'report_id': report.id})
    assert client.get(url).status_code == 200


def test_an_individual_learner_is_not_blocked_by_an_institute_module(client):
    """A learner with no school is outside the institute module economy.

    Their access is their own Subscription's business — the same call
    any_school_has_active_subscription() already makes. Gating them on a module
    no institute bought for them would lock them out of their own reports.
    """
    student = make_user('solo-learner', 'student')
    report = PeriodReport.objects.create(
        student=student, school=None, period_type='weekly',
        period_start=date.today() - timedelta(days=7),
        period_end=date.today(), data={},
    )

    client.force_login(student)
    url = reverse('progress:period_report_detail', kwargs={'report_id': report.id})
    assert client.get(url).status_code == 200
