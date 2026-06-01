"""
CPP-300 — End-to-end onboarding for CSV-imported school students.

Two product scenarios, driven through the real browser for every
user-facing step:

Scenario 1 (published school):
    Admin imports students into an ALREADY-published school. The
    welcome email with login credentials is sent immediately. The
    student logs in with those credentials, is hard-blocked onto the
    Complete-Profile page, and must either enter a 100% discount code
    (activates free) or proceed to card/payment.

Scenario 2 (unpublished school):
    Admin imports students into an unpublished school (no email yet),
    then clicks Publish. Only now is the welcome email sent. The rest
    of the student onboarding is identical to Scenario 1.

Why the import itself is done via the service layer
---------------------------------------------------
The CSV admin flow is a brittle four-step wizard (upload → column map →
structure map → confirm). Driving it through Playwright would test the
wizard plumbing, not the behaviour this ticket changed. So the bulk
creation is performed with ``import_services.execute_import`` — the exact
code path the confirm view calls — and the credentials it returns are the
same ones emailed to the student. Every step a real user performs
(student login, the payment/discount gate, the admin Publish click) is
driven through the browser. The view-level auto-send wiring is covered by
the unit tests in ``classroom/tests/test_csv_student_import.py``.

Email receipt is asserted two ways:
  * authoritative side effects — ``SchoolStudent.notified_at`` stamped and
    ``pending_password`` cleared only happen on a successful send, and
  * the credentials returned by the import are used to actually log the
    student in through the browser.
"""

from __future__ import annotations

import re

from decimal import Decimal

import pytest
from django.core import mail
from playwright.sync_api import expect

from .conftest import do_login, do_logout


pytestmark = pytest.mark.csv_import

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def locmem_email(settings):
    """Capture outgoing mail in django.core.mail.outbox for assertions."""
    settings.EMAIL_BACKEND = LOCMEM
    mail.outbox.clear()
    return mail.outbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_package(db):
    """The default student subscription package picked by CompleteProfileView."""
    from billing.models import Package

    return Package.objects.create(
        name="Student Monthly",
        class_limit=0,
        price=Decimal("19.90"),
        stripe_price_id="price_cpp300_test",
        trial_days=14,
        is_active=True,
        is_default=True,
        order=1,
    )


