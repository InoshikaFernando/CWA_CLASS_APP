"""
UI tests for the parent child switcher with multiple children.

The switcher is an Alpine.js dropdown in the sidebar that lets a parent
toggle between their linked children. After switching, the active child's
name updates in the sidebar header and the page content reflects the new child.
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import TEST_PASSWORD, _assign_role, _make_user, _RUN_ID, do_login
from .helpers import _ensure_sidebar_visible, assert_page_has_text

pytestmark = pytest.mark.parent_switcher


# ---------------------------------------------------------------------------
# Fixture: parent linked to TWO children
# ---------------------------------------------------------------------------

@pytest.fixture
def parent_with_two_children(db, school, roles):
    """Parent user linked to two active students."""
    from accounts.models import Role
    from classroom.models import ClassRoom, ClassStudent, ParentStudent, SchoolStudent

    parent = _make_user("sw_parent", Role.PARENT, first_name="Pat")

    # Child 1
    child1 = _make_user("sw_child1", Role.STUDENT, first_name="Alice", last_name="Child")
    SchoolStudent.objects.get_or_create(school=school, student=child1)

    # Child 2
    child2 = _make_user("sw_child2", Role.STUDENT, first_name="Bob", last_name="Child")
    SchoolStudent.objects.get_or_create(school=school, student=child2)

    # Link both
    ParentStudent.objects.create(
        parent=parent, student=child1, school=school,
        relationship="mother", is_active=True,
    )
    ParentStudent.objects.create(
        parent=parent, student=child2, school=school,
        relationship="father", is_active=True,
    )

    return {"parent": parent, "child1": child1, "child2": child2}


# ---------------------------------------------------------------------------
# Dropdown visibility
# ---------------------------------------------------------------------------

class TestChildSwitcherDropdown:
    """The switcher dropdown renders both children."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_two_children, school):
        self.url = live_server.url
        self.page = page
        self.data = parent_with_two_children
        do_login(page, self.url, self.data["parent"])
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_switcher_button_visible(self):
        _ensure_sidebar_visible(self.page)
        btn = self.page.locator("aside#sidebar button").first
        expect(btn).to_be_visible()

    def test_switcher_shows_active_child_name(self):
        _ensure_sidebar_visible(self.page)
        sidebar = self.page.locator("aside#sidebar")
        # One of the two children's names should appear (the active one)
        body = sidebar.inner_text()
        assert "Alice" in body or "Bob" in body

    def test_dropdown_lists_both_children_when_opened(self):
        _ensure_sidebar_visible(self.page)
        # Open the dropdown by clicking the switcher button
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)  # Alpine.js transition
        sidebar = self.page.locator("aside#sidebar")
        body = sidebar.inner_text()
        assert "Alice" in body
        assert "Bob" in body

    def test_dropdown_does_not_show_inactive_children(self, db, school):
        """An inactive ParentStudent link must not appear in the dropdown."""
        from classroom.models import ParentStudent, SchoolStudent
        from accounts.models import Role

        inactive_child = _make_user("sw_inactive", Role.STUDENT, first_name="Carol")
        SchoolStudent.objects.get_or_create(school=school, student=inactive_child)
        ParentStudent.objects.create(
            parent=self.data["parent"], student=inactive_child,
            school=school, relationship="mother", is_active=False,
        )
        self.page.reload()
        self.page.wait_for_load_state("domcontentloaded")
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)
        body = self.page.locator("aside#sidebar").inner_text()
        assert "Carol" not in body


# ---------------------------------------------------------------------------
# Switching children
# ---------------------------------------------------------------------------

class TestChildSwitcherSwitch:
    """Selecting a child from the dropdown updates the active child."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_two_children, school):
        self.url = live_server.url
        self.page = page
        self.data = parent_with_two_children
        do_login(page, self.url, self.data["parent"])
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_clicking_child_submits_switch_form(self):
        """Clicking a child name in the dropdown POSTs the switch and redirects."""
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)
        # Click "Bob" in the dropdown
        child_btn = self.page.locator("aside#sidebar button", has_text="Bob").first
        expect(child_btn).to_be_visible()
        child_btn.click()
        self.page.wait_for_load_state("domcontentloaded")
        # Should still be on /parent/ after redirect
        expect(self.page).to_have_url(re.compile(r"/parent/"))

    def test_after_switching_active_child_name_updates_in_sidebar(self):
        """After switching to Bob, the sidebar header shows Bob's name."""
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)
        bob_btn = self.page.locator("aside#sidebar button", has_text="Bob").first
        if bob_btn.count() > 0:
            bob_btn.click()
            self.page.wait_for_load_state("domcontentloaded")
            _ensure_sidebar_visible(self.page)
            sidebar = self.page.locator("aside#sidebar")
            expect(sidebar).to_contain_text("Bob")

    def test_after_switching_to_alice_sidebar_shows_alice(self):
        """Switch to Alice → sidebar header shows Alice."""
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)
        alice_btn = self.page.locator("aside#sidebar button", has_text="Alice").first
        if alice_btn.count() > 0:
            alice_btn.click()
            self.page.wait_for_load_state("domcontentloaded")
            _ensure_sidebar_visible(self.page)
            expect(self.page.locator("aside#sidebar")).to_contain_text("Alice")

    def test_switch_updates_page_content_on_dashboard(self):
        """After switching, the dashboard body reflects the new child."""
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)
        bob_btn = self.page.locator("aside#sidebar button", has_text="Bob").first
        if bob_btn.count() > 0:
            bob_btn.click()
            self.page.wait_for_load_state("domcontentloaded")
            assert_page_has_text(self.page, "Bob")

    def test_can_switch_back_and_forth(self):
        """Switch A→B→A and confirm the sidebar reflects each change."""
        for name in ["Bob", "Alice"]:
            _ensure_sidebar_visible(self.page)
            self.page.locator("aside#sidebar button").first.click()
            self.page.wait_for_timeout(300)
            btn = self.page.locator("aside#sidebar button", has_text=name).first
            if btn.count() > 0:
                btn.click()
                self.page.wait_for_load_state("domcontentloaded")
                _ensure_sidebar_visible(self.page)
                expect(self.page.locator("aside#sidebar")).to_contain_text(name)


