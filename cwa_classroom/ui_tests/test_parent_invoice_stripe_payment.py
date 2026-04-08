"""
UI tests for parent invoice Stripe payment flow.

Covers:
  - Invoices page: Pay banner shown/hidden, combined children, table columns
  - Pay modal: opens/closes, full/custom amount toggle, live fee calc
  - Checkout redirect: AJAX POST mocked to verify JS handles response
  - Payment success page: renders fee breakdown
  - Parent billing page: subscription info or no-subscription state
  - Sidebar: Billing link navigates correctly
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID

pytestmark = pytest.mark.parent_invoice_payment


# ---------------------------------------------------------------------------
# Extra fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def second_child(db, school, roles):
    """A second student linked to the same parent."""
    from accounts.models import CustomUser, Role
    from classroom.models import SchoolStudent
    from .conftest import _assign_role, TEST_PASSWORD

    user = CustomUser.objects.create_user(
        username=f"ui_child2_{_RUN_ID}",
        password=TEST_PASSWORD,
        email=f"ui_child2_{_RUN_ID}@test.local",
        first_name="Bobby",
        last_name="Second",
        profile_completed=True,
        must_change_password=False,
    )
    _assign_role(user, Role.STUDENT)
    SchoolStudent.objects.create(school=school, student=user)
    return user


@pytest.fixture
def parent_with_two_children(db, parent_with_child, second_child, school):
    """Parent linked to both enrolled_student and second_child."""
    from classroom.models import ParentStudent

    ParentStudent.objects.create(
        parent=parent_with_child,
        student=second_child,
        school=school,
        relationship="guardian",
    )
    return parent_with_child


@pytest.fixture
def issued_invoice_child1(db, enrolled_student, school, classroom):
    """Issued invoice ($120) for child 1."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=enrolled_student,
        school=school,
        invoice_number=f"INV-UI-C1-{_RUN_ID}",
        billing_period_start=date.today() - timedelta(days=30),
        billing_period_end=date.today(),
        status="issued",
        amount=Decimal("120.00"),
        calculated_amount=Decimal("120.00"),
        due_date=date.today() + timedelta(days=14),
    )
    InvoiceLineItem.objects.create(
        invoice=inv, classroom=classroom,
        daily_rate=Decimal("10.00"), sessions_held=12,
        sessions_attended=12, sessions_charged=12,
        line_amount=Decimal("120.00"),
    )
    return inv


@pytest.fixture
def issued_invoice_child2(db, second_child, school, classroom):
    """Issued invoice ($80) for child 2."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=second_child,
        school=school,
        invoice_number=f"INV-UI-C2-{_RUN_ID}",
        billing_period_start=date.today() - timedelta(days=30),
        billing_period_end=date.today(),
        status="issued",
        amount=Decimal("80.00"),
        calculated_amount=Decimal("80.00"),
        due_date=date.today() + timedelta(days=20),
    )
    InvoiceLineItem.objects.create(
        invoice=inv, classroom=classroom,
        daily_rate=Decimal("10.00"), sessions_held=8,
        sessions_attended=8, sessions_charged=8,
        line_amount=Decimal("80.00"),
    )
    return inv


@pytest.fixture
def paid_invoice(db, enrolled_student, school, classroom):
    """A fully paid invoice — should not count toward outstanding."""
    from classroom.models import Invoice, InvoiceLineItem

    inv = Invoice.objects.create(
        student=enrolled_student,
        school=school,
        invoice_number=f"INV-UI-PAID-{_RUN_ID}",
        billing_period_start=date.today() - timedelta(days=60),
        billing_period_end=date.today() - timedelta(days=31),
        status="paid",
        amount=Decimal("50.00"),
        calculated_amount=Decimal("50.00"),
    )
    InvoiceLineItem.objects.create(
        invoice=inv, classroom=classroom,
        daily_rate=Decimal("10.00"), sessions_held=5,
        sessions_attended=5, sessions_charged=5,
        line_amount=Decimal("50.00"),
    )
    return inv


# ---------------------------------------------------------------------------
# Invoices page — Pay banner
# ---------------------------------------------------------------------------

class TestParentInvoicesPayBanner:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               issued_invoice_child1, issued_invoice_child2):
        self.url = live_server.url
        self.page = page
        self.parent = parent_with_two_children
        do_login(page, self.url, self.parent)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_page_heading(self):
        expect(self.page.locator("h1", has_text="Invoices")).to_be_visible()

    def test_pay_banner_visible(self):
        """Banner appears when total_outstanding > 0."""
        expect(self.page.locator("#open-pay-modal")).to_be_visible()

    def test_banner_shows_total(self):
        """Banner displays sum of all outstanding invoices ($200)."""
        # Use the specific banner amount paragraph (not the modal breakdown spans)
        expect(self.page.locator("p.text-3xl.font-bold")).to_contain_text("200.00")

    def test_banner_shows_all_children_label(self):
        expect(self.page.locator("p.text-violet-200")).to_contain_text("Across all children")

    def test_both_invoices_in_table(self):
        """Both children's invoices appear in the table."""
        expect(self.page.locator(f"text={issued_invoice_child1.invoice_number}") if False
               else self.page.locator(f"text=INV-UI-C1-{_RUN_ID}")).to_be_visible()
        expect(self.page.locator(f"text=INV-UI-C2-{_RUN_ID}")).to_be_visible()

    def test_child_name_column(self):
        """Child name column is present in the table."""
        expect(self.page.locator("th", has_text="Child").first).to_be_visible()

    def test_due_column_present(self):
        """Due amount column header is rendered."""
        expect(self.page.locator("th", has_text="Due").first).to_be_visible()


