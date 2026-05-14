"""
Playwright UI tests — worksheet sidebar subject-filtering (CPP-276).

Verifies that the student sidebar shows a subject-filtered Worksheets link:
  • On /maths/ pages  → link points to ?subject=mathematics
  • On /coding/ pages → link points to ?subject=coding (via sidebar_coding.html)
  • On generic pages  → link is unfiltered (all subjects)

Also verifies the list view itself filters correctly.

Implementation note: static files (including tailwind.min.js) are not served in
the test environment, so the sidebar <aside> is visually hidden (hidden md:flex
collapses to hidden without CSS).  Sidebar link tests therefore use
get_attribute() / page.evaluate() which work on non-visible DOM elements.
Tests that need a clickable link force the sidebar open via JS first.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from .conftest import do_login, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Shared worksheet fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def maths_worksheet_assignment(db, school, teacher_user, level, topic, classroom):
    """A maths worksheet assigned to the test classroom."""
    from maths.models import Answer, Question
    from worksheets.models import Worksheet, WorksheetAssignment, WorksheetQuestion

    question = Question.objects.create(
        level=level,
        topic=topic,
        question_text="What is 3 × 3?",
        question_type="multiple_choice",
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=question, answer_text="9",  is_correct=True,  order=1)
    Answer.objects.create(question=question, answer_text="6",  is_correct=False, order=2)
    Answer.objects.create(question=question, answer_text="12", is_correct=False, order=3)
    Answer.objects.create(question=question, answer_text="18", is_correct=False, order=4)

    worksheet = Worksheet.objects.create(
        school=school,
        name="Maths Sidebar Test Worksheet",
        original_filename="maths_sidebar.pdf",
        created_by=teacher_user,
        question_count=1,
    )
    WorksheetQuestion.objects.create(
        worksheet=worksheet,
        question=question,
        order=1,
        subject_slug="mathematics",
        content_id=question.id,
    )
    assignment = WorksheetAssignment.objects.create(
        worksheet=worksheet,
        classroom=classroom,
        is_active=True,
    )
    return assignment


def _sidebar_worksheets_href(page: Page) -> str | None:
    """Return the href of the first Worksheets link inside the sidebar <aside>.

    Works even when the sidebar is visually hidden (no Tailwind CSS in test env).
    """
    return page.evaluate(
        """() => {
            const aside = document.getElementById('sidebar');
            if (!aside) return null;
            const link = aside.querySelector('a[href*="worksheets"]');
            return link ? link.getAttribute('href') : null;
        }"""
    )


def _force_sidebar_visible(page: Page) -> None:
    """Make the sidebar <aside> display:flex so Playwright can click its links."""
    page.evaluate(
        """() => {
            const aside = document.getElementById('sidebar');
            if (aside) aside.style.display = 'flex';
        }"""
    )


# ---------------------------------------------------------------------------
# Tests: sidebar link href
# ---------------------------------------------------------------------------

class TestWorksheetSidebarLinks:
    """
    The Worksheets link in the student sidebar must be subject-aware:
    maths context → ?subject=mathematics, coding context → ?subject=coding,
    generic context → no query param.
    """

    @pytest.mark.django_db(transaction=True)
    def test_maths_sidebar_worksheets_link_filtered_by_mathematics(
        self,
        page: Page,
        live_server,
        enrolled_student,
        maths_worksheet_assignment,
    ):
        """
        When a student visits a /maths/ page, the sidebar Worksheets link
        href must include ?subject=mathematics.
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/maths/")
        page.wait_for_load_state("networkidle")

        href = _sidebar_worksheets_href(page)
        assert href is not None, "No Worksheets link found in sidebar on /maths/ page"
        assert "subject=mathematics" in href, (
            f"Expected ?subject=mathematics in Worksheets href on /maths/ page, got: {href}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_coding_sidebar_worksheets_link_filtered_by_coding(
        self,
        page: Page,
        live_server,
        enrolled_student,
    ):
        """
        When a student visits a /coding/ page, the sidebar Worksheets link
        href must include ?subject=coding (rendered via sidebar_coding.html).
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/coding/")
        page.wait_for_load_state("networkidle")

        href = _sidebar_worksheets_href(page)
        assert href is not None, "No Worksheets link found in sidebar on /coding/ page"
        assert "subject=coding" in href, (
            f"Expected ?subject=coding in Worksheets href on /coding/ page, got: {href}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_generic_sidebar_worksheets_link_unfiltered(
        self,
        page: Page,
        live_server,
        enrolled_student,
        maths_worksheet_assignment,
    ):
        """
        On a non-subject page (e.g. /worksheets/my/), the Worksheets link should
        have no ?subject= query param — it shows all subjects.
        Note: /hub/ uses hide_sidebar=True so no sidebar is rendered there.
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/worksheets/my/")
        page.wait_for_load_state("networkidle")

        href = _sidebar_worksheets_href(page)
        assert href is not None, "No Worksheets link found in sidebar on /worksheets/my/ page"
        assert "subject=" not in href, (
            f"Expected no ?subject= param in Worksheets href on /worksheets/my/ page, got: {href}"
        )


