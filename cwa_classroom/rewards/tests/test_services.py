"""The points ledger: awarding, totalling and ranking."""

import pytest
from django.utils import timezone

from accounts.models import Role
from rewards.models import PointsAward, PointsSource, StudentPointsTotal
from rewards.services import (
    POINTS_PER_UNIT, award_points, award_points_safe, get_rank,
    get_student_standing, normalise, recalculate_total, should_show_daily_popup,
)

from .factories import make_student


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# normalise()
# ---------------------------------------------------------------------------

class TestNormalise:

    def test_scales_a_fraction_onto_the_shared_scale(self):
        assert normalise(7, 10) == 70.0
        assert normalise(10, 10) == POINTS_PER_UNIT

    def test_a_brainbuzz_session_cannot_outweigh_a_homework(self):
        """The whole point of normalising: BrainBuzz scores run to 1000 a
        question, so a perfect 5-question session must land on 100, not 5000."""
        assert normalise(5000, 5000) == POINTS_PER_UNIT

    @pytest.mark.parametrize('total', [0, None, ''])
    def test_a_missing_total_scores_zero_rather_than_dividing_by_zero(self, total):
        assert normalise(5, total) == 0.0

    def test_a_score_above_its_total_is_clamped(self):
        assert normalise(15, 10) == POINTS_PER_UNIT


# ---------------------------------------------------------------------------
# award_points()
# ---------------------------------------------------------------------------

class TestAwardPoints:

    def test_a_first_award_creates_the_row_and_the_total(self):
        student = make_student('alice')
        total = award_points(student, PointsSource.HOMEWORK, '1', 80)

        assert total == 80.0
        assert PointsAward.objects.get(student=student).points == 80.0
        assert StudentPointsTotal.objects.get(student=student).units_completed == 1

    def test_different_units_add_up(self):
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 80)
        award_points(student, PointsSource.CODING_PROBLEM, '1', 50)
        total = award_points(student, PointsSource.WORKSHEET, '1', 30)

        assert total == 160.0
        assert StudentPointsTotal.objects.get(student=student).units_completed == 3

    def test_points_are_awarded_regardless_of_subject_topic_or_year(self):
        """Every source lands in the same total — the requirement the whole
        ledger exists for."""
        student = make_student('alice')
        for source in PointsSource.values:
            award_points(student, source, 'unit-1', 10)

        total = StudentPointsTotal.objects.get(student=student)
        assert total.units_completed == len(PointsSource.values)
        assert total.total_points == 10.0 * len(PointsSource.values)

    def test_replaying_the_same_unit_does_not_inflate_the_total(self):
        """A double-clicked submit, or a homework re-graded twice, must not pay
        twice for one piece of work."""
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 80)
        total = award_points(student, PointsSource.HOMEWORK, '1', 80)

        assert total == 80.0
        assert PointsAward.objects.filter(student=student).count() == 1

    def test_a_better_attempt_raises_the_unit(self):
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 60)
        assert award_points(student, PointsSource.HOMEWORK, '1', 90) == 90.0

    def test_a_worse_attempt_never_costs_points_already_earned(self):
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 90)
        assert award_points(student, PointsSource.HOMEWORK, '1', 20) == 90.0

    def test_points_are_clamped_to_one_unit_of_work(self):
        student = make_student('alice')
        assert award_points(student, PointsSource.HOMEWORK, '1', 5000) == POINTS_PER_UNIT
        assert award_points(student, PointsSource.HOMEWORK, '2', -20) == POINTS_PER_UNIT

    def test_an_unknown_source_is_loud(self):
        """A mistyped source means that activity is silently earning nothing —
        exactly the failure mode the repo's no-silent-failure rule forbids."""
        student = make_student('alice')
        with pytest.raises(ValueError):
            award_points(student, 'not_a_source', '1', 10)

    def test_an_anonymous_player_is_ignored_not_an_error(self):
        assert award_points(None, PointsSource.BRAINBUZZ, '1', 10) == 0.0

    def test_a_label_is_refreshed_without_touching_the_score(self):
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 80, label='Old title')
        award_points(student, PointsSource.HOMEWORK, '1', 10, label='New title')

        award = PointsAward.objects.get(student=student)
        assert award.label == 'New title'
        assert award.points == 80.0

    def test_a_teacher_earns_points_but_is_kept_off_the_board(self):
        """A teacher previewing a quiz must not displace a child from the
        podium."""
        teacher = make_student('tina', role_name=Role.TEACHER)
        award_points(teacher, PointsSource.MATHS_QUIZ, 'topic:1:level:1', 100)

        row = StudentPointsTotal.objects.get(student=teacher)
        assert row.total_points == 100.0
        assert row.is_ranked is False

    def test_an_individual_student_is_ranked(self):
        student = make_student('ivan', role_name=Role.INDIVIDUAL_STUDENT)
        award_points(student, PointsSource.MATHS_QUIZ, 'topic:1:level:1', 50)
        assert StudentPointsTotal.objects.get(student=student).is_ranked is True