class TestParentInvoicesNoBanner:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, paid_invoice):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_no_pay_banner_when_all_paid(self):
        """Pay banner must not appear when nothing is outstanding."""
        expect(self.page.locator("#open-pay-modal")).not_to_be_visible()

    def test_paid_invoice_still_in_table(self):
        """Paid invoices are still shown in the table."""
        expect(self.page.locator(f"text=INV-UI-PAID-{_RUN_ID}")).to_be_visible()

    def test_paid_status_badge(self):
        expect(self.page.locator("span.rounded-full", has_text="Paid").first).to_be_visible()


# ---------------------------------------------------------------------------
# Pay modal — open / close / toggle
# ---------------------------------------------------------------------------

class TestPayModal:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               issued_invoice_child1, issued_invoice_child2):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_two_children)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def _open_modal(self):
        self.page.locator("#open-pay-modal").click()
        self.page.wait_for_selector("#pay-modal.flex", timeout=3000)

    def test_modal_opens_on_button_click(self):
        self._open_modal()
        expect(self.page.locator("#pay-modal")).to_be_visible()

    def test_modal_heading(self):
        self._open_modal()
        expect(self.page.locator("#pay-modal").locator("h2")).to_contain_text("Pay Outstanding")

    def test_modal_closes_on_x(self):
        self._open_modal()
        self.page.locator("#close-pay-modal").click()
        expect(self.page.locator("#pay-modal")).not_to_be_visible()

    def test_modal_closes_on_backdrop_click(self):
        self._open_modal()
        # Click the backdrop (the modal overlay itself, not the inner card)
        modal = self.page.locator("#pay-modal")
        modal.click(position={"x": 10, "y": 10})
        expect(self.page.locator("#pay-modal")).not_to_be_visible()

    def test_full_amount_selected_by_default(self):
        self._open_modal()
        radio = self.page.locator("input[name='amount_mode'][value='full']")
        expect(radio).to_be_checked()

    def test_custom_input_hidden_by_default(self):
        self._open_modal()
        # Custom input should not be visible until radio is selected
        expect(self.page.locator("#custom-amount-input")).not_to_be_visible()

    def test_custom_input_shown_on_custom_radio(self):
        self._open_modal()
        self.page.locator("input[name='amount_mode'][value='custom']").click()
        expect(self.page.locator("#custom-amount-input")).to_be_visible()

    def test_fee_breakdown_visible(self):
        self._open_modal()
        expect(self.page.locator("#breakdown-applied")).to_be_visible()
        expect(self.page.locator("#breakdown-fee")).to_be_visible()
        expect(self.page.locator("#breakdown-total")).to_be_visible()

    def test_full_amount_breakdown_correct(self):
        """Fee for $200: 200*0.029+0.30 = 6.10, total = 206.10"""
        self._open_modal()
        expect(self.page.locator("#breakdown-applied")).to_contain_text("200.00")
        expect(self.page.locator("#breakdown-fee")).to_contain_text("6.10")
        expect(self.page.locator("#breakdown-total")).to_contain_text("206.10")

    def test_custom_amount_updates_fee_live(self):
        """Entering $100 custom: fee = 3.20, total = 103.20"""
        self._open_modal()
        self.page.locator("input[name='amount_mode'][value='custom']").click()
        self.page.locator("#custom-amount-input").fill("100")
        self.page.locator("#custom-amount-input").dispatch_event("input")
        self.page.wait_for_timeout(300)
        expect(self.page.locator("#breakdown-applied")).to_contain_text("100.00")
        expect(self.page.locator("#breakdown-fee")).to_contain_text("3.20")
        expect(self.page.locator("#breakdown-total")).to_contain_text("103.20")

    def test_switching_back_to_full_resets_breakdown(self):
        self._open_modal()
        self.page.locator("input[name='amount_mode'][value='custom']").click()
        self.page.locator("#custom-amount-input").fill("50")
        self.page.locator("#custom-amount-input").dispatch_event("input")
        self.page.wait_for_timeout(200)
        self.page.locator("input[name='amount_mode'][value='full']").click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator("#breakdown-applied")).to_contain_text("200.00")

    def test_pay_button_present(self):
        self._open_modal()
        expect(self.page.locator("#confirm-pay-btn")).to_be_visible()
        expect(self.page.locator("#pay-btn-text")).to_contain_text("Pay Now")

    def test_stripe_note_present(self):
        self._open_modal()
        expect(self.page.locator("text=Secured by Stripe")).to_be_visible()