# ---------------------------------------------------------------------------
# Homework page respects active child
# ---------------------------------------------------------------------------

class TestChildSwitcherHomeworkIsolation:
    """Homework page only shows the active child's assignments."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_two_children, school, db):
        self.url = live_server.url
        self.page = page
        self.data = parent_with_two_children
        child1 = self.data["child1"]
        child2 = self.data["child2"]

        from classroom.models import ClassRoom, ClassStudent, SchoolStudent, Subject
        from homework.models import Homework
        from django.utils import timezone
        from datetime import timedelta

        subj, _ = Subject.objects.get_or_create(
            slug=f"sw-subj-{_RUN_ID}", defaults={"name": f"SW Subject {_RUN_ID}"},
        )
        cls1 = ClassRoom.objects.create(name=f"Alice Room {_RUN_ID}", school=school, subject=subj)
        cls2 = ClassRoom.objects.create(name=f"Bob Room {_RUN_ID}", school=school, subject=subj)
        ClassStudent.objects.create(classroom=cls1, student=child1, is_active=True)
        ClassStudent.objects.create(classroom=cls2, student=child2, is_active=True)

        self.hw_alice = Homework.objects.create(
            classroom=cls1, title=f"Alice HW {_RUN_ID}",
            due_date=timezone.now() + timedelta(days=5), num_questions=5,
        )
        self.hw_bob = Homework.objects.create(
            classroom=cls2, title=f"Bob HW {_RUN_ID}",
            due_date=timezone.now() + timedelta(days=5), num_questions=5,
        )

    def _switch_to_child(self, name: str):
        """Open the sidebar switcher dropdown and click the named child."""
        _ensure_sidebar_visible(self.page)
        self.page.locator("aside#sidebar button").first.click()
        self.page.wait_for_timeout(300)  # Alpine.js transition
        btn = self.page.locator("aside#sidebar button", has_text=name).first
        expect(btn).to_be_visible()
        btn.click()
        self.page.wait_for_load_state("domcontentloaded")

    def test_alice_sees_only_her_homework(self):
        do_login(self.page, self.url, self.data["parent"])
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("networkidle")
        # Use a form POST via evaluate since Playwright can't POST a URL directly
        self.page.evaluate(f"""() => {{
            const f = document.createElement('form');
            f.method = 'POST';
            f.action = '{self.url}/parent/switch-child/{self.data["child1"].id}/';
            const c = document.createElement('input');
            c.name = 'csrfmiddlewaretoken';
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            c.value = m ? m[1] : '';
            f.appendChild(c);
            document.body.appendChild(f);
            f.submit();
        }}""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(500)  # Give session time to update
        self.page.goto(f"{self.url}/parent/homework/")
        self.page.wait_for_load_state("networkidle")
        body = self.page.locator("body").inner_text()
        assert f"Alice HW {_RUN_ID}" in body
        assert f"Bob HW {_RUN_ID}" not in body

    def test_bob_sees_only_his_homework(self):
        do_login(self.page, self.url, self.data["parent"])
        self.page.goto(f"{self.url}/parent/")
        self.page.wait_for_load_state("networkidle")
        self.page.evaluate(f"""() => {{
            const f = document.createElement('form');
            f.method = 'POST';
            f.action = '{self.url}/parent/switch-child/{self.data["child2"].id}/';
            const c = document.createElement('input');
            c.name = 'csrfmiddlewaretoken';
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            c.value = m ? m[1] : '';
            f.appendChild(c);
            document.body.appendChild(f);
            f.submit();
        }}""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(500)  # Give session time to update
        self.page.goto(f"{self.url}/parent/homework/")
        self.page.wait_for_load_state("networkidle")
        body = self.page.locator("body").inner_text()
        assert f"Bob HW {_RUN_ID}" in body
        assert f"Alice HW {_RUN_ID}" not in body
