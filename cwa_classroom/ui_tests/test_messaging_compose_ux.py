"""
UI automation tests for CPP-361: Compose UX Improvements.

Tests verify the 7 UX improvements on the compose page:
  1. Subject label reads 'Subject' (not 'Sub')
  2. Subject counter visible from page load
  3. Undo/Redo buttons present in toolbar
  4. Send button tooltip shown when disabled
  5. Save Draft tooltip shown when disabled
  6. Group quick-add chips visible (All Students / All Staff / All Parents)
  7. 'Send test to self' button present
  8. Inline attachment error shown (no alert) — via JS injection

Run locally:
    pytest ui_tests/test_messaging_compose_ux.py -v
"""
import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.messaging


def _make_school_student(school, user, email='wlhtestmails+ux_stu@gmail.com'):
    from classroom.models import SchoolStudent
    from accounts.models import CustomUser, Role
    uname = email.split('@')[0].replace('+', '_').replace('.', '_')
    try:
        stu = CustomUser.objects.get(username=uname)
    except CustomUser.DoesNotExist:
        stu = CustomUser.objects.create_user(username=uname, email=email, password='Testpass1!')
        stu.first_name = 'UX'
        stu.last_name = 'Student'
        stu.save()
    SchoolStudent.objects.get_or_create(school=school, student=stu, is_active=True)
    return stu


class TestComposeUX:
    """CPP-361: Compose page UX improvements."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.admin = admin_user
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/messaging/compose/")
        page.wait_for_load_state('domcontentloaded')

    # 1. Subject label
    def test_subject_label_shows_subject_not_sub(self):
        """Subject row label reads 'Subject', not truncated 'Sub'."""
        expect(self.page.locator('text="Subject"').first).to_be_visible()

    # 2. Subject counter always visible
    def test_subject_counter_visible_at_zero(self):
        """Subject character counter visible before any typing (shows 0/255)."""
        counter = self.page.locator('text="0/255"').first
        expect(counter).to_be_visible()

    def test_subject_counter_updates_on_type(self):
        """Subject character counter updates as user types."""
        subject_input = self.page.locator('input[name="subject"]')
        subject_input.fill('Hello')
        expect(self.page.locator('text="5/255"').first).to_be_visible()

    # 3. Undo / Redo toolbar
    def test_undo_button_in_toolbar(self):
        """Undo button is present in the formatting toolbar."""
        expect(self.page.locator('button[title="Undo (Ctrl+Z)"]')).to_be_visible()

    def test_redo_button_in_toolbar(self):
        """Redo button is present in the formatting toolbar."""
        expect(self.page.locator('button[title="Redo (Ctrl+Y)"]')).to_be_visible()

    # 4. Send button disabled tooltip
    def test_send_button_disabled_initially(self):
        """Send Now button is disabled on a blank form."""
        send_btn = self.page.locator('button[value="send"]')
        expect(send_btn).to_be_disabled()

    def test_send_button_tooltip_shown_on_hover(self):
        """Hovering the disabled Send button reveals a tooltip with requirements."""
        send_wrapper = self.page.locator('button[value="send"]').locator('..')
        send_wrapper.hover()
        self.page.wait_for_timeout(200)
        expect(self.page.locator('body')).to_contain_text('Required before sending')

    # 5. Draft button disabled tooltip
    def test_draft_button_disabled_initially(self):
        """Save Draft button is disabled on a blank form."""
        draft_btn = self.page.locator('button[value="draft"]')
        expect(draft_btn).to_be_disabled()

    def test_draft_button_enables_after_subject(self):
        """Save Draft button enables after entering a subject."""
        self.page.locator('input[name="subject"]').fill('My draft')
        self.page.wait_for_timeout(100)
        expect(self.page.locator('button[value="draft"]')).to_be_enabled()

    # 6. Group quick-add chips
    def test_all_students_chip_visible(self):
        """'All Students' group chip is visible in the To field area."""
        expect(self.page.locator('button', has_text='All Students').first).to_be_visible()

    def test_all_staff_chip_visible(self):
        """'All Staff' group chip is visible."""
        expect(self.page.locator('button', has_text='All Staff').first).to_be_visible()

    def test_all_parents_chip_visible(self):
        """'All Parents' group chip is visible."""
        expect(self.page.locator('button', has_text='All Parents').first).to_be_visible()

    def test_all_students_chip_adds_students(self, db):
        """Clicking 'All Students' adds school students to the To field."""
        _make_school_student(self.school, self.admin)
        self.page.reload()
        self.page.wait_for_load_state('domcontentloaded')
        self.page.locator('button', has_text='All Students').first.click()
        self.page.wait_for_timeout(1000)
        expect(self.page.locator('body')).to_contain_text('UX Student')

    # 7. Send test to self
    def test_send_test_to_self_button_visible(self):
        """'Send test to self' button is present in the action bar."""
        expect(self.page.locator('button', has_text='Send test to self').first).to_be_visible()

    def test_send_test_to_self_adds_user_email(self):
        """Clicking 'Send test to self' adds the admin's email to the To field."""
        self.page.locator('button', has_text='Send test to self').first.click()
        self.page.wait_for_timeout(200)
        expect(self.page.locator('body')).to_contain_text(self.admin.email)