@pytest.fixture
def free_code(db):
    """A 100%-off discount code — activates access with no card required."""
    from billing.models import DiscountCode

    return DiscountCode.objects.create(
        code="FREELEARN",
        discount_percent=100,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_one_student(school, admin_user, *, first="Liam", last="Carter"):
    """Create one student (+ one parent) through the real import service.

    Returns the student credentials dict from the import:
    ``{'username', 'email', 'password', ...}`` — i.e. exactly what the
    welcome email delivers to the student.
    """
    from classroom import import_services as isvc

    student_email = f"{first.lower()}.{last.lower()}@example.com"
    parent_email = f"parent.{last.lower()}@example.com"
    data_rows = [[first, last, student_email, "Robin", last, parent_email]]
    column_mapping = {
        "first_name": 0,
        "last_name": 1,
        "email": 2,
        "parent1_first_name": 3,
        "parent1_last_name": 4,
        "parent1_email": 5,
    }
    preview = isvc.validate_and_preview(data_rows, column_mapping, school)
    results = isvc.execute_import(preview, school, admin_user)
    assert results["credentials"], "Import produced no student credentials"
    return results["credentials"][0]


def _send_publish_emails(school):
    """Invoke the same notifier the import-confirm / publish views call."""
    from classroom.email_service import send_school_publish_notifications

    return send_school_publish_notifications(school)


def _login_with_password(page, base_url, username, password):
    """Log in using an explicit (temporary) password rather than TEST_PASSWORD."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/accounts/login/")
    page.wait_for_load_state("domcontentloaded")
    page.locator("#id_username").fill(username)
    page.locator("#id_password").fill(password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)
    page.wait_for_load_state("domcontentloaded")


def _student_record(school, email):
    from classroom.models import SchoolStudent

    return SchoolStudent.objects.select_related("student").get(
        school=school, student__email__iexact=email,
    )


# ---------------------------------------------------------------------------
# Scenario 1 — import into an already-published school
# ---------------------------------------------------------------------------

class TestImportIntoPublishedSchool:
    """Published school: credentials are emailed the moment students are imported."""

    def test_published_import_emails_credentials_and_student_is_gated(
        self, live_server, page, admin_user, school, default_package, locmem_email,
    ):
        url = live_server.url

        # ── Admin imports into a PUBLISHED school ──────────────────────────
        school.is_published = True
        school.save(update_fields=["is_published"])

        creds = _import_one_student(school, admin_user, first="Liam", last="Carter")
        sent = _send_publish_emails(school)

        # Email was sent: authoritative side effects + outbox.
        assert sent["sent"] >= 1
        ss = _student_record(school, creds["email"])
        assert ss.notified_at is not None, "notified_at not stamped — email not sent"
        assert ss.pending_password == "", "pending_password not cleared after send"
        assert any(creds["email"] in (m.to or []) for m in mail.outbox), \
            "no welcome email addressed to the student"

        # Imported student is gated (Part 3): not yet able to use the app.
        student = ss.student
        assert student.profile_completed is False
        assert student.must_change_password is True
        assert student.creation_method == "institute"

        # ── Student logs in with the emailed credentials ───────────────────
        _login_with_password(page, url, creds["username"], creds["password"])

        # Hard-blocked onto Complete Profile by ProfileCompletionMiddleware.
        expect(page).to_have_url(re.compile(r"/accounts/complete-profile"))
        expect(page.locator("body")).to_contain_text("Complete Your Profile")

        # Both onboarding routes are offered: discount code AND card/subscription.
        expect(page.locator("input[name='discount_code']")).to_be_visible()
        expect(page.locator("body")).to_contain_text("Subscription")
        expect(
            page.get_by_role("button", name=re.compile("Complete Profile"))
        ).to_contain_text("Subscribe")

    def test_published_import_student_unlocks_with_full_discount_code(
        self, live_server, page, admin_user, school, default_package, free_code,
        locmem_email,
    ):
        url = live_server.url
        school.is_published = True
        school.save(update_fields=["is_published"])

        creds = _import_one_student(school, admin_user, first="Mia", last="Stone")
        _send_publish_emails(school)

        _login_with_password(page, url, creds["username"], creds["password"])
        expect(page).to_have_url(re.compile(r"/accounts/complete-profile"))

        # A 100% code requires NO card — activates immediately.
        page.locator("input[name='new_password']").fill("NewPass123!")
        page.locator("input[name='confirm_password']").fill("NewPass123!")
        page.locator("input[name='discount_code']").fill("FREELEARN")
        page.get_by_role("button", name=re.compile("Complete Profile")).click()

        # Left the gate — landed on the app, not bounced back to payment.
        page.wait_for_url(
            lambda u: "/accounts/complete-profile" not in u, timeout=10_000,
        )

        from accounts.models import CustomUser
        from billing.models import Subscription

        student = CustomUser.objects.get(email__iexact=creds["email"])
        assert student.profile_completed is True
        sub = Subscription.objects.get(user=student)
        assert sub.status == Subscription.STATUS_ACTIVE
        assert free_code.discount_percent == 100


# ---------------------------------------------------------------------------
# Scenario 2 — import into an unpublished school, then publish
# ---------------------------------------------------------------------------

class TestImportIntoUnpublishedThenPublish:
    """Unpublished school: no email at import; credentials emailed at publish."""

    def test_unpublished_import_holds_email_until_admin_publishes(
        self, live_server, page, admin_user, school, default_package, locmem_email,
    ):
        url = live_server.url

        # ── Admin imports into an UNPUBLISHED school — NO email yet ─────────
        school.is_published = False
        school.save(update_fields=["is_published"])

        creds = _import_one_student(school, admin_user, first="Noah", last="Reed")

        ss = _student_record(school, creds["email"])
        assert ss.notified_at is None, "email sent before publish — should be held"
        assert ss.pending_password != "", "credentials lost before publish"
        assert mail.outbox == [], "welcome email leaked before publish"
        assert ss.student.profile_completed is False  # gated regardless of publish

        # ── Admin publishes the school via the browser ─────────────────────
        do_login(page, url, admin_user)
        # SchoolPublishView is a POST endpoint; submit it from the authenticated
        # browser session so the real view runs and sends the emails.
        page.evaluate(
            """([base, schoolId]) => {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = `${base}/admin-dashboard/schools/${schoolId}/publish/`;
                const csrf = document.createElement('input');
                csrf.type = 'hidden';
                csrf.name = 'csrfmiddlewaretoken';
                const m = document.cookie.match(/csrftoken=([^;]+)/);
                csrf.value = m ? m[1] : '';
                form.appendChild(csrf);
                document.body.appendChild(form);
                form.submit();
            }""",
            [url, school.id],
        )
        page.wait_for_load_state("domcontentloaded")

        # Now the credentials have been emailed.
        ss.refresh_from_db()
        assert ss.notified_at is not None, "publish did not send the welcome email"
        assert ss.pending_password == "", "pending_password not cleared on publish"
        assert any(creds["email"] in (m.to or []) for m in mail.outbox), \
            "no welcome email to the student after publish"

        do_logout(page, url)

        # ── Student logs in with the now-delivered credentials ─────────────
        _login_with_password(page, url, creds["username"], creds["password"])
        expect(page).to_have_url(re.compile(r"/accounts/complete-profile"))
        expect(page.locator("body")).to_contain_text("Complete Your Profile")
        expect(page.locator("input[name='discount_code']")).to_be_visible()
        expect(page.locator("body")).to_contain_text("Subscription")
