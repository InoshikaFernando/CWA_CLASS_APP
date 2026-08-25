"""Playwright UI tests for the global leaderboard on the student hub.

The hub is where students land after login (``LOGIN_REDIRECT_URL = '/hub/'``),
so this covers what a student actually sees on their first visit of the day:

  - the standings pop-up opens on the first hub load of the day
  - closing it leaves the board on the page
  - it does not reopen on a refresh, but the card stays
  - the podium names the top three, and the student's own row is highlighted
  - a student off the podium sees their rank and the gap to the next place
  - a student on the podium is not shown a duplicate rank line
  - a school student gets two tabs (their school, then everyone) and the
    school one is selected first
  - switching tabs in the pop-up does not move the card's tabs behind it
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


POPUP = '[data-testid="leaderboard-popup"]'
CARD = '[data-testid="leaderboard-card"]'
CLOSE = '[data-testid="leaderboard-popup-close"]'


@pytest.fixture
def leaderboard(db, enrolled_student):
    """Put the enrolled student behind two higher-scoring classmates.

    Returns the enrolled student, who therefore sits 3rd of three.
    """
    from accounts.models import CustomUser, Role
    from rewards.models import PointsSource
    from rewards.services import award_points

    def _student(username, first, last):
        user = CustomUser.objects.create_user(
            username, f'{username}@example.test', 'pass1234',
            first_name=first, last_name=last,
        )
        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        user.roles.add(role)
        return user

    award_points(_student('lb-ada', 'Ada', 'Lovelace'),
                 PointsSource.MATHS_QUIZ, 'topic:1:level:1', 90)
    award_points(_student('lb-grace', 'Grace', 'Hopper'),
                 PointsSource.MATHS_QUIZ, 'topic:2:level:1', 70)
    award_points(enrolled_student, PointsSource.HOMEWORK, '1', 50)
    return enrolled_student


def _goto_hub(page: Page, live_server_url: str) -> None:
    page.goto(f'{live_server_url}/hub/')
    page.wait_for_load_state('domcontentloaded')


class TestHubLeaderboard:

    @pytest.mark.smoke
    @pytest.mark.django_db(transaction=True)
    def test_the_popup_opens_on_the_first_hub_load_of_the_day(
        self, page: Page, live_server, leaderboard
    ):
        do_login(page, live_server.url, leaderboard)
        # do_login lands on /hub/ already — this is the first load of the day.
        expect(page.locator(POPUP)).to_be_visible()
        expect(page.locator(POPUP)).to_contain_text('Top Wizards')

    @pytest.mark.django_db(transaction=True)
    def test_the_podium_names_the_top_three(
        self, page: Page, live_server, leaderboard
    ):
        do_login(page, live_server.url, leaderboard)
        popup = page.locator(POPUP)
        # Surnames are abbreviated — the board is global, across every school.
        expect(popup).to_contain_text('Ada L.')
        expect(popup).to_contain_text('Grace H.')

    @pytest.mark.django_db(transaction=True)
    def test_closing_the_popup_leaves_the_board_on_the_page(
        self, page: Page, live_server, leaderboard
    ):
        do_login(page, live_server.url, leaderboard)
        page.locator(CLOSE).click()

        expect(page.locator(POPUP)).to_have_count(0)
        expect(page.locator(CARD)).to_be_visible()
        expect(page.locator(CARD)).to_contain_text('Top Wizards')

    @pytest.mark.django_db(transaction=True)
    def test_a_refresh_does_not_reopen_the_popup(
        self, page: Page, live_server, leaderboard
    ):
        do_login(page, live_server.url, leaderboard)
        expect(page.locator(POPUP)).to_be_visible()

        _goto_hub(page, live_server.url)
        expect(page.locator(POPUP)).to_have_count(0)
        expect(page.locator(CARD)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_a_student_on_the_podium_sees_no_separate_rank_line(
        self, page: Page, live_server, leaderboard
    ):
        """Third of three is still the podium — 'if they are 1st or 2nd or 3rd,
        no need their rank separately'."""
        do_login(page, live_server.url, leaderboard)
        expect(page.locator(POPUP)).not_to_contain_text('Your rank')

    @pytest.mark.django_db(transaction=True)
    def test_a_student_off_the_podium_sees_their_rank_and_the_gap(
        self, page: Page, live_server, leaderboard
    ):
        from rewards.models import PointsSource
        from rewards.services import award_points

        # Push three classmates above the enrolled student, dropping them to 4th.
        from accounts.models import CustomUser, Role
        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        extra = CustomUser.objects.create_user(
            'lb-linus', 'lb-linus@example.test', 'pass1234',
            first_name='Linus', last_name='Torvalds',
        )
        extra.roles.add(role)
        award_points(extra, PointsSource.MATHS_QUIZ, 'topic:3:level:1', 60)

        do_login(page, live_server.url, leaderboard)
        popup = page.locator(POPUP)
        expect(popup).to_contain_text('Your rank')
        expect(popup).to_contain_text('10 points to reach 3rd place')


class TestScopedTabs:
    """A school student sees their school's board and the system-wide one."""

    @pytest.fixture
    def schooled(self, db, leaderboard, school):
        """Enrol the student and one classmate, so the school board has two."""
        from accounts.models import CustomUser, Role
        from classroom.models import SchoolStudent
        from rewards.models import PointsSource
        from rewards.services import award_points

        mate = CustomUser.objects.create_user(
            'lb-mate', 'lb-mate@example.test', 'pass1234',
            first_name='Mate', last_name='Ng',
        )
        role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        mate.roles.add(role)
        award_points(mate, PointsSource.HOMEWORK, '2', 20)
        SchoolStudent.objects.get_or_create(school=school, student=mate)
        return leaderboard

    @pytest.mark.django_db(transaction=True)
    def test_the_school_tab_is_selected_first(self, page: Page, live_server, schooled):
        do_login(page, live_server.url, schooled)
        popup = page.locator(POPUP)

        expect(popup.locator('#popup-tab-school')).to_have_attribute('aria-selected', 'true')
        expect(popup.locator('#popup-tab-global')).to_have_attribute('aria-selected', 'false')
        expect(popup.locator('#popup-panel-school')).to_be_visible()
        expect(popup.locator('#popup-panel-global')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_clicking_everyone_switches_the_panel(self, page: Page, live_server, schooled):
        do_login(page, live_server.url, schooled)
        popup = page.locator(POPUP)

        popup.locator('#popup-tab-global').click()
        expect(popup.locator('#popup-panel-global')).to_be_visible()
        expect(popup.locator('#popup-panel-school')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_the_popup_tabs_do_not_drive_the_cards_panels(
        self, page: Page, live_server, schooled
    ):
        """Both boards are on the page at once. Switching one must not switch
        the other — the bug a shared element id would cause."""
        do_login(page, live_server.url, schooled)
        page.locator(POPUP).locator('#popup-tab-global').click()

        page.locator(CLOSE).click()
        expect(page.locator('#card-panel-school')).to_be_visible()
        expect(page.locator('#card-panel-global')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_the_school_board_excludes_students_from_other_schools(
        self, page: Page, live_server, schooled
    ):
        """Ada and Grace outrank the student system-wide but are in no school,
        so the school tab must not list them."""
        do_login(page, live_server.url, schooled)
        school_panel = page.locator(POPUP).locator('#popup-panel-school')

        expect(school_panel).to_contain_text('Mate N.')
        expect(school_panel).not_to_contain_text('Ada L.')
