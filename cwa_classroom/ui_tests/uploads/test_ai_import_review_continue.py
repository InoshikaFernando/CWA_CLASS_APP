"""Playwright UI test — the AI-import review page's structured-spec panels.

Same failure as the homework PDF review page: every card renders all eight
structured-spec panels hidden so the type dropdown can reveal one without a
reload, and a browser posts every ENABLED field, shown or not — so a long
import crossed Django's request-parser field ceiling and "Save & Continue"
came back as a bare ``Bad Request (400)``.

The panels that don't apply are now disabled. This is the browser half of that:
the disabling is only safe if switching a question's type re-enables the panel
it switched to, and this page carries its own copy of ``handleTypeChange``
(a different template, a different script) from the homework one.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


def _session(user):
    from ai_import.models import AIImportSession

    return AIImportSession.objects.create(
        user=user, pdf_filename="w.pdf",
        status=AIImportSession.STATUS_READY, is_confirmed=False,
        extracted_data={
            'year_level': 4, 'subject': 'Mathematics', 'strand': 'Number',
            'topic': 'Mixed',
            'questions': [{
                'question_text': 'How many?', 'question_type': 'short_answer',
                'difficulty': 1, 'points': 1,
                'answers': [{'text': '4', 'is_correct': True}],
            }],
        },
        extracted_images={},
    )


class TestAIImportReviewPanels:

    @pytest.mark.django_db(transaction=True)
    def test_switching_type_enables_that_panel_and_the_edit_saves(
        self, page: Page, live_server, superuser
    ):
        session = _session(superuser)
        do_login(page, str(live_server), superuser)
        page.goto(f"{live_server}/ai-import/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        # A short answer edits none of the spec panels, so none of them post.
        number_line = page.locator('textarea[name="q_0_number_line_spec"]')
        expect(number_line).to_be_disabled()

        page.select_option('select[name="q_0_type"]', 'number_line')
        expect(number_line).to_be_enabled()
        number_line.fill('{"min": 0, "max": 10, "step": 1, '
                         '"mode": "mark", "target": [4]}')

        page.click('button[type="submit"]:has-text("Save & Continue")')
        page.wait_for_load_state("networkidle")

        assert 'Bad Request' not in page.locator('body').inner_text()
        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        assert saved['question_type'] == 'number_line'
        assert saved['number_line_spec']['target'] == [4]

    @pytest.mark.django_db(transaction=True)
    def test_the_hidden_twin_panel_does_not_overwrite_the_visible_one(
        self, page: Page, live_server, superuser
    ):
        """The graph and measure panels share three field names.

        Both enabled, both pre-filled from the same stored value, the POST
        carried each name twice — and a QueryDict keeps the LAST value, so the
        measure panel (rendered second, hidden on a read_graph question) beat
        what the teacher had just typed into the graph panel.
        """
        session = _session(superuser)
        do_login(page, str(live_server), superuser)
        page.goto(f"{live_server}/ai-import/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.select_option('select[name="q_0_type"]', 'read_graph')
        graph_panel = page.locator('#graph-section-0')
        graph_panel.locator('input[name="q_0_numeric_answer"]').fill('135')
        graph_panel.locator('input[name="q_0_answer_tolerance"]').fill('5')

        page.click('button[type="submit"]:has-text("Save & Continue")')
        page.wait_for_load_state("networkidle")

        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        assert saved['numeric_answer'] == '135', saved
        assert saved['answer_tolerance'] == '5', saved
