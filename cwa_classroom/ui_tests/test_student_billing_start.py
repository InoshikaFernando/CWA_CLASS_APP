"""UI tests for CPP-342 — editable per-student billing start date on class detail."""

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.invoice


class TestStudentBillingStart:
    """/class/<id>/ — HoI can view and edit a student's billing start date."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department,
               classroom, enrolled_student, school):
        # ClassDetailView requires the HoI to be the school's admin.
        school.admin = hoi_user
        school.save(update_fields=["admin"])
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        do_login(page, self.url, hoi_user)

    def _goto_class(self):
        self.page.goto(f"{self.url}/class/{self.classroom.id}/")
        self.page.wait_for_load_state("domcontentloaded")

    def _class_student(self):
        from classroom.models import ClassStudent
        return ClassStudent.objects.get(classroom=self.classroom, student=self.student)

    def test_start_date_button_visible(self):
        self._goto_class()
        expect(self.page.get_by_role("button", name="Start date").first).to_be_visible()

    def test_existing_date_displayed(self):
        import datetime
        cs = self._class_student()
        cs.billing_start_date = datetime.date(2026, 5, 15)
        cs.save(update_fields=["billing_start_date"])
        self._goto_class()
        assert_page_has_text(self.page, "bills from")

    def test_set_billing_start_date(self):
        self._goto_class()
        self.page.get_by_role("button", name="Start date").first.click()
        date_input = self.page.locator("input[name='billing_start_date']").first
        expect(date_input).to_be_visible()
        date_input.fill("2026-06-01")
        self.page.locator("form[action*='billing-start'] button[type='submit']").first.click()
        self.page.wait_for_load_state("domcontentloaded")
        # Persisted to the model.
        assert str(self._class_student().billing_start_date) == "2026-06-01"
