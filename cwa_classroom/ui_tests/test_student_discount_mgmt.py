"""UI test — HoI/admin sees student discount state and the Clear control (CPP-XXX)."""
from decimal import Decimal

import pytest

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.dashboard


class TestStudentDiscountManagement:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        from accounts.models import CustomUser, Role
        from billing.models import Package, Subscription
        from classroom.models import SchoolStudent

        self.url = live_server.url
        self.page = page

        student = CustomUser.objects.create_user(
            'disc_student', 'disc_student@t.com', 'pass1234', profile_completed=True,
        )
        student.roles.add(Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})[0])
        SchoolStudent.objects.create(school=school, student=student, is_active=True)
        pkg = Package.objects.create(name='Wizard UI', price=Decimal('19.90'), stripe_price_id='price_ui')
        Subscription.objects.create(
            user=student, package=pkg,
            status=Subscription.STATUS_ACTIVE, discount_percent_snapshot=100,
        )
        self.student = student
        self.school = school
        do_login(page, self.url, admin_user)

    def test_discount_badge_and_clear_control_present(self):
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/students/")
        self.page.wait_for_load_state("domcontentloaded")
        # The 100%-off (free, no payment) badge shows in the always-visible row.
        assert_page_has_text(self.page, "100% off")
        # The Clear-discount control points at the clear endpoint (in the DOM,
        # inside the collapsible edit panel).
        clear_url = f"/admin-dashboard/schools/{self.school.id}/students/{self.student.id}/clear-discount/"
        assert clear_url in self.page.content()
