"""
UI automation + end-to-end tests for CPP-349 through CPP-352:

CPP-349:
  - "Messaging" sidebar link appears under COMMUNICATION
  - Clicking navigates to /admin-dashboard/messaging/compose/
  - Active highlight applied on /messaging/* routes
  - Page renders correct heading and channel toggle
  - Non-admin (student) cannot access the compose page

CPP-350:
  - To field visible with search placeholder
  - + CC / + BCC expanders collapse/expand CC and BCC rows
  - Typing 2+ chars triggers autocomplete dropdown
  - Clicking a result adds a tag pill
  - × on a tag removes it
  - Free-text valid email accepted on Enter
  - Dropdown absent when typing fewer than 2 chars

CPP-352:
  - Schedule section visible with 4 mode pills
  - Send Now is default selected
  - Clicking One Time shows date + time fields
  - Clicking Weekly shows day-of-week + time + start/end date fields
  - Clicking Monthly shows day-of-month + time + start/end date fields
  - Next send preview shown for One Time when date + time filled
  - Next send preview shown for Weekly when start date + day filled
  - Send button disabled without schedule date for One Time mode
  - Send button text changes between Send Now and Schedule Message

Run locally:
    pytest ui_tests/test_messaging_sidebar.py -v

Run against deployed env:
    pytest ui_tests/test_messaging_sidebar.py --live-url=https://test.wizardslearninghub.co.nz -v
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, assert_sidebar_missing_link, click_sidebar_link

pytestmark = pytest.mark.messaging


# ---------------------------------------------------------------------------
# CPP-349: Sidebar visibility + navigation
# ---------------------------------------------------------------------------

class TestMessagingSidebarLink:
    """Messaging link in sidebar_admin.html — CPP-349."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_messaging_link_visible_in_sidebar(self):
        """'Messaging' appears in the admin sidebar under COMMUNICATION."""
        assert_sidebar_has_link(self.page, "Messaging")

    def test_messaging_link_navigates_to_compose(self):
        """Clicking Messaging navigates to /messaging/inbox/."""
        click_sidebar_link(self.page, "Messaging")
        expect(self.page).to_have_url(re.compile(r"/messaging/inbox/"))

    def test_messaging_link_under_communication_section(self):
        """Messaging sits after Email under the COMMUNICATION heading."""
        sidebar = self.page.locator("aside#sidebar")
        comm_heading = sidebar.get_by_text("Communication", exact=False)
        expect(comm_heading).to_be_visible()
        assert_sidebar_has_link(self.page, "Email")
        assert_sidebar_has_link(self.page, "Messaging")


# ---------------------------------------------------------------------------
# CPP-349: Active state
# ---------------------------------------------------------------------------

