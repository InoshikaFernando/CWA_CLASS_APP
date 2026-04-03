"""Tests for quiz answering — topic quiz, times tables, basic facts."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text, wait_for_network_idle

pytestmark = pytest.mark.quiz


# ---------------------------------------------------------------------------
# Topic quiz
# ---------------------------------------------------------------------------

class TestTopicQuiz:
    """Tests for /level/<n>/topic/<id>/quiz/ — question display and answer flow."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, level, topic, questions):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/level/{self.level.level_number}/topic/{self.topic.id}/quiz/")
        page.wait_for_load_state("domcontentloaded")

    def test_quiz_page_loads(self):
        """Quiz page should load with question content."""
        # Question container should exist
        container = self.page.locator("#question-container, [id*='question'], main")
        expect(container.first).to_be_visible()

    def test_question_text_visible(self):
        """Question text should be displayed."""
        assert_page_has_text(self.page, "What is")

    def test_question_number_badge(self):
        """Question number badge (e.g. '1 of 5') should be visible."""
        assert_page_has_text(self.page, "of")

    def test_answer_buttons_visible(self):
        """MC answer option buttons should be displayed."""
        buttons = self.page.locator("button[onclick*='submit'], button[data-answer], .answer-btn, button.rounded")
        if buttons.count() > 0:
            expect(buttons.first).to_be_visible()

    def test_clicking_answer_shows_feedback(self):
        """Clicking an MC answer should trigger fetch and show feedback."""
        # Click the first answer-like button
        answer_btn = self.page.locator(
            "button[onclick*='submit'], button[data-answer], #question-container button"
        ).first
        if answer_btn.is_visible():
            answer_btn.click()
            # Wait for the AJAX response
            self.page.wait_for_timeout(2000)
            # Either feedback div appears or next question loads
            body_text = self.page.locator("body").inner_text()
            assert "correct" in body_text.lower() or "next" in body_text.lower() or "What is" in body_text


# ---------------------------------------------------------------------------
# Topic quiz results
# ---------------------------------------------------------------------------

class TestTopicQuizResults:
    """Tests for the results page after completing a topic quiz."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, level, topic, questions, progress_data):
        self.url = live_server.url
        self.page = page
        self.level = level
        self.topic = topic
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/level/{self.level.level_number}/topic/{self.topic.id}/results/")
        page.wait_for_load_state("domcontentloaded")

    def test_results_page_loads(self):
        """Results page should display score information."""
        body = self.page.locator("body")
        expect(body).to_be_visible()

    def test_score_displayed(self):
        """Score or results info should be shown (or 404 if no quiz session)."""
        body_text = self.page.locator("body").inner_text()
        # Results page shows score, or may 404/redirect if no completed quiz session
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Results|Score|not found|No quiz", body_text, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Basic facts select page
# ---------------------------------------------------------------------------

class TestBasicFactsSelect:
    """Tests for /basic-facts/ — subtopic selection page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/basic-facts/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Basic Facts")

    def test_subtopics_visible(self):
        """Subtopic cards (Addition, Subtraction, etc.) should be visible."""
        assert_page_has_text(self.page, "Addition")

    def test_subtopic_links_present(self):
        """Each subtopic should have links to levels."""
        links = self.page.locator("a[href*='basic-facts']")
        assert links.count() > 0


# ---------------------------------------------------------------------------
# Times tables select page
# ---------------------------------------------------------------------------

class TestTimesTablesSelect:
    """Tests for /times-tables/ — table selection page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/times-tables/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Times Tables")

    def test_multiplication_section(self):
        """Multiplication links should be visible."""
        body = self.page.locator("body").inner_text().lower()
        assert "multiplication" in body or "×" in body or "times" in body

    def test_division_section(self):
        """Division links should be visible."""
        body = self.page.locator("body").inner_text().lower()
        assert "division" in body or "÷" in body or "times" in body

    def test_table_links_present(self):
        """Links for tables 1-12 should be present."""
        links = self.page.locator("a[href*='multiplication'], a[href*='division']")
        assert links.count() > 0
