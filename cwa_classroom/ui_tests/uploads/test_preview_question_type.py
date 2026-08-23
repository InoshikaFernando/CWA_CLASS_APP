"""Playwright UI tests — the "Question Type" dropdown on the PDF review page.

The failure this covers is one a teacher sees and a test suite can miss: a
question extracted as ``table_of_values`` rendered with the dropdown reading
**Multiple Choice** and an empty Answers list, because the hand-kept option list
behind that ``<select>`` had never gained the type. A select whose value matches
no option displays its FIRST option, and Save then wrote that value back —
losing the type and stranding the ``table_spec`` that made it gradeable.

So this drives the real page: every type the extractor can emit is selectable,
the card shows the type it was given, and a table's spec is editable rather than
replaced by an answers box it does not use.

No AI call or worker is involved — the session is created directly.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


_TABLE_SPEC = {
    "headers": ["Money value", "Decimal form"],
    "rows": [
        [{"given": "56c"}, {"answer": "0.56"}],
        [{"given": "20c"}, {"answer": "0.20"}],
    ],
    "tolerance": 0,
}


def _homework_session(user, school, question):
    from homework.models import HomeworkUploadSession

    return HomeworkUploadSession.objects.create(
        user=user, school=school, pdf_filename="money.pdf",
        # The title input is required=true — a blank one blocks the submit
        # in the browser, which is not what these tests are about.
        homework_title="Money values",
        status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
        extracted_data={
            "year_level": 4, "subject": "Mathematics", "topic": "Decimals",
            "questions": [question],
        },
        extracted_images={},
    )


def _table_question():
    return {
        "question_text": "Complete the chart by writing the decimal form of 56c and 20c.",
        "question_type": "table_of_values",
        "table_spec": _TABLE_SPEC,
        "explanation": "Cents are hundredths of a dollar.",
        "validation_type": "auto", "difficulty": 2, "points": 1,
        "answers": [], "include": True,
    }


class TestReviewPageKeepsTheExtractedType:

    @pytest.mark.django_db(transaction=True)
    def test_a_table_question_is_not_shown_as_multiple_choice(
        self, page: Page, live_server, school, teacher_user
    ):
        session = _homework_session(teacher_user, school, _table_question())
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        type_select = page.locator('select[name="q_0_type"]')
        # The whole bug in one assertion: the select's VALUE, which is what the
        # teacher reads and what Save posts back.
        expect(type_select).to_have_value("table_of_values")

        # The table is editable, and the answers box — which this type never
        # uses — is not the thing offered in its place.
        expect(page.locator('textarea[name="q_0_table_spec"]')).to_be_attached()
        expect(page.locator("#answers-row-0")).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_every_extractor_type_is_selectable(
        self, page: Page, live_server, school, teacher_user
    ):
        from worksheets.services import EXTRACTED_QUESTION_TYPES

        session = _homework_session(teacher_user, school, _table_question())
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        offered = page.locator('select[name="q_0_type"] option').evaluate_all(
            "options => options.map(o => o.value)")
        missing = [t for t in EXTRACTED_QUESTION_TYPES if t not in offered]
        assert not missing, f"types the extractor emits but the teacher cannot pick: {missing}"

    @pytest.mark.django_db(transaction=True)
    def test_saving_the_page_untouched_keeps_the_table(
        self, page: Page, live_server, school, teacher_user
    ):
        from homework.models import HomeworkUploadSession

        session = _homework_session(teacher_user, school, _table_question())
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="Continue to Confirm").click()
        page.wait_for_url(lambda url: "/confirm/" in url, timeout=15_000)

        saved = HomeworkUploadSession.objects.get(pk=session.pk).extracted_data["questions"][0]
        assert saved["question_type"] == "table_of_values"
        assert saved["table_spec"] == _TABLE_SPEC

    @pytest.mark.django_db(transaction=True)
    def test_a_choice_question_with_no_options_says_so(
        self, page: Page, live_server, school, teacher_user
    ):
        # The other half of what the teacher saw: an empty Answers list with no
        # explanation of why. A choice question with nothing to tick is broken,
        # so the page says it rather than leaving an empty box.
        question = _table_question()
        question.update(question_type="multiple_choice", table_spec=None, answers=[])
        session = _homework_session(teacher_user, school, question)
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("choice question with no options").first).to_be_visible()
