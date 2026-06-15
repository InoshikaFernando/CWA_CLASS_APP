"""Tests for saved attempt history + the last-10 retention policy.

Covers homework submissions and quiz results (StudentFinalAnswer /
BasicFactsResult), plus the cross-role (student / teacher / parent) viewing of
a saved attempt's questions and answers.
"""
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Level, ParentStudent, School,
    SchoolTeacher, Subject, Topic,
)
from classroom.attempt_retention import ATTEMPT_HISTORY_LIMIT
from maths.models import Answer, Question, BasicFactsResult, StudentFinalAnswer

from .models import Homework, HomeworkStudentAnswer, HomeworkSubmission


class AttemptHistoryBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        teacher_role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        student_role, _ = Role.objects.get_or_create(name='student', defaults={'display_name': 'Student'})
        parent_role, _ = Role.objects.get_or_create(name='parent', defaults={'display_name': 'Parent'})

        cls.teacher = CustomUser.objects.create_user('teach', 'teach@t.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)
        cls.outsider = CustomUser.objects.create_user('outsider', 'out@t.com', 'pass1234')
        cls.outsider.roles.add(teacher_role)
        cls.student = CustomUser.objects.create_user('stud', 'stud@t.com', 'pass1234')
        cls.student.roles.add(student_role)
        cls.parent = CustomUser.objects.create_user('par', 'par@t.com', 'pass1234')
        cls.parent.roles.add(parent_role)

        admin = CustomUser.objects.create_user('adm', 'adm@t.com', 'pass1234')
        cls.school = School.objects.create(name='S', slug='s', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        cls.classroom = ClassRoom.objects.create(name='C', code='AH01', school=cls.school)
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student, is_active=True)
        ClassStudent.objects.filter(classroom=cls.classroom).update(
            joined_at=timezone.now() - timedelta(days=30)
        )
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school, is_active=True,
        )

        subject, _ = Subject.objects.get_or_create(slug='m-ah', defaults={'name': 'M'})
        cls.level, _ = Level.objects.get_or_create(level_number=701, defaults={'display_name': 'L'})
        cls.topic = Topic.objects.create(subject=subject, name='Adding', slug='adding-ah')

        cls.homework = Homework.objects.create(
            classroom=cls.classroom, title='HW', due_date=timezone.now() + timedelta(days=3),
            created_by=cls.teacher,
        )

    def _make_submission(self, attempt_number, score=3, total=5):
        return HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=attempt_number, score=score, total_questions=total,
        )


class HomeworkRetentionTest(AttemptHistoryBase):
    def test_prune_keeps_only_last_n_with_answers(self):
        # 12 attempts, each with one answer row.
        for n in range(1, 13):
            sub = self._make_submission(n)
            HomeworkStudentAnswer.objects.create(
                submission=sub, subject_slug='mathematics', content_id=1, is_correct=True,
            )

        HomeworkSubmission.prune_old_attempts(self.homework, self.student)

        remaining = list(
            HomeworkSubmission.objects
            .filter(homework=self.homework, student=self.student)
            .order_by('attempt_number')
            .values_list('attempt_number', flat=True)
        )
        self.assertEqual(len(remaining), ATTEMPT_HISTORY_LIMIT)
        # Oldest two attempts (1, 2) are pruned; newest (12) is kept.
        self.assertEqual(remaining, list(range(3, 13)))
        # Cascaded answers for pruned submissions are gone too.
        self.assertEqual(HomeworkStudentAnswer.objects.count(), ATTEMPT_HISTORY_LIMIT)


class HomeworkAttemptCountVsPruneTest(AttemptHistoryBase):
    def test_attempt_count_survives_pruning(self):
        # 12 attempts taken; retention keeps 10 rows, but the *count of attempts
        # taken* must still report 12 so the max_attempts cap keeps working.
        for n in range(1, 13):
            self._make_submission(n)
        HomeworkSubmission.prune_old_attempts(self.homework, self.student)
        self.assertEqual(
            HomeworkSubmission.objects.filter(
                homework=self.homework, student=self.student).count(),
            ATTEMPT_HISTORY_LIMIT,
        )
        self.assertEqual(
            HomeworkSubmission.get_attempt_count(self.homework, self.student), 12,
        )

    def test_max_attempts_above_retention_limit_still_caps(self):
        # A teacher sets max_attempts higher than the 10-row retention limit.
        self.homework.max_attempts = 12
        self.homework.save(update_fields=['max_attempts'])
        for n in range(1, 13):
            self._make_submission(n)
        HomeworkSubmission.prune_old_attempts(self.homework, self.student)
        count = HomeworkSubmission.get_attempt_count(self.homework, self.student)
        # Cap reached → no further attempt allowed (mirrors the view's gate).
        self.assertFalse(
            self.homework.attempts_unlimited or count < self.homework.max_attempts
        )


