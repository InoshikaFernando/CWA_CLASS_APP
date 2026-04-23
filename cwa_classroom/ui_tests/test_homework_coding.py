"""
Playwright UI tests — coding homework end-to-end (Phase 2b).

Covers:

  - Teacher create page shows the Coding option in the subject selector
  - Selecting ?subject_slug=coding shows the coding topic tree (language →
    topic → level) and topic checkboxes POST as ``coding_topics``
  - Creating a coding homework persists ``subject_slug='coding'`` and the
    correct coding_topics M2M
  - HomeworkQuestion rows for coding homework carry subject_slug='coding' +
    content_id pointing at CodingExercise pks (and no legacy maths FK)
  - Student take page renders a coding editor (textarea) per exercise, with
    starter_code prefilled and language badge shown
  - Coding plugin.grade_answer marks submission correct when stdout matches
    expected_output for a browser-sandbox language (doesn't hit Piston)

NOTE: Piston-backed grading for server-side languages (python/javascript)
is tested at the plugin layer via a separate unit test — hitting a live
Piston from Playwright would make these tests require external
infrastructure.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from .conftest import do_login


# ---------------------------------------------------------------------------
# Fixtures — coding content + a ready-to-take homework wired to the classroom
# ---------------------------------------------------------------------------

@pytest.fixture
def coding_exercise(db, coding_topic_level):
    from coding.models import CodingExercise

    return CodingExercise.objects.create(
        topic_level=coding_topic_level,
        title="Print Hello",
        description="Print 'Hello' to the console.",
        starter_code="# Write your solution\n",
        expected_output="Hello",
        hints="Use print()",
        order=1,
        is_active=True,
    )


@pytest.fixture
def html_language(db):
    """An HTML coding language — uses_browser_sandbox → graded on submission."""
    from coding.models import CodingLanguage

    lang, _ = CodingLanguage.objects.get_or_create(
        slug=CodingLanguage.HTML,
        defaults={"name": "HTML", "order": 3, "is_active": True},
    )
    return lang


@pytest.fixture
def html_exercise(db, html_language):
    from coding.models import CodingExercise, CodingTopic, TopicLevel

    topic, _ = CodingTopic.objects.get_or_create(
        language=html_language, slug="basics",
        defaults={"name": "Basics", "order": 1, "is_active": True},
    )
    tl, _ = TopicLevel.get_or_create_for(topic, TopicLevel.BEGINNER)
    return CodingExercise.objects.create(
        topic_level=tl,
        title="Hello Page",
        description="Write an <h1> that says Hello.",
        starter_code="<h1></h1>",
        expected_output="",
        order=1,
        is_active=True,
    )


@pytest.fixture
def coding_homework_ready(db, classroom, teacher_user, coding_exercise):
    """A Homework with subject_slug='coding' and a HomeworkQuestion bound to a CodingExercise."""
    from homework.models import Homework, HomeworkQuestion

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Coding E2E",
        homework_type="topic",
        num_questions=1,
        subject_slug="coding",
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.coding_topics.add(coding_exercise.topic_level.topic)
    HomeworkQuestion.objects.create(
        homework=hw,
        subject_slug="coding",
        content_id=coding_exercise.pk,
        order=0,
    )
    return hw


# ---------------------------------------------------------------------------
# Teacher create page — subject selector + coding topic tree
# ---------------------------------------------------------------------------

class TestCodingHomeworkCreatePage:

    @pytest.mark.django_db(transaction=True)
    def test_subject_selector_offers_coding(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, coding_topic_level, coding_exercise,
    ):
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/")
        page.wait_for_load_state("networkidle")

        selector = page.locator("#subject_select_ui")
        # Coding option present
        option_values = selector.locator("option").evaluate_all(
            "opts => opts.map(o => o.value)"
        )
        assert "coding" in option_values, f"Expected 'coding' in {option_values}"

    @pytest.mark.django_db(transaction=True)
    def test_switching_to_coding_loads_coding_topic_tree(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, coding_topic_level, coding_exercise,
    ):
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/?subject_slug=coding")
        page.wait_for_load_state("networkidle")

        # Topic checkboxes now post as coding_topics (not 'topics')
        coding_boxes = page.locator("input[type='checkbox'][name='coding_topics']")
        assert coding_boxes.count() >= 1, "At least one coding topic-level checkbox should render"

        # Hidden subject_slug is set to coding
        hidden = page.locator("input[name='subject_slug']#subject_slug_hidden")
        assert hidden.input_value() == "coding"

    @pytest.mark.django_db(transaction=True)
    def test_creating_coding_homework_persists_subject_and_items(
        self, page: Page, live_server, teacher_user, classroom,
        coding_language, coding_topic, coding_topic_level, coding_exercise,
    ):
        from homework.models import Homework, HomeworkQuestion

        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}/homework/class/{classroom.pk}/create/?subject_slug=coding")
        page.wait_for_load_state("networkidle")

        page.locator("#id_title").fill("Coding Homework Created Via UI")
        due = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        page.locator("#id_due_date").fill(due)

        # Tick the TopicLevel checkbox (coding_topics posts TopicLevel pks)
        page.locator(
            f"input[name='coding_topics'][value='{coding_topic_level.pk}']"
        ).check()

        with page.expect_navigation():
            page.get_by_role("button", name=re.compile(r"Create Homework", re.I)).click()
        page.wait_for_load_state("networkidle")

        hw = Homework.objects.filter(
            classroom=classroom, title="Coding Homework Created Via UI"
        ).first()
        assert hw is not None
        assert hw.subject_slug == "coding"
        # Parent topic (not TopicLevel) recorded on the M2M
        assert coding_topic in list(hw.coding_topics.all())
        # HomeworkQuestion rows point at CodingExercise, no legacy maths FK
        rows = list(HomeworkQuestion.objects.filter(homework=hw))
        assert len(rows) >= 1
        for row in rows:
            assert row.subject_slug == "coding"
            assert row.content_id == coding_exercise.pk
            assert row.question_id is None, (
                "Coding HomeworkQuestion must NOT populate the legacy maths FK"
            )


# ---------------------------------------------------------------------------
# Student take page — coding editor rendering
# ---------------------------------------------------------------------------

class TestCodingHomeworkTake:

    @pytest.mark.django_db(transaction=True)
    def test_take_page_renders_coding_editor(
        self, page: Page, live_server, enrolled_student, coding_homework_ready, coding_exercise
    ):
        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{coding_homework_ready.pk}/take/")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text(coding_exercise.title)).to_be_visible()
        # A textarea for the coding editor per exercise
        editor = page.locator(f"textarea[name='code_{coding_exercise.pk}']")
        expect(editor).to_be_visible()
        # Starter code prefilled
        assert coding_exercise.starter_code.strip() in (editor.input_value() or "")
        # Language badge
        expect(page.get_by_text(coding_exercise.topic_level.topic.language.name).first).to_be_visible()


# ---------------------------------------------------------------------------
# Plugin grade_answer unit tests  (no Piston required)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_grade_answer_browser_sandbox_language_grades_on_submission(
    db, html_exercise
):
    """HTML/CSS/Scratch have no Piston mapping — any non-empty code → correct."""
    from coding.plugin import CodingExercisePlugin

    plugin = CodingExercisePlugin()
    post = {f'code_{html_exercise.pk}': '<h1>Hello</h1>'}
    result = plugin.grade_answer(html_exercise.pk, post)
    assert result['is_correct'] is True
    assert result['points_earned'] == 1
    assert result['answer_data']['code'] == '<h1>Hello</h1>'


@pytest.mark.django_db(transaction=True)
def test_grade_answer_empty_submission_is_wrong(db, coding_exercise):
    from coding.plugin import CodingExercisePlugin

    plugin = CodingExercisePlugin()
    result = plugin.grade_answer(coding_exercise.pk, {f'code_{coding_exercise.pk}': ''})
    assert result['is_correct'] is False
    assert result['points_earned'] == 0


@pytest.mark.django_db(transaction=True)
def test_pick_homework_items_returns_exercise_pks(
    db, classroom, coding_language, coding_topic, coding_topic_level, coding_exercise
):
    from coding.plugin import CodingExercisePlugin

    plugin = CodingExercisePlugin()
    picks = plugin.pick_homework_items(classroom, [coding_topic_level.pk], n=10)
    assert coding_exercise.pk in picks


@pytest.mark.django_db(transaction=True)
def test_homework_topic_tree_includes_populated_languages(
    db, coding_language, coding_topic, coding_topic_level, coding_exercise
):
    from coding.plugin import CodingExercisePlugin

    plugin = CodingExercisePlugin()
    tree = plugin.homework_topic_tree(classroom=None)
    assert tree, "Should have at least one language group when content exists"
    # The first (language, mid_items) tuple has our topic in its mids
    lang_wrap, mids = tree[0]
    assert coding_language.name == lang_wrap.name
    topics_in_mids = [mid.pk for mid, _ in mids]
    assert coding_topic.pk in topics_in_mids
