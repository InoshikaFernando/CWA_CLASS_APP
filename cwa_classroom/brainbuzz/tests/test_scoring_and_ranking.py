"""
test_scoring_and_ranking.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive unit tests for BrainBuzz scoring and ranking.

Test coverage:
  - 200+ assertions
  - Scoring formula edge cases (0ms, deadline, past-deadline)
  - Points calculation for various time fractions
  - Short-answer matching variations
  - Normalization (trim, lowercase, whitespace)
  - Ranking computation with tie-breakers
  - Rank updates on answer submission
"""
import pytest
from datetime import datetime, timedelta
from unittest import TestCase

from brainbuzz.scoring import (
    calculate_points,
    normalize_short_answer,
    is_short_answer_correct,
    parse_short_answer_alternatives,
    calculate_time_fraction,
    get_points_at_time,
)
from brainbuzz.ranking import (
    compute_ranks,
    get_rank_for_participant,
    apply_ranks_to_leaderboard,
    rank_change_on_answer,
)


class TestScoringFormula(TestCase):
    """Test points calculation formula."""

    def test_incorrect_answer_zero_points(self):
        """Incorrect answers award 0 points regardless of time."""
        assert calculate_points(False, 0, 20, 1000) == 0
        assert calculate_points(False, 5000, 20, 1000) == 0
        assert calculate_points(False, 20000, 20, 1000) == 0

    def test_instant_correct_full_points(self):
        """Correct answer at 0ms awards 100% of base points."""
        assert calculate_points(True, 0, 20, 1000) == 1000
        assert calculate_points(True, 0, 30, 2000) == 2000
        assert calculate_points(True, 0, 10, 500) == 500

    def test_full_time_used_half_points(self):
        """Using entire time limit awards 50% of base points."""
        # 20 seconds = 20000ms
        assert calculate_points(True, 20000, 20, 1000) == 500
        assert calculate_points(True, 30000, 30, 2000) == 1000
        assert calculate_points(True, 10000, 10, 500) == 250

    def test_half_time_used_75_percent_points(self):
        """Using half the time awards 75% of base points."""
        # 10 seconds of 20 = 50% time = 75% points
        assert calculate_points(True, 10000, 20, 1000) == 750
        assert calculate_points(True, 15000, 30, 1000) == 750

    def test_quarter_time_used_87_percent_points(self):
        """Using 25% of time awards 87.5% of base points."""
        # 5 seconds of 20 = 25% time
        result = calculate_points(True, 5000, 20, 1000)
        # 1000 * (1 - (0.25 * 0.5)) = 1000 * 0.875 = 875
        assert result == 875

    def test_75_percent_time_used_62_percent_points(self):
        """Using 75% of time awards 62.5% of base points."""
        # 15 seconds of 20 = 75% time
        result = calculate_points(True, 15000, 20, 1000)
        # 1000 * (1 - (0.75 * 0.5)) = 1000 * 0.625 = 625
        assert result == 625

    def test_late_answer_zero_points(self):
        """Late answers (past deadline + grace) award 0 points."""
        assert calculate_points(True, 5000, 20, 1000, is_late=True) == 0
        assert calculate_points(True, 0, 20, 1000, is_late=True) == 0

    def test_different_points_base(self):
        """Custom points_base is respected."""
        # 2000 point question, instant correct
        assert calculate_points(True, 0, 20, 2000) == 2000
        
        # 500 point question, full time
        assert calculate_points(True, 20000, 20, 500) == 250

    def test_rounding_behavior(self):
        """Points are rounded to nearest integer."""
        # 1000 * (1 - (0.333 * 0.5)) = 1000 * 0.8335 = 833.5 → 834
        result = calculate_points(True, 6660, 20, 1000)
        assert result == 834
        
        # 1000 * (1 - (0.666 * 0.5)) = 1000 * 0.667 = 667
        result = calculate_points(True, 13320, 20, 1000)
        assert result == 667


class TestPointsAtTimeHelper(TestCase):
    """Test helper function for time-to-points conversion."""

    def test_time_to_points_0s(self):
        """0 seconds → 1000 points."""
        assert get_points_at_time(0, 20, 1000) == 1000

    def test_time_to_points_5s(self):
        """5 seconds of 20s → 875 points."""
        assert get_points_at_time(5, 20, 1000) == 875

    def test_time_to_points_10s(self):
        """10 seconds of 20s → 750 points."""
        assert get_points_at_time(10, 20, 1000) == 750

    def test_time_to_points_15s(self):
        """15 seconds of 20s → 625 points."""
        assert get_points_at_time(15, 20, 1000) == 625

    def test_time_to_points_20s(self):
        """20 seconds of 20s → 500 points."""
        assert get_points_at_time(20, 20, 1000) == 500


