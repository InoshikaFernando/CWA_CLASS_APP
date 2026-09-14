"""Playwright UI test — addressing and writing a promotion from the compose page.

The unit tests prove the recipient lists are right and the copy substitutes
correctly. What only a browser can show is whether the page actually stops the
two mistakes these features exist to prevent:

* **Sending the offer to the families already paying.** The chip has to put the
  unsubscribed students in the To field and leave everyone else out — visibly,
  as tags somebody can read before pressing Send.
* **Sending a template with its blanks still in it.** ``[[CODE]]`` reaching two
  hundred parents is the failure mode of every pre-written message system. The
  Send button must be dead while one remains, and the page must say which.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import _RUN_ID, do_login

pytestmark = pytest.mark.messaging

COMPOSE = '/admin-dashboard/messaging/compose/'


@pytest.fixture
def two_kinds_of_family(db, school):
    """One student who is paying, one who is not — the whole point of the chip."""
    from accounts.models import CustomUser, Role, UserRole
    from billing.models import Package, Subscription
    from classroom.models import ParentStudent, SchoolStudent

    package, _ = Package.objects.get_or_create(
        name=f'Wizard {_RUN_ID}',
        defaults={'price': 19.90, 'stripe_price_id': f'price_ui_msg_{_RUN_ID}'})

    def _role(name):
        role, _ = Role.objects.get_or_create(
            name=name, defaults={'display_name': name.title()})
        return role

    def _student(tag, status):
        user = CustomUser.objects.create_user(
            username=f'{tag}_{_RUN_ID}', password='Testpass1!',
            email=f'{tag}_{_RUN_ID}@test.local', first_name=tag.title(),
            last_name='Student')
        UserRole.objects.create(user=user, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=school, student=user,
                                     is_active=True)
        if status:
            Subscription.objects.create(user=user, package=package,
                                        status=status)
        return user

    lapsed = _student('lapsed', Subscription.STATUS_EXPIRED)
    never = _student('never', None)
    paying = _student('paying', Subscription.STATUS_ACTIVE)

    parent = CustomUser.objects.create_user(
        username=f'parent_{_RUN_ID}', password='Testpass1!',
        email=f'parent_{_RUN_ID}@test.local', first_name='Lapsed',
        last_name='Parent')
    UserRole.objects.create(user=parent, role=_role(Role.PARENT))
    ParentStudent.objects.create(parent=parent, student=lapsed, school=school,
                                 is_active=True)

    yield {'lapsed': lapsed, 'never': never, 'paying': paying,
           'parent': parent}

    for user in (lapsed, never, paying, parent):
        user.delete()


class TestAddressingThePromotion:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, two_kinds_of_family):
        self.page = page
        self.family = two_kinds_of_family
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}{COMPOSE}')
        page.wait_for_load_state('domcontentloaded')

    def _to_field_text(self):
        return self.page.locator('input[name="recipients_to"]').input_value()

    def test_the_chip_adds_the_unsubscribed_students_only(self):
        self.page.get_by_role(
            'button', name='Unsubscribed Students').click()
        self.page.wait_for_timeout(600)

        tags = self._to_field_text()
        assert self.family['lapsed'].email in tags
        assert self.family['never'].email in tags
        assert self.family['paying'].email not in tags, (
            'a paying family was offered a subscription')

    def test_the_parents_chip_adds_the_parent_of_an_unsubscribed_student(self):
        self.page.get_by_role('button', name='Their Parents').click()
        self.page.wait_for_timeout(600)

        assert self.family['parent'].email in self._to_field_text()

    def test_the_all_students_chip_still_includes_everybody(self):
        """The original chip is unchanged — this is an addition, not a filter."""
        self.page.get_by_role('button', name='All Students').click()
        self.page.wait_for_timeout(600)

        assert self.family['paying'].email in self._to_field_text()


class TestWritingFromATemplate:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.page = page
        self.school = school
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}{COMPOSE}')
        page.wait_for_load_state('domcontentloaded')

    def test_the_templates_are_offered(self):
        expect(self.page.get_by_role(
            'button', name='Free trial invitation')).to_be_visible()
        expect(self.page.get_by_role(
            'button', name='Write my own')).to_be_visible()

    def test_picking_one_fills_the_subject_and_body(self):
        self.page.get_by_role('button', name='Free trial invitation').click()
        self.page.wait_for_timeout(300)

        subject = self.page.locator('input[name="subject"]').input_value()
        assert 'Two weeks free' in subject
        assert self.school.name in subject
        expect(self.page.locator('.compose-editor')).to_contain_text(
            'No card details are needed')

    def test_the_filled_in_text_is_still_editable(self):
        """A template is a starting point, not a form."""
        self.page.get_by_role('button', name='Free trial invitation').click()
        self.page.wait_for_timeout(300)

        subject_input = self.page.locator('input[name="subject"]')
        subject_input.fill('My own subject entirely')
        assert subject_input.input_value() == 'My own subject entirely'

    def test_send_is_blocked_while_a_placeholder_is_unfilled(self):
        """The failure this exists to prevent: [[CODE]] reaching real parents."""
        self.page.get_by_role('button', name='Free trial invitation').click()
        self.page.wait_for_timeout(300)

        expect(self.page.locator('button[name="action"][value="send"]')
               ).to_be_disabled()
        expect(self.page.get_by_text('[[CODE]]').first).to_be_visible()

    def test_the_page_names_which_placeholders_are_left(self):
        self.page.get_by_role('button', name='Free trial invitation').click()
        self.page.wait_for_timeout(300)

        warning = self.page.locator('text=before this can be sent')
        expect(warning).to_be_visible()

    def test_write_my_own_starts_from_a_blank_page(self):
        self.page.get_by_role('button', name='Free trial invitation').click()
        self.page.wait_for_timeout(300)
        # Accept the "replace what you have written?" confirm.
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.get_by_role('button', name='Write my own').click()
        self.page.wait_for_timeout(300)

        assert self.page.locator('input[name="subject"]').input_value() == ''
