"""Weekly content sweep — walk every year level and topic in a real browser and
report questions that look wrong, broken, or incomplete.

This does NOT check every question, and is not trying to. The topic quiz serves
a capped random subset (``8 + level*2``), so no browser run can address a
specific question by id — that is what ``manage.py verify_quiz_grading`` is
for. What this covers is every *level and topic*, a few questions deep, with a
different random draw each week. Coverage accumulates over runs.

It catches the class of problem no data check can see, because it only exists
once the page is rendered:

  * a question whose text is blank, or a template placeholder that leaked
    ("None", "{{ ... }}", "nan")
  * an image that 404s — the question asks about a picture nobody can see
  * LaTeX left unrendered, so the student reads ``\\frac{1}{2}``
  * options that are blank, duplicated, or too few to be a real choice
  * a question that cannot be answered at all (no control renders)

Run against a deployed environment:

    pytest ui_tests/live/test_content_sweep.py --live-url https://test.wizardslearninghub.co.nz

Targets come from ``manage.py list_quiz_targets`` (a student only sees their
own level, so the pages are not discoverable by crawling). Point
``QUIZ_TARGETS_FILE`` at that JSON. Credentials come from ``SWEEP_USERNAME``
and ``SWEEP_PASSWORD``.

Findings are collected and reported together: a sweep that stops at the first
bad question would hide the other 200.
"""
from __future__ import annotations

import json
import os
import re

import pytest

pytestmark = [pytest.mark.quiz]

# Text that should never reach a student — unrendered templates, Python repr
# leaking through, or a placeholder someone forgot to fill in.
PLACEHOLDER_MARKERS = (
    '{{', '}}', '{%', 'None', 'nan', 'undefined', 'null',
    'TODO', 'TBD', 'FIXME', 'lorem ipsum',
)

# LaTeX that reached the page as source rather than rendered maths.
RAW_LATEX_MARKERS = ('\\frac', '\\sqrt', '\\times', '\\div', '$$')

QUESTIONS_PER_TOPIC = int(os.environ.get('SWEEP_QUESTIONS_PER_TOPIC', '3'))


def _targets():
    """The level/topic pages to visit, from list_quiz_targets JSON."""
    path = os.environ.get('QUIZ_TARGETS_FILE')
    if not path or not os.path.exists(path):
        pytest.skip(
            'QUIZ_TARGETS_FILE not set — generate it with '
            '`manage.py list_quiz_targets > targets.json`'
        )
    with open(path) as handle:
        targets = json.load(handle)
    if not targets:
        pytest.skip('No quiz targets found in QUIZ_TARGETS_FILE')
    return targets


def _describe(target):
    return f"year {target['level']} / {target['topic']} (topic {target['topic_id']})"


def _placeholders_in(text):
    """Placeholder markers present in ``text``.

    Symbolic markers ('{{', '$$') are matched as substrings. Word markers
    ('None', 'nan', 'TODO') are matched whole-word only — otherwise "nan"
    fires on "nanometre" and "None" on "Nonetheless", and a sweep that cries
    wolf gets ignored.
    """
    lowered = text.lower()
    words = set(re.findall(r'[a-z]+', lowered))
    found = []
    for marker in PLACEHOLDER_MARKERS:
        if marker.isalpha():
            if marker.lower() in words:
                found.append(marker)
        elif marker in text:
            found.append(marker)
    return found


@pytest.fixture(scope='session')
def sweep_credentials():
    username = os.environ.get('SWEEP_USERNAME')
    password = os.environ.get('SWEEP_PASSWORD')
    if not username or not password:
        pytest.skip('SWEEP_USERNAME / SWEEP_PASSWORD not set')
    return username, password


def _inspect_question_card(page, problems, where):
    """Check the currently-rendered question card. Appends to ``problems``."""
    card = page.locator('#question-card')
    if not card.count():
        problems.append(f'{where}: no question card rendered')
        return False

    # --- question text -----------------------------------------------------
    text_node = card.locator('p').first
    question_text = text_node.inner_text().strip() if text_node.count() else ''
    if len(question_text) < 3:
        problems.append(f'{where}: question text is blank or too short')
    else:
        for marker in _placeholders_in(question_text):
            problems.append(
                f'{where}: placeholder {marker!r} in question text: '
                f'{question_text[:60]!r}')
            break
        for marker in RAW_LATEX_MARKERS:
            if marker in question_text:
                problems.append(
                    f'{where}: unrendered LaTeX {marker!r} in question text')
                break

    # --- images actually load ---------------------------------------------
    images = card.locator('img')
    for index in range(images.count()):
        image = images.nth(index)
        loaded = image.evaluate(
            '(img) => img.complete && img.naturalWidth > 0')
        if not loaded:
            src = image.get_attribute('src') or '(no src)'
            problems.append(f'{where}: image failed to load — {src}')

    # --- answer controls ---------------------------------------------------
    options = card.locator('.answer-btn[data-answer-id]')
    typed = card.locator('#text-answer-input')
    option_count = options.count()

    if option_count == 0 and typed.count() == 0:
        problems.append(f'{where}: no way to answer — no options and no input')
        return False

    if option_count:
        texts = []
        for index in range(option_count):
            label = options.nth(index).inner_text().strip()
            if not label:
                problems.append(f'{where}: option {index + 1} is blank')
            texts.append(label.lower())
        if option_count < 2:
            problems.append(
                f'{where}: only {option_count} option — not a real choice')
        duplicates = {t for t in texts if t and texts.count(t) > 1}
        if duplicates:
            problems.append(f'{where}: duplicate options {sorted(duplicates)}')

    return True


