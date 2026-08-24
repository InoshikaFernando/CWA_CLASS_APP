"""Playwright UI test — a partly-right chart is marked partly right.

The reported case: a money chart ("write the decimal form of each money
value") with one cell wrong scored zero and told the student "Not quite
right", naming nothing. A question that asks for several values is now marked
one value at a time, and this drives that end to end on the worksheet session:
the student fills the chart, gets one cell wrong, and the feedback panel that
replaces #answer-area must say it was partly correct, say how much of it was
right, and name the cell that cost the mark.

The JS half matters as much as the grading half: the cells are collected into a
hidden field by static/js/table_of_values.js through the shared maths_mounts.js
registry. If that never mounts the field stays empty, every cell reads as blank
and partial credit has nothing to work with — which no server-side test would
catch.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login
from .test_worksheet_session import _make_session_assignment

# Four rows, one answer cell each — the shape of the reported chart.
MONEY_SPEC = {
    'headers': ['Money value (¢)', 'Decimal form'],
    'rows': [
        [{'given': '56'}, {'answer': '0.56'}],
        [{'given': '84'}, {'answer': '0.84'}],
        [{'given': '7'}, {'answer': '0.07'}],
        [{'given': '96'}, {'answer': '0.96'}],
    ],
}


def _open_chart(page, live_server, student, school, teacher_user, level, topic, classroom):
    assignment, question = _make_session_assignment(
        'table_of_values', school, teacher_user, level, topic, classroom, student,
        question_text='Write the decimal form of each money value.',
        table_spec=MONEY_SPEC,
    )
    do_login(page, live_server.url, student)
    page.goto(f"{live_server.url}/worksheets/assignments/{assignment.pk}/session/")
    page.wait_for_load_state('networkidle')
    return assignment, question


def _fill_and_submit(page, values):
    cells = page.locator('[data-tv-cell]')
    expect(cells.first).to_be_visible(timeout=5000)
    for index, value in enumerate(values):
        cells.nth(index).fill(value)
    with page.expect_response(lambda r: '/answer/' in r.url and r.status == 200):
        page.locator("form[hx-post] button[type='submit']").click()
    return page.locator('#answer-area')


class TestWorksheetPartialCredit:

    @pytest.mark.django_db(transaction=True)
    def test_one_wrong_cell_is_marked_partly_correct(
        self, page: Page, live_server,
        enrolled_student, school, teacher_user, level, topic, classroom,
    ):
        _open_chart(page, live_server, enrolled_student,
                    school, teacher_user, level, topic, classroom)

        feedback = _fill_and_submit(page, ['0.56', '0.84', '0.70', '0.96'])

        expect(feedback).to_contain_text('Partially correct', timeout=6000)
        expect(feedback).to_contain_text('3 of the 4 cells are right.')
        # The mark, in points, on the same panel as the words.
        expect(feedback).to_contain_text('Worth 0.75 of 1 point')
        # And the cell that cost it, by the row the student can see.
        expect(feedback).to_contain_text('Decimal form for 7')
        expect(feedback).to_contain_text('0.07')
        # Not the flat rejection this used to be.
        expect(feedback).not_to_contain_text('Not quite right')

    @pytest.mark.django_db(transaction=True)
    def test_the_score_the_student_sees_is_the_score_that_is_stored(
        self, page: Page, live_server,
        enrolled_student, school, teacher_user, level, topic, classroom,
    ):
        _, question = _open_chart(page, live_server, enrolled_student,
                                  school, teacher_user, level, topic, classroom)

        _fill_and_submit(page, ['0.56', '0.84', '0.70', '0.96'])

        from worksheets.models import WorksheetStudentAnswer
        row = WorksheetStudentAnswer.objects.get(content_id=question.pk)
        assert row.is_correct is False        # full marks means every cell
        assert row.points_earned == 0.75
        assert row.answer_data['parts_correct'] == 3

    @pytest.mark.django_db(transaction=True)
    def test_every_cell_right_is_still_plain_correct(
        self, page: Page, live_server,
        enrolled_student, school, teacher_user, level, topic, classroom,
    ):
        _open_chart(page, live_server, enrolled_student,
                    school, teacher_user, level, topic, classroom)

        feedback = _fill_and_submit(page, ['0.56', '0.84', '0.07', '0.96'])

        expect(feedback).to_contain_text('Correct!', timeout=6000)
        expect(feedback).not_to_contain_text('Partially correct')