class TestAwardPointsSafe:

    def test_a_broken_award_never_breaks_the_students_submission(self, caplog):
        student = make_student('alice')
        award_points_safe(student, 'not_a_source', '1', 10)   # would raise
        assert not PointsAward.objects.filter(student=student).exists()

    def test_the_failure_is_logged_rather_than_swallowed(self, caplog):
        student = make_student('alice')
        with caplog.at_level('ERROR', logger='rewards.services'):
            award_points_safe(student, 'not_a_source', '1', 10)
        assert 'Failed to award' in caplog.text


class TestRecalculateTotal:

    def test_a_drifted_total_is_repaired_from_the_ledger(self):
        student = make_student('alice')
        award_points(student, PointsSource.HOMEWORK, '1', 80)
        StudentPointsTotal.objects.filter(student=student).update(total_points=999)

        assert recalculate_total(student) == 80.0

    def test_a_student_with_no_activity_gets_a_zero_row(self):
        student = make_student('alice')
        assert recalculate_total(student) == 0.0
        assert StudentPointsTotal.objects.get(student=student).total_points == 0.0


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _board(*scores):
    """Create one student per score and return them, best first."""
    students = []
    for i, score in enumerate(scores):
        student = make_student(f'student{i}', first_name=f'Name{i}', last_name=f'Sur{i}')
        award_points(student, PointsSource.MATHS_QUIZ, 'topic:1:level:1', score)
        students.append(student)
    return students


class TestRank:

    def test_the_best_score_is_first(self):
        _board(90, 50, 10)
        assert get_rank(90) == 1

    def test_rank_counts_everyone_above(self):
        _board(90, 50, 10)
        assert get_rank(50) == 2
        assert get_rank(10) == 3

    def test_ties_share_a_rank_and_the_next_place_skips(self):
        """Standard competition ranking: two joint 2nds are followed by 4th."""
        _board(90, 50, 50, 10)
        assert get_rank(50) == 2
        assert get_rank(10) == 4

    def test_a_student_with_no_points_has_no_rank(self):
        _board(90, 50)
        assert get_rank(0) == 0


