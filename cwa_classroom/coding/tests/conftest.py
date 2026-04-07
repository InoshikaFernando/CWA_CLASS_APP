"""
conftest.py — shared pytest fixtures for the coding app test suite.
All fixtures use Django's test database and are function-scoped by default.
"""
import pytest
from django.contrib.auth import get_user_model

from coding.models import (
    CodingLanguage,
    CodingTopic,
    CodingExercise,
    CodingProblem,
    ProblemTestCase,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@pytest.fixture
def student(db):
    """Regular student user."""
    return User.objects.create_user(
        username='test_student',
        password='testpass123',
        email='student@test.com',
    )


@pytest.fixture
def student2(db):
    """Second student — used for isolation tests."""
    return User.objects.create_user(
        username='test_student2',
        password='testpass123',
        email='student2@test.com',
    )


@pytest.fixture
def staff_user(db):
    """Staff/superuser for admin-only endpoints."""
    return User.objects.create_user(
        username='staff_user',
        password='testpass123',
        email='staff@test.com',
        is_staff=True,
        is_superuser=True,
    )


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

@pytest.fixture
def python_lang(db):
    return CodingLanguage.objects.create(
        name='Python',
        slug='python',
        description='Python language',
        color='#3b82f6',
        order=1,
        is_active=True,
    )


@pytest.fixture
def js_lang(db):
    return CodingLanguage.objects.create(
        name='JavaScript',
        slug='javascript',
        description='JavaScript language',
        color='#f59e0b',
        order=2,
        is_active=True,
    )


@pytest.fixture
def html_lang(db):
    return CodingLanguage.objects.create(
        name='HTML / CSS',
        slug='html-css',
        description='HTML and CSS',
        color='#ef4444',
        order=3,
        is_active=True,
    )


@pytest.fixture
def scratch_lang(db):
    return CodingLanguage.objects.create(
        name='Scratch',
        slug='scratch',
        description='Scratch visual language',
        color='#f97316',
        order=4,
        is_active=True,
    )


@pytest.fixture
def inactive_lang(db):
    return CodingLanguage.objects.create(
        name='Inactive',
        slug='python',  # won't conflict — different fixture scope
        description='Inactive language',
        is_active=False,
    )


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

@pytest.fixture
def python_topic(db, python_lang):
    return CodingTopic.objects.create(
        language=python_lang,
        name='Variables',
        slug='variables',
        description='Learn about variables',
        order=1,
        is_active=True,
    )


@pytest.fixture
def python_topic2(db, python_lang):
    return CodingTopic.objects.create(
        language=python_lang,
        name='Loops',
        slug='loops',
        description='Learn about loops',
        order=2,
        is_active=True,
    )


@pytest.fixture
def inactive_topic(db, python_lang):
    return CodingTopic.objects.create(
        language=python_lang,
        name='Inactive Topic',
        slug='inactive-topic',
        is_active=False,
    )


# ---------------------------------------------------------------------------
# Exercises
# ---------------------------------------------------------------------------

@pytest.fixture
def beginner_exercise(db, python_topic):
    return CodingExercise.objects.create(
        topic=python_topic,
        level=CodingExercise.BEGINNER,
        title='Hello World',
        description='Print Hello, World!',
        starter_code='# Write your code here\n',
        expected_output='Hello, World!',
        hints='Use print()',
        order=1,
        is_active=True,
    )


@pytest.fixture
def intermediate_exercise(db, python_topic):
    return CodingExercise.objects.create(
        topic=python_topic,
        level=CodingExercise.INTERMEDIATE,
        title='Type Inspector',
        description='Check types of variables',
        starter_code='# Check types\n',
        order=2,
        is_active=True,
    )


@pytest.fixture
def advanced_exercise(db, python_topic):
    return CodingExercise.objects.create(
        topic=python_topic,
        level=CodingExercise.ADVANCED,
        title='Type Casting',
        description='Cast types',
        order=3,
        is_active=True,
    )


@pytest.fixture
def inactive_exercise(db, python_topic):
    return CodingExercise.objects.create(
        topic=python_topic,
        level=CodingExercise.BEGINNER,
        title='Inactive Exercise',
        description='This is inactive',
        is_active=False,
    )


# ---------------------------------------------------------------------------
# Problems & Test Cases
# ---------------------------------------------------------------------------

@pytest.fixture
def python_problem(db, python_lang):
    return CodingProblem.objects.create(
        language=python_lang,
        title='Reverse a String',
        description='Read a string and print it reversed.',
        starter_code='s = input()\n',
        difficulty=1,
        is_active=True,
    )


@pytest.fixture
def hard_problem(db, python_lang):
    return CodingProblem.objects.create(
        language=python_lang,
        title='Bubble Sort',
        description='Sort a list using bubble sort.',
        starter_code='numbers = list(map(int, input().split()))\n',
        difficulty=5,
        is_active=True,
    )


@pytest.fixture
def visible_test_case(db, python_problem):
    return ProblemTestCase.objects.create(
        problem=python_problem,
        input_data='hello',
        expected_output='olleh',
        is_visible=True,
        description='Basic word',
        order=1,
    )


@pytest.fixture
def hidden_test_case(db, python_problem):
    return ProblemTestCase.objects.create(
        problem=python_problem,
        input_data='a',
        expected_output='a',
        is_visible=False,
        description='Single character',
        order=2,
    )


@pytest.fixture
def problem_with_cases(db, python_problem, visible_test_case, hidden_test_case):
    """Problem with 1 visible + 1 hidden test case."""
    return python_problem


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

@pytest.fixture
def completed_submission(db, student, beginner_exercise):
    return StudentExerciseSubmission.objects.create(
        student=student,
        exercise=beginner_exercise,
        code_submitted='print("Hello, World!")',
        output_received='Hello, World!',
        is_completed=True,
        time_taken_seconds=30,
    )


@pytest.fixture
def incomplete_submission(db, student, beginner_exercise):
    return StudentExerciseSubmission.objects.create(
        student=student,
        exercise=beginner_exercise,
        code_submitted='print("wrong")',
        output_received='wrong',
        is_completed=False,
    )


@pytest.fixture
def passing_problem_submission(db, student, python_problem):
    return StudentProblemSubmission.objects.create(
        student=student,
        problem=python_problem,
        attempt_number=1,
        code_submitted='s = input(); print(s[::-1])',
        passed_all_tests=True,
        visible_passed=1,
        visible_total=1,
        hidden_passed=1,
        hidden_total=1,
        points=85.5,
        time_taken_seconds=45,
    )


@pytest.fixture
def failing_problem_submission(db, student, python_problem):
    return StudentProblemSubmission.objects.create(
        student=student,
        problem=python_problem,
        attempt_number=1,
        code_submitted='print("wrong")',
        passed_all_tests=False,
        visible_passed=0,
        visible_total=1,
        hidden_passed=0,
        hidden_total=1,
        points=0.0,
        time_taken_seconds=20,
    )


# ---------------------------------------------------------------------------
# Authenticated clients
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_client(client, student):
    """Django test client logged in as a regular student."""
    client.force_login(student)
    return client


@pytest.fixture
def staff_client(client, staff_user):
    """Django test client logged in as staff/superuser."""
    client.force_login(staff_user)
    return client
