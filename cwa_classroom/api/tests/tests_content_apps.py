"""Billing, coding, puzzles, worksheets, help and feedback.

The answer-key tests here are the ones worth reading: an endpoint that ships
the solution alongside the exercise does not fail, it just quietly ends the
exercise for every student who opens developer tools.
"""

import pytest

from accounts.models import Role

pytestmark = pytest.mark.django_db


# --- Coding -----------------------------------------------------------------

@pytest.fixture
def coding_exercise(db):
    from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel

    language = CodingLanguage.objects.create(name='Python', slug='python')
    topic = CodingTopic.objects.create(language=language, name='Loops', slug='loops')
    topic_level = TopicLevel.objects.create(topic=topic, level_choice='beginner')
    return CodingExercise.objects.create(
        topic_level=topic_level, title='Count to ten',
        description='Print 1..10', starter_code='# here',
        solution_code='for i in range(1, 11): print(i)',
        expected_output='1\n2\n', order=0,
    )


def test_student_never_receives_the_reference_solution(api, auth, student,
                                                       coding_exercise):
    auth(student)
    response = api.get(f'/api/v1/coding/exercises/{coding_exercise.id}/')
    assert response.status_code == 200
    assert 'solution_code' not in response.data
    assert 'range(1, 11)' not in str(response.data)


def test_teacher_does_receive_the_reference_solution(api, auth, teacher,
                                                     coding_exercise):
    auth(teacher)
    response = api.get(f'/api/v1/coding/exercises/{coding_exercise.id}/')
    assert response.data['solution_code'] == 'for i in range(1, 11): print(i)'


def test_solution_is_absent_from_the_list_endpoint_too(api, auth, student,
                                                       coding_exercise):
    auth(student)
    response = api.get('/api/v1/coding/exercises/')
    assert 'solution_code' not in str(response.data)


def test_coding_submission_records_the_caller_not_the_payload(
        api, auth, student, other_student, coding_exercise):
    auth(student)
    response = api.post('/api/v1/coding/submissions/', {
        'exercise': coding_exercise.id,
        'code_submitted': 'print(1)',
        'student': other_student.id,   # ignored — the caller is the student
    }, format='json')
    assert response.status_code == 201, response.data

    from coding.models import StudentExerciseSubmission
    submission = StudentExerciseSubmission.objects.get()
    assert submission.student_id == student.id


def test_a_coding_submission_without_an_exercise_is_a_400_not_a_500(
        api, auth, student):
    """A missing relation must come back as a validation error the app can
    show, not as an unhandled server error."""
    auth(student)
    response = api.post('/api/v1/coding/submissions/',
                        {'code_submitted': 'print(1)'}, format='json')
    assert response.status_code == 400
    assert response.data['error']['code'] == 'validation_error'


# --- Number puzzles ---------------------------------------------------------

def test_puzzle_never_ships_its_solution(api, auth, student):
    from number_puzzles.models import NumberPuzzle, NumberPuzzleLevel

    level = NumberPuzzleLevel.objects.create(
        number=1, name='One', slug='one', operators_allowed='+-')
    NumberPuzzle.objects.create(
        level=level, operands=[2, 3], target=5,
        display_template='2 _ 3 = 5', solution='2 + 3')

    auth(student)
    response = api.get('/api/v1/puzzles/')
    assert response.status_code == 200
    assert '2 + 3' not in str(response.data)
    # Check the field key, not a substring: `has_multiple_solutions` is a
    # legitimate field and contains the word.
    assert 'solution' not in response.data['results'][0]


# --- Billing ----------------------------------------------------------------

@pytest.fixture
def invoice(db, school, student):
    from classroom.models import Invoice

    return Invoice.objects.create(
        invoice_number='INV-001', school=school, student=student,
        billing_period_start='2026-03-01', billing_period_end='2026-03-31',
        attendance_mode='all_class_days', amount=120, calculated_amount=120,
        status='issued',
    )


def test_student_sees_their_own_invoice(api, auth, student, invoice):
    auth(student)
    rows = api.get('/api/v1/invoices/').data['results']
    assert [row['invoice_number'] for row in rows] == ['INV-001']


