"""Playwright UI test — global topic/subtopic on the worksheet preview page.

Setting the global topic should default every question to it (questions stay
individually overridable). Leaving it blank keeps per-question topics.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _ready_session(teacher_user, school, level, n=2):
    from worksheets.models import WorksheetUploadSession

    questions = [
        {
            "include": True,
            "question_text": f"Question {i}",
            "question_type": "short_answer",
            "difficulty": 1,
            "points": 1,
            "year_level": level.level_number,
            "topic": "",
            "subtopic": "",
            "subject": "Mathematics",
            "answers": [],
        }
        for i in range(n)
    ]
    return WorksheetUploadSession.objects.create(
        user=teacher_user,
        school=school,
        pdf_filename="ws.pdf",
        worksheet_name="WS",
        status=WorksheetUploadSession.STATUS_READY,
        extracted_data={
            "year_level": level.level_number,
            "subject": "Mathematics",
            "questions": questions,
        },
    )


class TestWorksheetGlobalTopic:

    @pytest.mark.django_db(transaction=True)
    def test_global_topic_applies_to_all_questions(
        self, page: Page, live_server, school, teacher_user, subject, level
    ):
        from classroom.models import Topic

        algebra = Topic.objects.create(
            subject=subject, name="Algebra", slug="algebra-gt", is_active=True, order=1,
        )
        Topic.objects.create(
            subject=subject, parent=algebra, name="Quadratics",
            slug="quadratics-gt", is_active=True, order=1,
        )
        session = _ready_session(teacher_user, school, level)

        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/worksheets/upload/{session.pk}/preview/")
        page.wait_for_load_state("domcontentloaded")

        # Both questions start with no topic.
        expect(page.locator("input[name='q_0_topic']")).to_have_value("")
        expect(page.locator("input[name='q_1_topic']")).to_have_value("")

        # Set the global topic → both questions adopt it.
        page.locator("[data-testid='global-topic']").select_option("Algebra")
        expect(page.locator("input[name='q_0_topic']")).to_have_value("Algebra")
        expect(page.locator("input[name='q_1_topic']")).to_have_value("Algebra")

        # A per-question override still wins (change Q2's topic select back to none).
        # The first question's per-question topic <select> sits in its picker.
        q1_topic_select = page.locator("#q-1 select").filter(has=page.locator("option[value='__new__']")).first
        q1_topic_select.select_option("")
        expect(page.locator("input[name='q_1_topic']")).to_have_value("")
        # Q1 unchanged — still Algebra.
        expect(page.locator("input[name='q_0_topic']")).to_have_value("Algebra")
