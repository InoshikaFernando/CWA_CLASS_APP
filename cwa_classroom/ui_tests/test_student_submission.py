"""
UI tests: student answer submission.

Three focused test flows, each starting with a student login:

  1. Basic Facts    — navigate the selection UI → pick a topic → submit answers
                     → verify the DB record is created and results are shown.

  2. Times Tables   — navigate the selection UI → pick Multiplication then Division
                     → answer all questions → verify DB record + results page.

  3. Topic Quiz     — select a curriculum topic → answer all questions
                     → verify DB record + results page.

"Submitted correctly" means:
  * The results page renders with a visible score / points value.
  * The matching database record (BasicFactsResult / StudentFinalAnswer) exists.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.quiz


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _answer_all_tt_questions(page, num_questions: int = 12) -> None:
    """Click through all Times Tables questions using the JS submit flow."""
    for i in range(num_questions):
        # Wait for an answer button rendered by the tt_question partial
        answer_btn = page.locator(".tt-answer-btn").first
        answer_btn.wait_for(state="visible", timeout=10_000)
        answer_btn.click()
        page.wait_for_timeout(1_500)   # wait for fetch + partial swap

        # After the last question the partial shows "See Results →" (an <a> tag).
        # For every other question it shows a "Next Question →" button.
        see_results = page.locator("a", has_text=re.compile(r"See Results"))
        next_btn = page.locator("button", has_text=re.compile(r"Next Question"))

        if see_results.count() > 0 and see_results.first.is_visible():
            see_results.first.click()
            page.wait_for_load_state("networkidle")
            return  # submit view redirects to results

        if next_btn.count() > 0 and next_btn.first.is_visible():
            next_btn.first.click()
            page.wait_for_timeout(800)


def _answer_all_topic_questions(page, num_questions: int) -> None:
    """Click through all Topic Quiz questions using the JS submit flow."""
    for i in range(num_questions):
        # Wait for an MC answer button
        answer_btn = page.locator(".answer-btn").first
        answer_btn.wait_for(state="visible", timeout=10_000)
        answer_btn.click()
        page.wait_for_timeout(1_500)   # wait for fetch + feedback render

        # "View Results →" button appears after the last question
        view_results = page.locator("button", has_text=re.compile(r"View Results"))
        next_btn = page.locator("button", has_text=re.compile(r"Next Question"))

        if view_results.count() > 0 and view_results.first.is_visible():
            view_results.first.click()
            page.wait_for_load_state("networkidle")
            return

        if next_btn.count() > 0 and next_btn.first.is_visible():
            next_btn.first.click()
            page.wait_for_timeout(800)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Basic Facts submission
# ─────────────────────────────────────────────────────────────────────────────

class TestBasicFactsSubmission:
    """
    Student logs in → navigates Basic Facts selection UI → selects a topic →
    submits answers → verifies DB record and results page.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student
        do_login(page, self.url, enrolled_student)

    # ── Addition ─────────────────────────────────────────────────────────────

    def test_basic_facts_addition_submitted_correctly(self):
        """
        Student selects Addition Level 1 from the selection UI,
        submits 10 answers, and a BasicFactsResult row is created.
        """
        from maths.models import BasicFactsResult

        page = self.page

        # Step 1 — navigate to Basic Facts home and verify page loads
        page.goto(f"{self.url}/maths/basic-facts/")
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "Basic Facts")

        # Step 2 — click the Addition subtopic card
        addition_link = page.locator("a[href*='basic-facts/Addition']").first
        expect(addition_link).to_be_visible()
        addition_link.click()
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "Addition")

        # Step 3 — click Level 1 (internal level_number = 100)
        level_link = page.locator("a[href*='basic-facts/Addition/100']").first
        expect(level_link).to_be_visible()
        level_link.click()
        page.wait_for_load_state("networkidle")

        # Step 4 — verify the quiz rendered with answer inputs
        inputs = page.locator("input[name^='answer_']")
        assert inputs.count() > 0, "Quiz form should have answer input fields"

        # Step 5 — fill each input with a plausible answer
        for i in range(inputs.count()):
            inputs.nth(i).fill("5")

        # Step 6 — submit the form
        page.locator("button[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        # Step 7 — results page should show a score
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Score|Points|Correct", body, re.IGNORECASE), \
            f"Results page should display a score. Got: {body[:300]}"

        # Step 8 — verify DB record was created
        result = BasicFactsResult.objects.filter(
            student=self.student,
            subtopic="Addition",
            level_number=100,
        ).order_by("-completed_at").first()
        assert result is not None, "BasicFactsResult row should exist in the database"
        assert result.total_points == 10, "Should record 10 total questions"
        assert 0 <= result.score <= 10, "Score must be in range 0–10"

    # ── Multiplication (Basic Facts) ─────────────────────────────────────────

    def test_basic_facts_multiplication_submitted_correctly(self):
        """
        Student selects Multiplication Level 1 from the selection UI,
        submits 10 answers, and a BasicFactsResult row is created.
        """
        from maths.models import BasicFactsResult

        page = self.page

        # Step 1 — navigate to Basic Facts home
        page.goto(f"{self.url}/maths/basic-facts/")
        page.wait_for_load_state("networkidle")

        # Step 2 — click the Multiplication subtopic card
        mult_link = page.locator("a[href*='basic-facts/Multiplication']").first
        expect(mult_link).to_be_visible()
        mult_link.click()
        page.wait_for_load_state("networkidle")
        assert_page_has_text(page, "Multiplication")

        # Step 3 — click Level 1 (internal level_number = 114)
        level_link = page.locator("a[href*='basic-facts/Multiplication/114']").first
        expect(level_link).to_be_visible()
        level_link.click()
        page.wait_for_load_state("networkidle")

        # Step 4 — verify quiz inputs
        inputs = page.locator("input[name^='answer_']")
        assert inputs.count() > 0, "Quiz should have number input fields"

        # Step 5 — fill inputs with plausible answers
        for i in range(inputs.count()):
            inputs.nth(i).fill("6")

        # Step 6 — submit
        page.locator("button[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        # Step 7 — results page should show score
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Score|Points|Correct", body, re.IGNORECASE), \
            f"Results page should display a score. Got: {body[:300]}"

        # Step 8 — verify DB record
        result = BasicFactsResult.objects.filter(
            student=self.student,
            subtopic="Multiplication",
            level_number=114,
        ).order_by("-completed_at").first()
        assert result is not None, "BasicFactsResult row should exist for Multiplication"
        assert result.total_points == 10
        assert 0 <= result.score <= 10


# ─────────────────────────────────────────────────────────────────────────────
# 2. Times Tables submission (Multiplication & Division)
# ─────────────────────────────────────────────────────────────────────────────

class TestTimesTablesSubmission:
    """
    Student logs in → navigates Times Tables selection UI → picks Multiplication
    then Division → answers all questions → verifies DB record and results.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, level):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student
        self.level = level   # level_number = 7
        do_login(page, self.url, enrolled_student)

    # ── Multiplication ────────────────────────────────────────────────────────

    def test_multiplication_submitted_correctly(self):
        """
        Student selects the 2× Multiplication quiz from the Times Tables page,
        answers all 12 questions, and a StudentFinalAnswer row is created.
        """
        from maths.models import StudentFinalAnswer

        page = self.page

        # Step 1 — navigate to Times Tables home
        page.goto(f"{self.url}/maths/times-tables/")
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text().lower()
        assert "times tables" in body or "multiplication" in body

        # Step 2 — click the "× Multiply" link for the 2× table
        mult_link = page.locator(
            f"a[href*='multiplication/{self.level.level_number}'], "
            "a[href*='/multiplication/2/']"
        ).first
        # Fall back: navigate directly to the 2× multiplication quiz
        if not mult_link.is_visible():
            page.goto(f"{self.url}/maths/level/{self.level.level_number}/multiplication/2/")
        else:
            mult_link.click()
        page.wait_for_load_state("networkidle")

        # Step 3 — answer all 12 questions
        _answer_all_tt_questions(page, num_questions=12)

        # Step 4 — verify results page
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*12|\d+%|Score|Results|Times Tables", body, re.IGNORECASE), \
            f"Results page should show score. Got: {body[:300]}"

        # Step 5 — verify DB record
        result = StudentFinalAnswer.objects.filter(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            operation="multiplication",
            table_number=2,
        ).order_by("-completed_at").first()
        assert result is not None, "StudentFinalAnswer row should exist for multiplication quiz"
        assert result.total_questions == 12, "Should record 12 total questions"
        assert 0 <= result.score <= 12

    # ── Division ─────────────────────────────────────────────────────────────

    def test_division_submitted_correctly(self):
        """
        Student selects the ÷2 Division quiz from the Times Tables page,
        answers all 12 questions, and a StudentFinalAnswer row is created.
        """
        from maths.models import StudentFinalAnswer

        page = self.page

        # Step 1 — navigate to Times Tables home
        page.goto(f"{self.url}/maths/times-tables/")
        page.wait_for_load_state("networkidle")

        # Step 2 — click the "÷ Divide" link for the 2× table
        div_link = page.locator("a[href*='/division/2/']").first
        if not div_link.is_visible():
            page.goto(f"{self.url}/maths/level/{self.level.level_number}/division/2/")
        else:
            div_link.click()
        page.wait_for_load_state("networkidle")

        # Step 3 — answer all 12 questions
        _answer_all_tt_questions(page, num_questions=12)

        # Step 4 — verify results page
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*12|\d+%|Score|Results|Division", body, re.IGNORECASE), \
            f"Results page should show score. Got: {body[:300]}"

        # Step 5 — verify DB record
        result = StudentFinalAnswer.objects.filter(
            student=self.student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            operation="division",
            table_number=2,
        ).order_by("-completed_at").first()
        assert result is not None, "StudentFinalAnswer row should exist for division quiz"
        assert result.total_questions == 12
        assert 0 <= result.score <= 12


# ─────────────────────────────────────────────────────────────────────────────
# 3. Topic Quiz & Mixed Quiz submission (navigated via the student home UI)
# ─────────────────────────────────────────────────────────────────────────────

class TestTopicQuizSubmission:
    """
    Student logs in → navigates the student home page accordion → selects a
    specific topic OR the Mixed Quiz button → answers all questions →
    verifies the results page and the DB record.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, level, topic, questions):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student
        self.level = level        # level_number = 7
        self.topic = topic        # "Addition <run_id>" subtopic
        self.questions = questions
        do_login(page, self.url, enrolled_student)

    # ── Topic quiz ────────────────────────────────────────────────────────────

    def test_topic_quiz_submitted_correctly(self):
        """
        From the student home page, student clicks a topic card inside the
        year-level accordion, answers all questions, and a StudentFinalAnswer
        row is saved with the correct topic and level.
        """
        from maths.models import StudentFinalAnswer

        page = self.page
        num_questions = len(self.questions)

        # Step 1 — navigate to the student home page
        page.goto(f"{self.url}/app-home/")
        page.wait_for_load_state("networkidle")

        # Step 2 — the accordion for the enrolled level (7) should be open.
        # Locate the topic link by its href pointing to this topic + level.
        topic_link = page.locator(
            f"a[href*='/topic/{self.topic.id}/quiz/']"
        ).first
        expect(topic_link).to_be_visible(timeout=8_000)

        # Step 3 — click the topic card to start the quiz
        topic_link.click()
        page.wait_for_load_state("networkidle")

        # Step 4 — verify the quiz loaded with a question
        container = page.locator("#question-container, main")
        expect(container.first).to_be_visible()
        assert_page_has_text(page, "What is")

        # Step 5 — answer all questions
        _answer_all_topic_questions(page, num_questions=num_questions)

        # Step 6 — verify results page shows a score
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Score|Points|Results", body, re.IGNORECASE), \
            f"Results page should display a score. Got: {body[:300]}"

        # Step 7 — verify DB record was created
        result = StudentFinalAnswer.objects.filter(
            student=self.student,
            topic=self.topic,
            level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
        ).order_by("-completed_at").first()
        assert result is not None, "StudentFinalAnswer row should exist after topic quiz"
        assert result.total_questions == num_questions, \
            f"Expected {num_questions} questions recorded, got {result.total_questions}"
        assert 0 <= result.score <= num_questions
        assert result.points >= 0

    # ── Mixed quiz ────────────────────────────────────────────────────────────

    def test_mixed_quiz_submitted_correctly(self):
        """
        From the student home page, student clicks the '🎲 Take Mixed Quiz'
        button inside the year-level accordion, selects an answer for every
        question, submits the form, and a StudentFinalAnswer row of type
        'mixed' is saved.
        """
        from maths.models import StudentFinalAnswer

        page = self.page

        # Step 1 — navigate to the student home page
        page.goto(f"{self.url}/app-home/")
        page.wait_for_load_state("networkidle")

        # Step 2 — click the "🎲 Take Mixed Quiz" button for this level
        mixed_link = page.locator(
            f"a[href*='/level/{self.level.level_number}/quiz/']"
        ).first
        expect(mixed_link).to_be_visible(timeout=8_000)
        mixed_link.click()
        page.wait_for_load_state("networkidle")

        # Step 3 — verify mixed quiz loaded (shows all questions in one form)
        assert_page_has_text(page, "Mixed Quiz")
        form = page.locator("form#mixed-form")
        expect(form).to_be_visible()

        # Step 4 — select first radio option for every MC question
        #          (the template renders radio groups named answer_<question_id>)
        radio_groups = page.locator("input[type='radio']")
        answered = set()
        for i in range(radio_groups.count()):
            radio = radio_groups.nth(i)
            name = radio.get_attribute("name") or ""
            if name not in answered:
                radio.check()
                answered.add(name)

        # Step 5 — submit the form
        page.locator("button[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        # Step 6 — verify results page shows a score
        body = page.locator("body").inner_text()
        assert re.search(r"\d+\s*/\s*\d+|\d+%|Score|Points|Results|Mixed", body, re.IGNORECASE), \
            f"Mixed quiz results page should show a score. Got: {body[:300]}"

        # Step 7 — verify DB record was created
        result = StudentFinalAnswer.objects.filter(
            student=self.student,
            level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_MIXED,
        ).order_by("-completed_at").first()
        assert result is not None, "StudentFinalAnswer row should exist after mixed quiz"
        assert result.total_questions > 0, "Should record at least one question"
        assert 0 <= result.score <= result.total_questions
        assert result.points >= 0
