"""``manage.py rebuild_points_ledger`` — the day-one backfill.

Without it every existing student would arrive on the leaderboard at zero,
however much work they had already done.
"""

import pytest
from django.core.management import call_command
from django.utils import timezone

from rewards.models import PointsAward, PointsSource, StudentPointsTotal

from .factories import make_student


pytestmark = pytest.mark.django_db


def run(**kwargs):
    call_command('rebuild_points_ledger', verbosity=0, **kwargs)


@pytest.fixture
def student_with_history(db):
    """A student with pre-existing work in three different apps."""
    from classroom.models import ClassRoom, Level, School, Subject, Topic
    from homework.models import Homework, HomeworkSubmission
    from maths.models import BasicFactsResult, StudentFinalAnswer

    student = make_student('veteran', first_name='Vera', last_name='Ng')

    subject, _ = Subject.objects.get_or_create(
        slug='mathematics', school=None,
        defaults={'name': 'Mathematics', 'is_active': True},
    )
    level = Level.objects.create(level_number=4, display_name='Year 4')
    topic = Topic.objects.create(subject=subject, name='Addition', slug='addition')

    StudentFinalAnswer.objects.create(
        student=student, topic=topic, level=level,
        quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
        score=8, total_questions=10, points=64.0,
    )
    BasicFactsResult.objects.create(
        student=student, subtopic='Addition', level_number=1,
        score=9, total_points=10, points=88.0, time_taken_seconds=60,
    )
    school = School.objects.create(name='Old School', slug='old-school')
    classroom = ClassRoom.objects.create(name='Y4', code='OLD00001', school=school)
    homework = Homework.objects.create(
        classroom=classroom, title='Fractions', due_date=timezone.now(),
        num_questions=10,
    )
    HomeworkSubmission.objects.create(
        homework=homework, student=student, attempt_number=1,
        score=7, total_questions=10, points=61.0,
    )
    return student


class TestRebuild:

    def test_existing_work_lands_on_the_leaderboard(self, student_with_history):
        run()

        sources = set(
            PointsAward.objects
            .filter(student=student_with_history)
            .values_list('source', flat=True)
        )
        assert sources == {
            PointsSource.MATHS_QUIZ,
            PointsSource.BASIC_FACTS,
            PointsSource.HOMEWORK,
        }
        # 64 (topic quiz) + 88 (basic facts) + 70 (homework, by percentage)
        assert StudentPointsTotal.objects.get(
            student=student_with_history).total_points == 222.0

    def test_it_is_idempotent(self, student_with_history):
        run()
        run()

        assert PointsAward.objects.filter(student=student_with_history).count() == 3
        assert StudentPointsTotal.objects.get(
            student=student_with_history).total_points == 222.0

    def test_it_keeps_only_the_best_surviving_attempt_per_unit(self, student_with_history):
        from maths.models import StudentFinalAnswer

        first = StudentFinalAnswer.objects.get(student=student_with_history)
        StudentFinalAnswer.objects.create(
            student=student_with_history, topic=first.topic, level=first.level,
            quiz_type=first.quiz_type, attempt_number=2,
            score=9, total_questions=10, points=91.0,
        )
        run()

        award = PointsAward.objects.get(
            student=student_with_history, source=PointsSource.MATHS_QUIZ)
        assert award.points == 91.0

    def test_it_never_lowers_a_score_the_ledger_already_holds(self, student_with_history):
        """Re-running it repairs a drifted ledger; it must never punish a
        student whose best attempt has since been pruned from its source."""
        from homework.models import HomeworkSubmission
        from rewards.services import award_points

        homework_id = str(HomeworkSubmission.objects.get(
            student=student_with_history).homework_id)
        award_points(student_with_history, PointsSource.HOMEWORK, homework_id, 100)
        run()

        assert PointsAward.objects.get(
            student=student_with_history,
            source=PointsSource.HOMEWORK,
        ).points == 100.0

    def test_dry_run_writes_nothing(self, student_with_history):
        run(dry_run=True)
        assert not PointsAward.objects.exists()

    def test_it_can_be_limited_to_one_student(self, student_with_history):
        from maths.models import BasicFactsResult

        other = make_student('other')
        BasicFactsResult.objects.create(
            student=other, subtopic='Addition', level_number=1,
            score=5, total_points=10, points=50.0, time_taken_seconds=60,
        )
        run(student='veteran')

        assert PointsAward.objects.filter(student=student_with_history).exists()
        assert not PointsAward.objects.filter(student=other).exists()

    def test_a_student_with_no_activity_still_gets_a_zero_row(self):
        idle = make_student('idle')
        run()

        assert StudentPointsTotal.objects.get(student=idle).total_points == 0.0
