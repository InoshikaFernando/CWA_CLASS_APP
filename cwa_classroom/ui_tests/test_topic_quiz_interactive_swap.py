"""Playwright UI test — interactive question types must work as question #2+.

Regression for the bug where ``submitLongDivision`` / ``submitColumnOperation``
/ ``submitPrimeFactorization`` were defined inside inline <script> blocks in the
swapped-in partial. ``_loadNext()`` advances the quiz with
``#question-container.innerHTML = html``, and per the HTML spec <script> tags
inserted via innerHTML do NOT execute. So whenever one of these types was the
first of its kind to appear *after* a swap, clicking Submit threw a
ReferenceError and the answer never posted — and the per-cell auto-advance focus
was dead too.

The fix moves all submit/focus wiring into the persistent ``topic_quiz.html``
base script, re-bound by ``_initQuestion()`` after every swap. This test drives a
real quiz where a ``long_division`` question is #2 and a ``column_operation``
question is #3 (both reached only via a swap) and asserts both submit cleanly,
grade correct, advance, and raise no uncaught page errors.

Ordering is made deterministic by neutralising the view's ``random.shuffle`` and
giving the three questions ascending ``difficulty`` (the queryset orders by
``[level, difficulty, created_at]``).
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


@pytest.fixture
def swap_questions(db, level, topic):
    """MC (#1) → long_division (#2) → prime_factorization (#3) → column_operation
    (#4), in that fixed order. Only #1 is server-rendered; the three interactive
    types are each reached via an innerHTML swap."""
    from maths.models import Answer, Question

    mc = Question.objects.create(
        level=level, topic=topic,
        question_text="What is 2 + 2?",
        question_type=Question.MULTIPLE_CHOICE,
        difficulty=1, points=1,
    )
    Answer.objects.create(question=mc, answer_text="4", is_correct=True, order=0)
    Answer.objects.create(question=mc, answer_text="5", is_correct=False, order=1)

    long_div = Question.objects.create(
        level=level, topic=topic,
        question_text="Divide 84 by 4.",
        question_type=Question.LONG_DIVISION,
        difficulty=2, points=1,
        dividend=84, divisor=4,
    )
    Answer.objects.create(question=long_div, answer_text="21", is_correct=True, order=0)

    prime = Question.objects.create(
        level=level, topic=topic,
        question_text="Find the prime factors of 12.",
        question_type=Question.PRIME_FACTORIZATION,
        difficulty=3, points=1,
        target_number=12,
    )
    Answer.objects.create(question=prime, answer_text="2x2x3", is_correct=True, order=0)

    col_op = Question.objects.create(
        level=level, topic=topic,
        question_text="Add 45 and 27.",
        question_type=Question.COLUMN_OPERATION,
        difficulty=4, points=1,
        operands=[45, 27], operator="+",
    )
    Answer.objects.create(question=col_op, answer_text="72", is_correct=True, order=0)

    return {"mc": mc, "long_div": long_div, "prime": prime, "col_op": col_op}


class TestInteractiveQuestionSwap:

    @pytest.mark.django_db(transaction=True)
    def test_interactive_types_submit_after_swap(
        self, page: Page, live_server, monkeypatch,
        enrolled_student, school, classroom, level, topic, swap_questions,
    ):
        from maths.models import StudentAnswer

        # Freeze question order: keep DB order (level, difficulty, created_at).
        # live_server runs in this same process, so patching the module the view
        # calls (``random.shuffle``) reaches the request thread.
        monkeypatch.setattr("random.shuffle", lambda seq: None)

        # Collect uncaught JS errors — a ReferenceError from the onclick handler
        # would surface here before the fix.
        page_errors: list[str] = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        do_login(page, live_server.url, enrolled_student)
        page.goto(
            f"{live_server.url}/maths/level/{level.level_number}"
            f"/topic/{topic.id}/quiz/"
        )
        page.wait_for_load_state("domcontentloaded")

        # ── Question #1: multiple choice (server-rendered) ──
        expect(page.locator("#question-card")).to_contain_text("What is 2 + 2?")
        page.locator(".answer-btn", has_text="4").first.click()
        next_btn = page.get_by_role("button", name=re.compile(r"Next Question"))
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

        # ── Question #2: long_division — reached ONLY via an innerHTML swap ──
        expect(page.locator("#question-card")).to_contain_text("Divide 84 by 4.")
        quotient_cells = page.locator('input[data-ld="quotient"]')
        expect(quotient_cells).to_have_count(2)

        # Auto-advance focus must be live on the swapped-in question: typing the
        # first quotient digit should move focus to the second cell.
        quotient_cells.nth(0).click()
        page.keyboard.type("2")
        active_pos = page.evaluate(
            "() => document.activeElement.getAttribute('data-pos')"
        )
        assert active_pos == "1", (
            "Focus should auto-advance to the 2nd quotient cell after typing the "
            f"first digit on a swapped-in question; active data-pos={active_pos!r}"
        )
        page.keyboard.type("1")  # quotient = 21, exact (no remainder)

        page.locator('button[onclick*="submitLongDivision"]').click()

        # Submit worked → feedback renders. Before the fix this never appeared
        # (ReferenceError: submitLongDivision is not defined).
        expect(page.locator("#question-card")).to_contain_text("Correct", timeout=10_000)
        next_btn = page.get_by_role("button", name=re.compile(r"Next Question"))
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

        # ── Question #3: prime_factorization — also reached via a swap ──
        expect(page.locator("#question-card")).to_contain_text("Find the prime factors of 12.")
        prime_cells = page.locator('input[data-pf="prime"]')
        expect(prime_cells).to_have_count(3)
        for i, digit in enumerate(("2", "2", "3")):
            prime_cells.nth(i).fill(digit)
        # Live preview is wired by _initQuestion() on the swapped-in node.
        expect(page.locator("#pf-preview")).to_have_value("2×2×3")

        page.locator('button[onclick*="submitPrimeFactorization"]').click()
        expect(page.locator("#question-card")).to_contain_text("Correct", timeout=10_000)
        next_btn = page.get_by_role("button", name=re.compile(r"Next Question"))
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

        # ── Question #4: column_operation — also reached via a swap (and last) ──
        expect(page.locator("#question-card")).to_contain_text("Add 45 and 27.")
        answer_cells = page.locator('input[data-ca="answer"]')
        expect(answer_cells).to_have_count(2)
        answer_cells.nth(0).fill("7")
        answer_cells.nth(1).fill("2")  # answer = 72

        page.locator('button[onclick*="submitColumnOperation"]').click()
        expect(page.locator("#question-card")).to_contain_text("Correct", timeout=10_000)
        # Last question → the advance button reads "View Results".
        expect(
            page.get_by_role("button", name=re.compile(r"View Results"))
        ).to_be_visible()

        # No uncaught JS errors anywhere in the flow.
        assert not page_errors, f"Uncaught page errors during quiz: {page_errors}"

        # Both swapped-in interactive answers actually posted and graded correct.
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=swap_questions["long_div"],
            is_correct=True,
        ).exists(), "long_division answer did not post / grade after the swap"
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=swap_questions["prime"],
            is_correct=True,
        ).exists(), "prime_factorization answer did not post / grade after the swap"
        assert StudentAnswer.objects.filter(
            student=enrolled_student,
            question=swap_questions["col_op"],
            is_correct=True,
        ).exists(), "column_operation answer did not post / grade after the swap"
