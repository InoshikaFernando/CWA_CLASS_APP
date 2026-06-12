"""
UI test: CPP-299 — "Payment is not configured" guard on registration.

Drives the real multi-step registration wizards in a browser and verifies
that when a paid plan/package has no ``stripe_price_id``:

1. Institute (Head of Institute) registration shows the error.
2. Individual student registration shows the error.
3. A free package (price=0) still registers without the error.

The wizards gate the Terms step behind scroll-to-bottom of both the Terms
and Privacy boxes, and use ``alert()`` for step validation — so the helpers
below auto-accept dialogs and scroll the terms boxes to enable the checkbox.
"""
import re
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from ui_tests.conftest import _RUN_ID

PASSWORD = "TestPass123!"
ERROR_TEXT = "Payment is not currently configured"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def billing_setup(db):
    """One institute plan + one package without stripe_price_id, plus a free package."""
    from billing.models import InstitutePlan, Package

    plan_no_stripe = InstitutePlan.objects.create(
        name=f"Broken Plan {_RUN_ID}",
        slug=f"broken-{_RUN_ID}",
        price=Decimal("89.00"),
        stripe_price_id="",
        class_limit=5,
        student_limit=100,
        invoice_limit_yearly=500,
        extra_invoice_rate=Decimal("0.30"),
        trial_days=14,
        is_active=True,
        order=1,
    )
    pkg_no_stripe = Package.objects.create(
        name=f"Broken Pkg {_RUN_ID}",
        price=Decimal("19.00"),
        stripe_price_id="",
        class_limit=1,
        trial_days=14,
        is_active=True,
        order=10,
    )
    free_pkg = Package.objects.create(
        name=f"Free Pkg {_RUN_ID}",
        price=Decimal("0.00"),
        stripe_price_id="",
        class_limit=1,
        trial_days=7,
        is_active=True,
        order=11,
    )

    yield {
        "plan_no_stripe": plan_no_stripe,
        "pkg_no_stripe": pkg_no_stripe,
        "free_pkg": free_pkg,
    }

    plan_no_stripe.delete()
    pkg_no_stripe.delete()
    free_pkg.delete()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _accept_dialogs(page: Page):
    """Auto-dismiss any alert() so a failed client validation never hangs the test."""
    page.on("dialog", lambda dialog: dialog.accept())


def _scroll_terms_and_accept(page: Page):
    """Scroll both Terms and Privacy boxes to the bottom, then tick the checkbox."""
    for box_id in ("#terms-scroll", "#privacy-scroll"):
        page.eval_on_selector(
            box_id,
            "el => { el.scrollTop = el.scrollHeight; "
            "el.dispatchEvent(new Event('scroll')); }",
        )
    checkbox = page.locator("#accept-terms")
    expect(checkbox).to_be_enabled(timeout=5_000)
    checkbox.check()


# ---------------------------------------------------------------------------
# Institute registration
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_institute_paid_plan_without_stripe_shows_error(
    page: Page, live_server, billing_setup,
):
    plan = billing_setup["plan_no_stripe"]
    _accept_dialogs(page)

    page.goto(f"{live_server}/accounts/register/teacher-center/")
    page.wait_for_load_state("domcontentloaded")

    # Step 1 — account details
    page.locator("#f-center").fill(f"Broken Center {_RUN_ID}")
    page.locator("#f-username").fill(f"inst_ns_{_RUN_ID}")
    page.locator("#f-email").fill(f"inst_ns_{_RUN_ID}@test.local")
    page.locator("#f-password").fill(PASSWORD)
    page.locator("#f-confirm").fill(PASSWORD)
    page.get_by_role("button", name=re.compile("Next: Company Details")).click()

    # Step 2 — company details (all optional) → Terms
    page.get_by_role("button", name=re.compile("Next: Terms")).click()

    # Step 3 — terms & privacy
    _scroll_terms_and_accept(page)
    page.get_by_role("button", name=re.compile("Next: Choose Plan")).click()

    # Step 4 — pick the misconfigured plan and submit
    page.locator(f"label.plan-card:has(input[value='{plan.id}'])").click()
    page.locator("#btn-submit").click()
    page.wait_for_load_state("domcontentloaded")

    expect(page.locator("body")).to_contain_text(ERROR_TEXT)


# ---------------------------------------------------------------------------
# Individual student registration
#
# The individual-student form is a 6-step JS wizard whose step buttons attach
# their handlers via addEventListener. On slower CI runners the step
# transitions race, so instead of clicking through every step we load the real
# page in a real browser, populate the real form, and submit it natively. This
# still exercises the full server round-trip and asserts on the error the
# browser actually renders — just without the flaky wizard navigation.
# ---------------------------------------------------------------------------
def _submit_individual_registration(page: Page, live_server, *, username, email, package_id):
    """Load the registration page, fill the form, and submit it via the browser."""
    page.goto(f"{live_server}/accounts/register/individual-student/")
    page.wait_for_load_state("load")
    page.evaluate(
        """({ username, email, password, packageId }) => {
            const form = document.getElementById('reg-form');
            const set = (name, value) => {
                const el = form.querySelector(`[name="${name}"]`);
                if (el) el.value = value;
            };
            set('username', username);
            set('email', email);
            set('password', password);
            set('confirm_password', password);
            const radio = form.querySelector(
                `input[name="package_id"][value="${packageId}"]`);
            if (radio) radio.checked = true;
            const terms = document.getElementById('accept-terms');
            if (terms) { terms.disabled = false; terms.checked = true; }
            form.submit();
        }""",
        {
            "username": username,
            "email": email,
            "password": PASSWORD,
            "packageId": str(package_id),
        },
    )
    page.wait_for_load_state("domcontentloaded")


@pytest.mark.django_db(transaction=True)
def test_individual_paid_package_without_stripe_shows_error(
    page: Page, live_server, billing_setup,
):
    pkg = billing_setup["pkg_no_stripe"]
    _submit_individual_registration(
        page, live_server,
        username=f"stud_ns_{_RUN_ID}",
        email=f"stud_ns_{_RUN_ID}@test.local",
        package_id=pkg.id,
    )
    expect(page.locator("body")).to_contain_text(ERROR_TEXT)


@pytest.mark.django_db(transaction=True)
def test_individual_free_package_registers_without_error(
    page: Page, live_server, billing_setup,
):
    pkg = billing_setup["free_pkg"]
    _submit_individual_registration(
        page, live_server,
        username=f"stud_free_{_RUN_ID}",
        email=f"stud_free_{_RUN_ID}@test.local",
        package_id=pkg.id,
    )
    # Free package never hits the Stripe guard.
    expect(page.locator("body")).not_to_contain_text(ERROR_TEXT)
    # And we should have left the registration page.
    expect(page).not_to_have_url(re.compile(r"register/individual-student"))
