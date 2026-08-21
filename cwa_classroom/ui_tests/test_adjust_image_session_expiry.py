"""Playwright UI test for the "Adjust question image" crop modal's error reporting.

Regression: when the POST behind *Apply crop* came back as Django's HTML login
page (expired sign-in) instead of JSON, the modal ran ``response.json()`` on the
markup and showed the teacher `Unexpected token '<', "<!DOCTYPE "... is not valid
JSON` — an error that says nothing about what happened or what to do. The
endpoints now answer AJAX callers in JSON and the modal reads them defensively.
"""

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


@pytest.fixture
def homework_pdf_session(db, school, teacher_user):
    """A homework PDF upload session sitting at the review step, with one
    image-bearing question and a real (tiny) PDF to re-crop from."""
    import fitz
    from django.core.files.base import ContentFile

    from classroom.models import SchoolTeacher
    from homework.models import HomeworkUploadSession

    SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher_user, defaults={"role": "teacher"},
    )

    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 150, 280, 260), fill=(0.6, 0.6, 0.6))
    pdf_bytes = doc.tobytes()
    doc.close()

    session = HomeworkUploadSession.objects.create(
        user=teacher_user, school=school, pdf_filename="ui.pdf",
        status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
        extracted_data={"questions": [{
            "question_text": "Area of the rectangle?",
            "question_type": "multiple_choice", "has_image": True,
            "image_ref": "orig.png", "page_num": 1,
            "image_bbox_frac": [0.2, 0.2, 0.8, 0.6],
        }]},
        extracted_images={"orig.png": (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
            "awAAAABJRU5ErkJggg=="
        )},
    )
    session.pdf_file.save("ui.pdf", ContentFile(pdf_bytes), save=True)
    return session


def _open_adjust_modal(page: Page, live_server_url: str, session) -> None:
    page.goto(f"{live_server_url}/homework/pdf/preview/{session.pk}/")
    page.wait_for_load_state("domcontentloaded")
    page.locator('[data-adjust="0"]').first.click()
    # The crop box only appears once the source page image has loaded.
    expect(page.locator("#adjust-box")).to_be_visible(timeout=15_000)


def test_apply_crop_explains_an_expired_sign_in(page: Page, live_server, homework_pdf_session):
    """With the sign-in gone, Apply crop must say so — not leak a JSON parse error."""
    do_login(page, live_server.url, homework_pdf_session.user)
    _open_adjust_modal(page, live_server.url, homework_pdf_session)

    page.context.clear_cookies()          # the session expires while the modal is open
    page.locator("#adjust-apply").click()

    error = page.locator("#adjust-error")
    expect(error).to_contain_text("sign-in has expired", timeout=15_000)
    assert "Unexpected token" not in (error.text_content() or "")


def test_apply_crop_succeeds_when_signed_in(page: Page, live_server, homework_pdf_session):
    """The happy path still applies the crop and closes the modal."""
    do_login(page, live_server.url, homework_pdf_session.user)
    _open_adjust_modal(page, live_server.url, homework_pdf_session)

    page.locator("#adjust-apply").click()

    expect(page.locator("#adjust-modal")).to_be_hidden(timeout=20_000)
    homework_pdf_session.refresh_from_db()
    assert homework_pdf_session.extracted_data["questions"][0]["image_ref"].startswith("adjust_")
