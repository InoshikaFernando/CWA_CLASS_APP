"""
UI test for creating an "All Subjects" progress criterion via the slideover form.

Covers SPEC_TEACHER_CLASS_STUDENT_PROGRESS §12.6: a Senior Teacher can pick the
"All Subjects" option, submit, and the new (subject=null) criterion shows up in
the list rendered as "All Subjects".
"""
from __future__ import annotations

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from .conftest import do_login, _make_user

pytestmark = pytest.mark.progress


@pytest.fixture
def senior_teacher_member(db, school, roles):
    """A Senior Teacher who is a member of the test school (so the school resolves)."""
    from accounts.models import Role
    from classroom.models import SchoolTeacher

    teacher = _make_user(
        "ui_crit_senior", Role.SENIOR_TEACHER, first_name="Sid", last_name="Senior",
    )
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher, defaults={"role": "senior_teacher"},
    )
    return teacher


class TestAllSubjectsCriteriaForm:

    def test_subject_dropdown_offers_all_subjects(self, page, live_server, senior_teacher_member):
        """The slideover Subject select includes an 'All Subjects' option."""
        do_login(page, live_server.url, senior_teacher_member)
        page.goto(f"{live_server.url}{reverse('progress_criteria_list')}")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="New Criteria").click()
        option = page.locator("#panel-subject option[value='all']")
        expect(option).to_have_count(1)
        expect(option).to_have_text("All Subjects")

    def test_create_all_subjects_criterion(self, page, live_server, senior_teacher_member):
        """Selecting 'All Subjects' and submitting creates a criterion shown as 'All Subjects'."""
        do_login(page, live_server.url, senior_teacher_member)
        page.goto(f"{live_server.url}{reverse('progress_criteria_list')}")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name="New Criteria").click()
        page.locator("#panel-name").fill("Focus & Engagement")
        page.locator("#panel-subject").select_option("all")
        # Footer submit button is wired to the panel form via the form= attribute.
        page.locator("button[form='criteria-panel-form']").click()

        page.wait_for_load_state("domcontentloaded")
        table = page.locator("table")
        expect(table).to_contain_text("Focus & Engagement")
        expect(table).to_contain_text("All Subjects")
