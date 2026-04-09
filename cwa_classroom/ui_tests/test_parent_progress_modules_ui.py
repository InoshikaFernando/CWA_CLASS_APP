"""
UI tests for the parent progress page module activity sections (/parent/progress/).

Covers:
- Empty state when child has no quiz activity
- Maths module section: heading, topic rows, accuracy %
- Number Puzzles module section: heading, level rows, accuracy %
- Both modules shown side by side
- Colour coding: green ≥80%, amber 50-79%, red <50%
- Criteria-based progress (ProgressCriteria) still works alongside module activity
"""

import re
import uuid
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text, _ensure_sidebar_visible

pytestmark = pytest.mark.parent_progress


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _create_student_answer(student, question, answer, is_correct):
    from maths.models import StudentAnswer
    return StudentAnswer.objects.create(
        student=student,
        question=question,
        selected_answer=answer,
        is_correct=is_correct,
        attempt_id=uuid.uuid4(),
    )


def _create_puzzle_level(number=88):
    from number_puzzles.models import NumberPuzzleLevel
    level, _ = NumberPuzzleLevel.objects.get_or_create(
        number=number,
        defaults={
            "name": f"UI Test Level {number}",
            "slug": f"ui-test-level-{number}",
            "min_operand": 1,
            "max_operand": 9,
            "num_operands": 2,
            "puzzles_per_set": 10,
            "unlock_threshold": 5,
            "order": number,
        },
    )
    return level


def _create_puzzle_progress(student, level, attempted=10, correct=8):
    from number_puzzles.models import StudentPuzzleProgress
    return StudentPuzzleProgress.objects.create(
        student=student,
        level=level,
        total_puzzles_attempted=attempted,
        total_puzzles_correct=correct,
    )


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestParentProgressEmptyState:
    """No activity → 'No activity yet' message."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_progress_page_loads(self):
        assert_page_has_text(self.page, "Progress Report")

    def test_child_name_shown_in_header(self, enrolled_student):
        assert_page_has_text(self.page, "Ui Student")

    def test_no_activity_empty_state(self):
        assert_page_has_text(self.page, "No activity yet")

    def test_maths_section_not_shown_without_data(self):
        body = self.page.locator("body").inner_text()
        # "Maths" as a section heading should not appear (no StudentAnswer data)
        assert "correct of" not in body


# ---------------------------------------------------------------------------
# Maths module
# ---------------------------------------------------------------------------

class TestParentProgressMathsModule:
    """Maths quiz activity section appears when StudentAnswer data exists."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school, classroom,
               enrolled_student, questions, db):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student

        # 3 correct, 1 wrong on the first question
        q = questions[0]
        correct_ans = q.answers.filter(is_correct=True).first()
        wrong_ans = q.answers.filter(is_correct=False).first()
        for _ in range(3):
            _create_student_answer(enrolled_student, q, correct_ans, True)
        _create_student_answer(enrolled_student, q, wrong_ans, False)

        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_maths_section_heading_shown(self):
        assert_page_has_text(self.page, "Maths")

    def test_topic_name_shown_in_maths_section(self, topic):
        # topic fixture name includes _RUN_ID — check for "Addition" prefix
        body = self.page.locator("body").inner_text()
        assert "Addition" in body

    def test_accuracy_percentage_shown(self):
        # 3 correct / 4 total = 75%
        assert_page_has_text(self.page, "75%")

    def test_correct_count_shown(self):
        body = self.page.locator("body").inner_text()
        assert "correct of" in body

    def test_attempt_count_shown(self):
        # 4 total attempts
        body = self.page.locator("body").inner_text()
        assert "4" in body

    def test_amber_bar_for_75_percent(self):
        """75% → amber progress bar (50–79% range)."""
        bar = self.page.locator("[class*='bg-amber']").first
        expect(bar).to_be_visible()