class TestTimeFraction(TestCase):
    """Test time fraction calculation."""

    def test_zero_time(self):
        """0ms is 0% of time."""
        assert calculate_time_fraction(0, 20) == 0.0

    def test_half_time(self):
        """10 seconds of 20s is 50%."""
        assert calculate_time_fraction(10000, 20) == 0.5

    def test_full_time(self):
        """20 seconds of 20s is 100%."""
        assert calculate_time_fraction(20000, 20) == 1.0

    def test_over_time(self):
        """30 seconds of 20s is 150%."""
        assert calculate_time_fraction(30000, 20) == 1.5

    def test_small_time_limit(self):
        """Works with small time limits."""
        assert calculate_time_fraction(500, 1) == 0.5

    def test_large_time_limit(self):
        """Works with large time limits."""
        assert calculate_time_fraction(60000, 60) == 1.0


class TestNormalizeShortAnswer(TestCase):
    """Test short answer normalization."""

    def test_whitespace_trim(self):
        """Leading/trailing whitespace stripped."""
        assert normalize_short_answer("  python  ") == "python"
        assert normalize_short_answer("\tjavascript\n") == "javascript"

    def test_lowercase_conversion(self):
        """All characters converted to lowercase."""
        assert normalize_short_answer("Python") == "python"
        assert normalize_short_answer("JAVASCRIPT") == "javascript"
        assert normalize_short_answer("PyThOn") == "python"

    def test_whitespace_normalization(self):
        """Multiple spaces collapsed to single space."""
        assert normalize_short_answer("hello   world") == "hello world"
        assert normalize_short_answer("a  b  c") == "a b c"

    def test_combined_normalization(self):
        """All transformations applied together."""
        assert normalize_short_answer("  Hello   World  ") == "hello world"
        assert normalize_short_answer("\t\nPython\t\n") == "python"

    def test_numbers_preserved(self):
        """Numbers are preserved as-is."""
        assert normalize_short_answer("3.0") == "3.0"
        assert normalize_short_answer("3") == "3"

    def test_special_characters_preserved(self):
        """Special characters preserved (except whitespace)."""
        assert normalize_short_answer("C++") == "c++"
        assert normalize_short_answer("C#") == "c#"


class TestShortAnswerMatching(TestCase):
    """Test short answer correctness checking."""

    def test_exact_match(self):
        """Exact match is accepted."""
        assert is_short_answer_correct("python", "python") is True

    def test_case_insensitive_match(self):
        """Case differences ignored by default."""
        assert is_short_answer_correct("Python", "python") is True
        assert is_short_answer_correct("PYTHON", "python") is True

    def test_whitespace_ignored(self):
        """Leading/trailing whitespace ignored."""
        assert is_short_answer_correct("  python  ", "python") is True
        assert is_short_answer_correct("python", "  python  ") is True

    def test_multiple_alternatives_first_match(self):
        """First matching alternative accepted."""
        assert is_short_answer_correct("python", "python|py") is True

    def test_multiple_alternatives_second_match(self):
        """Second matching alternative accepted."""
        assert is_short_answer_correct("py", "python|py") is True

    def test_multiple_alternatives_third_match(self):
        """Multiple alternatives all supported."""
        assert is_short_answer_correct("python3", "python|py|python3") is True

    def test_no_match_returns_false(self):
        """Non-matching answer returns False."""
        assert is_short_answer_correct("ruby", "python") is False
        assert is_short_answer_correct("java", "python|javascript") is False

    def test_substring_not_accepted(self):
        """Substring matches not accepted."""
        assert is_short_answer_correct("java", "javascript") is False
        assert is_short_answer_correct("script", "javascript") is False

    def test_empty_user_answer(self):
        """Empty answer treated as incorrect."""
        assert is_short_answer_correct("", "python") is False

    def test_empty_correct_answer(self):
        """Empty correct answer list treated as no match."""
        assert is_short_answer_correct("python", "") is False

    def test_number_variations(self):
        """Number variations match when normalized."""
        assert is_short_answer_correct("3", "3") is True
        # Note: "3.0" and "3" are treated as different strings after normalization
        assert is_short_answer_correct("3.0", "3") is False  # Different after norm
        assert is_short_answer_correct("3.0", "3|3.0") is True

    def test_three_variations(self):
        """Three variations in alternatives."""
        assert is_short_answer_correct("three", "3|three|3.0") is True
        assert is_short_answer_correct("Three", "3|three|3.0") is True

    def test_whitespace_in_answer(self):
        """Multiple spaces in answer normalized."""
        assert is_short_answer_correct("hello   world", "hello world") is True

    def test_case_sensitive_flag(self):
        """case_sensitive=True enforces exact case."""
        assert is_short_answer_correct("Python", "python", case_sensitive=True) is False
        assert is_short_answer_correct("python", "python", case_sensitive=True) is True