class TestStanding:

    def test_the_podium_is_the_top_three_in_order(self):
        _board(90, 70, 50, 30)
        standing = get_student_standing(make_student('watcher'))

        assert [row['rank'] for row in standing.podium] == [1, 2, 3]
        assert [row['points'] for row in standing.podium] == [90.0, 70.0, 50.0]

    def test_the_student_is_marked_on_their_own_podium_row(self):
        top, _second = _board(90, 70)
        standing = get_student_standing(top)

        assert standing.podium[0]['is_me'] is True
        assert standing.podium[1]['is_me'] is False

    def test_a_podium_student_is_not_shown_a_separate_rank_line(self):
        """'If they are 1st or 2nd or 3rd, no need their rank separately.'"""
        students = _board(90, 70, 50, 30)
        for student in students[:3]:
            assert get_student_standing(student).show_own_rank is False

    def test_a_student_off_the_podium_is_shown_their_rank(self):
        fourth = _board(90, 70, 50, 30)[3]
        standing = get_student_standing(fourth)

        assert standing.rank == 4
        assert standing.show_own_rank is True

    def test_the_top_student_is_congratulated_not_chased(self):
        top = _board(90, 70)[0]
        standing = get_student_standing(top)

        assert standing.rank == 1
        assert 'keep up the great work' in standing.message.lower()
        assert 'points to reach' not in standing.message.lower()

    def test_everyone_else_is_told_the_gap_to_the_next_place(self):
        second = _board(90, 70)[1]
        standing = get_student_standing(second)

        assert standing.points_to_next == 20.0
        assert standing.next_rank == 1
        assert '20 points to reach 1st place' in standing.message

    def test_the_gap_is_measured_to_the_nearest_score_above_not_the_top(self):
        """Through a block of ties, the score to beat is the lowest one still
        above the student — that is what actually moves them up."""
        fourth = _board(90, 70, 70, 30)[3]
        standing = get_student_standing(fourth)

        assert standing.points_to_next == 40.0
        assert standing.next_rank == 2

    def test_a_student_with_no_points_is_invited_rather_than_ranked(self):
        _board(90, 70)
        standing = get_student_standing(make_student('newbie'))

        assert standing.rank == 0
        assert standing.show_own_rank is False
        assert 'get on the board' in standing.message

    def test_an_empty_board_hides_the_card(self):
        standing = get_student_standing(make_student('alice'))
        assert standing.has_board is False

    def test_a_teacher_never_appears_on_the_podium(self):
        teacher = make_student('tina', role_name=Role.TEACHER, first_name='Tina')
        award_points(teacher, PointsSource.MATHS_QUIZ, 'topic:1:level:1', 100)
        student = _board(10)[0]

        standing = get_student_standing(student)
        assert [row['name'] for row in standing.podium] == ['Name0 S.']
        assert standing.rank == 1

    def test_board_size_counts_only_students_with_points(self):
        _board(90, 70)
        make_student('idle')
        assert get_student_standing(make_student('watcher')).board_size == 2


class TestDisplayName:

    def test_a_global_board_shows_a_first_name_and_last_initial(self):
        """The board spans every school and country, so it must not name a
        child in full to strangers."""
        student = make_student('alice', first_name='Alice', last_name='Wanjiru')
        award_points(student, PointsSource.HOMEWORK, '1', 10)
        assert StudentPointsTotal.objects.get(student=student).display_name == 'Alice W.'

    def test_a_student_with_no_surname_shows_their_first_name(self):
        student = make_student('bob', first_name='Bob')
        award_points(student, PointsSource.HOMEWORK, '1', 10)
        assert StudentPointsTotal.objects.get(student=student).display_name == 'Bob'

    def test_a_student_with_no_name_at_all_falls_back_to_the_username(self):
        student = make_student('carol')
        award_points(student, PointsSource.HOMEWORK, '1', 10)
        assert StudentPointsTotal.objects.get(student=student).display_name == 'carol'


class TestDailyPopup:

    def test_it_opens_on_the_first_load_of_the_day(self):
        student = make_student('alice')
        assert should_show_daily_popup(student, timezone.localdate()) is True

    def test_a_refresh_does_not_reopen_it(self):
        student = make_student('alice')
        today = timezone.localdate()
        should_show_daily_popup(student, today)
        assert should_show_daily_popup(student, today) is False

    def test_it_opens_again_the_next_day(self):
        student = make_student('alice')
        today = timezone.localdate()
        should_show_daily_popup(student, today)
        tomorrow = today + timezone.timedelta(days=1)
        assert should_show_daily_popup(student, tomorrow) is True
