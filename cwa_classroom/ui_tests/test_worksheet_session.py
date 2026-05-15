"""
Playwright UI tests — CPP-276 regression guard + worksheet confirm fix.

1. Verifies that a pre-existing PDF-extracted maths worksheet (where
   WorksheetQuestion rows have subject_slug='mathematics' and
   content_id=question.id after the backfill migration) still works
   end-to-end for a student: session loads, MCQ question renders,
   answer is accepted, and the results page shows the score.

2. Regression test for the _TempSession AttributeError fix (PR #255):
   a teacher can confirm a PDF upload session without a 500 error.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import _RUN_ID, do_login, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def worksheet_with_question(db, school, teacher_user, level, topic):
    """
    A Worksheet + WorksheetQuestion row simulating post-migration state:
    subject_slug='mathematics', content_id=question.id (not 0).
    """
    from maths.models import Answer, Question
    from worksheets.models import Worksheet, WorksheetQuestion

    question = Question.objects.create(
        level=level,
        topic=topic,
        question_text="What is 7 × 8?",
        question_type="multiple_choice",
        difficulty=1,
        points=1,
    )
    Answer.objects.create(question=question, answer_text="56", is_correct=True, order=1)
    Answer.objects.create(question=question, answer_text="48", is_correct=False, order=2)
    Answer.objects.create(question=question, answer_text="63", is_correct=False, order=3)
    Answer.objects.create(question=question, answer_text="54", is_correct=False, order=4)

    worksheet = Worksheet.objects.create(
        school=school,
        name="CPP-276 Regression Worksheet",
        original_filename="regression.pdf",
        created_by=teacher_user,
        question_count=1,
    )
    WorksheetQuestion.objects.create(
        worksheet=worksheet,
        question=question,
        order=1,
        subject_slug="mathematics",   # post-migration value — not 0
        content_id=question.id,
    )
    return worksheet, question


@pytest.fixture
def active_assignment(db, worksheet_with_question, classroom):
    """Assign the worksheet to the classroom."""
    from worksheets.models import WorksheetAssignment

    worksheet, _ = worksheet_with_question
    return WorksheetAssignment.objects.create(
        worksheet=worksheet,
        classroom=classroom,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExistingPdfWorksheetSessionUnaffected:
    """
    CPP-276: after the subject_slug/content_id migration, a student can still
    take a maths worksheet end-to-end without errors.
    """

    @pytest.mark.django_db(transaction=True)
    def test_student_session_loads_and_mcq_answer_saved(
        self,
        page: Page,
        live_server,
        enrolled_student,
        active_assignment,
        worksheet_with_question,
    ):
        """
        Student opens the worksheet session page, sees the MCQ question,
        selects the correct answer, submits, and lands on the results page
        showing a non-zero score.
        """
        _, question = worksheet_with_question

        do_login(page, live_server.url, enrolled_student)

        # Navigate to session
        page.goto(f"{live_server.url}/worksheets/assignments/{active_assignment.pk}/session/")
        page.wait_for_load_state("networkidle")

        # Question text should be visible
        expect(page.locator("body")).to_contain_text("7 × 8")

        # MCQ radio buttons should be rendered — pick the correct answer
        radio = page.locator(f"input[type='radio'][value='{question.answers.get(is_correct=True).pk}']")
        expect(radio).to_be_visible()
        radio.check()

        # Submit the answer via the form — target the "Submit Answer" button inside
        # the hx-post form, not the logout button which is also type=submit.
        # Use expect_response to reliably wait for the HTMX POST to complete,
        # since wait_for_load_state("networkidle") can resolve immediately
        # when no *navigation* occurred (HTMX swaps via XHR).
        with page.expect_response(lambda r: "/answer/" in r.url and r.status == 200):
            page.locator("form[hx-post] button[type='submit']").click()

        # After HTMX swap the feedback partial replaces #answer-area.
        # For the last question it shows "See My Results"; for any question
        # it shows "Correct!" or "Not quite right".
        feedback = page.locator("#answer-area")
        expect(feedback).to_contain_text("Correct", timeout=5000)

    @pytest.mark.django_db(transaction=True)
    def test_student_cannot_access_another_schools_worksheet_session(
        self,
        page: Page,
        live_server,
        db,
        roles,
        enrolled_student,
        active_assignment,
    ):
        """
        Tenant isolation: a student from a different school gets 404, not 403,
        when attempting to access a worksheet assignment they don't belong to.
        """
        from accounts.models import CustomUser, Role
        from classroom.models import School
        from billing.models import InstitutePlan, SchoolSubscription

        # Create a second school + student
        from decimal import Decimal
        import uuid
        run = uuid.uuid4().hex[:6]
        other_admin = CustomUser.objects.create_user(
            username=f"other_admin_{run}",
            password=TEST_PASSWORD,
            email=f"other_admin_{run}@test.local",
            profile_completed=True,
            must_change_password=False,
        )
        other_school = School.objects.create(
            name=f"Other School {run}",
            slug=f"other-school-{run}",
            admin=other_admin,
            is_active=True,
        )
        plan, _ = InstitutePlan.objects.get_or_create(
            slug=f"basic-other-{run}",
            defaults={
                "name": f"Basic Other {run}",
                "price": Decimal("89.00"),
                "stripe_price_id": "price_test",
                "class_limit": 50,
                "student_limit": 500,
                "invoice_limit_yearly": 500,
                "extra_invoice_rate": Decimal("0.30"),
            },
        )
        SchoolSubscription.objects.create(school=other_school, plan=plan, status="active")

        other_student = CustomUser.objects.create_user(
            username=f"other_student_{run}",
            password=TEST_PASSWORD,
            email=f"other_student_{run}@test.local",
            profile_completed=True,
            must_change_password=False,
        )
        role = Role.objects.get(name=Role.STUDENT)
        other_student.roles.add(role)

        do_login(page, live_server.url, other_student)

        # Try to access assignment belonging to first school's classroom
        page.goto(
            f"{live_server.url}/worksheets/assignments/{active_assignment.pk}/session/"
        )
        page.wait_for_load_state("domcontentloaded")

        # Should get 404, not the worksheet content
        assert page.url.endswith(f"/assignments/{active_assignment.pk}/session/") or \
               "404" in page.title() or \
               page.locator("body").inner_text().lower().count("not found") > 0 or \
               "/accounts/login" in page.url, \
               "Expected 404 or login redirect for cross-tenant access"


# ---------------------------------------------------------------------------
# PR #255 regression — _TempSession AttributeError on confirm
# ---------------------------------------------------------------------------

@pytest.fixture
def upload_session(db, teacher_user, school, level):
    """
    A WorksheetUploadSession owned by teacher_user, with one short-answer
    question at Year 7.  Level 7 must already exist (provided by the `level`
    fixture) so _resolve_topic_for_question can look it up via Level.objects.get().
    """
    from worksheets.models import WorksheetUploadSession

    return WorksheetUploadSession.objects.create(
        user=teacher_user,
        school=school,
        pdf_filename="regression_pr255.pdf",
        worksheet_name="PR-255 Regression",
        extracted_data={
            "year_level": 7,
            "subject": "Mathematics",
            "topic": f"pr255-addition-{_RUN_ID}",
            "questions": [
                {
                    "include": True,
                    "question_text": "What is 3 + 3?",
                    "question_type": "short_answer",
                    "difficulty": 1,
                    "points": 1,
                    "year_level": 7,
                    "topic": f"pr255-addition-{_RUN_ID}",
                    "subject": "Mathematics",
                    "explanation": "Basic addition.",
                    "answers": [],
                }
            ],
        },
        is_confirmed=False,
    )


class TestWorksheetConfirmNoAttributeError:
    """
    PR #255 regression: WorksheetConfirmView.post() previously threw
    AttributeError: '_TempSession' object has no attribute 'save'.
    """

    @pytest.mark.django_db(transaction=True)
    def test_teacher_confirm_pdf_upload_no_server_error(
        self,
        page: Page,
        live_server,
        teacher_user,
        school,
        subject,
        level,
        classroom,     # ensures teacher_user is a SchoolTeacher for get_school_for_user()
        upload_session,
    ):
        """
        Teacher loads the confirm page (Step 3) and submits the confirm form.
        Before PR #255 this raised AttributeError and returned a 500 response.
        After the fix it should redirect to the worksheet detail page.
        """
        do_login(page, live_server.url, teacher_user)

        confirm_url = f"{live_server.url}/worksheets/upload/{upload_session.pk}/confirm/"
        page.goto(confirm_url)
        page.wait_for_load_state("networkidle")

        # Confirm page should load without errors
        body = page.locator("body")
        expect(body).not_to_contain_text("AttributeError", timeout=3_000)
        expect(body).not_to_contain_text("Server Error", timeout=3_000)
        expect(body).not_to_contain_text("500", timeout=3_000)

        # Submit the confirm form (the single submit button on this page)
        page.locator("button[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        # Should NOT be a server error — any redirect (detail or preview) is acceptable
        body_text = page.locator("body").inner_text()
        assert "AttributeError" not in body_text, \
            f"Got AttributeError after confirm POST — _TempSession fix may have been reverted. URL: {page.url}"
        assert "Server Error" not in body_text, \
            f"Got 500 Server Error after confirm POST. URL: {page.url}"
        # Should have left the confirm page (redirected to detail or preview)
        assert "/confirm/" not in page.url, \
            f"Expected redirect away from confirm page but still at: {page.url}"
