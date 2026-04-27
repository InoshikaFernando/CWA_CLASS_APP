"""
Playwright UI tests — maths homework end-to-end, used as the regression guard
for the Phase 2 subject-plugin refactor.

Covers three contract-critical paths:

  - Teacher create: submitting the form with a selected topic produces a
    Homework with HomeworkQuestion rows bound to maths.Question.
  - Student take: the take page renders one block per question with
    radio inputs for multiple_choice, and submission creates a
    HomeworkSubmission + HomeworkStudentAnswer rows with correct/incorrect
    flags set.
  - Student result: the result page shows the score card and an
    answer-review block per question (with the student's answer + the
    correct answer when wrong).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Fixtures — a ready-to-take maths homework with questions attached
# ---------------------------------------------------------------------------

@pytest.fixture
def maths_homework_ready(db, classroom, teacher_user, level, topic, questions):
    """A Homework with HomeworkQuestion rows bound to the `questions` fixture."""
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Maths E2E Regression",
        homework_type="topic",
        num_questions=len(questions),
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    for i, q in enumerate(questions):
        HomeworkQuestion.objects.create(homework=hw, question=q, order=i)
    return hw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMathsHomeworkCreate:

    @pytest.mark.django_db(transaction=True)
    def test_teacher_creates_homework_with_topic_and_questions_get_selected(
        self, page: Page, live_server, teacher_user, classroom, level, topic, questions
    ):
        """
        Teacher fills the create form, picks a topic that has maths.Questions at
        the classroom's level, submits, and ends up on a detail page for a new
        Homework with HomeworkQuestion rows attached.
        """
        from homework.models import Homework, HomeworkQuestion

        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")

        page.locator("#id_title").fill("Regression Week 1")
        due = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)

        # Tick the topic checkbox — class auto-selects a topic checkbox by value
        page.locator(f"input[name='topics'][value='{topic.pk}']").check()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Create Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        hw = Homework.objects.filter(classroom=classroom, title="Regression Week 1").first()
        assert hw is not None, "Homework row should be created"
        hw_questions = HomeworkQuestion.objects.filter(homework=hw)
        assert hw_questions.count() >= 1, "Create flow must attach at least one HomeworkQuestion"


class TestMathsHomeworkTakeAndResult:

    @pytest.mark.django_db(transaction=True)
    def test_student_sees_question_blocks_on_take_page(
        self, page: Page, live_server, enrolled_student, maths_homework_ready, questions
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{maths_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name=maths_homework_ready.title)).to_be_visible()
        # One "Question N" label per question
        for i in range(1, len(questions) + 1):
            expect(page.get_by_text(f"Question {i}", exact=True)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_student_submits_all_correct_gets_100_percent(
        self, page: Page, live_server, enrolled_student, maths_homework_ready, questions
    ):
        from homework.models import HomeworkStudentAnswer, HomeworkSubmission

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{maths_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Pick the correct answer for each question
        for q in questions:
            correct_id = q.answers.filter(is_correct=True).first().pk
            page.locator(f"#ans_{q.pk}_{correct_id}").evaluate("el => el.checked = true")

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Submit Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        sub = HomeworkSubmission.objects.filter(
            homework=maths_homework_ready, student=enrolled_student
        ).first()
        assert sub is not None
        assert sub.score == len(questions)
        assert sub.total_questions == len(questions)
        assert HomeworkStudentAnswer.objects.filter(submission=sub, is_correct=True).count() == len(questions)

    @pytest.mark.django_db(transaction=True)
    def test_result_page_shows_score_and_review(
        self, page: Page, live_server, enrolled_student, maths_homework_ready, questions
    ):
        from homework.models import HomeworkSubmission, HomeworkStudentAnswer

        # Create a pre-made submission (bypass UI — we're asserting the result view renders)
        sub = HomeworkSubmission.objects.create(
            homework=maths_homework_ready,
            student=enrolled_student,
            attempt_number=1,
            score=len(questions),
            total_questions=len(questions),
            points=50.0,
            time_taken_seconds=60,
        )
        for q in questions:
            HomeworkStudentAnswer.objects.create(
                submission=sub,
                question=q,
                selected_answer=q.answers.filter(is_correct=True).first(),
                is_correct=True,
                points_earned=1.0,
            )

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/result/{sub.pk}/")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text(re.compile(r"100%"))).to_be_visible()
        expect(page.get_by_text(re.compile(r"correct"))).to_be_visible()
        # Answer review section heading
        expect(page.get_by_role("heading", name=re.compile(r"Answer Review", re.I))).to_be_visible()


class TestMathsHomeworkAccessControl:

    @pytest.mark.django_db(transaction=True)
    def test_past_due_blocks_take(
        self, page: Page, live_server, enrolled_student, classroom, teacher_user, topic, questions
    ):
        """Taking a past-due homework redirects back to the student list with an error."""
        from homework.models import Homework, HomeworkQuestion

        hw = Homework.objects.create(
            classroom=classroom,
            created_by=teacher_user,
            title="Past Due",
            homework_type="topic",
            num_questions=len(questions),
            due_date=timezone.now() - timedelta(hours=1),
            max_attempts=1,
        )
        hw.topics.add(topic)
        for i, q in enumerate(questions):
            HomeworkQuestion.objects.create(homework=hw, question=q, order=i)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")
        # Redirected away from take page
        assert f"/homework/{hw.pk}/take/" not in page.url

    @pytest.mark.django_db(transaction=True)
    def test_not_enrolled_student_gets_404(
        self, page: Page, live_server, roles, maths_homework_ready, school
    ):
        """A student NOT enrolled in the class cannot open the take page."""
        from accounts.models import Role
        from .conftest import _make_user

        outsider = _make_user("other_student_hw", Role.STUDENT)
        do_login(page, live_server.url, outsider)
        page.goto(f"{live_server.url}/homework/{maths_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")
        # 404 page: no H1 match
        assert page.get_by_role("heading", name=maths_homework_ready.title).count() == 0
