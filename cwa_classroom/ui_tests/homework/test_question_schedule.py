"""
Playwright UI tests for the question automation schedule (CPP-399).

The journey a teacher actually takes: reach the planner from the homework
monitor, create a plan across a term, assign topics to a week, and generate
that week's set — landing on a real homework whose questions are there and
whose students still cannot see it.
"""

from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


@pytest.fixture
def term(db, school):
    """A four-week term starting on the Monday a fortnight out.

    Relative to today deliberately — a fixed term would drift into the past and
    start exercising the catch-up path instead of the normal one.
    """
    from classroom.models import AcademicYear, Term

    today = date.today()
    start = today + timedelta(days=14 - today.weekday())
    year, _ = AcademicYear.objects.get_or_create(
        school=school, year=start.year,
        defaults={
            'start_date': start - timedelta(days=60),
            'end_date': start + timedelta(days=200),
        },
    )
    return Term.objects.create(
        school=school, academic_year=year, name='UI Term',
        start_date=start, end_date=start + timedelta(days=27), order=1,
    )


def _open_planner(page: Page, live_server, teacher_user, classroom):
    do_login(page, live_server.url, teacher_user)
    page.goto(f'{live_server.url}/homework/class/{classroom.id}/schedules/')
    page.wait_for_load_state('domcontentloaded')


@pytest.mark.django_db
def test_teacher_reaches_the_planner_from_the_homework_monitor(
    page: Page, live_server, teacher_user, classroom, questions,
):
    do_login(page, live_server.url, teacher_user)
    page.goto(f'{live_server.url}/homework/monitor/?classroom={classroom.id}')
    page.wait_for_load_state('domcontentloaded')

    link = page.locator('#question-schedules-link')
    expect(link).to_be_visible()
    link.click()
    page.wait_for_load_state('domcontentloaded')
    expect(page.locator('h1')).to_contain_text('Question Schedules')


@pytest.mark.django_db
def test_teacher_creates_a_plan_assigns_topics_and_generates_a_week(
    page: Page, live_server, teacher_user, classroom, topic, questions, term,
):
    from homework.models import Homework, QuestionSchedule

    _open_planner(page, live_server, teacher_user, classroom)

    # --- create the plan ---------------------------------------------------
    page.locator('button[type="submit"]', has_text='New schedule').click()
    page.wait_for_load_state('domcontentloaded')

    page.locator('#id_name').fill('UI Term Maths plan')
    page.locator('#id_scope').select_option('term')
    page.locator('#id_term').select_option(str(term.id))
    page.locator('#id_num_questions').fill('3')
    page.locator('button[type="submit"]', has_text='Create schedule').click()
    page.wait_for_load_state('domcontentloaded')

    schedule = QuestionSchedule.objects.get(name='UI Term Maths plan')
    assert schedule.weeks.count() == 4
    expect(page.locator('h1')).to_contain_text('UI Term Maths plan')

    # --- plan week 1 -------------------------------------------------------
    week1 = schedule.weeks.get(week_number=1)
    week_block = page.locator('#week-1')
    expect(week_block).to_be_visible()

    week_block.locator(f'input[name="topic_ids"][value="{topic.id}"]').first.check()
    week_block.locator('button[type="submit"]', has_text='Save week').click()
    page.wait_for_load_state('domcontentloaded')

    week1.refresh_from_db()
    assert week1.topic_ids == [topic.id]

    # --- generate it now ---------------------------------------------------
    page.locator('#week-1').locator(
        'button[type="submit"]', has_text='Generate now',
    ).click()
    page.wait_for_load_state('domcontentloaded')

    week1.refresh_from_db()
    assert week1.generated_homework_id is not None

    homework = Homework.objects.get(pk=week1.generated_homework_id)
    assert homework.homework_questions.count() == 3
    assert homework.classroom_id == classroom.id
    # The whole point of the lead time: built, but not yet live for students.
    assert homework.published_at is None
    assert homework.publish_at is not None

    # We land on the homework itself so the teacher can review it.
    expect(page).to_have_url(f'{live_server.url}/homework/{homework.id}/')


@pytest.mark.django_db
def test_a_student_cannot_open_the_planner(
    page: Page, live_server, enrolled_student, classroom,
):
    """A student is bounced off the planner rather than shown it.

    RoleRequiredMixin redirects rather than returning a 4xx, so the assertion
    is on where the browser ends up — checking the status code would pass on
    the redirect target and prove nothing.
    """
    do_login(page, live_server.url, enrolled_student)
    page.goto(f'{live_server.url}/homework/class/{classroom.id}/schedules/')
    page.wait_for_load_state('domcontentloaded')

    assert '/schedules/' not in page.url
    expect(page.locator('h1')).not_to_contain_text('Question Schedules')