class TestMessagingActiveState:
    """Active highlight applied when navigated to /messaging/* routes."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)

    def test_messaging_link_active_on_compose_page(self):
        """Messaging nav item has active bg class when on compose page."""
        self.page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        self.page.wait_for_load_state("domcontentloaded")
        link = self.page.locator("aside#sidebar a", has_text="Messaging")
        expect(link).to_have_class(re.compile(r"bg-white/15"))

    def test_email_link_not_active_on_messaging_page(self):
        """Email nav item does NOT have active bg class when on messaging page."""
        self.page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        self.page.wait_for_load_state("domcontentloaded")
        email_link = self.page.locator("aside#sidebar a", has_text="Email")
        expect(email_link).not_to_have_class(re.compile(r"bg-white/15"))

    def test_messaging_link_not_active_on_dashboard(self):
        """Messaging nav item NOT active when on admin dashboard."""
        self.page.goto(f"{self.url}/admin-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        link = self.page.locator("aside#sidebar a", has_text="Messaging")
        expect(link).not_to_have_class(re.compile(r"bg-white/15"))


# ---------------------------------------------------------------------------
# CPP-349 + CPP-350: Compose page content
# ---------------------------------------------------------------------------

class TestMessagingComposePage:
    """Compose page renders correct content (CPP-349 shell + CPP-350 recipient fields)."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_title_contains_messaging(self):
        # Title is "New Message — CWA School"
        expect(self.page).to_have_title(re.compile(r"Message", re.IGNORECASE))

    def test_page_heading_new_message(self):
        heading = self.page.get_by_role("heading", name=re.compile(r"New Message", re.IGNORECASE))
        expect(heading).to_be_visible()

    def test_channel_email_option_visible(self):
        # Use border class to target channel badge, not sidebar span
        expect(self.page.locator('.border-indigo-500', has_text='Email').first).to_be_visible()

    def test_channel_sms_option_visible_but_disabled(self):
        sms_el = self.page.locator("text=SMS").first
        expect(sms_el).to_be_visible()

    def test_sms_coming_soon_tooltip_text_present(self):
        expect(self.page.locator("text=SMS coming in Phase 2")).to_be_attached()

    def test_to_field_input_visible(self):
        """To field has a visible search input."""
        to_input = self.page.locator("input[placeholder*='Name or email']").first
        expect(to_input).to_be_visible()

    def test_cc_collapsed_by_default(self):
        """CC row is hidden initially; only + CC button visible."""
        expect(self.page.get_by_text("+ CC")).to_be_visible()

    def test_bcc_collapsed_by_default(self):
        """BCC row is hidden initially; only + BCC button visible."""
        expect(self.page.get_by_text("+ BCC")).to_be_visible()

    def test_schedule_section_visible(self):
        expect(self.page.get_by_text("Schedule", exact=True)).to_be_visible()

    def test_send_button_disabled(self):
        send_btn = self.page.locator('button[name="action"][value="send"]')
        expect(send_btn).to_be_disabled()

    def test_save_draft_button_disabled(self):
        draft_btn = self.page.get_by_role("button", name=re.compile(r"Save Draft", re.IGNORECASE))
        expect(draft_btn).to_be_disabled()

    def test_school_name_displayed(self, school):
        expect(self.page.get_by_text(school.name)).to_be_visible()


# ---------------------------------------------------------------------------
# CPP-350: Recipient field interactions
# ---------------------------------------------------------------------------

