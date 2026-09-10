"""Playwright UI tests — a school with no AI module meets the PDF import screens.

Spending AI pages needs an AI module, and that is now true wherever the upload
starts. It used to be true only on the AI-import screens, so a school with no
module was locked out of that app and read unlimited PDFs through homework and
worksheets instead — every page a real Anthropic call, the counter untouched.

What the teacher should get is not a locked door. The pages open, everything
that costs no AI still works, and the PDF control says what it needs and where
to buy it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


PDF_UPLOAD_PAGES = [
    ("homework", "/homework/pdf/upload/"),
    ("worksheets", "/worksheets/upload/"),
    ("ai import", "/ai-import/upload/"),
]


def _teach_at(school, teacher):
    """Link the teacher to the school, so the quota resolves to that school.

    Without this the fixture teacher belongs to no school at all and every
    assertion below passes for the wrong reason — on the "your account is not
    linked to a school" branch rather than the "your school has no AI module"
    one they are written to check.
    """
    from classroom.models import SchoolTeacher

    SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher, defaults={"role": "teacher"},
    )


def _revoke_ai_modules(school):
    """Take the AI modules off a school the fixture granted everything to."""
    from billing.models import ModuleSubscription

    ModuleSubscription.objects.filter(
        school_subscription__school=school, module__startswith="ai_import_",
    ).update(is_active=False)


@pytest.fixture
def school_without_ai(school, teacher_user):
    _teach_at(school, teacher_user)
    _revoke_ai_modules(school)
    return school


@pytest.fixture
def school_with_ai(school, teacher_user):
    """A school on exactly one priced AI tier.

    The `school` fixture switches on every module in MODULE_CHOICES, including
    all three AI tiers, and none of them has a catalogue row. _active_tier takes
    whichever comes back first, so the school lands on an unpriced tier and is
    treated as unmetered — which is a fine answer for a school that has paid,
    but makes for a test that proves nothing. Grant one real tier instead.
    """
    from billing.testing import grant_ai_pages

    _teach_at(school, teacher_user)
    _revoke_ai_modules(school)
    grant_ai_pages(school, pages=600)
    return school


class TestNoAIModule:

    @pytest.mark.django_db(transaction=True)
    def test_every_pdf_upload_screen_opens_and_offers_the_plans(
        self, page: Page, live_server, school_without_ai, teacher_user
    ):
        """No module is not a locked door — including on AI import, which used
        to redirect to the plans page before the form was ever drawn."""
        do_login(page, str(live_server), teacher_user)

        for label, path in PDF_UPLOAD_PAGES:
            page.goto(f"{live_server}{path}")
            page.wait_for_load_state("domcontentloaded")

            assert path in page.url, f"{label}: bounced to {page.url}"
            expect(page.locator('[data-testid="no-ai-allowance"]'),
                   f"{label}: purchase panel").to_be_visible()
            expect(page.get_by_text("needs an AI module").first,
                   f"{label}: says what is needed").to_be_visible()
            # Specifically the no-module branch, not "you have no school".
            expect(page.get_by_text("Your school does not have one").first,
                   f"{label}: names the real reason").to_be_visible()

            # The PDF control is still there, and it leads to the page that
            # explains what happened rather than spending a round-trip to come
            # back with an error — or dumping the teacher on a price list with
            # no context, which was the first version of this.
            control = page.locator('[data-testid="pdf-needs-module"]')
            expect(control, f"{label}: PDF button").to_be_visible()
            href = control.get_attribute("href") or ""
            assert "/billing/ai-pages-required/" in href, f"{label}: {href}"
            # ...and it says which screen it came from, so the page can offer a
            # way back to the one the teacher was actually on.
            assert "from=" in href, f"{label}: {href}"

    @pytest.mark.django_db(transaction=True)
    def test_clicking_the_pdf_control_explains_what_happened(
        self, page: Page, live_server, school_without_ai, teacher_user
    ):
        """The click has to answer "what just happened?", not only "buy this".

        It used to go straight to the tier comparison, which is an answer to a
        question the teacher had not asked yet.
        """
        do_login(page, str(live_server), teacher_user)

        for label, path in PDF_UPLOAD_PAGES:
            page.goto(f"{live_server}{path}")
            page.wait_for_load_state("domcontentloaded")
            page.click('[data-testid="pdf-needs-module"]')
            page.wait_for_url("**/billing/ai-pages-required/**", timeout=15_000)

            expect(page.locator('[data-testid="ai-pages-required"]'),
                   f"{label}: explanation").to_be_visible()
            body = page.locator("body").inner_text()
            # What happened, what still works, and how to get it — all three,
            # because any one of them on its own leaves the teacher guessing.
            assert "needs an AI module" in body, f"{label}: {body[:300]}"
            assert "What still works without it" in body, f"{label}: {body[:300]}"
            expect(page.locator('[data-testid="see-ai-plans"]'),
                   f"{label}: plans link").to_be_visible()
            # And a way back to the screen they were on, not just to "/".
            back = page.locator('[data-testid="ai-pages-required-back"]')
            expect(back, f"{label}: back link").to_be_visible()
            assert back.get_attribute("href") == path, label

    @pytest.mark.django_db(transaction=True)
    def test_the_meter_is_not_drawn_as_an_empty_bar(
        self, page: Page, live_server, school_without_ai, teacher_user
    ):
        """A 0/0 bar and a 'resets on the 1st' would both be lies here."""
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/upload/")
        page.wait_for_load_state("domcontentloaded")

        body = page.locator("body").inner_text()
        assert "0/0 pages" not in body, body[:300]
        assert "resets" not in body.lower(), body[:300]

    @pytest.mark.django_db(transaction=True)
    def test_authored_json_upload_is_untouched(
        self, page: Page, live_server, school_without_ai, teacher_user
    ):
        """A hand-authored file makes no AI call, so it is not gated."""
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/upload/")
        page.wait_for_load_state("domcontentloaded")

        json_input = page.locator('input[name="json_file"]')
        expect(json_input).to_be_attached()
        expect(page.get_by_role("button", name="Upload questions")).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_a_school_with_a_module_gets_the_meter_and_a_working_button(
        self, page: Page, live_server, school_with_ai, teacher_user
    ):
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/upload/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.locator('[data-testid="no-ai-allowance"]')).to_have_count(0)
        expect(page.locator('[data-testid="pdf-needs-module"]')).to_have_count(0)
        expect(page.locator("#submit-btn")).to_be_visible()
        expect(page.get_by_text("0/600 pages").first).to_be_visible()
