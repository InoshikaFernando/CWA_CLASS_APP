"""
Playwright UI tests — the Scratch exercise page.

Untestable until now: Blockly came from unpkg, which the sandbox blocks, so no
workspace ever mounted and every assertion about it was guesswork. Blockly is
vendored now, so the block path can finally be driven for real.

Scratch is the one exercise language with no text editor. Its blocks generate
Python, which is what runs — so the page keeps the shared window's console
(cw_panes="console") and drives it with runWith().
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def scratch_exercise(db):
    from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel

    language = CodingLanguage.objects.create(
        name="Scratch", slug=CodingLanguage.SCRATCH, order=5, is_active=True,
    )
    topic = CodingTopic.objects.create(
        language=language, name="Blocks", slug="blocks", order=1, is_active=True,
    )
    level, _ = TopicLevel.get_or_create_for(topic, TopicLevel.BEGINNER)
    return CodingExercise.objects.create(
        topic_level=level,
        title="Say hello with blocks",
        description="Drag a print block into the workspace.",
        expected_output="hello",
        question_type=CodingExercise.WRITE_CODE,
        is_active=True,
    )


def _url(live_server, exercise):
    return (f"{live_server.url}/coding/"
            f"{exercise.topic_level.topic.language.slug}/exercise/{exercise.pk}/")


class TestScratchExercise:

    @pytest.mark.django_db(transaction=True)
    def test_blockly_workspace_mounts(
        self, page: Page, live_server, student_user, scratch_exercise,
    ):
        """The vendored Blockly loads and injects a workspace."""
        do_login(page, live_server.url, scratch_exercise and student_user)
        page.goto(_url(live_server, scratch_exercise))
        page.wait_for_load_state("networkidle")

        expect(page.locator("#blocklyDiv .blocklySvg")).to_be_visible(timeout=10000)
        assert page.evaluate("typeof Blockly !== 'undefined'"), "Blockly did not load"

    @pytest.mark.django_db(transaction=True)
    def test_toolbox_icons_are_served_locally(
        self, page: Page, live_server, student_user, scratch_exercise,
    ):
        """Blockly's media must come from static/, not the remote demo host.

        Left unpinned the workspace still appears and only the icons are
        missing, which is exactly the kind of failure nobody reports.
        """
        remote = []
        page.on("request", lambda r: remote.append(r.url)
                if "blockly-demo.appspot.com" in r.url else None)

        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, scratch_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#blocklyDiv .blocklySvg")).to_be_visible(timeout=10000)

        assert not remote, f"Blockly fetched media from the demo host: {remote}"

    @pytest.mark.django_db(transaction=True)
    def test_page_has_a_console_but_no_text_editor(
        self, page: Page, live_server, student_user, scratch_exercise,
    ):
        do_login(page, live_server.url, student_user)
        page.goto(_url(live_server, scratch_exercise))
        page.wait_for_load_state("networkidle")

        expect(page.locator("#cw-output .cw-stdout")).to_be_visible()
        expect(page.locator("#cw-editor")).to_have_count(0)

    @pytest.mark.django_db(transaction=True)
    def test_running_sends_generated_python_and_blocks_xml(
        self, page: Page, live_server, student_user, scratch_exercise,
    ):
        """Blocks → generated Python → console, the path I could not run before.

        A block is placed through Blockly's own API rather than by dragging:
        the drag is Blockly's behaviour to test, the generated code reaching
        the server is ours.
        """
        do_login(page, live_server.url, student_user)
        page.route("**/coding/api/run/", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"stdout": "hello", "stderr": "", "exit_code": 0,
                             "exercise_has_expected": True, "exercise_score": 100})))

        page.goto(_url(live_server, scratch_exercise))
        page.wait_for_load_state("networkidle")
        expect(page.locator("#blocklyDiv .blocklySvg")).to_be_visible(timeout=10000)

        # Drop a print("hello") block into the workspace.
        page.evaluate("""
            const xml = Blockly.Xml.textToDom(
              '<xml><block type="text_print"><value name="TEXT">'
              + '<block type="text"><field name="TEXT">hello</field></block>'
              + '</value></block></xml>');
            Blockly.Xml.domToWorkspace(xml, workspace);
        """)
        expect(page.locator("#sc-generated-code")).to_contain_text("print", timeout=5000)

        with page.expect_request("**/coding/api/run/") as request_info:
            page.locator("#ed-run-btn").click()

        payload = request_info.value.post_data_json
        assert "print" in payload["code"], (
            f"generated Python did not reach the server: {payload['code']!r}"
        )
        assert payload.get("blocks_xml"), "the blocks XML was not sent alongside"

        expect(page.locator("#cw-output .cw-stdout")).to_contain_text("hello")
        expect(page.locator("#ed-score-result")).to_contain_text("100%", timeout=5000)
