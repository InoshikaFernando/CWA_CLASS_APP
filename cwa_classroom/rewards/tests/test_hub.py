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

    def test_the_top_student_is_congratulated(self, board):
        _client, response = hub(board[0])
        assert 'keep up the great work' in response.content.decode().lower()

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


class TestNonStudentsAreUnaffected:

    def test_a_teacher_is_redirected_off_the_hub_as_before(self, board):
        teacher = make_student('tina', role_name=Role.TEACHER)
        _client, response = hub(teacher)
        assert response.status_code == 302
