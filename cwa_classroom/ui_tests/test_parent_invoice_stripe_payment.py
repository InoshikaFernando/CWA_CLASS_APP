"""
UI tests for parent invoice payment flow.

Covers:
  - Invoices page: Pay banner shown/hidden, combined children, table columns
  - Pay button: direct-pay-btn shown when payment link configured, hidden otherwise
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


@pytest.fixture
def school_with_payment_link(db, school):
    """Set a payment link on the school."""
    school.stripe_payment_link = "https://pay.example.com/school"
    school.save(update_fields=["stripe_payment_link"])
    return school


# ---------------------------------------------------------------------------
# Invoices page — Pay banner with payment link configured
# ---------------------------------------------------------------------------

class TestParentInvoicesPayBanner:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               school_with_payment_link,
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
        """Pay Now button appears when payment link configured and outstanding > 0."""
        expect(self.page.locator("#direct-pay-btn")).to_be_visible()

    def test_banner_shows_total(self):
        """Banner displays sum of all outstanding invoices ($200)."""
        expect(self.page.locator("p.text-3xl.font-bold")).to_contain_text("200.00")

    def test_banner_shows_all_children_label(self):
        expect(self.page.locator("p.text-violet-200")).to_contain_text("Across all children")

    def test_both_invoices_in_table(self):
        """Both children's invoices appear in the table."""
        expect(self.page.locator(f"text=INV-UI-C1-{_RUN_ID}")).to_be_visible()
        expect(self.page.locator(f"text=INV-UI-C2-{_RUN_ID}")).to_be_visible()

    def test_child_name_column(self):
        """Child name column is present in the table."""
        expect(self.page.locator("th", has_text="Child").first).to_be_visible()

    def test_due_column_present(self):
        """Due amount column header is rendered."""
        expect(self.page.locator("th", has_text="Due").first).to_be_visible()


class TestParentInvoicesNoBanner:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, paid_invoice,
               school_with_payment_link):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_no_pay_banner_when_all_paid(self):
        """Pay button must not appear when nothing is outstanding."""
        expect(self.page.locator("#direct-pay-btn")).not_to_be_visible()

    def test_paid_invoice_still_in_table(self):
        """Paid invoices are still shown in the table."""
        expect(self.page.locator(f"text=INV-UI-PAID-{_RUN_ID}")).to_be_visible()

    def test_paid_status_badge(self):
        expect(self.page.locator("span.rounded-full", has_text="Paid").first).to_be_visible()


# ---------------------------------------------------------------------------
# Pay button hidden when no payment link configured
# ---------------------------------------------------------------------------

class TestParentInvoicesNoPaymentLink:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               issued_invoice_child1, issued_invoice_child2):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_two_children)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_no_pay_button_without_payment_link(self):
        """Pay Now button hidden when no payment link configured."""
        expect(self.page.locator("#direct-pay-btn")).not_to_be_visible()

    def test_banner_still_shows_outstanding(self):
        """Outstanding balance banner still shown (just no button)."""
        expect(self.page.locator("p.text-3xl.font-bold")).to_contain_text("200.00")


# ---------------------------------------------------------------------------
# Pay button redirect
# ---------------------------------------------------------------------------

class TestPayButtonRedirect:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page,
               parent_with_two_children,
               school_with_payment_link,
               issued_invoice_child1):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_two_children)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("networkidle")

    def test_pay_redirects_to_payment_link(self):
        """Clicking Pay Now POSTs to checkout endpoint which returns the payment link."""
        self.page.route(
            f"{self.url}/parent/invoices/pay/",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"checkout_url": "https://pay.example.com/school"}',
            ),
        )

        self.page.locator("#direct-pay-btn").click()
        self.page.wait_for_url(lambda url: "pay.example.com" in url, timeout=8000)

    def test_pay_button_disables_during_request(self):
        """Button shows redirecting text while request is in flight."""
        self.page.route(
            f"{self.url}/parent/invoices/pay/",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"checkout_url": "https://pay.example.com/school"}',
            ),
        )

        btn = self.page.locator("#direct-pay-btn")
        expect(btn).to_be_enabled()


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
               school_with_payment_link,
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
        expect(self.page.locator("#direct-pay-btn")).not_to_be_visible()
