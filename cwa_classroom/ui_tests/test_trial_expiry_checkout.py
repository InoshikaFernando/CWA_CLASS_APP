"""
UI test: trial-expired institute → plan selection → checkout flow.

Verifies that when an institute's trial has expired:
1. The user is redirected to the trial-expired landing page.
2. Clicking "Choose a Plan" navigates to the plans page.
3. Each plan shows a "Subscribe" button.
4. Clicking Subscribe submits to the checkout (does NOT show
   "This plan is not yet available for online checkout").
"""
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ui_tests.conftest import TEST_PASSWORD, _RUN_ID, _make_user, do_login


@pytest.fixture
def expired_institute(db):
    """School with an expired trial subscription and plans that have stripe_price_ids."""
    from accounts.models import Role
    from billing.models import InstitutePlan, SchoolSubscription
    from classroom.models import School, SchoolTeacher

    owner = _make_user("trial_owner", Role.INSTITUTE_OWNER)

    school = School.objects.create(
        name=f"Expired Trial School {_RUN_ID}",
        slug=f"expired-trial-{_RUN_ID}",
        admin=owner,
        is_active=True,
    )

    plan = InstitutePlan.objects.create(
        name=f"Basic {_RUN_ID}",
        slug=f"basic-trial-{_RUN_ID}",
        price=Decimal("89.00"),
        stripe_price_id="price_test_basic_trial",
        class_limit=5,
        student_limit=100,
        invoice_limit_yearly=500,
        extra_invoice_rate=Decimal("0.30"),
        trial_days=14,
        is_active=True,
        order=1,
    )
    silver = InstitutePlan.objects.create(
        name=f"Silver {_RUN_ID}",
        slug=f"silver-trial-{_RUN_ID}",
        price=Decimal("129.00"),
        stripe_price_id="price_test_silver_trial",
        class_limit=10,
        student_limit=200,
        invoice_limit_yearly=750,
        extra_invoice_rate=Decimal("0.25"),
        trial_days=14,
        is_active=True,
        order=2,
    )

    sub = SchoolSubscription.objects.create(
        school=school,
        plan=plan,
        status=SchoolSubscription.STATUS_EXPIRED,
        trial_end=timezone.now() - timedelta(days=1),
        has_used_trial=True,
    )

    SchoolTeacher.objects.get_or_create(
        school=school, teacher=owner,
        defaults={"role": "head_of_institute"},
    )

    yield {
        "owner": owner,
        "school": school,
        "plan_basic": plan,
        "plan_silver": silver,
        "subscription": sub,
    }

    school.delete()
    plan.delete()
    silver.delete()
    owner.delete()


@pytest.mark.django_db(transaction=True)
def test_expired_trial_redirects_to_trial_expired_page(
    page: Page, live_server, expired_institute,
):
    """After login, an expired-trial institute owner lands on the trial-expired page."""
    do_login(page, str(live_server), expired_institute["owner"])
    expect(page).to_have_url(re.compile(r"trial-expired"), timeout=10_000)
    expect(page.locator("h1")).to_contain_text("Your Free Trial Has Ended")


@pytest.mark.django_db(transaction=True)
def test_choose_plan_navigates_to_plans_page(
    page: Page, live_server, expired_institute,
):
    """Clicking 'Choose a Plan' navigates to the plan selection page."""
    do_login(page, str(live_server), expired_institute["owner"])
    expect(page).to_have_url(re.compile(r"trial-expired"), timeout=10_000)

    page.locator("a:has-text('Choose a Plan')").click()
    page.wait_for_load_state("domcontentloaded")

    expect(page).to_have_url(re.compile(r"/billing/institute/plans/"), timeout=10_000)
    expect(page.locator("h1")).to_contain_text("Choose Your Plan")


@pytest.mark.django_db(transaction=True)
def test_plans_page_shows_subscribe_buttons(
    page: Page, live_server, expired_institute,
):
    """The plans page shows Subscribe buttons for each plan."""
    do_login(page, str(live_server), expired_institute["owner"])
    page.goto(f"{live_server}/billing/institute/plans/")
    page.wait_for_load_state("domcontentloaded")

    buttons = page.locator("button:has-text('Subscribe')")
    expect(buttons.first).to_be_visible()
    assert buttons.count() >= 2


@pytest.mark.django_db(transaction=True)
def test_subscribe_does_not_show_plan_unavailable_error(
    page: Page, live_server, expired_institute,
):
    """Clicking Subscribe on a plan with stripe_price_id does NOT show the
    'not yet available' error. It may show a Stripe API error (expected in
    test environments without Stripe keys), but the plan-level check passes."""
    do_login(page, str(live_server), expired_institute["owner"])
    page.goto(f"{live_server}/billing/institute/plans/")
    page.wait_for_load_state("domcontentloaded")

    page.locator("button:has-text('Subscribe')").first.click()
    page.wait_for_load_state("domcontentloaded")

    unavailable_msg = page.locator("text=not yet available for online checkout")
    expect(unavailable_msg).to_have_count(0)
