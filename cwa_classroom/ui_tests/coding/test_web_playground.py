"""
Playwright UI tests — the HTML / CSS / JS playground.

The web playground used to be two panes. JavaScript did run if a student typed
a <script> tag inside the HTML, but there was nowhere to write it properly and
no starter to copy. It has three panes now, assembled into one page: the CSS
goes in the head, the JS just before </body> so it runs against parsed markup.

Everything here happens in the browser — this playground never calls the
server, which is the other thing worth pinning down.

Nothing here waits on "networkidle" before an expect(). c54a0cd took that wait
out of the Scratch tests after two CI timeouts and left these files alone,
"worth revisiting if they ever flake"; test_verdict_is_rendered_from_the_response
then timed out at 30s on a release run whose tree had passed this same group
twenty minutes earlier. These pages mount CodeMirror and the vendored editor
assets, so "no request for 500ms" is a coin toss on a slow runner — and the
expect() that followed was already waiting for the editor, which is the thing
each test actually needs. The waits that remain are the ones doing real work:
before a bare assert, before an action, or at the tail of a helper.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


PLAYGROUND = "/coding/playground/html-css/"


def _open(page: Page, live_server, user):
    do_login(page, live_server.url, user)
    page.goto(f"{live_server.url}{PLAYGROUND}")
    expect(page.locator("[data-code-window] .CodeMirror").first).to_be_visible(timeout=5000)


def _type_into(page: Page, tab: str, text: str):
    """Switch to a pane and replace its contents (an empty string clears it).

    Select-all then type only replaces when there is something to type, so the
    delete is explicit — otherwise "clear this pane" silently leaves the
    starter code behind.
    """
    page.locator(f'.cw-tab[data-cw-tab="{tab}"]').click()
    editor = page.locator(f".cw-host-{tab} .CodeMirror")
    expect(editor).to_be_visible()
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    if text:
        page.keyboard.type(text)


class TestWebPlayground:

    @pytest.mark.django_db(transaction=True)
    def test_three_tabs_are_offered(self, page: Page, live_server, student_user):
        _open(page, live_server, student_user)
        for tab in ("html", "css", "js"):
            expect(page.locator(f'.cw-tab[data-cw-tab="{tab}"]')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_the_toolbar_does_not_overlap_itself(
        self, page: Page, live_server, student_user,
    ):
        """A third tab must not slide under the Reset/Run buttons.

        It did: the toolbar was a single non-wrapping row, which fit two tabs
        and not three, and Playwright still called the hidden tab "visible".
        """
        page.set_viewport_size({"width": 1440, "height": 1000})
        _open(page, live_server, student_user)

        tab = page.locator('.cw-tab[data-cw-tab="js"]').bounding_box()
        for other in (".cw-reset", ".cw-run"):
            box = page.locator(other).bounding_box()
            assert tab and box
            overlaps = (tab["x"] < box["x"] + box["width"]
                        and box["x"] < tab["x"] + tab["width"]
                        and tab["y"] < box["y"] + box["height"]
                        and box["y"] < tab["y"] + tab["height"])
            assert not overlaps, f"script.js tab overlaps {other}"

    @pytest.mark.django_db(transaction=True)
    def test_switching_tabs_shows_the_right_editor(
        self, page: Page, live_server, student_user,
    ):
        _open(page, live_server, student_user)

        page.locator('.cw-tab[data-cw-tab="js"]').click()
        expect(page.locator(".cw-host-js")).to_be_visible()
        expect(page.locator(".cw-host-html")).to_be_hidden()
        expect(page.locator(".cw-file-label")).to_have_text("script.js")

        page.locator('.cw-tab[data-cw-tab="css"]').click()
        expect(page.locator(".cw-host-css")).to_be_visible()
        expect(page.locator(".cw-host-js")).to_be_hidden()
        expect(page.locator(".cw-file-label")).to_have_text("style.css")

    @pytest.mark.django_db(transaction=True)
    def test_javascript_runs_against_the_page(
        self, page: Page, live_server, student_user,
    ):
        """The script must land after the markup, or every DOM lookup is null.

        This is the whole reason the script goes before </body> rather than in
        the head — a student's querySelector has to find the element they just
        wrote in the HTML pane.
        """
        _open(page, live_server, student_user)

        _type_into(page, "html", '<div id="target">before</div>')
        _type_into(page, "js", 'document.getElementById("target").textContent = "after";')

        page.locator(".cw-run").click()

        frame = page.frame_locator(".cw-preview")
        expect(frame.locator("#target")).to_have_text("after", timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_css_still_applies_alongside_the_script(
        self, page: Page, live_server, student_user,
    ):
        _open(page, live_server, student_user)

        _type_into(page, "html", '<p id="p">styled</p>')
        _type_into(page, "css", "#p { color: rgb(255, 0, 0); }")
        _type_into(page, "js", 'document.getElementById("p").dataset.ran = "yes";')

        page.locator(".cw-run").click()

        frame = page.frame_locator(".cw-preview")
        target = frame.locator("#p")
        expect(target).to_have_attribute("data-ran", "yes", timeout=5000)
        assert target.evaluate("el => getComputedStyle(el).color") == "rgb(255, 0, 0)"

    @pytest.mark.django_db(transaction=True)
    def test_an_empty_js_pane_adds_no_script_tag(
        self, page: Page, live_server, student_user,
    ):
        """Blank JS must not leave an empty <script> in the student's page."""
        _open(page, live_server, student_user)

        _type_into(page, "html", "<p>plain</p>")
        _type_into(page, "js", "")
        page.locator(".cw-run").click()

        frame = page.frame_locator(".cw-preview")
        expect(frame.locator("p")).to_have_text("plain", timeout=5000)
        assert frame.locator("script").count() == 0

    @pytest.mark.django_db(transaction=True)
    def test_nothing_is_sent_to_the_server(
        self, page: Page, live_server, student_user,
    ):
        """A web page renders in the browser; Piston is not involved."""
        calls = []
        page.route("**/coding/api/**", lambda route: (calls.append(route.request.url), route.abort()))

        _open(page, live_server, student_user)
        _type_into(page, "js", 'console.log("hi");')
        page.locator(".cw-run").click()
        page.wait_for_timeout(500)

        assert not calls, f"the web playground called the server: {calls}"

    @pytest.mark.django_db(transaction=True)
    def test_reset_restores_all_three_panes(
        self, page: Page, live_server, student_user,
    ):
        _open(page, live_server, student_user)
        page.on("dialog", lambda dialog: dialog.accept())

        _type_into(page, "js", "// wiped")
        _type_into(page, "html", "<p>wiped</p>")

        page.locator(".cw-reset").click()

        expect(page.locator(".cw-host-html .CodeMirror")).to_contain_text("Hello, world!")
        page.locator('.cw-tab[data-cw-tab="js"]').click()
        expect(page.locator(".cw-host-js .CodeMirror")).to_contain_text("addEventListener")