# ---------------------------------------------------------------------------
# Tests: list view filtering
# ---------------------------------------------------------------------------

class TestWorksheetListSubjectFilter:
    """
    The student worksheet list view filters by ?subject= correctly.
    """

    @pytest.mark.django_db(transaction=True)
    def test_maths_filter_shows_maths_worksheet(
        self,
        page: Page,
        live_server,
        enrolled_student,
        maths_worksheet_assignment,
    ):
        """
        Visiting /worksheets/my/?subject=mathematics shows the maths worksheet.
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/worksheets/my/?subject=mathematics")
        page.wait_for_load_state("networkidle")

        # Page heading should say "Maths Worksheets"
        heading = page.locator("h1").first.inner_text()
        assert "Maths" in heading, f"Expected 'Maths' in heading, got: {heading}"

        # The worksheet card should appear
        body_text = page.locator("body").inner_text()
        assert maths_worksheet_assignment.worksheet.name in body_text, (
            f"Expected worksheet name in body text"
        )

        # "← All subjects" back-link should appear since we're filtered
        back_link_href = page.evaluate(
            "() => document.querySelector('a[href$=\"/worksheets/my/\"]')?.getAttribute('href')"
        )
        assert back_link_href is not None, "Expected '← All subjects' back-link to be present"

    @pytest.mark.django_db(transaction=True)
    def test_maths_filter_hides_non_maths_worksheet(
        self,
        page: Page,
        live_server,
        enrolled_student,
        school,
        teacher_user,
        classroom,
        level,
        topic,
    ):
        """
        A worksheet flagged as coding should not appear when filtered
        by ?subject=mathematics.
        """
        from maths.models import Question
        from worksheets.models import Worksheet, WorksheetAssignment, WorksheetQuestion

        # Create a coding worksheet — uses subject_slug='coding' to simulate
        # a future coding question entry.  question FK is still non-null (Sprint 3
        # will relax this), so we use a placeholder maths Question row.
        # save() only auto-sets content_id (not subject_slug), so 'coding' is preserved.
        placeholder_q = Question.objects.create(
            level=level,
            topic=topic,
            question_text="coding placeholder",
            question_type="multiple_choice",
            difficulty=1,
            points=1,
        )

        worksheet = Worksheet.objects.create(
            school=school,
            name="Coding Only Worksheet",
            original_filename="coding.pdf",
            created_by=teacher_user,
            question_count=1,
        )
        WorksheetQuestion.objects.create(
            worksheet=worksheet,
            question=placeholder_q,
            order=1,
            subject_slug="coding",
            content_id=placeholder_q.id,
        )
        WorksheetAssignment.objects.create(
            worksheet=worksheet,
            classroom=classroom,
            is_active=True,
        )

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/worksheets/my/?subject=mathematics")
        page.wait_for_load_state("networkidle")

        # The coding worksheet should NOT appear on the maths-filtered page
        body_text = page.locator("body").inner_text()
        assert "Coding Only Worksheet" not in body_text, (
            "Coding worksheet should not appear under ?subject=mathematics filter"
        )

    @pytest.mark.django_db(transaction=True)
    def test_clicking_maths_sidebar_link_lands_on_maths_worksheet_list(
        self,
        page: Page,
        live_server,
        enrolled_student,
        maths_worksheet_assignment,
    ):
        """
        Clicking the Worksheets link on a /maths/ page navigates to the
        maths-filtered list and shows the maths worksheet.
        The sidebar is forced visible since static CSS is not served in tests.
        """
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/maths/")
        page.wait_for_load_state("networkidle")

        # Force sidebar open (hidden md:flex collapses without CSS in test env)
        _force_sidebar_visible(page)

        # Click the sidebar Worksheets link
        ws_link = page.locator("#sidebar a[href*='subject=mathematics']").first
        ws_link.click()
        page.wait_for_load_state("networkidle")

        # Should be on the filtered list page
        assert "subject=mathematics" in page.url, (
            f"Expected ?subject=mathematics in URL after clicking sidebar link, got: {page.url}"
        )
        heading = page.locator("h1").first.inner_text()
        assert "Maths" in heading, f"Expected 'Maths' in heading, got: {heading}"
        body_text = page.locator("body").inner_text()
        assert maths_worksheet_assignment.worksheet.name in body_text
