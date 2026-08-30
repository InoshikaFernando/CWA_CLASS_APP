"""Playwright UI test — "Preview as student" in the global question bank.

The admin question bank shows what is STORED: the text, the type, the ticked
answer. What decides whether a question is any good is what a child MEETS —
the options they can pick and whether the marker accepts a sensible answer.
The three PDF review screens already have that button for a question being
imported; these are the questions that already reached children.

Two things this proves that no server-side test can:

* the button reaches the real endpoint through the shared preview modal, from
  the listing row AND from inside the edit modal (two different openers, one
  modal, one page), and
* previewing an edit that is still unsaved shows the EDIT — and leaves the
  stored question exactly as it was. A preview that quietly saved would be far
  worse than no preview at all.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

BANK_URL = "/admin-dashboard/global-questions/"


@pytest.fixture
def global_question(db, level, topic):
    """A global (school=NULL) multiple-choice question, as the bank holds them."""
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text="What is 7 + 8?",
        question_type=Question.MULTIPLE_CHOICE,
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=q, answer_text="15", is_correct=True, order=0)
    Answer.objects.create(question=q, answer_text="14", is_correct=False, order=1)
    return q


@pytest.fixture
def bank(live_server, page, admin_user, global_question):
    do_login(page, live_server.url, admin_user)
    page.goto(f"{live_server.url}{BANK_URL}")
    page.wait_for_load_state("networkidle")
    return global_question


def _row(page, question):
    return page.locator(f"#question-row-{question.id}")


def _preview(page):
    return page.locator("#student-preview")


class TestPreviewFromTheListing:

    def test_the_row_opens_the_student_view(self, page, bank):
        _row(page, bank).locator("[data-testid='preview-as-student']").click()

        preview = _preview(page)
        expect(preview).to_be_visible()
        expect(preview.get_by_text("As a student sees it")).to_be_visible()
        # The real take partial: the question, and an option to pick.
        expect(preview.get_by_text("What is 7 + 8?")).to_be_visible()
        expect(preview.locator("label", has_text="15")).to_be_visible()

    def test_an_answer_is_marked_by_the_real_grader(self, page, bank):
        _row(page, bank).locator("[data-testid='preview-as-student']").click()
        preview = _preview(page)
        expect(preview).to_be_visible()

        preview.locator("label", has_text="15").click()
        preview.get_by_role("button", name="Mark my answer").click()

        expect(preview.locator("[data-preview-result='correct']")).to_be_visible()

    def test_it_closes_again(self, page, bank):
        _row(page, bank).locator("[data-testid='preview-as-student']").click()
        preview = _preview(page)
        expect(preview).to_be_visible()

        preview.locator("[data-preview-close]").last.click()
        expect(preview).to_be_hidden()


class TestPreviewFromTheEditor:

    def _open_editor(self, page, question):
        _row(page, question).get_by_role("button", name="Edit").click()
        expect(page.locator("#question-edit-form")).to_be_visible()

    def test_the_editor_previews_the_unsaved_edit(self, page, bank):
        self._open_editor(page, bank)
        page.fill("textarea[name='question_text']", "What is 8 + 8?")

        page.locator("#edit-modal [data-testid='preview-as-student']").click()

        preview = _preview(page)
        expect(preview).to_be_visible()
        # The edit in front of them, not the row on disk.
        expect(preview.get_by_text("What is 8 + 8?")).to_be_visible()

    def test_previewing_does_not_save(self, page, bank):
        self._open_editor(page, bank)
        page.fill("textarea[name='question_text']", "What is 8 + 8?")
        page.locator("#edit-modal [data-testid='preview-as-student']").click()
        expect(_preview(page).get_by_text("What is 8 + 8?")).to_be_visible()

        bank.refresh_from_db()
        assert bank.question_text == "What is 7 + 8?"
        assert sorted(a.answer_text for a in bank.answers.all()) == ["14", "15"]

    def test_an_unsaved_new_option_is_previewed(self, page, bank):
        self._open_editor(page, bank)
        page.get_by_test_id("add-answer").click()
        page.fill("input[name='new_answer_text_1']", "16")

        page.locator("#edit-modal [data-testid='preview-as-student']").click()

        preview = _preview(page)
        expect(preview.locator("label", has_text="16")).to_be_visible()
        assert bank.answers.count() == 2
