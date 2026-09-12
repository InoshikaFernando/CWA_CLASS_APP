"""Playwright UI tests — answering must autosave, however you answer.

Regression guard for a bug that made the take page's debounced autosave dead
for the commonest answer type of all.

Each option is a sibling ``<label for=…>`` and the page had added its own click
handler that set ``input.checked = true``. The browser checks the radio itself,
but as the click's DEFAULT ACTION — after every listener has run. Finding it
already checked, it then fired nothing at all: no ``input``, no ``change``. The
selection appeared on screen, the form never heard about it, and the
``form.addEventListener('change', scheduleSave)`` autosave below it never ran.
A student picking answers saw no "Saved" confirmation and rode entirely on the
30-second heartbeat, losing up to half a minute of work if the tab died.

The click-driven maths widgets had the same bug for a different reason: they
are answered by tapping an SVG, and write their answer straight into a hidden
input. Assigning to ``.value`` in script fires no event either, so plotting a
point was just as invisible to the autosave as picking a radio was.

Both are driven here against the real page, and both assert a save actually
reaches the server shortly after the interaction — WITHOUT touching "Save &
continue later", which always worked and would hide the bug.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from ..conftest import do_login

# Comfortably longer than the page's 1.5s debounce, and far shorter than its
# 30s heartbeat — so a pass here means the DEBOUNCE fired, not the fallback.
SAVE_TIMEOUT_MS = 10_000


@pytest.fixture
def autosave_homework(db, classroom, teacher_user, level, topic):
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Answer, Question

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Autosave Homework",
        homework_type="topic",
        num_questions=2,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    questions = []
    for i in range(2):
        q = Question.objects.create(
            level=level, topic=topic,
            question_text=f"What is {i} + 3?",
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text=str(i + 3), is_correct=True, order=1)
        Answer.objects.create(question=q, answer_text=str(i + 8), is_correct=False, order=2)
        HomeworkQuestion.objects.create(homework=hw, question=q, order=i)
        questions.append(q)
    return hw, questions


def _first_option_label(page, question):
    answer = question.answers.order_by("order").first()
    return page.locator(f"label[for='ans_{question.id}_{answer.id}']")


class TestAutosaveOnAnswer:

    @pytest.mark.django_db(transaction=True)
    def test_choosing_an_option_saves_it_without_pressing_save(
        self, page: Page, live_server, enrolled_student, autosave_homework
    ):
        from homework.models import HomeworkDraft

        hw, questions = autosave_homework
        answer = questions[0].answers.order_by("order").first()

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        assert not HomeworkDraft.objects.filter(
            homework=hw, student=enrolled_student).exists()

        with page.expect_response(
            lambda r: "/save-progress/" in r.url and r.status == 200,
            timeout=SAVE_TIMEOUT_MS,
        ):
            _first_option_label(page, questions[0]).click()

        # The student is told it worked, and the answer really is on the server.
        expect(page.locator("#save-status")).to_contain_text("Saved")
        draft = HomeworkDraft.objects.get(homework=hw, student=enrolled_student)
        assert draft.answers_data.get(f"answer_{questions[0].id}") == str(answer.pk)

    @pytest.mark.django_db(transaction=True)
    def test_a_label_click_fires_the_events_the_form_listens_for(
        self, page: Page, live_server, enrolled_student, autosave_homework
    ):
        """The mechanism itself, pinned directly.

        The autosave test above could be made to pass again by a handler that
        dispatched a synthetic event. This asserts the real contract: native
        label activation both checks the radio AND notifies the form — and
        stays quiet when an already-selected option is clicked a second time,
        which a synthetic dispatch would get wrong.
        """
        hw, questions = autosave_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        page.evaluate(
            """() => {
                window.__seen = [];
                const form = document.getElementById('hw-form');
                form.addEventListener('input', e => window.__seen.push('input'));
                form.addEventListener('change', e => window.__seen.push('change'));
            }"""
        )

        label = _first_option_label(page, questions[0])
        label.click()
        assert page.evaluate("() => window.__seen") == ["input", "change"]

        # Re-clicking the option that is already selected changes nothing, so it
        # must stay silent rather than trigger a pointless save.
        label.click()
        assert page.evaluate("() => window.__seen") == ["input", "change"]

        # A different option is a real change and must be announced.
        _first_option_label(page, questions[1]).click()
        assert page.evaluate("() => window.__seen") == [
            "input", "change", "input", "change",
        ]


PLOT_POINTS_SPEC = {
    'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
    'mode': 'points',
    'target': {'points': [[3, -2]]},
    'allow_extra': False,
}


@pytest.fixture
def plot_points_homework(db, classroom, teacher_user, level, topic):
    """A homework whose only question is answered by tapping the plane."""
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Question

    hw = Homework.objects.create(
        classroom=classroom,
        created_by=teacher_user,
        title="Plot Points Autosave",
        homework_type="topic",
        num_questions=1,
        due_date=timezone.now() + timedelta(days=3),
        max_attempts=3,
    )
    hw.topics.add(topic)
    q = Question.objects.create(
        level=level, topic=topic,
        question_text="Plot the point (3, -2).",
        question_type=Question.PLOT_POINTS,
        difficulty=1, points=1,
        plane_spec=PLOT_POINTS_SPEC,
    )
    HomeworkQuestion.objects.create(homework=hw, question=q, order=0)
    return hw, q


class TestAutosaveOnWidgetAnswer:

    @pytest.mark.django_db(transaction=True)
    def test_plotting_a_point_saves_it_without_pressing_save(
        self, page: Page, live_server, enrolled_student, plot_points_homework
    ):
        import json

        from homework.models import HomeworkDraft

        hw, question = plot_points_homework

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")

        dot = page.locator(f'[data-pl-dot="{question.pk}"][data-gx="3"][data-gy="-2"]')
        with page.expect_response(
            lambda r: "/save-progress/" in r.url and r.status == 200,
            timeout=SAVE_TIMEOUT_MS,
        ):
            dot.click()

        expect(page.locator("#save-status")).to_contain_text("Saved")
        draft = HomeworkDraft.objects.get(homework=hw, student=enrolled_student)
        saved = json.loads(draft.answers_data[f"answer_{question.pk}"])
        assert saved["points"] == [[3, -2]], saved

    @pytest.mark.django_db(transaction=True)
    def test_a_resumed_draft_does_not_trigger_a_pointless_save(
        self, page: Page, live_server, enrolled_student, plot_points_homework
    ):
        """The dispatch is guarded on a real change for a reason.

        Rebuilding a resumed draft's working calls the widget's sync with the
        value it already has. Announcing that would flash "Unsaved changes…" and
        fire an autosave on every page load that changed nothing.
        """
        import json

        from homework.models import HomeworkDraft

        hw, question = plot_points_homework
        HomeworkDraft.objects.create(
            homework=hw, student=enrolled_student,
            answers_data={
                f"answer_{question.pk}": json.dumps({"points": [[3, -2]]}),
            },
        )

        saves: list[str] = []
        page.on("request", lambda r: saves.append(r.url)
                if "/save-progress/" in r.url else None)

        do_login(page, live_server.url, enrolled_student)
        page.goto(f"{live_server.url}/homework/{hw.pk}/take/")
        page.wait_for_load_state("networkidle")
        # Comfortably past the 1.5s debounce, nowhere near the 30s heartbeat.
        page.wait_for_timeout(4000)

        assert saves == [], f"a resumed page saved without the student doing anything: {saves}"
        expect(page.locator("#save-status")).to_be_empty()