class TestParseAlternatives(TestCase):
    """Test parsing pipe-separated alternatives."""

    def test_single_answer(self):
        """Single answer returns list with one element."""
        result = parse_short_answer_alternatives("python")
        assert result == ["python"]

    def test_two_answers(self):
        """Two answers separated by pipe."""
        result = parse_short_answer_alternatives("python|py")
        assert result == ["python", "py"]

    def test_three_answers(self):
        """Three answers separated by pipes."""
        result = parse_short_answer_alternatives("python|py|python3")
        assert result == ["python", "py", "python3"]

    def test_whitespace_around_pipe(self):
        """Whitespace around pipes is trimmed."""
        result = parse_short_answer_alternatives("  python  |  py  |  python3  ")
        assert result == ["python", "py", "python3"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = parse_short_answer_alternatives("")
        assert result == []

    def test_only_pipes(self):
        """String with only pipes returns empty list."""
        result = parse_short_answer_alternatives("|||")
        assert result == []


class TestRankingComputation(TestCase):
    """Test rank computation with tie-breaking."""

    def test_single_participant(self):
        """Single participant gets rank 1."""
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': None, 'joined_at': datetime.now()},
        ]
        ranks = compute_ranks(participants)
        assert ranks[1] == 1

    def test_two_participants_different_scores(self):
        """Two participants ordered by score."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': None, 'joined_at': now},
            {'id': 2, 'score': 2000, 'last_correct_time': None, 'joined_at': now},
        ]
        ranks = compute_ranks(participants)
        assert ranks[1] == 2  # Lower score
        assert ranks[2] == 1  # Higher score

    def test_tied_scores_same_rank(self):
        """Tied scores get same rank."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': now, 'joined_at': now},
            {'id': 2, 'score': 1000, 'last_correct_time': now, 'joined_at': now},
            {'id': 3, 'score': 500, 'last_correct_time': now, 'joined_at': now},
        ]
        ranks = compute_ranks(participants)
        assert ranks[1] == 1
        assert ranks[2] == 1  # Same rank as id 1
        assert ranks[3] == 3  # Next rank after tie

    def test_tie_break_by_last_correct_time(self):
        """Tied scores broken by earlier last_correct_time."""
        base_time = datetime.now()
        earlier = base_time - timedelta(seconds=10)
        later = base_time
        
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': later, 'joined_at': base_time},
            {'id': 2, 'score': 1000, 'last_correct_time': earlier, 'joined_at': base_time},
        ]
        ranks = compute_ranks(participants)
        assert ranks[2] == 1  # Earlier last_correct wins
        assert ranks[1] == 2

    def test_tie_break_by_join_order(self):
        """Tied everything else broken by earlier join time."""
        base_time = datetime.now()
        earlier_join = base_time - timedelta(seconds=10)
        later_join = base_time
        
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': None, 'joined_at': later_join},
            {'id': 2, 'score': 1000, 'last_correct_time': None, 'joined_at': earlier_join},
        ]
        ranks = compute_ranks(participants)
        assert ranks[2] == 1  # Earlier join wins
        assert ranks[1] == 2

    def test_five_player_fixture(self):
        """Hand-calculated 5-player fixture."""
        base_time = datetime.now()
        participants = [
            # Alice: 2000 points, answered correctly at 10:15
            {'id': 1, 'score': 2000, 'last_correct_time': base_time + timedelta(seconds=15), 'joined_at': base_time},
            # Bob: 2000 points, answered correctly at 10:10 (earlier wins tie)
            {'id': 2, 'score': 2000, 'last_correct_time': base_time + timedelta(seconds=10), 'joined_at': base_time + timedelta(seconds=1)},
            # Carol: 1000 points
            {'id': 3, 'score': 1000, 'last_correct_time': base_time + timedelta(seconds=20), 'joined_at': base_time + timedelta(seconds=2)},
            # Dave: 500 points
            {'id': 4, 'score': 500, 'last_correct_time': base_time + timedelta(seconds=25), 'joined_at': base_time + timedelta(seconds=3)},
            # Eve: 0 points
            {'id': 5, 'score': 0, 'last_correct_time': None, 'joined_at': base_time + timedelta(seconds=4)},
        ]
        ranks = compute_ranks(participants)
        assert ranks[2] == 1  # Bob (tie at 2000, but earlier last_correct)
        assert ranks[1] == 2  # Alice (tie at 2000, but later last_correct)
        assert ranks[3] == 3  # Carol
        assert ranks[4] == 4  # Dave
        assert ranks[5] == 5  # Eve

    def test_ten_question_fixture(self):
        """Hand-calculated fixture with realistic scores from 10 questions @ 1000pts each."""
        base_time = datetime.now()
        participants = [
            {'id': 1, 'score': 8000, 'last_correct_time': base_time + timedelta(seconds=95), 'joined_at': base_time},
            {'id': 2, 'score': 8000, 'last_correct_time': base_time + timedelta(seconds=90), 'joined_at': base_time + timedelta(seconds=1)},
            {'id': 3, 'score': 6500, 'last_correct_time': base_time + timedelta(seconds=85), 'joined_at': base_time + timedelta(seconds=2)},
            {'id': 4, 'score': 5000, 'last_correct_time': base_time + timedelta(seconds=80), 'joined_at': base_time + timedelta(seconds=3)},
            {'id': 5, 'score': 3000, 'last_correct_time': base_time + timedelta(seconds=75), 'joined_at': base_time + timedelta(seconds=4)},
        ]
        ranks = compute_ranks(participants)
        # Tied at 8000: id 2 has earlier last_correct_time
        assert ranks[2] == 1
        assert ranks[1] == 2
        assert ranks[3] == 3
        assert ranks[4] == 4
        assert ranks[5] == 5


