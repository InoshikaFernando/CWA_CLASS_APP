"""
UI automation tests for CPP-358: Message History Inbox.

Tests verify visible behaviour of the inbox list page and row actions:
  - Inbox loads with tabs and New Message button
  - Draft messages show Edit + Delete actions
  - Scheduled messages show Cancel action
  - Failed messages show Retry action
  - Sent messages show no action buttons
  - Tab filter navigation works
  - Delete draft shows confirm dialog and removes row
  - Cancel scheduled shows confirm dialog and changes status badge
  - Search filters by subject

Run locally:
    pytest ui_tests/test_messaging_inbox.py -v
"""
import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.messaging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scheduled_message(school, user, subject, status='draft', frequency='now'):
    from classroom.models import ScheduledMessage
    return ScheduledMessage.objects.create(
        school=school,
        created_by=user,
        subject=subject,
        body_html='<p>Test body</p>',
        status=status,
        frequency=frequency,
        recipients_to=[{'id': 1, 'name': 'Alice', 'email': 'alice@test.com', 'role': 'staff'}],
        recipients_cc=[],
        recipients_bcc=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMessagingInbox:
    """CPP-358: inbox page visible behaviour."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.admin = admin_user
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/messaging/inbox/")
        page.wait_for_load_state('domcontentloaded')

    def test_inbox_page_loads(self):
        """Inbox page renders with Messages heading."""
        expect(self.page.locator('h1')).to_contain_text('Messages')

    def test_new_message_button_visible(self):
        """New Message button is present and links to compose."""
        btn = self.page.locator('a', has_text='New Message')
        expect(btn).to_be_visible()
        expect(btn).to_have_attribute('href', '/admin-dashboard/messaging/compose/')

    def test_tabs_visible(self):
        """All status tabs (All, Draft, Scheduled, Sent, Failed) are visible."""
        for tab_text in ['All', 'Draft', 'Scheduled', 'Sent', 'Failed']:
            expect(self.page.locator(f'text="{tab_text}"').first).to_be_visible()

    def test_empty_state_shown_when_no_messages(self):
        """Empty state text shown when inbox is empty."""
        expect(self.page.locator('body')).to_contain_text('No messages found')

    def test_draft_message_appears_in_list(self, db):
        """A draft message's subject appears in the inbox table."""
        _make_scheduled_message(self.school, self.admin, 'My First Draft')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('body')).to_contain_text('My First Draft')

    def test_draft_shows_edit_and_delete_buttons(self, db):
        """Draft row shows Edit and Delete action buttons."""
        _make_scheduled_message(self.school, self.admin, 'Draft With Actions')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('text="Edit"').first).to_be_visible()
        expect(self.page.locator('button', has_text='Delete').first).to_be_visible()

    def test_scheduled_shows_cancel_button(self, db):
        """Scheduled row shows Cancel action button."""
        _make_scheduled_message(self.school, self.admin, 'Sched Msg', status='scheduled')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('button', has_text='Cancel').first).to_be_visible()

    def test_failed_shows_retry_button(self, db):
        """Failed row shows Retry action button."""
        _make_scheduled_message(self.school, self.admin, 'Failed Msg', status='failed')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('button', has_text='Retry').first).to_be_visible()

    def test_sent_shows_delete_button(self, db):
        """Sent row shows a Delete button (delete allowed for all statuses)."""
        _make_scheduled_message(self.school, self.admin, 'Sent Msg', status='sent')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('body')).to_contain_text('Sent Msg')
        expect(self.page.locator('button', has_text='Delete').first).to_be_visible()

    def test_tab_draft_filter(self, db):
        """Clicking Draft tab filters to only draft messages."""
        _make_scheduled_message(self.school, self.admin, 'OnlyDraft', status='draft')
        _make_scheduled_message(self.school, self.admin, 'OnlySent', status='sent')
        self.page.goto(f"{self.url}/admin-dashboard/messaging/inbox/?tab=draft")
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('body')).to_contain_text('OnlyDraft')
        expect(self.page.locator('body')).not_to_contain_text('OnlySent')

    def test_search_filters_by_subject(self, db):
        """Search form filters messages by subject."""
        _make_scheduled_message(self.school, self.admin, 'UniqueXYZSubject')
        _make_scheduled_message(self.school, self.admin, 'OtherMessage')
        self.page.goto(f"{self.url}/admin-dashboard/messaging/inbox/?q=UniqueXYZ")
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('body')).to_contain_text('UniqueXYZSubject')
        expect(self.page.locator('body')).not_to_contain_text('OtherMessage')

    def test_delete_draft_removes_from_list(self, db):
        """Clicking Delete on draft and confirming via custom modal removes it."""
        _make_scheduled_message(self.school, self.admin, 'DraftToDelete', status='draft')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.locator('button', has_text='Delete').first.click()
        # Custom confirm modal — click "Yes, delete"; wait for navigation to complete
        with self.page.expect_navigation():
            self.page.locator('button', has_text='Yes, delete').click()
        expect(self.page.locator('body')).not_to_contain_text('DraftToDelete')

    def test_cancel_scheduled_shows_success_toast(self, db):
        """Cancelling a scheduled message via custom modal shows success flash."""
        _make_scheduled_message(self.school, self.admin, 'SchedToCancel', status='scheduled')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.locator('button', has_text='Cancel').first.click()
        # Custom confirm modal — click "Yes, cancel"; wait for navigation to complete
        with self.page.expect_navigation():
            self.page.locator('button', has_text='Yes, cancel').click()
        expect(self.page.locator('body')).to_contain_text('cancelled')

    def test_sidebar_messaging_link_points_to_inbox(self):
        """Sidebar Messaging link points to the inbox, not compose."""
        link = self.page.locator('nav a', has_text='Messaging').first
        expect(link).to_have_attribute('href', '/admin-dashboard/messaging/inbox/')

    def test_dashboard_redirect_lands_on_inbox(self):
        """Navigating to /messaging/ redirects to inbox."""
        self.page.goto(f"{self.url}/admin-dashboard/messaging/")
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page).to_have_url(f"{self.url}/admin-dashboard/messaging/inbox/")

    def test_status_badge_shown_for_draft(self, db):
        """Draft status badge is visible in the table."""
        _make_scheduled_message(self.school, self.admin, 'BadgeTest', status='draft')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('text="Draft"').first).to_be_visible()

    # -- CPP-348: custom confirm modal --

    def test_confirm_modal_shows_on_delete(self, db):
        """Clicking Delete opens the custom confirm modal (not browser native dialog)."""
        _make_scheduled_message(self.school, self.admin, 'ModalTest', status='draft')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.locator('button', has_text='Delete').first.click()
        expect(self.page.locator('button', has_text='Yes, delete')).to_be_visible()
        expect(self.page.locator('button', has_text='Keep it')).to_be_visible()

    def test_confirm_modal_dismiss_keeps_message(self, db):
        """Clicking 'Keep it' in confirm modal does NOT delete the message."""
        _make_scheduled_message(self.school, self.admin, 'NotDeleted', status='draft')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.locator('button', has_text='Delete').first.click()
        self.page.locator('button', has_text='Keep it').click()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('body')).to_contain_text('NotDeleted')

    def test_delete_all_statuses_has_delete_button(self, db):
        """Sent, failed, and cancelled messages all show a Delete action button."""
        _make_scheduled_message(self.school, self.admin, 'SentMsg', status='sent')
        _make_scheduled_message(self.school, self.admin, 'FailedMsg', status='failed')
        _make_scheduled_message(self.school, self.admin, 'CancelledMsg', status='cancelled')
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        delete_buttons = self.page.locator('button', has_text='Delete')
        expect(delete_buttons.first).to_be_visible()
        assert delete_buttons.count() >= 3

    # -- CPP-348: tab notification badges --

    def test_tab_badges_visible_for_new_messages(self, db):
        """Status count badges appear on inbox tabs when there are unseen messages."""
        _make_scheduled_message(self.school, self.admin, 'SentBadge', status='sent')
        # Clear seen state so badges show
        self.page.evaluate("localStorage.removeItem('cwa_msg_seen_v2')")
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)  # Alpine init
        # Badge span with x-show="hasBadge(...)" should be visible
        badge = self.page.locator('[x-show*="hasBadge"]').first
        expect(badge).to_be_visible()

    def test_tab_badge_updates_localStorage_on_click(self, db):
        """Clicking a tab writes seen count to localStorage so badge disappears."""
        _make_scheduled_message(self.school, self.admin, 'SentSeen', status='sent')
        self.page.evaluate("localStorage.removeItem('cwa_msg_seen_v2')")
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(500)  # Alpine init
        self.page.locator('button', has_text='Sent').first.click()
        self.page.wait_for_timeout(300)
        seen = self.page.evaluate("localStorage.getItem('cwa_msg_seen_v2')")
        assert seen is not None, 'localStorage key not written after tab click'
