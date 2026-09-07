"""
Playwright UI tests — the problem page on the shared coding window.

Like the exercise page, this had no browser coverage. It renders the window in
"editor" mode only: a problem is graded against test cases, so it reports
per-case verdicts rather than stdout and shows no console. The page keeps its
own Reset/Submit toolbar, and the window's Ctrl-Enter reaches it as
`code-window:run`.

Piston is unreachable in CI, so the submit endpoint is stubbed where a verdict
is needed; the code-reaches-the-server test reads the outgoing request instead.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def coding_problem(db, coding_language):
    from coding.models import CodingProblem, ProblemTestCase

    problem = CodingProblem.objects.create(
        language=coding_language,
        title="Sum two numbers",
        description="Read two integers and print their sum.",
        category="arrays",
        starter_code='# Read the numbers here\n',
        difficulty=1,
        is_active=True,
    )
    ProblemTestCase.objects.create(
        problem=problem, input_data="1 2", expected_output="3",
        is_visible=True, description="Simple case",
    )
    ProblemTestCase.objects.create(
        problem=problem, input_data="10 5", expected_output="15",
        is_visible=False,
    )
    return problem


def _url(live_server, problem):
    return f"{live_server.url}/coding/{problem.language.slug}/problems/{problem.pk}/"


class TestProblemDetailWindow:

    @pytest.mark.django_db(transaction=True)
    def test_editor_renders_with_the_starter_code(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-problem .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        expect(editor).to_contain_text("Read the numbers here")

    @pytest.mark.django_db(transaction=True)
    def test_no_console_is_rendered(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        """A problem is graded on test cases — a stdout pane would mislead."""
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-problem .CodeMirror")).to_be_visible(timeout=5000)

        expect(page.locator("#cw-problem .cw-stdout")).to_have_count(0)
        # …and the page's own test-case panel is still there.
        expect(page.locator("#pd-results")).to_be_attached()
        expect(page.get_by_text("Simple case")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_no_stdin_box_is_offered(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        """Test cases supply the input here — a stdin box would go nowhere."""
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-problem .CodeMirror")).to_be_visible(timeout=5000)
        expect(page.locator(".cw-stdin")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_submit_sends_the_typed_code(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        """The whole point of the migration: getCode() reads the shared window."""
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-problem .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.type("print(sum(map(int, input().split())))")

        with page.expect_request("**/coding/api/submit/**") as request_info:
            page.locator("#pd-submit-btn").click()

        payload = request_info.value.post_data_json
        assert "print(sum(map(int" in payload["code"], (
            f"the submission sent the wrong code: {payload['code']!r}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_ctrl_enter_submits(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        """The window's run shortcut is wired to this page's Submit."""
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-problem .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        editor.click()
        page.keyboard.type("print(3)")

        with page.expect_request("**/coding/api/submit/**"):
            page.keyboard.press("Control+Enter")

    @pytest.mark.django_db(transaction=True)
    def test_verdict_is_rendered_from_the_response(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        do_login(page, live_server.url, student_user)
        page.route("**/coding/api/submit/**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "passed_all": True,
                "visible_results": [
                    {"input": "1 2", "expected": "3", "actual": "3", "passed": True},
                ],
                "hidden_passed": 1, "hidden_total": 1,
                "points_earned": 10, "score": 100,
            })))
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#cw-problem .CodeMirror")).to_be_visible(timeout=5000)

        page.locator("#pd-submit-btn").click()
        expect(page.locator("#pd-verdict-title")).not_to_be_empty(timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_reset_restores_the_starter_code(
        self, page: Page, live_server, student_user, coding_problem,
    ):
        do_login(page, live_server.url, student_user)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(_url(live_server, coding_problem))
        page.wait_for_load_state("networkidle")

        editor = page.locator("#cw-problem .CodeMirror")
        expect(editor).to_be_visible(timeout=5000)
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.type("something else entirely")
        expect(editor).to_contain_text("something else")

        page.locator(".pd-reset-btn").click()
        expect(editor).to_contain_text("Read the numbers here")