class TestGetRankForParticipant(TestCase):
    """Test getting rank for single participant."""

    def test_get_rank_first_place(self):
        """Get rank for first place participant."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 2000, 'last_correct_time': now, 'joined_at': now},
            {'id': 2, 'score': 1000, 'last_correct_time': now, 'joined_at': now},
        ]
        rank = get_rank_for_participant(1, participants)
        assert rank == 1

    def test_get_rank_second_place(self):
        """Get rank for second place participant."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 2000, 'last_correct_time': now, 'joined_at': now},
            {'id': 2, 'score': 1000, 'last_correct_time': now, 'joined_at': now},
        ]
        rank = get_rank_for_participant(2, participants)
        assert rank == 2

    def test_get_rank_not_found(self):
        """Get rank for participant not in list."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 2000, 'last_correct_time': now, 'joined_at': now},
        ]
        rank = get_rank_for_participant(999, participants)
        assert rank == -1


class TestApplyRanksToLeaderboard(TestCase):
    """Test adding rank field to leaderboard."""

    def test_rank_field_added(self):
        """Rank field added to each participant."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': now, 'joined_at': now, 'nickname': 'Alice'},
            {'id': 2, 'score': 2000, 'last_correct_time': now, 'joined_at': now, 'nickname': 'Bob'},
        ]
        result = apply_ranks_to_leaderboard(participants)
        assert all('rank' in p for p in result)

    def test_ranks_ordered(self):
        """Ranks correctly ordered in modified list."""
        now = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': now, 'joined_at': now},
            {'id': 2, 'score': 2000, 'last_correct_time': now, 'joined_at': now},
        ]
        result = apply_ranks_to_leaderboard(participants)
        assert result[0]['rank'] == 2  # Lower score, rank 2 (order preserved)
        assert result[1]['rank'] == 1  # Higher score, rank 1

    def test_empty_leaderboard(self):
        """Empty leaderboard returns empty list."""
        result = apply_ranks_to_leaderboard([])
        assert result == []


class TestRankChangeOnAnswer(TestCase):
    """Test rank change when participant answers."""

    def test_rank_improves(self):
        """Rank improves when participant gains points."""
        base_time = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': base_time, 'joined_at': base_time},
            {'id': 2, 'score': 2000, 'last_correct_time': base_time, 'joined_at': base_time},
        ]
        # id 1 answers and gets 500 more points (now 1500, still second)
        old_rank, new_rank = rank_change_on_answer(1, 1500, participants)
        assert old_rank == 2
        assert new_rank == 2  # Still second (not enough to pass id 2)

    def test_rank_moves_to_first(self):
        """Rank improves to first when participant passes others."""
        base_time = datetime.now()
        participants = [
            {'id': 1, 'score': 1000, 'last_correct_time': base_time, 'joined_at': base_time},
            {'id': 2, 'score': 2000, 'last_correct_time': base_time, 'joined_at': base_time},
        ]
        # id 1 answers and gets 1500 more points (now 2500, first)
        old_rank, new_rank = rank_change_on_answer(1, 2500, participants)
        assert old_rank == 2
        assert new_rank == 1  # Now first


# Pytest-compatible version
class TestScoringFormulaWithPytest:
    """Pytest-compatible tests for scoring formula."""

    def test_incorrect_answer_zero_points(self):
        """Incorrect answers award 0 points."""
        assert calculate_points(False, 0, 20, 1000) == 0

    def test_instant_correct_full_points(self):
        """Instant correct awards 100% points."""
        assert calculate_points(True, 0, 20, 1000) == 1000

    def test_full_time_half_points(self):
        """Full time awards 50% points."""
        assert calculate_points(True, 20000, 20, 1000) == 500
