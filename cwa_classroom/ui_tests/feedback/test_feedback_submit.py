"""
Playwright UI tests for the global 'Send Feedback' capture flow (CPP-322).

One scenario per role: the launcher button is visible, opens the modal, the
form submits over HTMX, and a confirmation is shown — all without a full-page
reload.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login
from ..helpers import wait_for_htmx

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


def test_feedback_launcher_visible_on_quiz_page(
    page, live_server, monkeypatch,
    enrolled_student, school, classroom, level, topic, questions,
):
    """CPP-324 Part B: the quiz page (base_quiz.html) now carries the launcher.

    Quizzes render a minimal standalone base; the launcher was previously absent
    so a student stuck on a broken question had no way to report it. Assert the
    button is present and opens the HTMX modal on a real quiz page.
    """
    monkeypatch.setattr("random.shuffle", lambda seq: None)
    do_login(page, live_server.url, enrolled_student)
    page.goto(
        f"{live_server.url}/maths/level/{level.level_number}"
        f"/topic/{topic.id}/quiz/"
    )
    page.wait_for_load_state("domcontentloaded")

    button = page.locator("#send-feedback-btn")
    expect(button).to_be_visible()
    button.click()
    page.wait_for_selector("#feedback-form", state="attached", timeout=10_000)
    wait_for_htmx(page)
    expect(page.locator("#feedback-dropzone")).to_be_visible()


def test_bug_submit_with_screenshot(page, live_server, tmp_path, student_user):
    """CPP-324 Part A: a picked screenshot previews and uploads with the form."""
    from PIL import Image
    from feedback.models import Feedback

    shot = tmp_path / "shot.png"
    Image.new("RGB", (4, 4), "red").save(shot)

    do_login(page, live_server.url, student_user)
    page.locator("#send-feedback-btn").click()
    page.wait_for_selector("#feedback-form", state="attached", timeout=10_000)
    wait_for_htmx(page)

    page.locator("#feedback-form select[name='category']").select_option(
        "bug", force=True,
    )
    page.locator("#feedback-form textarea[name='description']").fill(
        "This question renders wrong — see screenshot.", force=True,
    )
    # The hidden input is what the paste/drag handlers feed into; setting it
    # directly exercises the same change → preview → submit path.
    page.locator("#feedback-screenshots").set_input_files(str(shot))
    expect(page.locator("#feedback-previews img")).to_be_visible()

    page.locator("#feedback-form button[type='submit']").click(force=True)
    expect(page.locator("[data-feedback-success]")).to_be_visible(timeout=10_000)

    fb = Feedback.objects.get(submitted_by=student_user)
    try:
        assert fb.images.count() == 1
    finally:
        # Don't leave the uploaded file behind in the dev media dir.
        for img in fb.images.all():
            img.image.delete(save=False)


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