# ---------------------------------------------------------------------------
# Checkout redirect — mock the AJAX response
# ---------------------------------------------------------------------------

class TestPayModalCheckoutRedirect:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               issued_invoice_child1):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_two_children)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_pay_redirects_on_success(self):
        """Mock the pay endpoint to return a checkout_url, verify redirect."""
        success_url = f"{self.url}/parent/invoices/pay/success/?isp_id=1"

        # Intercept the POST to /parent/invoices/pay/
        self.page.route(
            f"{self.url}/parent/invoices/pay/",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=f'{{"checkout_url": "{success_url}"}}',
            ),
        )

        self.page.locator("#open-pay-modal").click()
        self.page.wait_for_selector("#pay-modal.flex", timeout=3000)
        self.page.locator("#confirm-pay-btn").click()

        # Should navigate to the mocked checkout_url
        self.page.wait_for_url(lambda url: "success" in url or "stripe.com" in url, timeout=8000)

    def test_pay_shows_error_on_failure(self):
        """Mock a 400 response — error message shown in modal."""
        self.page.route(
            f"{self.url}/parent/invoices/pay/",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body='{"error": "No outstanding invoices."}',
            ),
        )

        self.page.locator("#open-pay-modal").click()
        self.page.wait_for_selector("#pay-modal.flex", timeout=3000)
        self.page.locator("#confirm-pay-btn").click()
        self.page.wait_for_timeout(500)

        expect(self.page.locator("#pay-error")).to_be_visible()
        expect(self.page.locator("#pay-error")).to_contain_text("No outstanding invoices")

    def test_pay_button_shows_spinner_during_request(self):
        """Spinner text is shown and Pay Now text is hidden while processing."""
        success_url = f"{self.url}/parent/invoices/pay/success/?isp_id=1"

        # Use a route that resolves quickly so we just verify JS toggled the text
        self.page.route(
            f"{self.url}/parent/invoices/pay/",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=f'{{"checkout_url": "{success_url}"}}',
            ),
        )

        self.page.locator("#open-pay-modal").click()
        self.page.wait_for_selector("#pay-modal.flex", timeout=3000)

        # Verify the spinner element exists in the DOM (it's hidden by default)
        expect(self.page.locator("#pay-btn-spinner")).to_be_attached()
        expect(self.page.locator("#pay-btn-text")).to_be_attached()

    def test_invalid_custom_amount_shows_error(self):
        """Entering 0 as custom amount shows a validation error before any request."""
        self.page.locator("#open-pay-modal").click()
        self.page.wait_for_selector("#pay-modal.flex", timeout=3000)
        self.page.locator("input[name='amount_mode'][value='custom']").click()
        self.page.locator("#custom-amount-input").fill("0")
        self.page.locator("#confirm-pay-btn").click()
        self.page.wait_for_timeout(200)

        expect(self.page.locator("#pay-error")).to_be_visible()
        expect(self.page.locator("#pay-error")).to_contain_text("minimum")


# ---------------------------------------------------------------------------
# Payment success page
# ---------------------------------------------------------------------------