@pytest.mark.django_db
def test_coverage_warns_live_when_a_topic_cannot_fill_the_set(
    page: Page, live_server, teacher_user, classroom, topic, questions, term,
):
    """Ticking a thin topic must warn before the teacher saves, not weeks later.

    The `questions` fixture supplies 5; the plan asks for 10, so the moment the
    topic is ticked the week should say it is 5 short — with no page reload.
    """
    from homework.models import QuestionSchedule

    _open_planner(page, live_server, teacher_user, classroom)

    page.locator('button[type="submit"]', has_text='New schedule').click()
    page.wait_for_load_state('domcontentloaded')
    page.locator('#id_name').fill('Coverage plan')
    page.locator('#id_scope').select_option('term')
    page.locator('#id_term').select_option(str(term.id))
    page.locator('#id_num_questions').fill('10')
    page.locator('button[type="submit"]', has_text='Create schedule').click()
    page.wait_for_load_state('domcontentloaded')

    schedule = QuestionSchedule.objects.get(name='Coverage plan')
    week = page.locator('#week-1')
    line = week.locator('[data-week-coverage]')

    # Nothing planned yet.
    expect(line).to_contain_text('No topics selected')

    # The count sits beside the topic itself, before anything is ticked.
    box = week.locator(f'input[name="topic_ids"][value="{topic.id}"]').first
    expect(box).to_have_attribute('data-total', '5')

    # Ticking it warns immediately — no save, no reload.
    box.check()
    expect(line).to_contain_text('5 short of the 10')

    # And the warning survives the save, rendered server-side this time.
    week.locator('button[type="submit"]', has_text='Save week').click()
    page.wait_for_load_state('domcontentloaded')
    expect(page.locator('#week-1').locator('[data-week-coverage]')).to_contain_text(
        '5 short of the 10',
    )
    assert schedule.weeks.get(week_number=1).topic_ids == [topic.id]


@pytest.mark.django_db
def test_the_create_form_says_topics_come_next(
    page: Page, live_server, teacher_user, classroom, questions,
):
    """The gap that made the feature look missing: nothing said where topics were."""
    _open_planner(page, live_server, teacher_user, classroom)
    page.locator('button[type="submit"]', has_text='New schedule').click()
    page.wait_for_load_state('domcontentloaded')
    expect(page.locator('body')).to_contain_text('Topics come next')


@pytest.fixture
def topic_tree(db, subject, level, topic):
    """A three-level tree: strand > topic > two subtopics, all with questions.

    The shared `topic` fixture is only two deep, so it renders as a plain
    checkbox and exercises none of the parent/child behaviour. Questions sit on
    the parent topic as well as on each subtopic, because reaching the parent's
    own questions is half the point of making it selectable.
    """
    from classroom.models import Topic
    from maths.models import Answer, Question

    suffix = f'{level.pk}'
    strand = Topic.objects.create(
        subject=subject, name=f'Number Tree {suffix}',
        slug=f'number-tree-{suffix}', order=90,
    )
    parent = Topic.objects.create(
        subject=subject, parent=strand, name=f'Multiplication {suffix}',
        slug=f'multiplication-tree-{suffix}', order=1,
    )
    subs = [
        Topic.objects.create(
            subject=subject, parent=parent, name=f'Multiplication ({n}x)',
            slug=f'mult-{n}x-tree-{suffix}', order=n,
        )
        for n in (2, 3)
    ]
    for node, count in ((parent, 3), (subs[0], 4), (subs[1], 5)):
        node.levels.add(level)
        for i in range(count):
            q = Question.objects.create(
                level=level, topic=node, question_text=f'{node.slug} q{i}?',
                question_type='multiple_choice', difficulty=1, points=1,
            )
            Answer.objects.create(question=q, answer_text='right',
                                  is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text='wrong',
                                  is_correct=False, order=1)
    return {'strand': strand, 'parent': parent, 'subs': subs}


def _make_plan(page: Page, live_server, term, name, num_questions):
    page.locator('button[type="submit"]', has_text='New schedule').click()
    page.wait_for_load_state('domcontentloaded')
    page.locator('#id_name').fill(name)
    page.locator('#id_scope').select_option('term')
    page.locator('#id_term').select_option(str(term.id))
    page.locator('#id_num_questions').fill(str(num_questions))
    page.locator('button[type="submit"]', has_text='Create schedule').click()
    page.wait_for_load_state('domcontentloaded')


def _expand_topic_groups(week):
    """Open the picker's strand accordions — they start shut.

    A teacher clicks the strand header to open it, so the tests do the same
    rather than driving the ``<details>`` from script. Groups already open
    (a lone strand, or one holding a selection) are left alone: clicking
    their summary would shut them.
    """
    summaries = week.locator('details[data-topic-group] > summary')
    for i in range(summaries.count()):
        summary = summaries.nth(i)
        if summary.evaluate('el => !el.parentElement.open'):
            summary.click()


