"""The "Subscribed only" chip on Manage Students.

The chip is a link, not a form control, so the thing worth driving in a browser
is that it survives the page's HTMX: the students panel is swapped on every
keystroke and every sort click, and a filter dropped by one of those swaps
would quietly widen the list while the chip still reads as active.
"""

import re

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.subscribed_filter


@pytest.fixture
def subscribed_and_not(db, school, enrolled_student):
    """Two more students: one subscribed, one whose subscription is cancelled."""
    from billing.models import Subscription
    from classroom.models import SchoolStudent

    from ..conftest import _make_user
    from accounts.models import Role

    made = {}
    for key, status, first in (
        ('subscribed', Subscription.STATUS_ACTIVE, 'Subbed'),
        ('lapsed', Subscription.STATUS_CANCELLED, 'Lapsed'),
    ):
        user = _make_user(f'ui_{key}_stu', Role.STUDENT, first_name=first,
                          last_name='Student')
        SchoolStudent.objects.get_or_create(school=school, student=user)
        Subscription.objects.create(user=user, status=status)
        made[key] = user
    # ``enrolled_student`` deliberately keeps no subscription row at all.
    made['none'] = enrolled_student
    return made


class TestSubscribedChip:
    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, subscribed_and_not):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.students = subscribed_and_not
        do_login(page, self.url, admin_user)

    def _open(self, query=''):
        self.page.goto(
            f'{self.url}/admin-dashboard/schools/{self.school.id}/students/{query}'
        )
        self.page.wait_for_load_state('networkidle')

    def _usernames(self):
        return self.page.locator('#students-panel').inner_text()

    def test_the_chip_is_offered(self):
        self._open()
        expect(self.page.locator('[data-testid="subscribed-filter"]')).to_be_visible()

    def test_clicking_it_narrows_the_list(self):
        self._open()
        assert self.students['lapsed'].username in self._usernames()

        self.page.locator('[data-testid="subscribed-filter"]').click()
        self.page.wait_for_load_state('networkidle')

        expect(self.page).to_have_url(re.compile(r'subscribed=1'))
        listed = self._usernames()
        assert self.students['subscribed'].username in listed
        assert self.students['lapsed'].username not in listed
        assert self.students['none'].username not in listed

    def test_clicking_it_again_restores_everyone(self):
        self._open('?subscribed=1')
        self.page.locator('[data-testid="subscribed-filter"]').click()
        self.page.wait_for_load_state('networkidle')

        assert self.students['lapsed'].username in self._usernames()

    def test_the_search_keeps_the_filter(self):
        """The HTMX swap replaces the panel only, so the flag has to survive
        outside it — otherwise typing quietly un-filters the list."""
        self._open('?subscribed=1')
        self.page.locator("input[name='q'][hx-target='#students-panel']").fill('Student')
        self.page.wait_for_load_state('networkidle')
        self.page.wait_for_timeout(600)

        listed = self._usernames()
        assert self.students['subscribed'].username in listed
        assert self.students['lapsed'].username not in listed

    def test_sorting_keeps_the_filter(self):
        self._open('?subscribed=1')
        self.page.get_by_role('button', name='Email').click()
        self.page.wait_for_load_state('networkidle')
        self.page.wait_for_timeout(600)

        listed = self._usernames()
        assert self.students['subscribed'].username in listed
        assert self.students['lapsed'].username not in listed

    def test_the_count_stops_calling_itself_the_total(self):
        self._open('?subscribed=1')
        expect(self.page.locator('text=Subscribed Students')).to_be_visible()
