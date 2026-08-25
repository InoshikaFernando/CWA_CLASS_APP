"""The leaderboard on the student hub — the card and the once-a-day pop-up."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from rewards.models import PointsSource, StudentPointsTotal
from rewards.services import award_points

from .factories import make_student


pytestmark = pytest.mark.django_db


@pytest.fixture
def board(db):
    """Three students with points, best first."""
    students = []
    for i, (name, score) in enumerate(
        [('Ada', 90), ('Grace', 70), ('Linus', 50)]
    ):
        student = make_student(name.lower(), first_name=name, last_name=f'Sur{i}')
        award_points(student, PointsSource.MATHS_QUIZ, f'topic:{i}:level:1', score)
        students.append(student)
    return students


def hub(student):
    client = Client()
    client.force_login(student)
    return client, client.get(reverse('subjects_hub'))


class TestHubLeaderboardCard:

    def test_the_podium_is_on_the_page(self, board):
        _client, response = hub(board[0])
        body = response.content.decode()

        assert response.status_code == 200
        assert 'Top Wizards' in body
        for name in ('Ada S.', 'Grace S.', 'Linus S.'):
            assert name in body

    def test_the_top_student_is_congratulated_for_the_right_scope(self, board):
        """These students are in no school, so the only board is system-wide —
        the winner's line must say so rather than claiming a school."""
        _client, response = hub(board[0])
        body = response.content.decode()

        assert 'every school on the system' in body
        assert 'your whole school' not in body

    def test_a_student_off_the_podium_sees_their_rank_and_the_gap(self, board):
        fourth = make_student('newcomer', first_name='Nia')
        award_points(fourth, PointsSource.HOMEWORK, '1', 30)

        _client, response = hub(fourth)
        body = response.content.decode()

        assert 'Your rank' in body
        assert '20 points to reach 3rd place' in body

    def test_a_podium_student_is_not_shown_a_separate_rank_line(self, board):
        """'If they are 1st or 2nd or 3rd, no need their rank separately.'"""
        for student in board:
            _client, response = hub(student)
            assert 'Your rank' not in response.content.decode()

    def test_a_student_with_no_points_is_invited_to_start(self, board):
        _client, response = hub(make_student('quiet'))
        body = response.content.decode()

        assert 'Your rank' not in body
        assert 'get on the board' in body

    def test_the_card_is_hidden_while_nobody_has_points(self):
        _client, response = hub(make_student('first-ever'))
        assert 'Top Wizards' not in response.content.decode()


class TestDailyPopup:

    def test_it_opens_on_the_first_hub_load_of_the_day(self, board):
        _client, response = hub(board[0])
        assert 'leaderboard-popup' in response.content.decode()

    def test_it_does_not_reopen_on_a_refresh(self, board):
        client, first = hub(board[0])
        assert 'leaderboard-popup' in first.content.decode()

        again = client.get(reverse('subjects_hub'))
        assert 'leaderboard-popup' not in again.content.decode()

    def test_the_card_stays_after_the_popup_is_done_for_the_day(self, board):
        """The pop-up is once a day; the board itself is always available."""
        client, _first = hub(board[0])
        again = client.get(reverse('subjects_hub'))
        assert 'Top Wizards' in again.content.decode()

    def test_it_opens_again_the_next_day(self, board):
        client, _first = hub(board[0])
        StudentPointsTotal.objects.filter(student=board[0]).update(
            leaderboard_shown_on=timezone.localdate() - timezone.timedelta(days=1),
        )
        again = client.get(reverse('subjects_hub'))
        assert 'leaderboard-popup' in again.content.decode()


class TestScopedBoards:

    @pytest.fixture
    def schooled(self, db, board):
        """Put the third-placed student into a school with one classmate."""
        from classroom.models import School, SchoolStudent

        school = School.objects.create(
            name='Wizards', slug='wizards', admin=make_student('adm', Role.ADMIN),
        )
        me = board[2]
        classmate = make_student('mate', first_name='Mate', last_name='Ng')
        award_points(classmate, PointsSource.HOMEWORK, '1', 20)
        for student in (me, classmate):
            SchoolStudent.objects.create(school=school, student=student, is_active=True)
        return me

    def test_both_tabs_render_for_a_school_student(self, schooled):
        _client, response = hub(schooled)
        body = response.content.decode()

        assert 'Wizards' in body       # the school tab
        assert 'Everyone' in body      # the system-wide tab

    def test_the_school_tab_comes_first(self, schooled):
        _client, response = hub(schooled)
        body = response.content.decode()
        assert body.index('card-tab-school') < body.index('card-tab-global')

    def test_the_student_ranks_higher_in_their_school(self, schooled):
        """3rd of five system-wide, 1st of two at school."""
        from rewards.services import get_standings
        school_standing, global_standing = get_standings(schooled)

        assert school_standing.rank == 1
        assert global_standing.rank == 3

    def test_topping_the_school_board_does_not_claim_the_system(self, schooled):
        _client, response = hub(schooled)
        assert 'your whole school' in response.content.decode()

    def test_a_student_with_no_school_gets_no_tab_strip(self, board):
        _client, response = hub(board[0])
        body = response.content.decode()

        assert 'role="tablist"' not in body
        assert 'Top Wizards' in body

    def test_the_card_and_popup_do_not_share_element_ids(self, schooled):
        """Both copies are on the page at once — a shared id would make the
        pop-up's tabs drive the card's panels."""
        _client, response = hub(schooled)
        body = response.content.decode()

        for scope in ('school', 'global'):
            assert body.count(f'id="card-panel-{scope}"') == 1
            assert body.count(f'id="popup-panel-{scope}"') == 1


class TestNonStudentsAreUnaffected:

    def test_a_teacher_is_redirected_off_the_hub_as_before(self, board):
        teacher = make_student('tina', role_name=Role.TEACHER)
        _client, response = hub(teacher)
        assert response.status_code == 302
