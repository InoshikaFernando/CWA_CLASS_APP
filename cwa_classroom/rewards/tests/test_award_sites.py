"""Every activity credits the same global total.

The requirement these tests exist for: *"We add points when students work on
this system, regardless of the subject / topic / year — whether a student does
global questions or homework, it should add points."*

Each test drives the real award site — the view or the helper the view calls —
rather than calling ``award_points`` directly, so a refactor that quietly stops
crediting an activity fails here instead of shipping a leaderboard that has
silently stopped moving.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from classroom.models import Level, School, SchoolStudent, Subject, Topic
from maths.models import Answer, Question
from rewards.models import PointsAward, PointsSource, StudentPointsTotal

from .factories import make_student


pytestmark = pytest.mark.django_db


def award_for(student, source):
    return PointsAward.objects.filter(student=student, source=source).first()


def total_for(student):
    row = StudentPointsTotal.objects.filter(student=student).first()
    return row.total_points if row else 0.0


# ---------------------------------------------------------------------------
# Global questions — the case the requirement calls out by name
# ---------------------------------------------------------------------------

@pytest.fixture
def global_maths_quiz(db):
    """A topic quiz over the *global* question bank (``school=None``).

    ``TopicQuizView`` serves ``Question.objects.global_only()``, so this is
    exactly the "student does global questions" path.
    """
    subject, _ = Subject.objects.get_or_create(
        slug='mathematics', school=None,
        defaults={'name': 'Mathematics', 'is_active': True},
    )
    level = Level.objects.create(level_number=4, display_name='Year 4')
    topic = Topic.objects.create(
        subject=subject, name='Addition', slug='addition', is_active=True,
    )
    topic.levels.add(level)
    for i in range(12):
        question = Question.objects.create(
            question_text=f'What is {i}+1?', question_type='multiple_choice',
            topic=topic, level=level,
        )
        Answer.objects.create(question=question, answer_text=str(i + 1), is_correct=True, order=1)
        Answer.objects.create(question=question, answer_text=str(i + 2), is_correct=False, order=2)
    assert Question.objects.filter(school__isnull=True).count() == 12
    return {'subject': subject, 'level': level, 'topic': topic}


def _sit_topic_quiz(client, topic, level_number=4, subject='mathematics'):
    """Play a whole topic quiz through the real views, answering correctly."""
    url = reverse('topic_quiz', kwargs={
        'subject': subject, 'level_number': level_number, 'topic_id': topic.id,
    })
    assert client.get(url).status_code == 200

    session_key = next(
        k for k in client.session.keys()
        if k.startswith('tq_') and not k.startswith('tq_result_')
    )
    session_id = session_key[3:]
    submit_url = reverse('api_submit_topic_answer')
    for entry in client.session[session_key]['questions']:
        question = Question.objects.get(pk=entry['id'])
        correct = question.answers.filter(is_correct=True).first()
        response = client.post(
            submit_url,
            data=json.dumps({
                'session_id': session_id,
                'question_id': question.id,
                'answer_id': correct.id,
            }),
            content_type='application/json',
        )
        assert response.status_code == 200


class TestGlobalQuestionsAwardPoints:

    def test_finishing_a_global_question_quiz_credits_the_total(self, global_maths_quiz):
        student = make_student('gq-student')
        SchoolStudent.objects.create(
            school=School.objects.create(name='Test School'),
            student=student, is_active=True,
        )
        client = Client()
        client.force_login(student)

        _sit_topic_quiz(client, global_maths_quiz['topic'])

        award = award_for(student, PointsSource.MATHS_QUIZ)
        assert award is not None, 'a completed global-question quiz awarded nothing'
        assert award.points > 0
        assert total_for(student) == award.points

    def test_the_unit_is_the_topic_and_level_not_the_attempt(self, global_maths_quiz):
        """Re-sitting the same quiz raises that one unit — it does not add a
        second one. Otherwise a student could farm the podium by replaying one
        easy topic."""
        student = make_student('gq-repeat')
        client = Client()
        client.force_login(student)

        _sit_topic_quiz(client, global_maths_quiz['topic'])
        _sit_topic_quiz(client, global_maths_quiz['topic'])

        assert PointsAward.objects.filter(student=student).count() == 1

    def test_a_student_with_no_school_still_earns(self, global_maths_quiz):
        """The global bank is the whole curriculum for a student who belongs to
        no school, so it must credit them without a SchoolStudent row."""
        student = make_student('solo')
        assert not SchoolStudent.objects.filter(student=student).exists()
        client = Client()
        client.force_login(student)

        _sit_topic_quiz(client, global_maths_quiz['topic'])

        assert total_for(student) > 0
        assert StudentPointsTotal.objects.get(student=student).is_ranked is True


# ---------------------------------------------------------------------------
# Homework
# ---------------------------------------------------------------------------

@pytest.fixture
def homework_for(db):
    """Build a homework in its own school — School.slug and ClassRoom.code are
    both unique, so each call needs its own."""
    from itertools import count

    from classroom.models import ClassRoom
    from homework.models import Homework

    counter = count(1)

    def _make(title='Fractions 1'):
        n = next(counter)
        school = School.objects.create(name=f'HW School {n}', slug=f'hw-school-{n}')
        classroom = ClassRoom.objects.create(
            name='Y5', code=f'HW{n:06d}', school=school,
        )
        return Homework.objects.create(
            classroom=classroom, title=title,
            due_date=timezone.now(), num_questions=10,
        )
    return _make


class TestHomeworkAwards:

    def test_a_submission_credits_the_total(self, homework_for):
        from homework.models import HomeworkSubmission
        from homework.views import _award_homework_points

        student = make_student('hw-student')
        submission = HomeworkSubmission.objects.create(
            homework=homework_for(), student=student, attempt_number=1,
            score=8, total_questions=10, points=73.4, time_taken_seconds=300,
        )
        _award_homework_points(submission)

        assert award_for(student, PointsSource.HOMEWORK).points == 80.0

    def test_it_is_scored_on_percentage_so_a_regrade_cannot_change_the_scale(self, homework_for):
        """``submission.points`` has two writers on two different scales — the
        submit path sets 0–100, ``_recalculate_submission_score`` sums roughly
        one per question. Percentage is what they agree on."""
        from homework.models import HomeworkSubmission
        from homework.views import _award_homework_points

        student = make_student('hw-regrade')
        homework = homework_for()
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=student, attempt_number=1,
            score=8, total_questions=10, points=73.4,
        )
        _award_homework_points(submission)
        before = award_for(student, PointsSource.HOMEWORK).points

        submission.points = 8.0            # the small-scale writer
        submission.save(update_fields=['points'])
        _award_homework_points(submission)

        assert award_for(student, PointsSource.HOMEWORK).points == before == 80.0

    def test_a_late_regrade_can_raise_but_never_lower_the_award(self, homework_for):
        from homework.models import HomeworkSubmission
        from homework.views import _award_homework_points

        student = make_student('hw-ai')
        homework = homework_for()
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=student, attempt_number=1,
            score=6, total_questions=10,
        )
        _award_homework_points(submission)

        submission.score = 9               # AI grader marks the written answers
        submission.save(update_fields=['score'])
        _award_homework_points(submission)
        assert award_for(student, PointsSource.HOMEWORK).points == 90.0

        submission.score = 2               # a worse later attempt
        submission.save(update_fields=['score'])
        _award_homework_points(submission)
        assert award_for(student, PointsSource.HOMEWORK).points == 90.0

    def test_a_second_homework_adds_a_second_unit(self, homework_for):
        from homework.models import HomeworkSubmission
        from homework.views import _award_homework_points

        student = make_student('hw-two')
        for title in ('Fractions 1', 'Fractions 2'):
            homework = homework_for()
            homework.title = title
            homework.save(update_fields=['title'])
            _award_homework_points(HomeworkSubmission.objects.create(
                homework=homework, student=student, attempt_number=1,
                score=5, total_questions=10,
            ))

        assert PointsAward.objects.filter(
            student=student, source=PointsSource.HOMEWORK).count() == 2
        assert total_for(student) == 100.0


# ---------------------------------------------------------------------------
# Number puzzles — no points column of their own before this
# ---------------------------------------------------------------------------

class TestNumberPuzzleAwards:

    def test_completing_a_puzzle_level_credits_the_total(self):
        from number_puzzles.models import NumberPuzzleLevel, PuzzleSession
        from number_puzzles.views import _update_progress

        student = make_student('puzzler')
        level = NumberPuzzleLevel.objects.create(number=1, name='Level 1')
        session = PuzzleSession.objects.create(
            student=student, level=level, score=7, total_questions=10,
            status='completed', duration_seconds=120,
        )
        _update_progress(student, level, session)

        assert award_for(student, PointsSource.NUMBER_PUZZLE).points == 70.0

    def test_a_worse_replay_keeps_the_students_best(self):
        from number_puzzles.models import NumberPuzzleLevel, PuzzleSession
        from number_puzzles.views import _update_progress

        student = make_student('puzzler2')
        level = NumberPuzzleLevel.objects.create(number=1, name='Level 1')
        for score in (9, 3):
            session = PuzzleSession.objects.create(
                student=student, level=level, score=score, total_questions=10,
                status='completed', duration_seconds=120,
            )
            _update_progress(student, level, session)

        assert award_for(student, PointsSource.NUMBER_PUZZLE).points == 90.0


# ---------------------------------------------------------------------------
# Coding exercises — also awarded nothing before this
# ---------------------------------------------------------------------------

class TestCodingExerciseAwards:

    @pytest.fixture
    def exercise(self, db):
        from coding.models import (
            CodingExercise, CodingLanguage, CodingTopic, TopicLevel,
        )
        language = CodingLanguage.objects.create(
            name='Python', slug='python', is_active=True,
        )
        topic = CodingTopic.objects.create(
            language=language, name='Loops', slug='loops', is_active=True,
        )
        topic_level = TopicLevel.objects.create(
            topic=topic, level_choice=CodingExercise.BEGINNER,
        )
        return CodingExercise.objects.create(
            topic_level=topic_level, title='Count to ten',
            description='Print the numbers 1 to 10.', is_active=True,
        )

    def test_completing_an_exercise_credits_the_total(self, exercise):
        from coding.views import _save_exercise_submission

        student = make_student('coder')
        _save_exercise_submission(
            student, exercise.id, exercise.topic_level.topic.language,
            code='print(1)', stdout='1', stderr='', completed=True,
        )

        assert award_for(student, PointsSource.CODING_EXERCISE).points == 100.0

    def test_an_unfinished_exercise_awards_nothing(self, exercise):
        from coding.views import _save_exercise_submission

        student = make_student('coder2')
        _save_exercise_submission(
            student, exercise.id, exercise.topic_level.topic.language,
            code='print(', stdout='', stderr='SyntaxError', completed=False,
        )

        assert award_for(student, PointsSource.CODING_EXERCISE) is None


# ---------------------------------------------------------------------------
# Coverage: no activity is left out
# ---------------------------------------------------------------------------

def test_every_source_is_written_by_some_award_site():
    """A source nobody writes is an activity earning nothing.

    Grep the apps for the ``PointsSource`` members they hand to
    ``award_points`` — if a member is declared but never awarded anywhere, the
    ledger claims to cover an activity it does not.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    written = set()
    for path in root.glob('*/views.py'):
        if path.parent.name == 'rewards':
            continue
        for name in re.findall(r'PointsSource\.([A-Z_]+)', path.read_text()):
            written.add(name)

    declared = {member.name for member in PointsSource}
    assert declared - written == set(), (
        f'PointsSource members no award site writes: {sorted(declared - written)}'
    )