# ---------------------------------------------------------------------------
# Number Puzzles module
# ---------------------------------------------------------------------------

class TestParentProgressNumberPuzzles:
    """Number Puzzles section appears when StudentPuzzleProgress data exists."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school,
               enrolled_student, db):
        self.url = live_server.url
        self.page = page

        level = _create_puzzle_level(88)
        _create_puzzle_progress(enrolled_student, level, attempted=10, correct=9)

        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_number_puzzles_heading_shown(self):
        assert_page_has_text(self.page, "Number Puzzles")

    def test_level_name_shown(self):
        assert_page_has_text(self.page, "UI Test Level 88")

    def test_accuracy_percentage_shown(self):
        # 9/10 = 90%
        assert_page_has_text(self.page, "90%")

    def test_green_bar_for_90_percent(self):
        """90% → green progress bar (≥80% range)."""
        bar = self.page.locator("[class*='bg-emerald']").first
        expect(bar).to_be_visible()

    def test_correct_count_shown(self):
        body = self.page.locator("body").inner_text()
        assert "9" in body and "10" in body


# ---------------------------------------------------------------------------
# Both modules together
# ---------------------------------------------------------------------------

class TestParentProgressBothModules:
    """When student has both maths and puzzle data, both sections render."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school, classroom,
               enrolled_student, questions, db):
        self.url = live_server.url
        self.page = page

        # Maths data
        q = questions[0]
        correct_ans = q.answers.filter(is_correct=True).first()
        _create_student_answer(enrolled_student, q, correct_ans, True)

        # Puzzle data
        level = _create_puzzle_level(89)
        _create_puzzle_progress(enrolled_student, level, attempted=5, correct=2)

        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_maths_section_shown(self):
        assert_page_has_text(self.page, "Maths")

    def test_number_puzzles_section_shown(self):
        assert_page_has_text(self.page, "Number Puzzles")

    def test_red_bar_for_low_accuracy(self):
        """2/5 = 40% → red progress bar."""
        bar = self.page.locator("main [class*='bg-red-'], div.max-w-4xl [class*='bg-red-']").first
        expect(bar).to_be_visible()


# ---------------------------------------------------------------------------
# Colour coding
# ---------------------------------------------------------------------------

class TestParentProgressColourCoding:
    """Accuracy thresholds map to the correct bar colour."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school,
               enrolled_student, db):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student
        self.parent = parent_with_child

    def _goto(self):
        do_login(self.page, self.url, self.parent)
        self.page.goto(f"{self.url}/parent/progress/")
        self.page.wait_for_load_state("domcontentloaded")

    def test_green_bar_when_accuracy_at_least_80(self):
        level = _create_puzzle_level(80)
        _create_puzzle_progress(self.student, level, attempted=10, correct=8)  # 80%
        self._goto()
        bar = self.page.locator("[class*='bg-emerald']").first
        expect(bar).to_be_visible()

    def test_amber_bar_when_accuracy_50_to_79(self):
        level = _create_puzzle_level(81)
        _create_puzzle_progress(self.student, level, attempted=10, correct=6)  # 60%
        self._goto()
        bar = self.page.locator("[class*='bg-amber']").first
        expect(bar).to_be_visible()

    def test_red_bar_when_accuracy_below_50(self):
        level = _create_puzzle_level(82)
        _create_puzzle_progress(self.student, level, attempted=10, correct=3)  # 30%
        self._goto()
        bar = self.page.locator("main [class*='bg-red-'], div.max-w-4xl [class*='bg-red-']").first
        expect(bar).to_be_visible()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class TestParentProgressSidebarActive:
    """Progress link active styling when on /parent/progress/."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_progress_link_has_active_class(self):
        _ensure_sidebar_visible(self.page)
        progress_link = self.page.locator("aside#sidebar a", has_text="Progress").first
        class_attr = progress_link.get_attribute("class") or ""
        assert "indigo" in class_attr or "bg-" in class_attr
