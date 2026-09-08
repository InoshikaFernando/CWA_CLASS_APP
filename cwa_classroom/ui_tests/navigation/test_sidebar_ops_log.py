"""The application log page — reachable, superuser-only, and it shows the error.

The page exists because Stripe told us exactly what was wrong with a student's
checkout ("The price specified is inactive") and that sentence lived only in
/var/log/cwa/django-error.log, where finding it took an SSH session and a grep
two weeks later.

So the thing worth driving through a browser is the journey a superuser takes
at 11pm when a parent says payment is broken: sidebar → Logs → search → read
what the server actually said.
"""
import re
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ..conftest import do_login
from ..helpers import assert_sidebar_has_link, assert_sidebar_missing_link

pytestmark = pytest.mark.sidebar

REAL_ERROR = (
    '[2026-09-07 23:23:35,968] ERROR accounts.views views:1082 — Stripe '
    'checkout session creation failed for user 804: The price specified is '
    'inactive. This field only accepts active prices.'
)
UNRELATED = (
    '[2026-09-07 09:00:00,000] ERROR worksheets.views views:12 — something else'
)


@pytest.fixture
def log_dir(settings):
    """A real log directory with real files, as the server would have."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'django-error.log').write_text(
            UNRELATED + '\n' + REAL_ERROR + '\n')
        settings.LOG_DIR = path
        yield path


class TestOpsLogSidebar:

    def test_logs_link_hidden_for_regular_admin(
        self, live_server, page, admin_user, school,
    ):
        """Logs carry emails, usernames and request paths."""
        do_login(page, live_server.url, admin_user)
        page.goto(f"{live_server.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        assert_sidebar_missing_link(page, "Logs")

    def test_logs_link_visible_for_superuser(
        self, live_server, page, superuser, school,
    ):
        do_login(page, live_server.url, superuser)
        page.goto(f"{live_server.url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(page, "Logs")


class TestOpsLogPage:

    def test_superuser_reads_what_stripe_actually_said(
        self, live_server, page, superuser, school, log_dir,
    ):
        do_login(page, live_server.url, superuser)
        page.goto(f"{live_server.url}/admin-dashboard/ops/logs/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator("h1")).to_contain_text("Application Log")
        expect(page.locator("[data-testid='log-entries']")).to_contain_text(
            "The price specified is inactive")
        expect(page.locator("[data-testid='log-entries']")).to_contain_text(
            "accounts.views")

    def test_search_narrows_to_the_failure(
        self, live_server, page, superuser, school, log_dir,
    ):
        do_login(page, live_server.url, superuser)
        page.goto(f"{live_server.url}/admin-dashboard/ops/logs/")
        page.locator("input[name='q']").fill("inactive")
        page.get_by_role("button", name=re.compile("Apply")).click()
        page.wait_for_load_state("domcontentloaded")

        entries = page.locator("[data-testid='log-entries']")
        expect(entries).to_contain_text("The price specified is inactive")
        expect(entries).not_to_contain_text("something else")

    def test_reachable_from_the_ops_dashboard(
        self, live_server, page, superuser, school, log_dir,
    ):
        do_login(page, live_server.url, superuser)
        page.goto(f"{live_server.url}/admin-dashboard/ops/")
        page.wait_for_load_state("domcontentloaded")
        page.locator("[data-testid='ops-log-link']").click()
        expect(page).to_have_url(re.compile(r"/admin-dashboard/ops/logs/"))

    def test_empty_state_explains_itself_rather_than_looking_healthy(
        self, live_server, page, superuser, school, settings,
    ):
        """An empty page must not read the same as 'nothing is wrong'."""
        with tempfile.TemporaryDirectory() as tmp:
            settings.LOG_DIR = Path(tmp)
            do_login(page, live_server.url, superuser)
            page.goto(f"{live_server.url}/admin-dashboard/ops/logs/")
            page.wait_for_load_state("domcontentloaded")
            expect(page.locator("[data-testid='log-empty']")).to_contain_text(
                "nothing has been written")