class HomeworkHistoryViewAccessTest(AttemptHistoryBase):
    def setUp(self):
        self.client = Client()
        self.sub = self._make_submission(1)
        HomeworkStudentAnswer.objects.create(
            submission=self.sub, subject_slug='mathematics', content_id=1, is_correct=True,
        )

    def test_student_sees_own_history(self):
        self.client.force_login(self.student)
        r = self.client.get(reverse('homework:attempt_history', args=[self.homework.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Attempt 1')

    def test_teacher_sees_student_history_and_result(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse(
            'homework:student_attempt_history', args=[self.homework.id, self.student.id],
        ))
        self.assertEqual(r.status_code, 200)
        # Teacher can open the per-attempt review (questions/answers) page.
        r2 = self.client.get(reverse('homework:student_result', args=[self.sub.id]))
        self.assertEqual(r2.status_code, 200)

    def test_parent_sees_child_history(self):
        self.client.force_login(self.parent)
        r = self.client.get(reverse(
            'homework:student_attempt_history', args=[self.homework.id, self.student.id],
        ))
        self.assertEqual(r.status_code, 200)

    def test_unrelated_teacher_is_blocked(self):
        self.client.force_login(self.outsider)
        r = self.client.get(reverse(
            'homework:student_attempt_history', args=[self.homework.id, self.student.id],
        ))
        self.assertEqual(r.status_code, 404)
        r2 = self.client.get(reverse('homework:student_result', args=[self.sub.id]))
        self.assertEqual(r2.status_code, 404)


class QuizRetentionTest(AttemptHistoryBase):
    def test_studentfinalanswer_pruned_per_series(self):
        for n in range(1, 13):
            StudentFinalAnswer.objects.create(
                student=self.student, topic=self.topic, level=self.level,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
                score=1, total_questions=5, attempt_number=n,
            )
        last = StudentFinalAnswer.objects.filter(student=self.student).order_by('-id').first()
        StudentFinalAnswer.prune_old_attempts(last)
        self.assertEqual(
            StudentFinalAnswer.objects.filter(student=self.student).count(),
            ATTEMPT_HISTORY_LIMIT,
        )

    def test_times_table_series_isolated_from_topic(self):
        # A different series (times tables) must not be pruned by topic pruning.
        for n in range(1, 13):
            StudentFinalAnswer.objects.create(
                student=self.student, topic=self.topic, level=self.level,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
                score=1, total_questions=5, attempt_number=n,
            )
        tt = StudentFinalAnswer.objects.create(
            student=self.student, quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=7, operation='multiplication', score=5, total_questions=5,
        )
        StudentFinalAnswer.prune_old_attempts(
            StudentFinalAnswer.objects.filter(
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC).order_by('-id').first()
        )
        # The lone times-table attempt survives.
        self.assertTrue(StudentFinalAnswer.objects.filter(pk=tt.pk).exists())

    def test_basic_facts_pruned(self):
        for _ in range(12):
            r = BasicFactsResult.objects.create(
                student=self.student, subtopic='Addition', level_number=1,
                session_id='x', score=5, total_points=5, time_taken_seconds=10, points=1,
                questions_data=[{'question': '1+1', 'student_answer': '2',
                                 'answer': 2, 'is_correct': True}],
            )
        BasicFactsResult.prune_old_attempts(r)
        self.assertEqual(
            BasicFactsResult.objects.filter(student=self.student).count(),
            ATTEMPT_HISTORY_LIMIT,
        )


class QuizReviewViewTest(AttemptHistoryBase):
    def setUp(self):
        self.client = Client()
        self.sfa = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
            score=1, total_questions=2, attempt_number=1,
            questions_data=[
                {'question': '2+2=?', 'student_answer': '4', 'correct_answer': '4', 'is_correct': True},
                {'question': '3+3=?', 'student_answer': '5', 'correct_answer': '6', 'is_correct': False},
            ],
        )

    def test_student_review_shows_questions_and_answers(self):
        self.client.force_login(self.student)
        r = self.client.get(reverse('quiz_attempt_review', args=['sfa', self.sfa.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '2+2=?')
        self.assertContains(r, '3+3=?')

    def test_teacher_can_review_student_quiz(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('quiz_attempt_review', args=['sfa', self.sfa.id]))
        self.assertEqual(r.status_code, 200)

    def test_outsider_blocked(self):
        self.client.force_login(self.outsider)
        r = self.client.get(reverse('quiz_attempt_review', args=['sfa', self.sfa.id]))
        self.assertEqual(r.status_code, 404)

    def test_history_list_for_student(self):
        self.client.force_login(self.student)
        r = self.client.get(reverse('quiz_attempt_history'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.topic.name)

    def test_teacher_sees_student_quiz_history(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('quiz_student_attempt_history', args=[self.student.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.topic.name)

    def test_parent_sees_child_quiz_history(self):
        self.client.force_login(self.parent)
        r = self.client.get(reverse('quiz_student_attempt_history', args=[self.student.id]))
        self.assertEqual(r.status_code, 200)

    def test_outsider_blocked_from_quiz_history(self):
        self.client.force_login(self.outsider)
        r = self.client.get(reverse('quiz_student_attempt_history', args=[self.student.id]))
        self.assertEqual(r.status_code, 404)

    def test_history_hides_review_link_when_no_questions_data(self):
        # setUp already created one attempt WITH questions_data (reviewable).
        # An extra attempt with empty questions_data must not be clickable, so
        # the page should hold exactly one review link.
        StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
            score=0, total_questions=2, attempt_number=2, questions_data=[],
        )
        self.client.force_login(self.student)
        r = self.client.get(reverse('quiz_attempt_history'))
        self.assertEqual(r.status_code, 200)
        review_url = reverse('quiz_attempt_review', args=['sfa', self.sfa.id])
        self.assertContains(r, review_url, count=1)
