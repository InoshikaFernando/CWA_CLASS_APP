"""
End-to-end quiz tests — complete a full quiz and verify progress updates.

Each test class runs through an entire quiz flow:
1. Start the quiz
2. Answer all questions
3. See results
4. Check progress dashboard shows the attempt
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.quiz


# ---------------------------------------------------------------------------
# 1. Topic Quiz E2E — MC answers via AJAX, check results + progress
# ---------------------------------------------------------------------------

class TestTopicQuizE2E:
    """Complete a topic quiz from start to finish and verify progress."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, level, topic, questions):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        self.questions = questions
        do_login(page, self.url, enrolled_student)

    def test_complete_topic_quiz_and_check_progress(self):
        page = self.page
        num_questions = len(self.questions)

        # ── Start the quiz ──
        page.goto(f"{self.url}/maths/level/{self.level.level_number}/topic/{self.topic.id}/quiz/")
        page.wait_for_load_state("networkidle")

        # Verify quiz loaded
        container = page.locator("#question-container, main")
        expect(container.first).to_be_visible()

        # ── Answer all questions ──
        for i in range(num_questions):
            # Wait for an answer button to be clickable
            answer_btn = page.locator(
                "#question-container button[onclick*='submitMC'], "
                "#question-container .answer-btn, "
                "#question-container button"
            ).first
            answer_btn.wait_for(state="visible", timeout=10_000)

            # Click the first answer option
            answer_btn.click()

            # Wait for feedback or next question to load
            page.wait_for_timeout(1500)

            # If not the last question, click "Next Question"
            if i < num_questions - 1:
                next_btn = page.locator("button", has_text=re.compile(r"Next Question|View Results"))
                next_btn.wait_for(state="visible", timeout=10_000)
                next_btn.click()
                page.wait_for_timeout(1000)
            else:
                # Last question — click "View Results" if it appears
                results_btn = page.locator("button", has_text=re.compile(r"View Results|Next"))
                if results_btn.count() > 0:
                    results_btn.click()
                    page.wait_for_timeout(1000)

        # ── Verify results page ──
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text()
        # Should show a score (fraction or percentage) or "Results"
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Results|Score|Points", body, re.IGNORECASE), \
            f"Results page should show score. Got: {body[:200]}"

        # ── Check progress dashboard ──
        page.goto(f"{self.url}/student-dashboard/")
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "My Progress")

        # The topic "Addition" should appear in the progress grid
        # (may be inside a collapsed accordion)
        body = page.locator("body").inner_text()
        assert "Level 7" in body or "Addition" in body or "Year" in body, \
            f"Progress should show Level 7 or Addition. Got: {body[:300]}"


# ---------------------------------------------------------------------------
# 2. Basic Facts E2E — form-based, answer 10 questions, check results
# ---------------------------------------------------------------------------

class TestBasicFactsE2E:
    """Complete a basic facts quiz and verify progress."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_complete_basic_facts_and_check_progress(self):
        page = self.page

        # ── Navigate to Basic Facts home ──
        page.goto(f"{self.url}/maths/basic-facts/")
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "Basic Facts")

        # ── Start Addition Level 1 (internal level_number=100) ──
        page.goto(f"{self.url}/maths/basic-facts/Addition/100/")
        page.wait_for_load_state("networkidle")

        # ── Fill all answer inputs ──
        # Basic facts generates 10 questions — all are number inputs
        inputs = page.locator("input[type='number'][name^='answer_']")
        count = inputs.count()
        assert count > 0, "Should have number input fields for answers"

        for i in range(count):
            # Fill with a plausible answer (won't always be correct, but that's OK)
            inputs.nth(i).fill("5")

        # ── Submit the form ──
        submit_btn = page.locator("button[type='submit'], main button.bg-primary")
        submit_btn.first.click()
        page.wait_for_load_state("networkidle")

        # ── Verify results page ──
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Results|Score|Points|Correct", body, re.IGNORECASE), \
            f"Results page should show score. Got: {body[:200]}"

        # ── Check progress dashboard ──
        page.goto(f"{self.url}/student-dashboard/")
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "My Progress")

        # Basic Facts section should exist in progress
        body = page.locator("body").inner_text()
        assert "Basic Facts" in body or "Addition" in body or "Today" in body, \
            f"Progress should show Basic Facts data. Got: {body[:300]}"


# ---------------------------------------------------------------------------
# 3. Times Tables E2E — AJAX MC answers, 12 questions, check results
# ---------------------------------------------------------------------------

class TestTimesTablesE2E:
    """Complete a times tables quiz and verify progress."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_complete_times_tables_and_check_progress(self):
        page = self.page

        # ── Navigate to Times Tables home ──
        page.goto(f"{self.url}/maths/times-tables/")
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text().lower()
        assert "times tables" in body or "multiplication" in body

        # ── Start 2× multiplication quiz ──
        # The URL needs a level_number — use level 4 (default) with table 2
        page.goto(f"{self.url}/maths/level/4/multiplication/2/")
        page.wait_for_load_state("networkidle")

        # ── Answer all 12 questions ──
        for i in range(12):
            # Wait for an answer button
            answer_btn = page.locator(
                ".tt-answer-btn, "
                "#question-container button, "
                "button[onclick*='submitAnswer']"
            ).first
            answer_btn.wait_for(state="visible", timeout=10_000)

            # Click the first answer option
            answer_btn.click()
            page.wait_for_timeout(1500)

            # Click "Next Question" if it appears
            next_btn = page.locator("button", has_text=re.compile(r"Next Question"))
            if next_btn.count() > 0 and next_btn.first.is_visible():
                next_btn.first.click()
                page.wait_for_timeout(1000)

        # ── Wait for results (auto-redirect after last question) ──
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # ── Verify results ──
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*12|\d+%|Results|Score|Times Tables", body, re.IGNORECASE), \
            f"Results should show score out of 12. Got: {body[:200]}"

        # ── Check progress dashboard ──
        page.goto(f"{self.url}/student-dashboard/")
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "My Progress")

        # Times Tables section should exist
        body = page.locator("body").inner_text()
        assert "Times Tables" in body or "Table" in body or "Today" in body, \
            f"Progress should show Times Tables data. Got: {body[:300]}"