def test_draft_invoices_are_never_returned(api, auth, student, invoice):
    """A draft is the school's working state, not a bill anyone has been asked
    to pay."""
    invoice.status = 'draft'
    invoice.save(update_fields=['status'])
    auth(student)
    assert api.get('/api/v1/invoices/').data['results'] == []


def test_another_student_cannot_see_the_invoice(api, auth, other_student, invoice):
    auth(other_student)
    assert api.get('/api/v1/invoices/').data['results'] == []
    assert api.get(f'/api/v1/invoices/{invoice.id}/').status_code == 404


def test_parent_sees_their_childs_invoice(api, auth, parent, student, invoice):
    from classroom.models import ParentStudent

    ParentStudent.objects.create(parent=parent, student=student, is_active=True)
    auth(parent)
    rows = api.get('/api/v1/invoices/').data['results']
    assert [row['invoice_number'] for row in rows] == ['INV-001']


def test_invoices_are_read_only(api, auth, student, invoice):
    """Money has one source of truth and it is not the phone."""
    auth(student)
    assert api.post('/api/v1/invoices/', {'amount': 1}, format='json').status_code == 405
    assert api.patch(f'/api/v1/invoices/{invoice.id}/', {'amount': 0},
                     format='json').status_code == 405


# --- Help -------------------------------------------------------------------

def test_help_articles_are_filtered_to_the_callers_role(api, auth, student, teacher):
    from help.models import HelpArticle, HelpArticleRole, HelpCategory

    category = HelpCategory.objects.create(name='Billing', slug='billing')
    staff_only = HelpArticle.objects.create(
        title='Issuing invoices', slug='issuing-invoices',
        category=category, body_markdown='Internal fee cascade notes.')
    HelpArticleRole.objects.create(article=staff_only, role_group='hoi')

    for_students = HelpArticle.objects.create(
        title='Doing your homework', slug='doing-homework',
        category=category, body_markdown='Tap the homework tab.')
    HelpArticleRole.objects.create(article=for_students, role_group='student')

    auth(student)
    titles = [row['title'] for row in api.get('/api/v1/help/articles/').data['results']]
    assert titles == ['Doing your homework']
    assert 'Issuing invoices' not in titles


def test_a_student_cannot_fetch_a_staff_article_by_slug(api, auth, student):
    from help.models import HelpArticle, HelpArticleRole, HelpCategory

    category = HelpCategory.objects.create(name='Billing', slug='billing')
    article = HelpArticle.objects.create(
        title='Salary slips', slug='salary-slips',
        category=category, body_markdown='Internal.')
    HelpArticleRole.objects.create(article=article, role_group='hoi')

    auth(student)
    assert api.get('/api/v1/help/articles/salary-slips/').status_code == 404


# --- Feedback ---------------------------------------------------------------

def test_feedback_is_filed_as_the_caller(api, auth, student, other_student):
    auth(student)
    response = api.post('/api/v1/feedback/', {
        'category': 'bug',
        'title': 'Homework tab is blank',
        'description': 'Nothing loads.',
        'submitted_by': other_student.id,   # ignored
    }, format='json')
    assert response.status_code == 201

    from feedback.models import Feedback
    assert Feedback.objects.get().submitted_by_id == student.id


def test_a_user_only_sees_their_own_feedback(api, auth, student, other_student):
    from feedback.models import Feedback

    Feedback.objects.create(submitted_by=student, category='bug',
                            title='Mine', description='x')
    Feedback.objects.create(submitted_by=other_student, category='bug',
                            title='Theirs', description='y')
    auth(student)
    rows = api.get('/api/v1/feedback/').data['results']
    assert [row['title'] for row in rows] == ['Mine']


def test_feedback_does_not_expose_triage_state(api, auth, student):
    from feedback.models import Feedback

    Feedback.objects.create(submitted_by=student, category='bug',
                            title='Mine', description='x',
                            jira_key='CPP-999', priority='High')
    auth(student)
    row = api.get('/api/v1/feedback/').data['results'][0]
    assert 'jira_key' not in row
    assert 'assignee' not in row
    assert 'priority' not in row
