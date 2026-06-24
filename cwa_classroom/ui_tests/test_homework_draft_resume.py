"""Playwright UI test — resuming a saved homework draft preserves construction-
style maths answers through submit.

Regression guard for the resume→submit data-loss bug: long-division /
prime-factorisation (and the other interactive maths widgets) only save their
final synthesised answer, not the individual working cells. On resume the cells
came back blank, and each widget's on-submit handler then rebuilt the hidden
answer from those empty cells — silently wiping the student's work at submit.

The fix rehydrates each widget's working from the restored hidden value on load
(``window.__hwRehydrateMaths``), so a resumed answer is both visible and
survives the on-submit rebuild. These tests prove a student can save, reopen,
and submit WITHOUT re-entering the working, and still be graded correct.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


@pytest.fixture
def construction_homework(db, classroom, teacher_user, level, topic):
    """A homework with one long-division and one prime-factorisation question."""
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Question

    long_div = Question.objects.create(
        level=level, topic=topic,
        question_text="Divide 48 by 4.",
        question_type=Question.LONG_DIVISION,
        difficulty=1, points=1,
        dividend=48, divisor=4,           # quotient 12, remainder 0 → "12"
    )
    prime_fac = Question.objects.create(
        level=level, topic=topic,
        question_text="Find the prime factors of 12.",
        question_type=Question.PRIME_FACTORIZATION,
        difficulty=1, points=1,
        target_number=12,                 # 2 × 2 × 3 → "2x2x3"
    )

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Resume Construction E2E",
        homework_type="topic",
        num_questions=2,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    HomeworkQuestion.objects.create(homework=hw, question=long_div, order=0)
    HomeworkQuestion.objects.create(homework=hw, question=prime_fac, order=1)
    return hw, long_div, prime_fac


class TestDraftResumeConstructionWidgets:

    @pytest.mark.django_db(transaction=True)
    def test_resume_rehydrates_cells_and_submit_preserves_answers(
        self, page: Page, live_server, enrolled_student, construction_homework
    ):
        from homework.models import (
            HomeworkDraft,
            HomeworkStudentAnswer,
            HomeworkSubmission,
        )

        hw, long_div, prime_fac = construction_homework

        # The student saved correct answers earlier — only the final hidden
        # values are stored, exactly as the live widget sync produces them.
        HomeworkDraft.objects.create(
            homework=hw,
            student=enrolled_student,
            answers_data={
                f"answer_{long_div.id}": "12",
                f"answer_{prime_fac.id}": "2x2x3",
            },
            time_taken_seconds=90,
        )

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Resume rebuilt the on-screen working from the saved answer:
        # long division — quotient digits right-aligned into the cells ("1","2")…
        ld_cells = page.locator(f"input[data-ld-q='{long_div.id}']")
        expect(ld_cells).to_have_count(2)
        expect(ld_cells.nth(0)).to_have_value("1")
        expect(ld_cells.nth(1)).to_have_value("2")
        # …prime factorisation — the prime ladder inputs ("2","2","3").
        pf_cells = page.locator(f"input[data-pf-p='{prime_fac.id}']")
        expect(pf_cells.nth(0)).to_have_value("2")
        expect(pf_cells.nth(1)).to_have_value("2")
        expect(pf_cells.nth(2)).to_have_value("3")

        # Submit WITHOUT touching the cells — the answers must survive the
        # widgets' on-submit rebuild.
        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=hw, student=enrolled_student
        ).first()
        assert sub is not None
        ld_ans = HomeworkStudentAnswer.objects.get(submission=sub, question=long_div)
        pf_ans = HomeworkStudentAnswer.objects.get(submission=sub, question=prime_fac)
        assert ld_ans.is_correct is True, ld_ans.text_answer
        assert pf_ans.is_correct is True, pf_ans.text_answer

        # Submitting clears the draft (so the list no longer offers "Resume").
        assert not HomeworkDraft.objects.filter(
            homework=hw, student=enrolled_student
        ).exists()