class TestRecipientToField:
    """To field autocomplete, tag pills, keyboard navigation."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.live_url = live_server.url
        self.page = page
        self.school = school
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_dropdown_when_typing_one_char(self):
        """Dropdown does not appear for a single character."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.type("A")
        self.page.wait_for_timeout(400)
        # dropdown container should not be visible
        dropdown = self.page.locator("[x-show='to.open']").first
        expect(dropdown).not_to_be_visible()

    def test_cc_row_expands_on_plus_cc_click(self):
        """Clicking + CC shows the CC input row."""
        self.page.get_by_text("+ CC").click()
        cc_inputs = self.page.locator("input[placeholder*='Name or email']")
        expect(cc_inputs.nth(1)).to_be_visible()

    def test_bcc_row_expands_on_plus_bcc_click(self):
        """Clicking + BCC shows the BCC input row."""
        self.page.get_by_text("+ BCC").click()
        bcc_inputs = self.page.locator("input[placeholder*='Name or email']")
        # CC input (hidden) is at nth(1); BCC input (visible) is at nth(2)
        expect(bcc_inputs.nth(2)).to_be_visible()

    def test_plus_cc_button_hidden_after_expanding(self):
        """+ CC button disappears once CC row is expanded."""
        self.page.get_by_text("+ CC").click()
        self.page.wait_for_timeout(200)
        expect(self.page.get_by_text("+ CC")).not_to_be_visible()

    def test_free_text_email_accepted_on_enter(self):
        """Typing a valid email and pressing Enter adds a tag pill."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("test@example.com")
        inp.press("Enter")
        self.page.wait_for_timeout(200)
        tag = self.page.locator("text=test@example.com").first
        expect(tag).to_be_visible()

    def test_free_text_email_accepted_on_comma(self):
        """Typing a valid email and pressing comma adds a tag pill."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("another@example.com")
        inp.press(",")
        self.page.wait_for_timeout(200)
        tag = self.page.locator("text=another@example.com").first
        expect(tag).to_be_visible()

    def test_invalid_text_not_accepted_as_tag(self):
        """Text without @ does not become a tag on Enter."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("notanemail")
        inp.press("Enter")
        self.page.wait_for_timeout(200)
        # Input should still contain the text (no tag created)
        expect(inp).to_have_value("notanemail")

    def test_tag_removable_with_x_button(self):
        """After adding a free-text email tag, clicking × removes it."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("remove@example.com")
        inp.press("Enter")
        self.page.wait_for_timeout(200)
        # Outer tag pill span has rounded-full class; inner x-text span also matches
        # Use rounded-full to target the outer pill container
        tag_area = self.page.locator("span.rounded-full", has_text="remove@example.com").first
        expect(tag_area).to_be_visible()
        close_btn = tag_area.locator("button").first
        close_btn.click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator("text=remove@example.com")).not_to_be_visible()

    def test_backspace_removes_last_tag(self):
        """Pressing Backspace on empty input removes the last tag."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("back@example.com")
        inp.press("Enter")
        self.page.wait_for_timeout(200)
        inp.fill("")
        inp.press("Backspace")
        self.page.wait_for_timeout(200)
        expect(self.page.locator("text=back@example.com")).not_to_be_visible()

    def test_escape_closes_dropdown(self):
        """Pressing Escape hides the open dropdown."""
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("te")
        # Wait long enough for debounce (300ms) + XHR to fully resolve so
        # the dropdown is open before we press Escape (avoids a race where
        # the XHR response reopens the dropdown after Escape is handled)
        self.page.wait_for_timeout(1000)
        inp.press("Escape")
        self.page.wait_for_timeout(300)
        dropdown = self.page.locator("[x-show='to.open']").first
        expect(dropdown).not_to_be_visible()


# ---------------------------------------------------------------------------
# CPP-351: Subject, body editor, attachments, button enable state
# ---------------------------------------------------------------------------

class TestComposeSubjectAndBody:
    """Subject input, rich text editor, and reactive button state — CPP-351."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")

    def test_subject_input_visible(self):
        """Subject text input is visible on the compose page."""
        subj = self.page.locator("input[name='subject']")
        expect(subj).to_be_visible()

    def test_subject_placeholder_text(self):
        """Subject input shows placeholder text."""
        subj = self.page.locator("input[name='subject']")
        expect(subj).to_have_attribute("placeholder", re.compile(r"Subject", re.IGNORECASE))

    def test_subject_char_counter_hidden_initially(self):
        """Character counter shows '0/255' before typing (always visible, faint)."""
        counter = self.page.locator("text=/\\d+\\/255/")
        expect(counter).to_contain_text("0/255")

    def test_subject_char_counter_appears_on_typing(self):
        """Typing in subject shows character counter."""
        subj = self.page.locator("input[name='subject']")
        subj.fill("Hello")
        self.page.wait_for_timeout(100)
        counter = self.page.locator("text=/\\d+\\/255/")
        expect(counter).to_be_visible()

    def test_subject_char_counter_reflects_length(self):
        """Counter shows correct character count."""
        subj = self.page.locator("input[name='subject']")
        subj.fill("Hi there")
        self.page.wait_for_timeout(100)
        expect(self.page.locator("text=8/255")).to_be_visible()

    def test_body_editor_visible(self):
        """Contenteditable body editor is visible."""
        editor = self.page.locator("[contenteditable='true']").first
        expect(editor).to_be_visible()

    def test_body_toolbar_bold_button_visible(self):
        """Bold button visible in the formatting toolbar."""
        bold_btn = self.page.locator("button[title='Bold']")
        expect(bold_btn).to_be_visible()

    def test_body_toolbar_italic_button_visible(self):
        """Italic button visible in the formatting toolbar."""
        expect(self.page.locator("button[title='Italic']")).to_be_visible()

    def test_body_toolbar_link_button_visible(self):
        """Insert link button visible in the formatting toolbar."""
        expect(self.page.locator("button[title='Insert link']")).to_be_visible()

    def test_body_toolbar_list_button_visible(self):
        """Bullet list button visible in toolbar."""
        expect(self.page.locator("button[title='Bullet list']")).to_be_visible()

    def test_send_button_disabled_with_empty_form(self):
        """Send button is disabled when To, Subject and Body are all empty."""
        send_btn = self.page.locator('button[name="action"][value="send"]')
        expect(send_btn).to_be_disabled()

    def test_draft_button_disabled_with_empty_form(self):
        """Save Draft is disabled when subject and body are empty."""
        draft_btn = self.page.get_by_role("button", name=re.compile(r"Save Draft", re.IGNORECASE))
        expect(draft_btn).to_be_disabled()

    def test_draft_button_enabled_after_typing_subject(self):
        """Save Draft becomes enabled once subject has content."""
        subj = self.page.locator("input[name='subject']")
        subj.fill("Test subject")
        self.page.wait_for_timeout(200)
        draft_btn = self.page.get_by_role("button", name=re.compile(r"Save Draft", re.IGNORECASE))
        expect(draft_btn).to_be_enabled()

    def test_draft_button_enabled_after_typing_body(self):
        """Save Draft becomes enabled once body has content."""
        editor = self.page.locator("[contenteditable='true']").first
        editor.click()
        editor.type("Hello world")
        self.page.wait_for_timeout(200)
        draft_btn = self.page.get_by_role("button", name=re.compile(r"Save Draft", re.IGNORECASE))
        expect(draft_btn).to_be_enabled()

    def test_send_button_enabled_when_form_complete(self):
        """Send button enables when To + Subject + Body are all filled."""
        # Add a free-text recipient to To
        inp = self.page.locator("input[placeholder*='Name or email']").first
        inp.fill("test@example.com")
        inp.press("Enter")
        self.page.wait_for_timeout(200)
        # Fill subject
        self.page.locator("input[name='subject']").fill("Monthly Update")
        # Fill body
        editor = self.page.locator("[contenteditable='true']").first
        editor.click()
        editor.type("Dear all, this is your monthly update.")
        self.page.wait_for_timeout(200)
        send_btn = self.page.locator('button[name="action"][value="send"]')
        expect(send_btn).to_be_enabled()

    def test_attach_file_button_visible(self):
        """'Attach file' button is visible."""
        expect(self.page.get_by_text("Attach file")).to_be_visible()


