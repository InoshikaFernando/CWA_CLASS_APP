"""
Playwright UI tests — the exercise page on the shared coding window.

This page had no browser coverage at all, which is part of why nobody noticed
it was fetching CodeMirror from a CDN. It builds the window in two halves —
console on the left beside the exercise text, editor on the right — and keeps
its own Run button, score card and mark-complete state machine, driven by the
`code-window:result` event the window dispatches after each run.

Piston is unreachable in CI, so the run endpoint is stubbed: what these tests
cover is the page's wiring, not the sandbox.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def python_exercise(db, coding_topic_level):
    from coding.models import CodingExercise

    return CodingExercise.objects.create(
        topic_level=coding_topic_level,
        title="Print a greeting",
        description="Print the word hello.",
        starter_code='# Write your solution here\n',
        expected_output="hello",
        hints="Use print().",
        question_type=CodingExercise.WRITE_CODE,
        is_active=True,
    )


@pytest.fixture
def dom_exercise(db, coding_topic_level):
    """A DOM exercise — renders in the browser, never reaches Piston."""
    from coding.models import CodingExercise

    return CodingExercise.objects.create(
        topic_level=coding_topic_level,
        title="Build a heading",
        description="Show an h1.",
        starter_code='<h1>Hello</h1>\n',
        question_type=CodingExercise.WRITE_CODE,
        uses_browser_sandbox=True,
        is_active=True,
    )


def _url(live_server, exercise):
    language = exercise.topic_level.topic.language
    return f"{live_server.url}/coding/{language.slug}/exercise/{exercise.pk}/"


def _stub_run(page, body):
    page.route("**/coding/api/run/", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(body)))


class TestExerciseDetailWindow:

    @pytest.mark.django_db(transaction=True)
    def test_editor_and_console_both_render(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-editor .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        expect(editor).to_contain_text("Write your solution here")
        expect(page.locator("#cw-output .cw-stdout")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_run_sends_the_typed_code_and_shows_output(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        do_login(page, live_server.url, student_user)
        _stub_run(page, {"stdout": "hello", "stderr": "", "exit_code": 0,
                         "exercise_has_expected": True, "exercise_score": 100})
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-editor .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.type('print("hello")')

        with page.expect_request("**/coding/api/run/") as request_info:
            page.locator("#ed-run-btn").click()

        payload = request_info.value.post_data_json
        assert 'print("hello")' in payload["code"], (
            f"the run sent the wrong code: {payload['code']!r}"
        )
        assert payload["exercise_id"] == python_exercise.pk

        expect(page.locator("#cw-output .cw-stdout")).to_contain_text("hello")

    @pytest.mark.django_db(transaction=True)
    def test_matching_output_scores_and_completes_the_exercise(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        """The score card and mark-complete button read the server's verdict."""
        do_login(page, live_server.url, student_user)
        _stub_run(page, {"stdout": "hello", "stderr": "", "exit_code": 0,
                         "exercise_has_expected": True, "exercise_score": 100})
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-editor .CodeMirror")).to_be_visible(timeout=5000)

        page.locator("#ed-run-btn").click()

        expect(page.locator("#ed-score-result")).to_contain_text("100%", timeout=5000)
        expect(page.locator("#ed-mark-btn")).to_contain_text("completed")
        expect(page.locator(".ed-done-badge")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_non_matching_output_does_not_complete_the_exercise(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        do_login(page, live_server.url, student_user)
        _stub_run(page, {"stdout": "nope", "stderr": "", "exit_code": 0,
                         "exercise_has_expected": True, "exercise_score": 0})
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-editor .CodeMirror")).to_be_visible(timeout=5000)

        page.locator("#ed-run-btn").click()

        expect(page.locator("#ed-score-result")).to_contain_text("0%", timeout=5000)
        expect(page.locator("#ed-mark-btn")).not_to_contain_text("completed")
        expect(page.locator(".ed-done-badge")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_stderr_is_shown(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        do_login(page, live_server.url, student_user)
        _stub_run(page, {"stdout": "", "stderr": "NameError: name 'x'",
                         "exit_code": 1, "exercise_has_expected": True,
                         "exercise_score": 0})
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-editor .CodeMirror")).to_be_visible(timeout=5000)

        page.locator("#ed-run-btn").click()
        expect(page.locator("#cw-output .cw-stderr")).to_contain_text("NameError", timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_the_result_is_reported_once(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        """The page has its own score card; the window must not say it too."""
        do_login(page, live_server.url, student_user)
        _stub_run(page, {"stdout": "hello", "stderr": "", "exit_code": 0,
                         "exercise_has_expected": True, "exercise_score": 100})
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-editor .CodeMirror")).to_be_visible(timeout=5000)

        page.locator("#ed-run-btn").click()
        expect(page.locator("#ed-score-result")).to_contain_text("100%", timeout=5000)
        expect(page.locator("#cw-output .cw-match")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_no_stdin_box_is_offered(
        self, page: Page, live_server, student_user, python_exercise,
    ):
        """This page never piped stdin; an inert box would only mislead."""
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, python_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-editor .CodeMirror")).to_be_visible(timeout=5000)
        expect(page.locator(".cw-stdin")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_dom_exercise_previews_in_the_browser_without_a_server_call(
        self, page: Page, live_server, student_user, dom_exercise,
    ):
        """A browser-sandbox exercise renders locally — no console, no request."""
        calls = []
        page.route("**/coding/api/run/", lambda route: (calls.append(1), route.abort()))

        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, dom_exercise))
        page.wait_for_load_state("networkidle")

        expect(page.locator("#cw-preview-output")).to_be_visible()
        expect(page.locator("#cw-output .cw-stdout")).to_have_count(0)

        page.locator("#ed-run-btn").click()
        page.wait_for_timeout(500)

        frame = page.frame_locator("#cw-preview-output")
        expect(frame.locator("h1")).to_contain_text("Hello")
        assert not calls, "a browser-sandbox exercise must not call the run endpoint"
