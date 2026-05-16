"""
Playwright UI tests — CPP-282: Worksheet Builder.

Verifies that a teacher can open the builder, see the filter panel,
filter by topic, search for questions, and that students are blocked.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def question_bank(db, school, teacher_user, level, topic):
    """A handful of questions in the global + school question banks."""
    from maths.models import Answer, Question

    # Global question (school=None)
    q1 = Question.objects.create(
        level=level,
        topic=topic,
        question_text="What is 3 + 4?",
        question_type="multiple_choice",
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=q1, answer_text="7", is_correct=True, order=1)
    Answer.objects.create(question=q1, answer_text="6", is_correct=False, order=2)

    # School-specific question
    q2 = Question.objects.create(
        school=school,
        level=level,
        topic=topic,
        question_text="Explain the concept of fractions.",
        question_type="extended_answer",
        difficulty=2,
        points=3,
    )

    return [q1, q2]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWorksheetBuilderTeacher:
    """CPP-282: Teacher can access and use the worksheet builder."""

    @pytest.mark.django_db(transaction=True)
    def test_teacher_opens_builder_sees_filter_panel(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Builder page loads with filter panel and question list."""
        do_login(page, live_server.url, teacher_user)

        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_load_state("networkidle")

        # Filter panel elements visible
        expect(page.locator("select#filter-subject")).to_be_visible()
        expect(page.locator("select#filter-topic")).to_be_visible()
        expect(page.locator("select#filter-level")).to_be_visible()
        expect(page.locator("input#filter-search")).to_be_visible()

        # Question list loaded (HTMX trigger=load)
        expect(page.locator("#question-list")).to_be_visible()

        # At least one question card visible
        expect(page.locator("#question-list .bg-white").first).to_be_visible(timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_teacher_search_filters_results(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Typing in the search box updates the question list via HTMX."""
        do_login(page, live_server.url, teacher_user)

        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_load_state("networkidle")

        # Wait for initial load
        page.wait_for_selector("#question-list .bg-white", timeout=5000)

        # Search for "fractions"
        with page.expect_response(lambda r: "builder/questions" in r.url and r.status == 200):
            page.locator("input#filter-search").fill("fractions")

        # Should show the extended answer question about fractions
        expect(page.locator("#question-list")).to_contain_text("fractions", timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_teacher_sees_question_cards_with_badges(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Question cards display type and difficulty badges."""
        do_login(page, live_server.url, teacher_user)

        page.goto(f"{live_server.url}/worksheets/builder/")

        # Wait for questions to load
        page.wait_for_selector("#question-list .bg-white", timeout=6000)

        # At least one difficulty badge visible (Easy/Medium/Hard)
        badges = page.locator("#question-list").get_by_text("Easy").or_(
            page.locator("#question-list").get_by_text("Medium")
        ).or_(
            page.locator("#question-list").get_by_text("Hard")
        )
        expect(badges.first).to_be_visible(timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_select_button_is_disabled_on_cards(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Select button on cards is disabled (CPP-283 not yet implemented)."""
        do_login(page, live_server.url, teacher_user)

        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .bg-white", timeout=6000)

        select_btn = page.locator("#question-list button:has-text('Select')").first
        expect(select_btn).to_be_disabled(timeout=5000)


class TestWorksheetBuilderAccessControl:
    """CPP-282: Role-based access control for builder."""

    @pytest.mark.django_db(transaction=True)
    def test_student_cannot_access_builder(
        self,
        page: Page,
        live_server,
        enrolled_student,
    ):
        """Students should be blocked from the builder (403 or redirect)."""
        do_login(page, live_server.url, enrolled_student)

        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_load_state("domcontentloaded")

        # Should NOT see the builder filter panel
        assert (
            page.locator("select#filter-subject").count() == 0
            or "403" in page.title()
            or "/accounts/login" in page.url
        ), "Student should not see the worksheet builder"