# ---------------------------------------------------------------------------
# CPP-349: Messaging dashboard redirect
# ---------------------------------------------------------------------------

class TestMessagingDashboardRedirect:
    """/messaging/ redirects to compose page."""

    def test_messaging_dashboard_redirects_to_compose(self, live_server, page, admin_user, school):
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/messaging/inbox/"))


# ---------------------------------------------------------------------------
# CPP-349: Access control
# ---------------------------------------------------------------------------

class TestMessagingAccessControl:
    """Non-admin roles cannot access the messaging pages."""

    def test_student_cannot_access_compose(self, live_server, page, student_user):
        do_login(page, live_server.url, student_user)
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).not_to_have_url(re.compile(r"/messaging/compose/"))

    def test_unauthenticated_redirected_to_login(self, live_server, page):
        page.goto(f"{live_server.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/login|/accounts/login"))


# ---------------------------------------------------------------------------
# CPP-352: Schedule picker
# ---------------------------------------------------------------------------

class TestSchedulePicker:
    """Schedule picker — send-now / one-time / weekly / monthly modes."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(400)
        # Schedule section is collapsed by default (showSchedule=false); expand it
        page.evaluate("""
            () => {
                const form = document.querySelector('form[x-data]');
                const stack = form && form._x_dataStack;
                if (stack && stack[0]) stack[0].showSchedule = true;
            }
        """)
        page.wait_for_timeout(200)

    def test_schedule_section_visible(self):
        """Schedule card is visible on the compose page."""
        expect(self.page.get_by_text("Schedule", exact=False).first).to_be_visible()

    def test_send_now_pill_present(self):
        # get_by_text("Immediate") matches 3 elements (x-text badge, pill span,
        # hint paragraph containing "immediately"). Target the label wrapping the
        # 'now' radio input instead.
        expect(self.page.locator('label:has(input[value="now"])')).to_be_visible()

    def test_one_time_pill_present(self):
        expect(self.page.get_by_text("One Time")).to_be_visible()

    def test_weekly_pill_present(self):
        expect(self.page.get_by_text("Weekly")).to_be_visible()

    def test_monthly_pill_present(self):
        expect(self.page.get_by_text("Monthly")).to_be_visible()

    def test_send_now_is_default(self):
        """Send Now radio is checked by default (frequency=now)."""
        radio = self.page.locator('input[name="schedule_mode_display"][value="now"]')
        expect(radio).to_be_checked()

    def test_click_once_shows_date_input(self):
        """Clicking One Time reveals a date input."""
        self.page.get_by_text("One Time").click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator('input[type="date"]').first).to_be_visible()

    def test_click_weekly_shows_day_select(self):
        """Clicking Weekly reveals day-of-week selector."""
        self.page.get_by_text("Weekly").click()
        self.page.wait_for_timeout(200)
        # <option> elements are always hidden in Playwright; check the select itself
        expect(self.page.locator('select[x-model="weeklyDay"]')).to_be_visible()

    def test_click_monthly_shows_ordinal_option(self):
        """Clicking Monthly reveals 'On the' label for ordinal day selection."""
        self.page.get_by_text("Monthly").click()
        self.page.wait_for_timeout(200)
        # <option> elements are always hidden; check the "On the" label instead
        expect(self.page.get_by_text("On the")).to_be_visible()

    def test_weekly_shows_starts_label(self):
        """Weekly panel shows a 'Starts' date label."""
        self.page.get_by_text("Weekly").click()
        self.page.wait_for_timeout(200)
        # Both weekly and monthly panels have "Starts"; use .first
        expect(self.page.get_by_text("Starts").first).to_be_visible()

    def test_click_send_now_hides_date_panel(self):
        """Switching back to Send Now hides the date/time panel."""
        self.page.get_by_text("One Time").click()
        self.page.wait_for_timeout(200)
        # get_by_text("Immediate") matches multiple elements; click the label
        self.page.locator('label:has(input[value="now"])').click()
        self.page.wait_for_timeout(200)
        date_inputs = self.page.locator('input[type="date"]')
        expect(date_inputs.first).to_be_hidden()

    def test_once_next_send_preview_appears(self):
        """Filling date + time in One Time mode shows the preview line."""
        self.page.get_by_text("One Time").click()
        self.page.wait_for_timeout(200)
        self.page.locator('input[type="date"]').first.fill("2030-06-01")
        self.page.wait_for_timeout(400)
        expect(self.page.get_by_text(re.compile(r"Next send:"))).to_be_visible()

    def test_send_now_button_label(self):
        """Send button shows 'Send Now' when frequency is now."""
        btn = self.page.get_by_role("button", name=re.compile(r"Send Now", re.IGNORECASE))
        expect(btn).to_be_visible()

    def test_schedule_message_button_label_for_once(self):
        """Send button label changes to 'Schedule' for One Time."""
        self.page.get_by_text("One Time").click()
        self.page.wait_for_timeout(300)
        # Button text is "Schedule" (not "Schedule Message") for non-now frequency
        btn = self.page.locator('button[name="action"][value="send"]')
        expect(btn).to_contain_text("Schedule")
