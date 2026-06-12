"""
Playwright UI tests for the global 'Send Feedback' capture flow (CPP-322).

One scenario per role: the launcher button is visible, opens the modal, the
form submits over HTMX, and a confirmation is shown — all without a full-page
reload.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import wait_for_htmx

pytestmark = pytest.mark.dashboard


def _submit_feedback(page, live_server, user, category_value: str, description: str):
    """Log in, open the feedback modal, fill it and submit."""
    do_login(page, live_server.url, user)

    button = page.locator("#send-feedback-btn")
    expect(button).to_be_visible()
    button.click()

    # HTMX lazily loads the form partial into the modal body.
    page.wait_for_selector("#feedback-form", state="attached", timeout=10_000)
    wait_for_htmx(page)

    page.locator("#feedback-form select[name='category']").select_option(
        category_value, force=True,
    )
    page.locator("#feedback-form textarea[name='description']").fill(
        description, force=True,
    )
    page.locator("#feedback-form button[type='submit']").click(force=True)

    # Success partial swaps into the same modal body — no navigation.
    expect(page.locator("[data-feedback-success]")).to_be_visible(timeout=10_000)
    expect(page.get_by_text("Thanks for your feedback")).to_be_visible()


def test_teacher_submits_bug(page, live_server, teacher_user):
    _submit_feedback(
        page, live_server, teacher_user,
        "bug", "The attendance page throws an error when I save.",
    )
    from feedback.models import Feedback
    fb = Feedback.objects.get(submitted_by=teacher_user)
    assert fb.category == Feedback.CATEGORY_BUG


def test_parent_submits_feature_request(page, live_server, parent_user):
    _submit_feedback(
        page, live_server, parent_user,
        "feature", "Please add a calendar export for my child's sessions.",
    )
    from feedback.models import Feedback
    fb = Feedback.objects.get(submitted_by=parent_user)
    assert fb.category == Feedback.CATEGORY_FEATURE


def test_student_submits_improvement(page, live_server, student_user):
    _submit_feedback(
        page, live_server, student_user,
        "improvement", "The quiz timer would be clearer in the top corner.",
    )
    from feedback.models import Feedback
    fb = Feedback.objects.get(submitted_by=student_user)
    assert fb.category == Feedback.CATEGORY_IMPROVEMENT
