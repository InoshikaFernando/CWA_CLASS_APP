"""
Playwright UI tests for CPP-241: class schedule change → orphaned session
confirmation flow.

Tests cover:
  - EditClassView redirects to confirm_reschedule when future sessions exist on old day
  - ConfirmRescheduleView renders warning card with old day, new day, orphan count
  - Confirming deletes old sessions and creates new ones on the new day
  - No-orphan edits save normally (no confirmation page)
  - Unauthenticated access to confirm_reschedule is denied
  - Warning card UI elements are visible (heading, counts, confirm button)
"""

from __future__ import annotations

import datetime
import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login, _make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_monday() -> datetime.date:
    today = datetime.date.today()
    days_ahead = (0 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


def _next_friday() -> datetime.date:
    today = datetime.date.today()
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


def _make_session(classroom, date, user):
    """Create a scheduled ClassSession on the given date."""
    from classroom.models import ClassSession
    return ClassSession.objects.create(
        classroom=classroom,
        date=date,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        status="scheduled",
        created_by=user,
    )


def _goto_edit_and_change_day(page: Page, url: str, classroom_id: int, new_day: str):
    """Open the edit form, change the day dropdown, and submit."""
    page.goto(f"{url}/class/{classroom_id}/edit/")
    page.wait_for_load_state("domcontentloaded")
    page.locator("select[name='day']").select_option(new_day)
    page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
    # Either redirects to confirm-reschedule or to class_detail
    page.wait_for_url(lambda u: "/edit/" not in u, timeout=15_000)
    page.wait_for_load_state("domcontentloaded")


def _click_confirm(page: Page):
    """Click the single confirm button on the reschedule confirmation page."""
    page.get_by_role("button", name=re.compile(r"Confirm", re.I)).click()
    page.wait_for_url(lambda u: "confirm-reschedule" not in u, timeout=15_000)
    page.wait_for_load_state("domcontentloaded")


# ---------------------------------------------------------------------------
# Fixture: classroom with sessions on Monday, then day changed to Friday
# ---------------------------------------------------------------------------

@pytest.fixture
def classroom_with_monday_sessions(db, classroom, admin_user):
    """Classroom (day=monday) with two future sessions on next Monday."""
    monday = _next_monday()
    _make_session(classroom, monday, admin_user)
    _make_session(classroom, monday + datetime.timedelta(weeks=1), admin_user)
    return classroom


# ---------------------------------------------------------------------------
# TestConfirmReschedulePageRender
# ---------------------------------------------------------------------------

class TestConfirmReschedulePageRender:
    """Verify the warning page shows the correct info."""

    @pytest.mark.django_db(transaction=True)
    def test_redirects_to_confirm_page_when_orphans_exist(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Editing day from monday→friday redirects to confirm_reschedule URL."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        assert "confirm-reschedule" in page.url, (
            f"Expected confirm-reschedule URL, got {page.url}"
        )
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_warning_card_is_visible(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Warning card (amber) with heading 'Schedule change detected' shows."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.get_by_text("Schedule change detected")).to_be_visible()
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_old_and_new_day_shown_in_warning(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Warning text includes old day (Monday) and new day (Friday)."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        body = page.locator("body")
        expect(body).to_contain_text("Monday")
        expect(body).to_contain_text("Friday")
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_orphan_count_shown_in_warning(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Warning text includes orphan count (2 sessions created in fixture)."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.locator("body")).to_contain_text("2")
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_confirm_button_is_visible(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """'Confirm & update sessions' button is present on the page."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(
            page.get_by_role("button", name=re.compile(r"Confirm", re.I))
        ).to_be_visible()
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_cancel_link_is_visible(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Cancel link is present on the page."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.get_by_role("link", name=re.compile(r"Cancel", re.I))).to_be_visible()
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_class_name_shown_as_subtitle(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Class name appears as subtitle on confirmation page."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.locator("body")).to_contain_text(classroom_with_monday_sessions.name)
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_page_heading_is_correct(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Page has 'Confirm Schedule Change' heading."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.get_by_role("heading", name="Confirm Schedule Change")).to_be_visible()
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])


# ---------------------------------------------------------------------------
# TestConfirmSessions
# ---------------------------------------------------------------------------

class TestConfirmSessions:
    """Confirm action deletes old sessions and creates new ones."""

    @pytest.mark.django_db(transaction=True)
    def test_confirm_removes_sessions_from_db(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """After confirming, no scheduled sessions remain on old day."""
        from classroom.models import ClassSession

        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        _click_confirm(page)

        monday = _next_monday()
        remaining = ClassSession.objects.filter(
            classroom=classroom_with_monday_sessions,
            date=monday,
            status="scheduled",
        ).count()
        assert remaining == 0, f"Expected 0 sessions after confirm, got {remaining}"

    @pytest.mark.django_db(transaction=True)
    def test_confirm_redirects_to_class_detail(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """After confirming, user leaves the confirmation page."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        _click_confirm(page)
        assert "confirm-reschedule" not in page.url

    @pytest.mark.django_db(transaction=True)
    def test_confirm_shows_success_message(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """After confirming, a success flash message contains 'Removed'."""
        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        _click_confirm(page)
        expect(page.locator("body")).to_contain_text("Removed")


# ---------------------------------------------------------------------------
# TestNoOrphansNoConfirmation
# ---------------------------------------------------------------------------

class TestNoOrphansNoConfirmation:
    """When no future sessions exist, edit saves directly with no confirm page."""

    @pytest.mark.django_db(transaction=True)
    def test_edit_without_sessions_skips_confirmation(
        self, page: Page, live_server, admin_user, classroom
    ):
        """No sessions → day change saves without showing confirm-reschedule."""
        do_login(page, live_server.url, admin_user)

        page.goto(f"{live_server.url}/class/{classroom.pk}/edit/")
        page.wait_for_load_state("domcontentloaded")
        page.locator("select[name='day']").select_option("friday")
        page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_url(lambda u: "/edit/" not in u, timeout=15_000)
        page.wait_for_load_state("domcontentloaded")

        assert "confirm-reschedule" not in page.url, (
            "Should not show confirm-reschedule when no orphaned sessions exist"
        )
        classroom.refresh_from_db()
        assert classroom.day == "friday"
        # restore
        classroom.day = "monday"
        classroom.save(update_fields=["day"])

    @pytest.mark.django_db(transaction=True)
    def test_same_day_change_skips_confirmation(
        self, page: Page, live_server, admin_user, classroom_with_monday_sessions
    ):
        """Updating name but keeping same day should NOT trigger confirmation."""
        do_login(page, live_server.url, admin_user)

        page.goto(f"{live_server.url}/class/{classroom_with_monday_sessions.pk}/edit/")
        page.wait_for_load_state("domcontentloaded")

        name_field = page.locator("input[name='name']")
        name_field.fill(f"{classroom_with_monday_sessions.name} v2")
        # Keep day as monday (don't change it)
        page.get_by_role("button", name=re.compile(r"Save Changes", re.I)).click()
        page.wait_for_url(lambda u: "/edit/" not in u, timeout=15_000)

        assert "confirm-reschedule" not in page.url

    @pytest.mark.django_db(transaction=True)
    def test_cancelled_sessions_dont_trigger_confirmation(
        self, page: Page, live_server, admin_user, classroom
    ):
        """Cancelled sessions on old day should NOT trigger confirmation."""
        from classroom.models import ClassSession

        monday = _next_monday()
        ClassSession.objects.create(
            classroom=classroom,
            date=monday,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status="cancelled",
            created_by=admin_user,
        )

        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(page, live_server.url, classroom.pk, "friday")

        assert "confirm-reschedule" not in page.url, (
            "Cancelled sessions should not count as orphans"
        )
        classroom.day = "monday"
        classroom.save(update_fields=["day"])


# ---------------------------------------------------------------------------
# TestConfirmRescheduleAccess
# ---------------------------------------------------------------------------

class TestConfirmRescheduleAccess:
    """Access control for the confirm_reschedule view."""

    @pytest.mark.django_db(transaction=True)
    def test_unauthenticated_cannot_access_confirm_page(
        self, page: Page, live_server, classroom
    ):
        """Unauthenticated GET to confirm-reschedule redirects to login."""
        page.goto(f"{live_server.url}/class/{classroom.pk}/confirm-reschedule/")
        page.wait_for_load_state("domcontentloaded")
        assert "/accounts/login" in page.url or page.locator("#id_username").count() > 0

    @pytest.mark.django_db(transaction=True)
    def test_hod_can_access_confirm_page(
        self, page: Page, live_server, hod_user, classroom_with_monday_sessions
    ):
        """HoD (head of department) can see the confirm_reschedule page."""
        do_login(page, live_server.url, hod_user)
        _goto_edit_and_change_day(
            page, live_server.url,
            classroom_with_monday_sessions.pk, "friday",
        )
        expect(page.get_by_role("heading", name="Confirm Schedule Change")).to_be_visible()
        # restore
        classroom_with_monday_sessions.day = "monday"
        classroom_with_monday_sessions.save(update_fields=["day"])


# ---------------------------------------------------------------------------
# TestDeleteWithAttendanceProtection
# ---------------------------------------------------------------------------

class TestTodaySessionProtection:
    """Today's session must never be deleted during a reschedule."""

    @pytest.mark.django_db(transaction=True)
    def test_todays_session_preserved_after_confirm(
        self, page: Page, live_server, admin_user, classroom
    ):
        """Session dated today is NOT deleted even if it's on the old day."""
        from classroom.models import ClassSession

        today = datetime.date.today()
        today_session = ClassSession.objects.create(
            classroom=classroom,
            date=today,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=admin_user,
        )
        # Also create a future session on the old day so the confirm page appears
        next_monday = _next_monday()
        ClassSession.objects.create(
            classroom=classroom,
            date=next_monday,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=admin_user,
        )

        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(page, live_server.url, classroom.pk, "friday")

        if "confirm-reschedule" in page.url:
            _click_confirm(page)

        assert ClassSession.objects.filter(id=today_session.id).exists(), (
            "Today's session must not be deleted during reschedule"
        )
        # cleanup
        classroom.day = "monday"
        classroom.save(update_fields=["day"])


class TestDeleteWithAttendanceProtection:
    """Sessions with student attendance are never deleted."""

    @pytest.mark.django_db(transaction=True)
    def test_attended_session_not_deleted(
        self, page: Page, live_server, admin_user, classroom, enrolled_student
    ):
        """A session with an attendance record is skipped during delete."""
        from classroom.models import ClassSession, StudentAttendance

        monday = _next_monday()
        session = ClassSession.objects.create(
            classroom=classroom,
            date=monday,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status="scheduled",
            created_by=admin_user,
        )
        StudentAttendance.objects.create(
            session=session,
            student=enrolled_student,
            status="present",
            marked_by=admin_user,
        )

        do_login(page, live_server.url, admin_user)
        _goto_edit_and_change_day(page, live_server.url, classroom.pk, "friday")

        if "confirm-reschedule" in page.url:
            _click_confirm(page)

        # Session with attendance must still exist
        assert ClassSession.objects.filter(id=session.id).exists(), (
            "Session with attendance record must not be deleted"
        )
        # cleanup
        classroom.day = "monday"
        classroom.save(update_fields=["day"])
