"""Scheduled report sending is a paid add-on (``report_automation``).

The split is deliberate: ``student_progress_reports`` buys the report,
``report_automation`` buys it going out without anyone clicking. A school that
has not bought automation is not blocked — it drops back to MANUAL and staff
send by hand. The feature degrades; it does not vanish.

The gate lives in ``report_settings.enabled_classrooms`` rather than in
``is_auto``, because that is the function the nightly
``generate_progress_reports`` command actually reads. Gating only ``is_auto``
looks right and does nothing: the command compares the resolved mode itself.
That near-miss is what the last test here pins.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
from classroom.models import ClassRoom, Subject
from progress import report_settings
from progress.models import ProgressReportSetting
from progress.tests.factories import make_school

pytestmark = pytest.mark.django_db


def _subscribe(school):
    return SchoolSubscription.objects.create(
        school=school,
        plan=InstitutePlan.objects.create(
            name='Standard', slug='standard', price=Decimal('99.00'),
            class_limit=0, student_limit=0, invoice_limit_yearly=100,
            extra_invoice_rate=Decimal('0.50'),
        ),
        status=SchoolSubscription.STATUS_ACTIVE,
    )


def _grant(sub, module):
    return ModuleSubscription.objects.create(
        school_subscription=sub, module=module, is_active=True)


@pytest.fixture
def auto_class(db):
    """A class configured to send weekly reports automatically."""
    school = make_school(slug='auto-school', modules=[])
    sub = _subscribe(school)
    subject = Subject.objects.create(name='Maths', slug='maths-auto')
    classroom = ClassRoom.objects.create(
        name='Auto Class', code='AUTO0001', school=school, subject=subject)
    ProgressReportSetting.objects.create(
        school=school, weekly=True, mode=ProgressReportSetting.MODE_AUTO)
    return classroom, sub


def test_a_school_without_the_module_falls_back_to_manual(auto_class):
    """Configured automatic, not entitled — so it runs manual, not nothing."""
    classroom, _sub = auto_class
    assert report_settings.is_auto(classroom) is False

    values = report_settings.effective(classroom)
    # The stored setting is untouched: this is an entitlement, not an edit.
    assert values['mode'] == ProgressReportSetting.MODE_AUTO
    assert report_settings.entitled_mode(classroom, values) == \
        ProgressReportSetting.MODE_MANUAL


def test_the_module_turns_automatic_back_on(auto_class):
    classroom, sub = auto_class
    _grant(sub, ModuleSubscription.MODULE_REPORT_AUTOMATION)
    assert report_settings.is_auto(classroom) is True


def test_the_nightly_run_skips_an_unentitled_class(auto_class):
    """enabled_classrooms(mode=AUTO) is what the cron asks for.

    This is the assertion that would still fail if the gate had been put in
    is_auto() alone — the command never calls it.
    """
    classroom, sub = auto_class

    automatic = report_settings.enabled_classrooms(
        'weekly', school=classroom.school, mode=ProgressReportSetting.MODE_AUTO)
    assert automatic == []

    _grant(sub, ModuleSubscription.MODULE_REPORT_AUTOMATION)
    automatic = report_settings.enabled_classrooms(
        'weekly', school=classroom.school, mode=ProgressReportSetting.MODE_AUTO)
    assert [c.id for c in automatic] == [classroom.id]


def test_staff_can_still_send_by_hand_without_the_module(auto_class):
    """The downgrade, stated as a test: the class appears in the manual run.

    A gate that dropped the class out of both runs would take reports away
    from a school that pays for reports — the wrong module's worth of harm.
    """
    classroom, _sub = auto_class

    manual = report_settings.enabled_classrooms(
        'weekly', school=classroom.school,
        mode=ProgressReportSetting.MODE_MANUAL)
    assert [c.id for c in manual] == [classroom.id]