@pytest.mark.live
def test_every_level_and_topic_renders_answerable_questions(
        page, request, sweep_credentials):
    """Visit every level/topic quiz and report anything a student shouldn't see."""
    from ..live_helpers import live_login

    base_url = request.config.getoption('--live-url', default=None)
    if not base_url:
        pytest.skip('--live-url required: this sweep runs against a deployed site')

    username, password = sweep_credentials
    live_login(page, base_url, username, password)

    problems = []
    visited = 0

    for target in _targets():
        where = _describe(target)
        try:
            page.goto(f"{base_url}{target['url']}", timeout=30_000)
            page.wait_for_load_state('domcontentloaded')
        except Exception as exc:                                # noqa: BLE001
            problems.append(f'{where}: page failed to load — {exc!r}')
            continue

        if not page.locator('#question-card').count():
            # A topic with questions in the DB that serves none is itself a
            # finding — the student is sent to an empty quiz.
            problems.append(
                f"{where}: quiz served no questions "
                f"(database says {target['questions']})")
            continue

        visited += 1
        for depth in range(QUESTIONS_PER_TOPIC):
            if not _inspect_question_card(page, problems, f'{where} q{depth + 1}'):
                break
            # Answer to advance. Any option will do — this sweep is about how
            # the question reads, not whether the pick is right.
            options = page.locator('.answer-btn[data-answer-id]')
            if not options.count():
                break
            options.first.click()
            page.wait_for_timeout(1_200)
            if not page.locator('#question-card').count():
                break

    print(f'\nContent sweep: visited {visited} level/topic quizzes, '
          f'{len(problems)} problem(s)')
    for problem in problems:
        print(f'  {problem}')

    assert not problems, (
        f'{len(problems)} content problem(s) across {visited} quizzes:\n' +
        '\n'.join(f'  - {p}' for p in problems)
    )


# ---------------------------------------------------------------------------
# Proof the checks fire
# ---------------------------------------------------------------------------
# The sweep above needs a deployed site, so it cannot run in CI. These tests
# drive the same _inspect_question_card against a locally served page with
# deliberately broken content, so the detection logic itself is covered by the
# normal test run. A sweep that silently detects nothing would otherwise look
# exactly like a clean estate.


@pytest.fixture
def broken_question(db, level, topic):
    """A question carrying a leaked placeholder and a blank option."""
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='The answer is None',
        question_type=Question.MULTIPLE_CHOICE,
        difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text='5', is_correct=True, order=1)
    Answer.objects.create(question=q, answer_text='', is_correct=False, order=2)
    Answer.objects.create(question=q, answer_text='7', is_correct=False, order=3)
    return q


@pytest.fixture
def healthy_question(db, level, topic):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, topic=topic,
        question_text='Calculate: 1/2 + 1/4',
        question_type=Question.MULTIPLE_CHOICE,
        difficulty=1, points=1,
    )
    for order, (text, correct) in enumerate(
            [('3/4', True), ('1/4', False), ('2/3', False)], start=1):
        Answer.objects.create(question=q, answer_text=text,
                              is_correct=correct, order=order)
    return q


class TestContentChecksFire:

    def _open_quiz(self, page, live_server, student, level, topic):
        from ..conftest import do_login
        do_login(page, live_server.url, student)
        page.goto(f'{live_server.url}/maths/level/{level.level_number}'
                  f'/topic/{topic.id}/quiz/')
        page.wait_for_load_state('networkidle')

    def test_placeholder_and_blank_option_are_reported(
            self, live_server, page, enrolled_student, level, topic,
            broken_question):
        self._open_quiz(page, live_server, enrolled_student, level, topic)
        problems = []
        _inspect_question_card(page, problems, 'fixture')
        joined = ' | '.join(problems)
        assert 'placeholder' in joined, f'placeholder not detected: {problems}'
        assert 'blank' in joined, f'blank option not detected: {problems}'

    def test_healthy_question_reports_nothing(
            self, live_server, page, enrolled_student, level, topic,
            healthy_question):
        self._open_quiz(page, live_server, enrolled_student, level, topic)
        problems = []
        _inspect_question_card(page, problems, 'fixture')
        assert problems == [], f'clean question was flagged: {problems}'