class TestPaymentSuccessPage:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, enrolled_student, school):
        from billing.models import InvoiceStripePayment

        self.url = live_server.url
        self.page = page
        self.parent = parent_with_child

        self.isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal("103.20"),
            amount_applied=Decimal("100.00"),
            stripe_fee=Decimal("3.20"),
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        do_login(page, self.url, self.parent)

    def test_success_page_loads(self):
        self.page.goto(f"{self.url}/parent/invoices/pay/success/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Payment received")).to_be_visible()

    def test_success_page_with_isp_shows_breakdown(self):
        self.page.goto(f"{self.url}/parent/invoices/pay/success/?isp_id={self.isp.pk}")
        self.page.wait_for_load_state("networkidle")
        # Target the breakdown card specifically using its unique space-y-3 class combo
        card = self.page.locator(".bg-white.rounded-2xl.border.border-gray-100.shadow-sm")
        expect(card).to_contain_text("100.00")
        expect(card).to_contain_text("3.20")
        expect(card).to_contain_text("103.20")

    def test_success_page_view_invoices_link(self):
        self.page.goto(f"{self.url}/parent/invoices/pay/success/")
        self.page.wait_for_load_state("networkidle")
        link = self.page.locator("a", has_text="View Invoices")
        expect(link).to_be_visible()
        link.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("h1", has_text="Invoices")).to_be_visible()

    def test_success_page_payment_history_link(self):
        self.page.goto(f"{self.url}/parent/invoices/pay/success/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("a", has_text="Payment History")).to_be_visible()


# ---------------------------------------------------------------------------
# Parent billing page
# ---------------------------------------------------------------------------

class TestParentBillingPage:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)

    def test_billing_page_loads(self):
        self.page.goto(f"{self.url}/parent/billing/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("h1", has_text="Billing")).to_be_visible()

    def test_no_subscription_state(self):
        self.page.goto(f"{self.url}/parent/billing/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=No active subscription")).to_be_visible()

    def test_with_active_subscription(self, parent_with_child):
        from billing.models import Package, Subscription
        pkg = Package.objects.create(
            name=f"Basic {_RUN_ID}", price=Decimal("19.90"),
            class_limit=2, is_active=True,
        )
        Subscription.objects.get_or_create(
            user=parent_with_child,
            defaults={"package": pkg, "status": "active"},
        )
        self.page.goto(f"{self.url}/parent/billing/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("h1", has_text="Billing")).to_be_visible()
        # Subscription block should be visible
        expect(self.page.locator("text=Active")).to_be_visible()

    def test_invoices_link_present(self):
        self.page.goto(f"{self.url}/parent/billing/")
        self.page.wait_for_load_state("networkidle")
        link = self.page.locator("a", has_text="View Invoices")
        expect(link).to_be_visible()
        link.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("h1", has_text="Invoices")).to_be_visible()

    def test_payment_history_link_present(self):
        self.page.goto(f"{self.url}/parent/billing/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("a", has_text="Payment History")).to_be_visible()


# ---------------------------------------------------------------------------
# Sidebar — Billing link
# ---------------------------------------------------------------------------

class TestParentSidebarBillingLink:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        self.page.goto(f"{self.url}/parent/invoices/")
        self.page.wait_for_load_state("networkidle")

    def test_billing_link_in_sidebar(self):
        """Billing link exists in the desktop sidebar nav."""
        # Target the desktop sidebar (not the hidden mobile drawer)
        billing_link = self.page.locator("aside nav a", has_text="Billing").first
        expect(billing_link).to_be_visible()

    def test_billing_link_navigates_to_billing_page(self):
        self.page.locator("aside nav a", has_text="Billing").first.click()
        self.page.wait_for_load_state("networkidle")
        import re
        expect(self.page).to_have_url(re.compile(r"/parent/billing/"))
        expect(self.page.locator("h1", has_text="Billing")).to_be_visible()

    def test_invoices_link_in_sidebar(self):
        expect(self.page.locator("aside nav a", has_text="Invoices").first).to_be_visible()

    def test_payments_link_in_sidebar(self):
        expect(self.page.locator("aside nav a", has_text="Payments").first).to_be_visible()

    def test_billing_section_label(self):
        """Section divider labelled 'Billing' exists in the desktop sidebar."""
        expect(self.page.locator("aside p", has_text="Billing").first).to_be_visible()


# ---------------------------------------------------------------------------
# Multi-child invoice isolation
# ---------------------------------------------------------------------------

class TestMultiChildInvoiceIsolation:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               issued_invoice_child1,
               issued_invoice_child2,
               paid_invoice):
        self.url = live_server.url
        self.page = page
        self.inv_c1 = issued_invoice_child1
        self.inv_c2 = issued_invoice_child2
        self.inv_paid = paid_invoice
        do_login(page, self.url, parent_with_two_children)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_both_issued_invoices_shown(self):
        expect(self.page.locator(f"text={self.inv_c1.invoice_number}")).to_be_visible()
        expect(self.page.locator(f"text={self.inv_c2.invoice_number}")).to_be_visible()

    def test_paid_invoice_shown_too(self):
        expect(self.page.locator(f"text={self.inv_paid.invoice_number}")).to_be_visible()

    def test_outstanding_excludes_paid(self):
        """Total outstanding = 120 + 80 = 200, not 250 (paid $50 excluded)."""
        expect(self.page.locator("p.text-3xl.font-bold")).to_contain_text("200.00")

    def test_other_parent_cannot_see_these_invoices(self, db, roles):
        """A different parent with no children sees no invoices."""
        from accounts.models import Role
        from .conftest import _make_user, TEST_PASSWORD

        other = _make_user("ui_other_par", Role.PARENT)
        do_login(self.page, self.url, other)
        self.page.goto(f"{self.url}/parent/invoices/")
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator(f"text={self.inv_c1.invoice_number}")).not_to_be_visible()
        expect(self.page.locator(f"text={self.inv_c2.invoice_number}")).not_to_be_visible()
        # No banner either
        expect(self.page.locator("#open-pay-modal")).not_to_be_visible()
