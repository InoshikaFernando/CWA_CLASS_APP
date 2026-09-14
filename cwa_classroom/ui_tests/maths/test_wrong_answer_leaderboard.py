"""The "most often answered wrong" panel on the question-health dashboard.

The deterministic audits on that page read the question's stored data. This
panel reads the ANSWERS, which is the only place a quietly-wrong answer key
shows up at all: the question passes every check and goes on marking child
after child wrong.

These tests drive the real page — the rate is shown, the question is previewed
as a student meets it, it is opened in the editor, and the Reviewed verdict
takes it off the list in front of the person who gave it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

pytestmark = pytest.mark.dashboard

HEALTH_URL = "/admin-dashboard/question-health/"


@pytest.fixture
def badly_answered_question(db, level, topic):
    """A global question six children in a row have been marked wrong on."""
    from django.contrib.auth import get_user_model

    from maths.models import Answer, Question, StudentAnswer

    question = Question.objects.create(
        level=level, topic=topic, school=None,
        question_text="Write 666 in expanded form",
        question_type="multiple_choice", difficulty=1, points=1,
    )
    chosen = Answer.objects.create(question=question,
                                   answer_text="600 + 60 + 6",
                                   is_correct=False, order=0)
    Answer.objects.create(question=question, answer_text="6 + 6 + 6",
                          is_correct=True, order=1)

    user_model = get_user_model()
    for index in range(6):
        student = user_model.objects.create_user(
            username=f"leaderboard_kid_{index}",
            email=f"lk{index}@test.local", password="ui-test-pass-123")
        StudentAnswer.objects.create(
            student=student, question=question, selected_answer=chosen,
            is_correct=False, attempt_id=uuid.uuid4())
    return question


def _open_health_page(page, live_server, user):
    do_login(page, live_server.url, user)
    page.goto(f"{live_server.url}{HEALTH_URL}")
    page.wait_for_load_state("domcontentloaded")


def test_the_question_is_listed_with_its_wrong_answer_rate(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    _open_health_page(page, live_server, superuser)

    row = page.locator(f"#wrong-rate-row-{badly_answered_question.id}")
    expect(row).to_be_visible()
    expect(row.locator("[data-testid='wrong-rate-percent']")).to_have_text("100%")
    # The rate alone could be one child answering once, so the row must also
    # say how many answers it is built on.
    expect(row).to_contain_text("6 wrong of 6")


def test_preview_as_student_opens_the_question_as_a_child_meets_it(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    _open_health_page(page, live_server, superuser)

    row = page.locator(f"#wrong-rate-row-{badly_answered_question.id}")
    row.locator("[data-testid='wrong-rate-preview']").click()

    preview = page.locator("#student-preview")
    expect(preview).to_be_visible()
    expect(preview).to_contain_text("Write 666 in expanded form")
    # Not the stored row dumped on screen — the options as a child picks them.
    expect(preview).to_contain_text("600 + 60 + 6")


def test_modify_opens_the_editor_for_that_question(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    _open_health_page(page, live_server, superuser)

    row = page.locator(f"#wrong-rate-row-{badly_answered_question.id}")
    row.locator("[data-testid='wrong-rate-edit']").click()

    modal = page.locator("#edit-modal-content")
    expect(modal).to_contain_text(
        f"Edit Question #{badly_answered_question.id}")


def test_fixing_the_answer_key_gives_the_marks_back(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    """The half of the repair the editor never did.

    Six children picked "600 + 60 + 6" and were marked wrong by a key that had
    the wrong option ticked. Correcting the key must not only fix the question
    from now on — it must re-mark what is already recorded, or every one of
    them keeps the nought in their history.
    """
    from maths.models import Answer, StudentAnswer

    _open_health_page(page, live_server, superuser)
    page.locator(f"#wrong-rate-row-{badly_answered_question.id}"
                 ).locator("[data-testid='wrong-rate-edit']").click()
    expect(page.locator("#edit-modal-content")).to_contain_text("Edit Question")

    # Opened from this page, the re-mark tick arrives already ticked: the
    # question is on this list precisely because children lost marks to it.
    expect(page.locator("[data-testid='regrade-answers']")).to_be_checked()

    right = Answer.objects.get(question=badly_answered_question,
                               answer_text="600 + 60 + 6")
    wrong = Answer.objects.get(question=badly_answered_question,
                               answer_text="6 + 6 + 6")
    page.locator(f"input[name='is_correct_{right.id}']").check()
    page.locator(f"input[name='is_correct_{wrong.id}']").uncheck()
    page.locator("#question-edit-form button[type='submit']").click()

    # Visible, not merely rendered: the modal used to close in the same frame
    # this notice arrived in, so nobody ever read it.
    note = page.locator("[data-testid='regraded-note']")
    expect(note).to_be_visible()
    expect(note).to_contain_text("now marked correct")

    assert StudentAnswer.objects.filter(
        question=badly_answered_question, is_correct=True).count() == 6


def test_the_re_mark_is_opt_in_from_the_question_bank(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    """The same editor, opened from the bank, leaves children's records alone.

    This is the narrowing: re-marking is the leaderboard's job, not a
    consequence of pressing Save wherever the editor happens to be opened.
    """
    from maths.models import Answer, StudentAnswer

    do_login(page, live_server.url, superuser)
    page.goto(f"{live_server.url}/admin-dashboard/global-questions/"
              f"?edit={badly_answered_question.id}")
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("#edit-modal-content")).to_contain_text("Edit Question")

    expect(page.locator("[data-testid='regrade-answers']")).not_to_be_checked()

    right = Answer.objects.get(question=badly_answered_question,
                               answer_text="600 + 60 + 6")
    wrong = Answer.objects.get(question=badly_answered_question,
                               answer_text="6 + 6 + 6")
    page.locator(f"input[name='is_correct_{right.id}']").check()
    page.locator(f"input[name='is_correct_{wrong.id}']").uncheck()
    page.locator("#question-edit-form button[type='submit']").click()

    expect(page.locator("#edit-saved")).to_contain_text("Saved")

    # The question is fixed; the six recorded marks are untouched.
    right.refresh_from_db()
    assert right.is_correct
    assert StudentAnswer.objects.filter(
        question=badly_answered_question, is_correct=True).count() == 0


def test_reviewed_takes_it_off_the_list(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    from maths.models import QuestionReview

    _open_health_page(page, live_server, superuser)

    row = page.locator(f"#wrong-rate-row-{badly_answered_question.id}")
    row.locator("[data-testid='wrong-rate-reviewed']").click()

    expect(page.locator(
        f"#wrong-rate-row-{badly_answered_question.id}")).to_have_count(0)
    # And it says what was recorded, rather than the row simply vanishing.
    expect(page.locator("[data-testid='wrong-rate-notice']")).to_contain_text(
        "reviewed and correct")

    review = QuestionReview.objects.get(question=badly_answered_question)
    assert review.verdict == QuestionReview.VERDICT_CORRECT
    assert review.reviewed_by == superuser


def test_a_verdict_given_by_mistake_can_be_undone_from_the_page(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    """The way back from one click on the wrong row.

    Marking a question "Reviewed — correct" takes it off this list, which is
    the point of the verdict; but it also takes it off the only surface that
    showed it, so before the undo strip a misclick had nowhere to be seen and
    no way back. Undo must delete the verdict, not write a second one over it:
    a "needs fixing" verdict settles the past answers just the same and would
    leave the question off the list — the mistake made permanent.
    """
    from maths.models import QuestionReview

    _open_health_page(page, live_server, superuser)
    page.locator(f"#wrong-rate-row-{badly_answered_question.id}"
                 ).locator("[data-testid='wrong-rate-reviewed']").click()

    # Gone from the list, but listed as just reviewed — with the question text,
    # so it can be re-read without hunting for it.
    strip = page.locator(f"#recent-review-{badly_answered_question.id}")
    expect(strip).to_be_visible()
    expect(strip).to_contain_text("Write 666 in expanded form")

    strip.locator("[data-testid='recent-review-undo']").click()

    expect(page.locator("[data-testid='wrong-rate-notice']")).to_contain_text(
        "Undone")
    # Back on the list with every answer counting again, and the verdict gone
    # rather than replaced.
    expect(page.locator(
        f"#wrong-rate-row-{badly_answered_question.id}")).to_be_visible()
    assert not QuestionReview.objects.filter(
        question=badly_answered_question).exists()


def test_the_row_shows_what_the_children_actually_answered(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    """The half of the diagnosis the percentage cannot give.

    Six children were marked wrong. That they all picked the SAME option is
    what says the answer key is at fault rather than the children, and it is
    unreadable from "100%" alone.
    """
    _open_health_page(page, live_server, superuser)

    row = page.locator(f"#wrong-rate-row-{badly_answered_question.id}")
    given = row.locator("[data-testid='wrong-rate-given']")
    expect(given).to_contain_text("600 + 60 + 6")
    expect(given).to_contain_text("×6")
    # And what it would have accepted instead, side by side with it.
    expect(row.locator("[data-testid='wrong-rate-expected']")).to_contain_text(
        "6 + 6 + 6")


def test_the_bands_count_every_ranked_question_not_just_the_ten_listed(
    page, live_server, superuser, subject, level, topic, badly_answered_question,
):
    _open_health_page(page, live_server, superuser)

    bands = page.locator("[data-testid='wrong-rate-bands']")
    expect(bands).to_be_visible()
    expect(bands).to_contain_text("Always wrong")
    expect(page.locator("[data-testid='wrong-rate-ranked-total']")
           ).to_have_text("1")
