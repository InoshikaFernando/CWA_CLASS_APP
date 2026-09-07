"""The "Subscribed students only" filter on the report preview page.

Driven in a browser because the risk here is a mismatch between what staff read
and what the send does: the checkbox has to come back ticked, and the hidden
field it puts into the send form is what stops "Generate and send" mailing the
families the reader just filtered out.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import _make_user, do_login

pytestmark = pytest.mark.subscribed_filter

PREVIEW_URL = '/progress/reports/preview/'


def _enable_weekly(school):
    from progress import report_settings

    fields = (
        report_settings.PERIOD_FIELDS
        + report_settings.DELIVERY_FIELDS
        + report_settings.SCHEDULE_FIELDS
        + report_settings.CONTENT_FIELDS
        + ('mode',)
    )
    values = {field: None for field in fields}
    values['weekly'] = True
    report_settings.set_for(school, 'school', school, values)


@pytest.fixture
def preview_scope(db, school, classroom, enrolled_student):
    """A weekly-enabled class holding a subscribed and an unsubscribed student."""
    from accounts.models import Role
    from billing.models import Subscription
    from classroom.models import ClassStudent, SchoolStudent

    _enable_weekly(school)

    subscribed = _make_user(
        'ui_prev_subbed', Role.STUDENT, first_name='Subbed', last_name='Kid',
    )
    SchoolStudent.objects.get_or_create(school=school, student=subscribed)
    ClassStudent.objects.create(
        classroom=classroom, student=subscribed, is_active=True,
    )
    Subscription.objects.create(
        user=subscribed, status=Subscription.STATUS_ACTIVE,
    )
    # ``enrolled_student`` has no subscription, so it is the one the filter drops.
    return {'subscribed': subscribed, 'unsubscribed': enrolled_student}


class TestPreviewSubscribedFilter:
    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, preview_scope):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.students = preview_scope
        do_login(page, self.url, admin_user)

    def _open(self, query=''):
        self.page.goto(f'{self.url}{PREVIEW_URL}?school={self.school.id}{query}')
        self.page.wait_for_load_state('networkidle')

    def _names(self):
        return self.page.locator('[data-testid="report-preview"]').inner_text()

    def _full_name(self, key):
        return self.students[key].get_full_name()

    def test_unfiltered_lists_both_students(self):
        self._open()

        listed = self._names()
        assert self._full_name('subscribed') in listed
        assert self._full_name('unsubscribed') in listed

    def test_ticking_the_box_drops_the_unsubscribed_student(self):
        self._open()
        self.page.locator('[data-testid="preview-subscribed"]').check()
        self.page.get_by_role('button', name='Preview').click()
        self.page.wait_for_load_state('networkidle')

        listed = self._names()
        assert self._full_name('subscribed') in listed
        assert self._full_name('unsubscribed') not in listed

    def test_the_box_comes_back_ticked(self):
        """An unticked box over a filtered table would read as the school
        having lost a student."""
        self._open('&subscribed=1')

        expect(self.page.locator('[data-testid="preview-subscribed"]')).to_be_checked()
        expect(
            self.page.locator('[data-testid="preview-subscribed-note"]')
        ).to_be_visible()

    def test_the_send_form_carries_the_filter(self):
        """The load-bearing one: without this field the send covers everybody
        while the page on screen shows a narrower list."""
        self._open('&subscribed=1')

        hidden = self.page.locator(
            'form[method="post"] input[name="subscribed"]'
        )
        assert hidden.count() == 1
        assert hidden.first.get_attribute('value') == '1'

    def test_unticking_it_widens_the_scope_again(self):
        self._open('&subscribed=1')
        self.page.locator('[data-testid="preview-subscribed"]').uncheck()
        self.page.get_by_role('button', name='Preview').click()
        self.page.wait_for_load_state('networkidle')

        assert self._full_name('unsubscribed') in self._names()