@pytest.mark.django_db
def test_ticking_a_topic_selects_all_its_subtopics(
    page: Page, live_server, teacher_user, classroom, topic, questions,
    topic_tree, term,
):
    """The ask: select a Topic and its subtopics come with it."""
    from homework.models import QuestionSchedule

    _open_planner(page, live_server, teacher_user, classroom)
    _make_plan(page, live_server, term, 'Cascade plan', 6)
    schedule = QuestionSchedule.objects.get(name='Cascade plan')

    week = page.locator('#week-1')
    _expand_topic_groups(week)
    parent_box = week.locator(
        f'input[name="topic_ids"][value="{topic_tree["parent"].id}"]').first
    sub_boxes = [
        week.locator(f'input[name="topic_ids"][value="{sub.id}"]').first
        for sub in topic_tree['subs']
    ]

    expect(parent_box).to_have_attribute('data-group-toggle', '')
    for box in sub_boxes:
        expect(box).not_to_be_checked()

    parent_box.check()
    for box in sub_boxes:
        expect(box).to_be_checked()

    # And the whole subtree survives the save, parent included — that is what
    # puts the parent's OWN questions in the pool.
    week.locator('button[type="submit"]', has_text='Save week').click()
    page.wait_for_load_state('domcontentloaded')

    saved = schedule.weeks.get(week_number=1).topic_ids
    for node in [topic_tree['parent']] + topic_tree['subs']:
        assert node.id in saved, f'{node.name} was not saved'


@pytest.mark.django_db
def test_unticking_one_subtopic_leaves_the_topic_half_selected(
    page: Page, live_server, teacher_user, classroom, topic, questions,
    topic_tree, term,
):
    """A parent must not read as fully on while a subtopic is off.

    The count rendered beside a parent is its whole subtree, so a parent that
    stayed ticked with a subtopic off would promise questions the set would
    not contain.
    """
    _open_planner(page, live_server, teacher_user, classroom)
    _make_plan(page, live_server, term, 'Half plan', 6)

    week = page.locator('#week-1')
    _expand_topic_groups(week)
    parent_box = week.locator(
        f'input[name="topic_ids"][value="{topic_tree["parent"].id}"]').first

    parent_box.check()
    expect(parent_box).to_be_checked()

    week.locator(
        f'input[name="topic_ids"][value="{topic_tree["subs"][0].id}"]',
    ).first.uncheck()

    expect(parent_box).not_to_be_checked()
    assert parent_box.evaluate('el => el.indeterminate') is True


@pytest.mark.django_db
def test_a_topic_shows_the_count_for_its_whole_subtree(
    page: Page, live_server, teacher_user, classroom, topic, questions,
    topic_tree, term,
):
    """3 of its own + 4 + 5 in its subtopics = the 12 a teacher would get."""
    _open_planner(page, live_server, teacher_user, classroom)
    _make_plan(page, live_server, term, 'Count plan', 6)

    week = page.locator('#week-1')
    _expand_topic_groups(week)
    parent_label = week.locator(
        f'input[name="topic_ids"][value="{topic_tree["parent"].id}"]',
    ).first.locator('xpath=..')
    expect(parent_label).to_contain_text('(12)')

    # Its own data- attribute stays at 3: the live tally sums every ticked box,
    # so a subtree total here would count the subtopics twice.
    expect(
        week.locator(
            f'input[name="topic_ids"][value="{topic_tree["parent"].id}"]').first,
    ).to_have_attribute('data-total', '3')


@pytest.mark.django_db
def test_topic_groups_start_shut_and_reopen_on_a_planned_week(
    page: Page, live_server, teacher_user, classroom, topic, questions,
    topic_tree, term,
):
    """The complaint this answers: one alphabetical wall of sub-topics.

    With more than one strand the picker opens on the strand names alone. A
    group is shut, not hidden: it carries an "n selected" badge as soon as
    something inside is ticked, and comes back open on the next visit so a
    planned week never hides its own selection.
    """
    _open_planner(page, live_server, teacher_user, classroom)
    _make_plan(page, live_server, term, 'Accordion plan', 6)

    week = page.locator('#week-1')
    sub_box = week.locator(
        f'input[name="topic_ids"][value="{topic_tree["subs"][0].id}"]').first
    expect(sub_box).to_be_hidden()

    _expand_topic_groups(week)
    expect(sub_box).to_be_visible()

    week.locator(
        f'input[name="topic_ids"][value="{topic_tree["parent"].id}"]',
    ).first.check()
    badge = week.locator(
        'details[data-topic-group] > summary [data-group-selected]').first
    expect(badge).to_contain_text('selected')

    week.locator('button[type="submit"]', has_text='Save week').click()
    page.wait_for_load_state('domcontentloaded')

    planned = page.locator('#week-1').locator(
        f'details[data-topic-group]:has(input[value="{topic_tree["subs"][0].id}"])',
    ).first
    assert planned.evaluate('el => el.open') is True
