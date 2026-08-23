"""Playwright UI test — the shared interactive-widget mount registry.

Every interactive maths question type mounts through static/js/maths_mounts.js:
it mounts each widget on load and again after the topic quiz / worksheet session
swaps a question in with innerHTML. This test proves the registry actually
mounts more than one KIND of widget on one page — which is the whole reason it
exists, and the thing that silently breaks if a widget's registration is wrong.

A widget that fails to mount does not error: it renders, the student fills it
in, and the hidden field it should have been syncing stays empty, so the answer
grades wrong. Nothing server-side can catch that, so it is checked here.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def mixed_widget_homework(db, classroom, teacher_user, topic, level):
    """One homework carrying all three registry-mounted question types."""
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Question

    number_line = Question.objects.create(
        level=level, topic=topic,
        question_text="Mark 6 on the number line.",
        question_type=Question.NUMBER_LINE, difficulty=1, points=1,
        number_line_spec={"min": 0, "max": 10, "step": 1,
                          "mode": "mark", "target": [6]},
    )
    table = Question.objects.create(
        level=level, topic=topic,
        question_text="Complete the table for y = x + 1.",
        question_type=Question.TABLE_OF_VALUES, difficulty=1, points=1,
        table_spec={"headers": ["x", "y"],
                    "rows": [[{"given": "1"}, {"answer": "2"}]]},
    )
    blanks = Question.objects.create(
        level=level, topic=topic,
        question_text="A triangle has ___ sides and ___ angles.",
        question_type=Question.FILL_BLANK, difficulty=1, points=1,
        blank_spec={"blanks": [{"answers": ["3", "three"]},
                               {"answers": ["3", "three"]}]},
    )

    hw = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title="Interactive widgets", homework_type="topic",
        num_questions=3,
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    hw.topics.add(topic)
    for order, q in enumerate((number_line, table, blanks)):
        HomeworkQuestion.objects.create(homework=hw, question=q, order=order)
    return hw


class TestMathsMountRegistry:

    @pytest.mark.django_db(transaction=True)
    def test_every_widget_kind_mounts_on_one_page(
        self, page: Page, live_server, enrolled_student, mixed_widget_homework
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{mixed_widget_homework.pk}/take/")
        page.wait_for_load_state("networkidle")

        # Each widget sets its own mounted flag once the registry has run it.
        expect(page.locator("[data-fb-stage][data-fb-mounted='1']")).to_have_count(1)
        expect(page.locator("[data-tv-stage][data-tv-mounted='1']")).to_have_count(1)
        expect(page.locator("[data-nl-stage][data-nl-mounted='1']")).to_have_count(1)

    @pytest.mark.django_db(transaction=True)
    def test_the_registry_loaded_without_error(
        self, page: Page, live_server, enrolled_student, mixed_widget_homework
    ):
        """Each widget errors loudly if maths_mounts.js did not load first —
        catching a script-order mistake that would otherwise only show up as
        students being marked wrong."""
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{mixed_widget_homework.pk}/take/")
        page.wait_for_load_state("networkidle")

        assert not [e for e in errors if "maths_mounts.js must load first" in e]

    @pytest.mark.django_db(transaction=True)
    def test_each_widget_syncs_its_own_hidden_field(
        self, page: Page, live_server, enrolled_student, mixed_widget_homework
    ):
        """Widgets are scoped to their own stage — filling one must not write
        into another's payload."""
        import json

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{mixed_widget_homework.pk}/take/")
        page.wait_for_load_state("networkidle")

        page.locator("[data-fb-input]").nth(0).fill("3")
        page.locator("[data-fb-input]").nth(1).fill("three")
        page.locator("[data-tv-cell]").first.fill("2")

        blanks = json.loads(page.locator("[data-fb-hidden]").input_value())
        cells = json.loads(page.locator("[data-tv-hidden]").input_value())
        assert blanks == {"blanks": ["3", "three"]}
        assert cells == {"cells": {"0,1": "2"}}
