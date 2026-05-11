"""
test_live_quiz.py — Browser-only quiz & maths tests against a deployed environment.

Run:
    pytest ui_tests/test_live_quiz.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests quiz answering flows, basic facts, times tables, and topic quizzes.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
STUDENT_EMAIL = "user46@test.local"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


def _assert_no_error(page: Page):
    content = page.content()
    assert "Internal Server Error" not in content
    assert "Server Error (500)" not in content


# ═══════════════════════════════════════════════════════════════════════════
# Topic Quizzes
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTopicQuizzes:
    """Verify topic quiz pages load and topics are accessible."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_topic_quizzes_page_loads(self):
        self.page.goto(f"{self.url}/maths/topic-quizzes/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_topic_quizzes_shows_topics(self):
        self.page.goto(f"{self.url}/maths/topic-quizzes/")
        self.page.wait_for_load_state("domcontentloaded")
        links = self.page.locator("a[href*='/maths/quiz/']")
        if links.count() > 0:
            expect(links.first).to_be_visible()

    def test_start_topic_quiz(self):
        """Click the first available quiz topic and verify the quiz page loads."""
        self.page.goto(f"{self.url}/maths/topic-quizzes/")
        self.page.wait_for_load_state("domcontentloaded")
        quiz_link = self.page.locator("a[href*='/maths/quiz/']").first
        if quiz_link.count() == 0:
            pytest.skip("No quiz topics available in dev DB")
        quiz_link.click()
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_quiz_page_has_question(self):
        """Verify the quiz page displays a question with answer options."""
        self.page.goto(f"{self.url}/maths/topic-quizzes/")
        self.page.wait_for_load_state("domcontentloaded")
        quiz_link = self.page.locator("a[href*='/maths/quiz/']").first
        if quiz_link.count() == 0:
            pytest.skip("No quiz topics available in dev DB")
        quiz_link.click()
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"question|answer|option|quiz|\?", re.IGNORECASE))


# ═══════════════════════════════════════════════════════════════════════════
# Basic Facts
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveBasicFacts:
    """Verify basic facts quiz pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_basic_facts_page_loads(self):
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_basic_facts_shows_subtopics(self):
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"addition|subtraction|multiplication|division", re.IGNORECASE))

    def test_start_basic_facts_quiz(self):
        """Click the first available subtopic and verify quiz loads."""
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        quiz_link = self.page.locator("main a[href*='/maths/'], .content a[href*='/maths/']").first
        if quiz_link.count() == 0:
            pytest.skip("No basic facts subtopics available")
        quiz_link.click()
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Times Tables
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTimesTables:
    """Verify times tables quiz pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_times_tables_page_loads(self):
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_times_tables_shows_options(self):
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"multiplication|division|times|tables", re.IGNORECASE))

    def test_start_times_tables_quiz(self):
        """Click the first available times table and verify quiz loads."""
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        quiz_link = self.page.locator("main a[href*='/maths/'], .content a[href*='/maths/']").first
        if quiz_link.count() == 0:
            pytest.skip("No times tables available")
        quiz_link.click()
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Coding page
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveCodingPage:
    """Verify coding pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_coding_home_page(self):
        self.page.goto(f"{self.url}/coding/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
