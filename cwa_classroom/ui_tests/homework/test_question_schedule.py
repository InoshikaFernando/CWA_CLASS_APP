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
