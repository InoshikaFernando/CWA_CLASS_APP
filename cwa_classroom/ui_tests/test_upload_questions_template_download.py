"""
Playwright UI tests for /upload-questions/template/?subject=<slug>.

Covers ``upload_questions_template`` (classroom/views.py) — the endpoint that
returns a sample JSON file for the selected subject.

  - Template link is present in the upload form
  - mathematics template contains expected keys (strand, topic, year_level, questions)
  - coding template contains expected keys (language, topic, level, exercises)
  - coding_problem template contains expected keys (language, problems[].test_cases)
  - Unknown subject slug returns 404
"""

from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _fetch_template(page: Page, live_server_url: str, subject: str):
    """Fetch the template JSON via the already-authenticated browser context."""
    # Use page.request (carries cookies/session from browser context)
    return page.request.get(f"{live_server_url}/upload-questions/template/?subject={subject}")


class TestUploadQuestionsTemplate:

    @pytest.mark.django_db(transaction=True)
    def test_template_link_visible(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/upload-questions/")
        page.wait_for_load_state("networkidle")
        link = page.get_by_role("link", name=re.compile(r"sample template", re.I))
        expect(link).to_be_visible()
        href = link.get_attribute("href") or ""
        assert "/upload-questions/template/" in href

    @pytest.mark.django_db(transaction=True)
    def test_mathematics_template_content(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        resp = _fetch_template(page, live_server.url, "mathematics")
        assert resp.status == 200
        data = json.loads(resp.body())
        assert set(data) >= {"strand", "topic", "year_level", "questions"}
        assert isinstance(data["questions"], list) and len(data["questions"]) >= 1
        assert "answers" in data["questions"][0]

    @pytest.mark.django_db(transaction=True)
    def test_coding_template_content(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        resp = _fetch_template(page, live_server.url, "coding")
        assert resp.status == 200
        data = json.loads(resp.body())
        assert data.get("subject") == "coding"
        assert set(data) >= {"language", "topic", "level", "exercises"}
        ex = data["exercises"][0]
        assert set(ex) >= {"title", "instructions"}

    @pytest.mark.django_db(transaction=True)
    def test_coding_problem_template_content(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        resp = _fetch_template(page, live_server.url, "coding_problem")
        assert resp.status == 200
        data = json.loads(resp.body())
        assert data.get("subject") == "coding_problem"
        assert "problems" in data
        prob = data["problems"][0]
        assert "test_cases" in prob
        assert isinstance(prob["test_cases"], list) and len(prob["test_cases"]) >= 1

    @pytest.mark.django_db(transaction=True)
    def test_unknown_subject_returns_404(
        self, page: Page, live_server, teacher_user, classroom
    ):
        do_login(page, live_server.url, teacher_user)
        resp = _fetch_template(page, live_server.url, "not-a-subject")
        assert resp.status == 404
