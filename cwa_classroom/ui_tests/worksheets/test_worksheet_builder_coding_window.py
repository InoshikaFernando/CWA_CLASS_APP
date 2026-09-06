"""
Playwright UI tests — the live coding window in the worksheet builder's preview.

A teacher building a coding worksheet used to see a coding exercise as static
text: starter code in a <pre>, expected output in another, and no way to run it.
Previewing one now opens the same editor-and-console window the student gets,
wired to a teacher-only runner that records nothing, so the exercise can be
checked before it goes onto a worksheet.

These tests drive the real page: open the builder, switch the subject filter to
Coding, click a coding exercise, and assert the window mounts and works.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")


@pytest.fixture
def coding_exercise(db, coding_topic_level):
    """A global Python write-code exercise the builder will list."""
    from coding.models import CodingExercise

    return CodingExercise.objects.create(
        topic_level=coding_topic_level,
        title="Print a greeting",
        description="Print the words hello world, exactly as shown.",
        starter_code='# Write your code below\nname = "world"\n',
        expected_output="hello world",
        solution_code='name = "world"\nprint(f"hello {name}")\n',
        question_type=CodingExercise.WRITE_CODE,
        is_active=True,
    )


def _go_to_builder(page: Page) -> None:
    """Reach the builder the way a teacher does — by clicking the sidebar.

    Deliberately no page.goto(): typing the URL would pass even if the sidebar
    entry did not exist, and for a long time it did not. The builder's only way
    in was a button on the Worksheets page, so a teacher who did not already
    know the page was there could not find it.
    """
    page.get_by_role("link", name="Worksheet Builder").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("select#filter-subject")).to_be_visible(timeout=10000)


def _open_coding_preview(page: Page) -> None:
    """From the builder, filter to Coding and open an exercise's preview."""

    # Subject → Coding swaps the cascade (topic/level/type selects), which in
    # turn reloads the question list. Wait for a coding card rather than for a
    # particular request, so the test does not encode that request order.
    page.locator("select#filter-subject").select_option("coding")

    card = page.locator('#question-list .question-card[data-subject-slug="coding"]').first
    expect(card).to_be_visible(timeout=15000)
    card.click()

    expect(page.locator("#preview-modal")).to_be_visible(timeout=10000)


class TestBuilderCodingWindow:

    @pytest.mark.django_db(transaction=True)
    def test_preview_opens_the_coding_window(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """Editor and console both render, with the starter code loaded."""
        do_login(page, live_server.url, teacher_user)
        _go_to_builder(page)
        _open_coding_preview(page)

        window = page.locator("#preview-modal [data-code-window]")
        expect(window).to_be_visible()

        # CodeMirror mounted (the plain textarea is replaced by .CodeMirror)
        # and it holds the exercise's starter code.
        expect(window.locator(".CodeMirror")).to_be_visible(timeout=5000)
        expect(window.locator(".CodeMirror")).to_contain_text('name = "world"')

        # Console beside it, plus the exercise's expected output to check against.
        expect(window.locator(".cw-stdout")).to_be_visible()
        expect(window.locator(".cw-run")).to_be_visible()
        expect(window.locator(".cw-expected")).to_contain_text("hello world")

    @pytest.mark.django_db(transaction=True)
    def test_editor_is_typable(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """A window that mounts while its modal is hidden must still work.

        CodeMirror measures itself on mount; mounted inside the hidden modal it
        renders a zero-height box that looks like a broken page until the
        builder refreshes it. This is the regression guard for that refresh.
        """
        do_login(page, live_server.url, teacher_user)
        _go_to_builder(page)
        _open_coding_preview(page)

        editor = page.locator("#preview-modal .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)

        box = editor.bounding_box()
        assert box is not None and box["height"] > 50, (
            f"editor collapsed to {box['height'] if box else 'nothing'}px — "
            "CodeWindow.refreshAll() did not run after the modal was shown"
        )

        editor.click()
        page.keyboard.type('print("hi")')
        expect(editor).to_contain_text('print("hi")')

    @pytest.mark.django_db(transaction=True)
    def test_run_posts_to_the_teacher_endpoint(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """Run must hit api_preview_run — api_run_code would score a submission.

        Piston is not reachable in CI, so the request is intercepted: what is
        under test is which endpoint the window calls and that the reply lands
        in the console, not the sandbox itself.
        """
        do_login(page, live_server.url, teacher_user)

        def _fake_run(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"stdout": "hello world", "stderr": "", "exit_code": 0}',
            )

        page.route("**/coding/api/preview-run/", _fake_run)

        _go_to_builder(page)
        _open_coding_preview(page)

        with page.expect_request("**/coding/api/preview-run/"):
            page.locator("#preview-modal .cw-run").click()

        expect(page.locator("#preview-modal .cw-stdout")).to_contain_text(
            "hello world", timeout=5000)
        # Output matched the exercise's expected output — say so.
        expect(page.locator("#preview-modal .cw-match")).to_contain_text("matches")

    @pytest.mark.django_db(transaction=True)
    def test_load_solution_fills_the_editor(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """One click to check the reference solution against expected output."""
        do_login(page, live_server.url, teacher_user)
        _go_to_builder(page)
        _open_coding_preview(page)

        page.locator("#preview-modal .cw-load").click()
        expect(page.locator("#preview-modal .CodeMirror")).to_contain_text(
            'print(f"hello {name}")')

    @pytest.mark.django_db(transaction=True)
    def test_add_to_worksheet_still_works_from_the_preview(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """The window is an addition to the preview, not a replacement."""
        do_login(page, live_server.url, teacher_user)
        _go_to_builder(page)
        _open_coding_preview(page)

        page.locator("#preview-modal .preview-add-btn").click()
        expect(page.locator("#sidebar-question-list")).to_contain_text(
            "Print a greeting", timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_capture_preview_screenshots(
        self, page: Page, live_server, teacher_user, classroom, coding_exercise,
    ):
        """Not an assertion — writes ui_tests/screenshots/ for design review.

        Two frames: the preview as it opens, and the same window after a run.
        Piston is unreachable in CI, so the run's reply is stubbed — the layout
        is what these images are for, not the sandbox.
        """
        page.set_viewport_size({"width": 1440, "height": 1000})
        do_login(page, live_server.url, teacher_user)

        page.route("**/coding/api/preview-run/", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"stdout": "hello world", "stderr": "", "exit_code": 0}',
        ))

        _go_to_builder(page)
        _open_coding_preview(page)
        expect(page.locator("#preview-modal .CodeMirror")).to_be_visible(timeout=5000)
        page.wait_for_timeout(400)

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "builder_coding_window.png"),
            full_page=False,
        )

        page.locator("#preview-modal .cw-load").click()
        page.locator("#preview-modal .cw-run").click()
        expect(page.locator("#preview-modal .cw-match")).to_contain_text(
            "matches", timeout=5000)
        page.wait_for_timeout(200)
        page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, "builder_coding_window_after_run.png"),
            full_page=False,
        )
