"""
Playwright UI tests — CPP-282 / CPP-283: Worksheet Builder.

CPP-282: Filter panel, HTMX question list, access control.
CPP-283: Question selection sidebar, drag-to-reorder (SortableJS),
         save button validation, htmx:afterSwap selected-state preservation.
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
    def test_add_button_visible_on_cards(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Each question card has an active '+ Add' button (CPP-283)."""
        do_login(page, live_server.url, teacher_user)

        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        add_btn = page.locator("#question-list button.add-question-btn").first
        expect(add_btn).to_be_visible(timeout=5000)
        expect(add_btn).to_be_enabled(timeout=5000)


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


# ---------------------------------------------------------------------------
# CPP-283: Selection sidebar behaviour
# ---------------------------------------------------------------------------

class TestWorksheetBuilderSidebar:
    """CPP-283: Question selection sidebar with drag-to-reorder."""

    @pytest.mark.django_db(transaction=True)
    def test_teacher_adds_question_to_sidebar(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Clicking + Add on a card adds it to the sidebar list."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        page.locator("#question-list button.add-question-btn").first.click()

        expect(page.locator("#sidebar-question-list li")).to_have_count(1, timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_teacher_added_question_shows_disabled_in_results(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """After adding, the same card's Add button is disabled and shows ✓ Added."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        first_btn = page.locator("#question-list button.add-question-btn").first
        first_btn.click()

        # Button should now be disabled
        expect(first_btn).to_be_disabled(timeout=3000)
        expect(first_btn).to_contain_text("Added", timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_teacher_removes_question_from_sidebar(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Clicking × removes the question from the sidebar and re-enables its card button."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        first_card_btn = page.locator("#question-list button.add-question-btn").first
        first_card_btn.click()
        expect(page.locator("#sidebar-question-list li")).to_have_count(1, timeout=3000)

        # Remove from sidebar
        page.locator("#sidebar-question-list .remove-question-btn").first.click()
        expect(page.locator("#sidebar-question-list li")).to_have_count(0, timeout=3000)

        # Card button re-enabled
        expect(first_card_btn).to_be_enabled(timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_save_button_disabled_with_empty_selection(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Save button is disabled when no questions are selected."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_load_state("networkidle")

        expect(page.locator("#save-worksheet-btn")).to_be_disabled(timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_save_button_disabled_with_no_name(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Save remains disabled when a question is added but name is empty."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        page.locator("#question-list button.add-question-btn").first.click()
        # Leave name empty
        expect(page.locator("#save-worksheet-btn")).to_be_disabled(timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_save_button_enabled_with_name_and_questions(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Save becomes enabled when at least 1 question is added and name is filled."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        page.locator("#question-list button.add-question-btn").first.click()
        page.locator("#worksheet-name").fill("Test Worksheet")

        expect(page.locator("#save-worksheet-btn")).to_be_enabled(timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_question_count_badge_updates(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """Count badge increments/decrements as questions are added/removed."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        # Add first question
        add_btns = page.locator("#question-list button.add-question-btn")
        add_btns.nth(0).click()
        expect(page.locator("#question-count-badge")).to_have_text("1", timeout=3000)

        # Add second question
        add_btns.nth(1).click()
        expect(page.locator("#question-count-badge")).to_have_text("2", timeout=3000)

        # Remove one
        page.locator("#sidebar-question-list .remove-question-btn").first.click()
        expect(page.locator("#question-count-badge")).to_have_text("1", timeout=3000)

    @pytest.mark.django_db(transaction=True)
    def test_filter_refresh_preserves_selected_state(
        self,
        page: Page,
        live_server,
        teacher_user,
        question_bank,
        classroom,
    ):
        """After an HTMX filter swap, already-selected cards stay disabled (htmx:afterSwap)."""
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/worksheets/builder/")
        page.wait_for_selector("#question-list .question-card", timeout=6000)

        # Grab the data-content-id of the first card
        first_card = page.locator("#question-list .question-card").first
        content_id = first_card.get_attribute("data-content-id")

        # Add it to the sidebar
        first_card.locator("button.add-question-btn").click()
        expect(first_card.locator("button.add-question-btn")).to_be_disabled(timeout=3000)

        # Trigger an HTMX refresh by changing the search input (clear → triggers reload)
        with page.expect_response(lambda r: "builder/questions" in r.url and r.status == 200):
            page.locator("#filter-search").fill("fraction")

        page.wait_for_selector("#question-list .question-card", timeout=5000)

        # Go back to full list
        with page.expect_response(lambda r: "builder/questions" in r.url and r.status == 200):
            page.locator("#filter-search").fill("")

        page.wait_for_selector("#question-list .question-card", timeout=5000)

        # The previously selected card should still show as disabled
        reloaded_card = page.locator(f"#question-list .question-card[data-content-id='{content_id}']")
        if reloaded_card.count() > 0:
            expect(reloaded_card.locator("button.add-question-btn")).to_be_disabled(timeout=3000)
