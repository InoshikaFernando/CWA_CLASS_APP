"""
Tests for the question-automation schedule (CPP-399).

Covers the four things that make or break this feature in production:
  * the plan is built over the right weeks, and holidays are respected;
  * generation is idempotent, so a class never gets two sets for one week;
  * a week that yields nothing is loud, not silent;
  * students see nothing until the existing publish cron says so.
"""

import re
from datetime import date, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    AcademicYear,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    Department,
    Level,
    Notification,
    PublicHoliday,
    School,
    SchoolHoliday,
    SchoolTeacher,
    Subject,
    Term,
    Topic,
)
from maths.models import Answer, Question

from . import schedule_services as svc
from .models import Homework, HomeworkQuestion, QuestionSchedule, ScheduleWeek


class ScheduleTestBase(TestCase):
    """A school with a real calendar: an academic year, a term, and a class."""

    @classmethod
    def setUpTestData(cls):
        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})
        student_role, _ = Role.objects.get_or_create(
            name='student', defaults={'display_name': 'Student'})

        cls.teacher = CustomUser.objects.create_user('sched_teacher', 't@test.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)
        cls.other_teacher = CustomUser.objects.create_user('sched_other', 'o@test.com', 'pass1234')
        cls.other_teacher.roles.add(teacher_role)
        cls.hod = CustomUser.objects.create_user('sched_hod', 'h@test.com', 'pass1234')
        cls.hod.roles.add(teacher_role)
        cls.student = CustomUser.objects.create_user('sched_student', 's@test.com', 'pass1234')
        cls.student.roles.add(student_role)

        admin = CustomUser.objects.create_user('sched_admin', 'a@test.com', 'pass1234')
        cls.school = School.objects.create(
            name='Schedule School', slug='schedule-school', admin=admin,
        )
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        cls.department = Department.objects.create(
            school=cls.school, name='Maths Dept', head=cls.hod,
        )

        # A four-week term starting on the Monday a fortnight out. Relative to
        # today on purpose: a hard-coded 2026 term would slide into the past and
        # start producing already-expired homework, quietly testing the catch-up
        # path instead of the normal one. TERM_START is a Monday, so the
        # week-count arithmetic below stays obvious.
        today = timezone.localdate()
        cls.term_start = today + timedelta(days=14 - today.weekday())
        cls.term_end = cls.term_start + timedelta(days=27)
        cls.academic_year = AcademicYear.objects.create(
            school=cls.school, year=cls.term_start.year,
            start_date=cls.term_start - timedelta(days=60),
            end_date=cls.term_start + timedelta(days=200),
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.academic_year, name='Term 2',
            start_date=cls.term_start, end_date=cls.term_end, order=2,
        )

        cls.classroom = ClassRoom.objects.create(
            name='Year 5 Maths', code='SCHED001', school=cls.school,
            department=cls.department, academic_year=cls.academic_year,
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.student, is_active=True,
        )

        cls.other_classroom = ClassRoom.objects.create(
            name='Year 6 Maths', code='SCHED002', school=cls.school,
            department=cls.department, academic_year=cls.academic_year,
        )
        ClassTeacher.objects.create(classroom=cls.other_classroom, teacher=cls.teacher)

        subject, _ = Subject.objects.get_or_create(
            slug='maths-sched-test', defaults={'name': 'Maths Sched Test'},
        )
        cls.level, _ = Level.objects.get_or_create(
            level_number=601, defaults={'display_name': 'Sched Test Level'},
        )
        cls.classroom.levels.add(cls.level)
        cls.other_classroom.levels.add(cls.level)

        cls.topic = Topic.objects.create(
            subject=subject, name='Fractions', slug='fractions-sched',
        )
        cls.empty_topic = Topic.objects.create(
            subject=subject, name='Statistics', slug='statistics-sched',
        )

        cls.questions = []
        for i in range(12):
            q = Question.objects.create(
                level=cls.level, topic=cls.topic,
                question_text=f'Sched Q{i + 1}?',
                question_type=Question.MULTIPLE_CHOICE, difficulty=1,
            )
            Answer.objects.create(question=q, answer_text='Right', is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text='Wrong', is_correct=False, order=1)
            cls.questions.append(q)

    def make_schedule(self, **overrides):
        kwargs = dict(
            classroom=self.classroom,
            subject_slug='mathematics',
            name='Term 2 Maths plan',
            scope=QuestionSchedule.SCOPE_TERM,
            academic_year=self.academic_year,
            term=self.term,
            start_date=self.term.start_date,
            end_date=self.term.end_date,
            release_weekday=0,
            release_time=time(8, 0),
            due_days=7,
            lead_days=3,
            num_questions=5,
            avoid_repeat_weeks=8,
            created_by=self.teacher,
        )
        kwargs.update(overrides)
        schedule = QuestionSchedule.objects.create(**kwargs)
        svc.build_weeks(schedule)
        return schedule

    def plan_week(self, schedule, number, topics=None, **overrides):
        week = schedule.weeks.get(week_number=number)
        week.topic_ids = [t.pk for t in (topics if topics is not None else [self.topic])]
        week.topic_labels = svc.refresh_topic_labels(week)
        for field, value in overrides.items():
            setattr(week, field, value)
        week.save()
        return week


# ---------------------------------------------------------------------------
# Period resolution + week building
# ---------------------------------------------------------------------------

class PeriodResolutionTest(ScheduleTestBase):
    def test_term_scope_reads_the_terms_dates(self):
        schedule = self.make_schedule()
        self.assertEqual(
            svc.resolve_period(schedule),
            (self.term.start_date, self.term.end_date),
        )

    def test_year_scope_reads_the_academic_years_dates(self):
        schedule = self.make_schedule(
            scope=QuestionSchedule.SCOPE_YEAR,
            start_date=self.academic_year.start_date,
            end_date=self.academic_year.end_date,
        )
        self.assertEqual(
            svc.resolve_period(schedule),
            (self.academic_year.start_date, self.academic_year.end_date),
        )

    def test_custom_scope_uses_the_stored_dates(self):
        start = self.term_start + timedelta(days=56)
        end = start + timedelta(days=27)
        schedule = self.make_schedule(
            scope=QuestionSchedule.SCOPE_CUSTOM, start_date=start, end_date=end,
        )
        self.assertEqual(svc.resolve_period(schedule), (start, end))

    def test_a_deleted_term_leaves_the_schedule_readable(self):
        """SET_NULL on the FK must not make an existing plan unreadable."""
        schedule = self.make_schedule()
        self.term.delete()
        schedule.refresh_from_db()
        self.assertIsNone(schedule.term_id)
        self.assertEqual(
            svc.resolve_period(schedule),
            (schedule.start_date, schedule.end_date),
        )


class WeekBuildingTest(ScheduleTestBase):
    def test_one_week_row_per_teaching_week(self):
        schedule = self.make_schedule()
        # 6 Apr – 3 May inclusive is exactly four Monday-anchored weeks.
        self.assertEqual(schedule.weeks.count(), 4)

    def test_weeks_are_monday_anchored_and_numbered_from_one(self):
        schedule = self.make_schedule()
        weeks = list(schedule.weeks.order_by('week_number'))
        self.assertEqual([w.week_number for w in weeks], [1, 2, 3, 4])
        self.assertEqual(weeks[0].week_start_date, self.term_start)
        self.assertEqual(weeks[0].week_end_date, self.term_start + timedelta(days=6))
        for week in weeks:
            self.assertEqual(week.week_start_date.weekday(), 0)

    def test_a_custom_period_starting_midweek_still_anchors_to_monday(self):
        schedule = self.make_schedule(
            scope=QuestionSchedule.SCOPE_CUSTOM,
            start_date=self.term_start + timedelta(days=2),  # a Wednesday
            end_date=self.term_start + timedelta(days=14),
        )
        first = schedule.weeks.order_by('week_number').first()
        self.assertEqual(first.week_start_date, self.term_start)

    def test_school_holiday_week_is_created_off_with_a_reason(self):
        SchoolHoliday.objects.create(
            school=self.school, name='Easter break',
            start_date=self.term_start + timedelta(days=7),
            end_date=self.term_start + timedelta(days=13),
        )
        schedule = self.make_schedule()
        week2 = schedule.weeks.get(week_number=2)
        self.assertFalse(week2.is_active)
        self.assertEqual(week2.skip_reason, 'School holiday: Easter break')
        # The surrounding weeks are untouched.
        self.assertTrue(schedule.weeks.get(week_number=1).is_active)
        self.assertTrue(schedule.weeks.get(week_number=3).is_active)

    def test_public_holiday_on_the_release_day_switches_that_week_off(self):
        PublicHoliday.objects.create(
            school=self.school, name='ANZAC Day',
            date=self.term_start + timedelta(days=14),  # the week-3 Monday
        )
        schedule = self.make_schedule()
        week3 = schedule.weeks.get(week_number=3)
        self.assertFalse(week3.is_active)
        self.assertEqual(week3.skip_reason, 'Public holiday: ANZAC Day')

    def test_a_public_holiday_away_from_the_release_day_does_not_kill_the_week(self):
        """A Friday holiday must not cost a class its Monday homework."""
        PublicHoliday.objects.create(
            school=self.school, name='Staff day',
            date=self.term_start + timedelta(days=18),  # the week-3 Friday
        )
        schedule = self.make_schedule()
        self.assertTrue(schedule.weeks.get(week_number=3).is_active)

    def test_rebuilding_keeps_topic_selections(self):
        schedule = self.make_schedule()
        self.plan_week(schedule, 2)
        svc.build_weeks(schedule)
        self.assertEqual(
            schedule.weeks.get(week_number=2).topic_ids, [self.topic.pk],
        )

    def test_rebuilding_does_not_re_disable_a_week_the_teacher_turned_on(self):
        SchoolHoliday.objects.create(
            school=self.school, name='Easter break',
            start_date=self.term_start + timedelta(days=7),
            end_date=self.term_start + timedelta(days=13),
        )
        schedule = self.make_schedule()
        week2 = self.plan_week(schedule, 2, is_active=True, skip_reason='')
        svc.build_weeks(schedule)
        week2.refresh_from_db()
        self.assertTrue(week2.is_active)

    def test_shrinking_the_period_drops_ungenerated_weeks_only(self):
        schedule = self.make_schedule()
        week4 = self.plan_week(schedule, 4)
        homework = Homework.objects.create(
            classroom=self.classroom, title='Kept', due_date=timezone.now(),
        )
        week4.generated_homework = homework
        week4.save(update_fields=['generated_homework'])

        schedule.scope = QuestionSchedule.SCOPE_CUSTOM
        schedule.start_date = self.term_start
        schedule.end_date = self.term_start + timedelta(days=13)
        schedule.save()
        svc.build_weeks(schedule)

        # Week 3 had nothing generated and is gone; week 4 produced a homework
        # and is kept so the link to it survives.
        self.assertTrue(schedule.weeks.filter(pk=week4.pk).exists())
        self.assertEqual(schedule.weeks.count(), 3)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

class GenerationTest(ScheduleTestBase):
    def setUp(self):
        self.schedule = self.make_schedule()
        self.week = self.plan_week(self.schedule, 1)

    def test_generates_one_homework_with_the_planned_dates(self):
        result = svc.generate_week(self.week, force=True)
        self.assertTrue(result.created)

        homework = result.homework
        release = svc.release_datetime(self.week)
        self.assertEqual(homework.publish_at, release)
        self.assertEqual(homework.due_date, release + timedelta(days=7))
        self.assertEqual(homework.classroom, self.classroom)
        self.assertEqual(homework.subject_slug, 'mathematics')
        self.assertEqual(homework.homework_questions.count(), 5)

    def test_the_homework_is_hidden_from_students_until_the_publish_cron_runs(self):
        result = svc.generate_week(self.week, force=True)
        homework = result.homework
        self.assertIsNone(homework.published_at)
        self.assertEqual(homework.status, Homework.STATUS_CREATED)
        self.assertEqual(
            Notification.objects.filter(notification_type='homework_assigned').count(), 0,
        )

        # Wind the clock past the release time and run the existing cron.
        Homework.objects.filter(pk=homework.pk).update(
            publish_at=timezone.now() - timedelta(minutes=1),
        )
        call_command('publish_scheduled_homework', stdout=StringIO())

        homework.refresh_from_db()
        self.assertIsNotNone(homework.published_at)
        self.assertEqual(
            Notification.objects.filter(
                notification_type='homework_assigned',
                user=self.student,
            ).count(),
            1,
        )

    def test_generation_is_idempotent(self):
        first = svc.generate_week(self.week, force=True)
        self.week.refresh_from_db()
        second = svc.generate_week(self.week, force=True)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.status, ScheduleWeek.STATUS_SKIPPED)
        self.assertEqual(Homework.objects.filter(classroom=self.classroom).count(), 1)

    def test_a_week_with_no_topics_is_skipped_not_generated(self):
        week2 = self.schedule.weeks.get(week_number=2)
        result = svc.generate_week(week2, force=True)
        self.assertEqual(result.status, ScheduleWeek.STATUS_SKIPPED)
        self.assertIsNone(result.homework)

    def test_an_inactive_week_is_skipped(self):
        self.week.is_active = False
        self.week.save(update_fields=['is_active'])
        result = svc.generate_week(self.week, force=True)
        self.assertEqual(result.status, ScheduleWeek.STATUS_SKIPPED)

    def test_a_paused_schedule_generates_nothing(self):
        self.schedule.is_active = False
        self.schedule.save(update_fields=['is_active'])
        self.week.refresh_from_db()
        result = svc.generate_week(self.week, force=True)
        self.assertEqual(result.status, ScheduleWeek.STATUS_SKIPPED)
        self.assertEqual(Homework.objects.filter(classroom=self.classroom).count(), 0)

    def test_a_week_before_its_lead_time_is_not_generated_without_force(self):
        result = svc.generate_week(self.week, now=svc.build_at(self.week) - timedelta(days=1))
        self.assertEqual(result.status, ScheduleWeek.STATUS_SKIPPED)
        self.assertIn('Not due yet', result.message)

    def test_the_per_week_question_count_overrides_the_plan_default(self):
        self.week.num_questions = 3
        self.week.save(update_fields=['num_questions'])
        result = svc.generate_week(self.week, force=True)
        self.assertEqual(result.homework.homework_questions.count(), 3)


class NoContentTest(ScheduleTestBase):
    def test_a_week_with_no_matching_questions_notifies_and_creates_nothing(self):
        schedule = self.make_schedule()
        week = self.plan_week(schedule, 1, topics=[self.empty_topic])

        result = svc.generate_week(week, force=True)

        self.assertFalse(result.created)
        self.assertEqual(result.status, ScheduleWeek.STATUS_NO_CONTENT)
        self.assertEqual(Homework.objects.filter(classroom=self.classroom).count(), 0)

        week.refresh_from_db()
        self.assertEqual(week.generation_status, ScheduleWeek.STATUS_NO_CONTENT)
        self.assertTrue(week.generation_message)

        notes = Notification.objects.filter(user=self.teacher)
        self.assertEqual(notes.count(), 1)
        self.assertIn('No questions could be set', notes.first().message)

    def test_a_stale_topic_id_is_reported_rather_than_silently_dropped(self):
        schedule = self.make_schedule()
        week = self.plan_week(schedule, 1)
        week.topic_ids = [self.topic.pk, 999999]
        week.save(update_fields=['topic_ids'])

        self.assertEqual(svc.unresolved_topic_ids(week), [999999])
        result = svc.generate_week(week, force=True)
        self.assertTrue(result.created)
        self.assertIn('no longer exist', result.message)

    def test_a_removed_topic_still_shows_in_the_plan(self):
        schedule = self.make_schedule()
        week = self.plan_week(schedule, 1)
        self.topic.delete()
        week.refresh_from_db()
        labels = svc.refresh_topic_labels(week)
        self.assertEqual(len(labels), 1)
        self.assertIn('removed', labels[0])


class RepeatAvoidanceTest(ScheduleTestBase):
    def test_questions_used_recently_are_not_picked_again(self):
        schedule = self.make_schedule(num_questions=6)
        week1 = self.plan_week(schedule, 1)
        week2 = self.plan_week(schedule, 2)

        first = svc.generate_week(week1, force=True)
        used = set(first.homework.homework_questions.values_list('content_id', flat=True))

        week2.refresh_from_db()
        second = svc.generate_week(week2, force=True)
        got = set(second.homework.homework_questions.values_list('content_id', flat=True))

        self.assertEqual(len(got), 6)
        self.assertFalse(used & got, 'week 2 reused a question from week 1')

    def test_a_bank_too_small_tops_up_with_repeats_rather_than_shipping_short(self):
        """Ten of the twelve questions are already spent; the set must still be 6."""
        schedule = self.make_schedule(num_questions=6)
        week1 = self.plan_week(schedule, 1, num_questions=10)
        week2 = self.plan_week(schedule, 2)

        svc.generate_week(week1, force=True)
        week2.refresh_from_db()
        result = svc.generate_week(week2, force=True)

        self.assertEqual(result.homework.homework_questions.count(), 6)
        week2.refresh_from_db()
        self.assertIn('reused', week2.generation_message)

    def test_a_zero_look_back_disables_the_check(self):
        schedule = self.make_schedule(num_questions=6, avoid_repeat_weeks=0)
        week1 = self.plan_week(schedule, 1)
        svc.generate_week(week1, force=True)

        self.assertEqual(
            svc.recent_content_ids(self.classroom, 'mathematics', 0), set(),
        )

    def test_hand_made_homework_counts_towards_the_look_back(self):
        """A teacher's own set must not be handed straight back by the plan."""
        homework = Homework.objects.create(
            classroom=self.classroom, title='Manual set',
            subject_slug='mathematics', due_date=timezone.now() + timedelta(days=3),
        )
        HomeworkQuestion.objects.create(
            homework=homework, question=self.questions[0],
            subject_slug='mathematics', content_id=self.questions[0].pk, order=0,
        )
        recent = svc.recent_content_ids(self.classroom, 'mathematics', 8)
        self.assertIn(self.questions[0].pk, recent)


# ---------------------------------------------------------------------------
# The management command
# ---------------------------------------------------------------------------

class CommandTest(ScheduleTestBase):
    def setUp(self):
        self.schedule = self.make_schedule()
        self.week = self.plan_week(self.schedule, 1)
        self.after_lead = svc.build_at(self.week) + timedelta(hours=1)

    def test_due_weeks_respects_the_lead_time(self):
        self.assertEqual(svc.due_weeks(svc.build_at(self.week) - timedelta(days=1)), [])
        self.assertEqual(
            [w.pk for w in svc.due_weeks(self.after_lead)], [self.week.pk],
        )

    def test_run_due_generates_and_is_safe_to_repeat(self):
        first = svc.run_due(self.after_lead)
        second = svc.run_due(self.after_lead)
        self.assertEqual(len([r for r in first if r.created]), 1)
        self.assertEqual(second, [])
        self.assertEqual(Homework.objects.filter(classroom=self.classroom).count(), 1)

    def test_dry_run_writes_nothing(self):
        out = StringIO()
        call_command(
            'generate_scheduled_questions', '--dry-run',
            '--as-of', str(svc.build_at(self.week).date() + timedelta(days=1)),
            stdout=out, stderr=StringIO(),
        )
        self.assertIn('Dry run', out.getvalue())
        self.assertEqual(Homework.objects.filter(classroom=self.classroom).count(), 0)
        self.week.refresh_from_db()
        self.assertEqual(self.week.generation_status, ScheduleWeek.STATUS_PENDING)

    def test_as_of_generates_the_weeks_due_by_that_date(self):
        call_command(
            'generate_scheduled_questions',
            '--as-of', str(svc.build_at(self.week).date() + timedelta(days=1)),
            stdout=StringIO(), stderr=StringIO(),
        )
        self.week.refresh_from_db()
        self.assertEqual(self.week.generation_status, ScheduleWeek.STATUS_GENERATED)
        self.assertIsNotNone(self.week.generated_homework_id)

    def test_schedule_filter_limits_the_run(self):
        other = self.make_schedule(
            classroom=self.other_classroom, name='Other plan',
        )
        other_week = self.plan_week(other, 1)

        call_command(
            'generate_scheduled_questions', '--schedule', str(self.schedule.pk),
            '--as-of', str(svc.build_at(self.week).date() + timedelta(days=1)),
            stdout=StringIO(), stderr=StringIO(),
        )
        self.week.refresh_from_db()
        other_week.refresh_from_db()
        self.assertEqual(self.week.generation_status, ScheduleWeek.STATUS_GENERATED)
        self.assertEqual(other_week.generation_status, ScheduleWeek.STATUS_PENDING)

    def test_a_bad_as_of_is_rejected_rather_than_silently_meaning_now(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('generate_scheduled_questions', '--as-of', 'next tuesday',
                         stdout=StringIO(), stderr=StringIO())


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------

class CopyScheduleTest(ScheduleTestBase):
    def test_copy_carries_the_week_plan_and_starts_paused(self):
        schedule = self.make_schedule()
        self.plan_week(schedule, 2, num_questions=7)

        clone = svc.copy_schedule(schedule, self.other_classroom, self.teacher)

        self.assertEqual(clone.classroom, self.other_classroom)
        self.assertFalse(clone.is_active)
        self.assertEqual(clone.weeks.count(), schedule.weeks.count())

        copied = clone.weeks.get(week_number=2)
        self.assertEqual(copied.topic_ids, [self.topic.pk])
        self.assertEqual(copied.num_questions, 7)
        # Generation state is not carried — the new class has had none of this.
        self.assertIsNone(copied.generated_homework_id)
        self.assertEqual(copied.generation_status, ScheduleWeek.STATUS_PENDING)

    def test_copying_twice_to_the_same_class_does_not_break_the_unique_name(self):
        schedule = self.make_schedule()
        first = svc.copy_schedule(schedule, self.other_classroom, self.teacher)
        second = svc.copy_schedule(schedule, self.other_classroom, self.teacher)
        self.assertNotEqual(first.name, second.name)


# ---------------------------------------------------------------------------
# Views + permissions
# ---------------------------------------------------------------------------

class ScheduleViewTest(ScheduleTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='sched_teacher', password='pass1234')
        self.schedule = self.make_schedule()

    def test_teacher_can_create_a_schedule_and_gets_its_weeks(self):
        resp = self.client.post(
            reverse('homework:schedule_create', kwargs={'classroom_id': self.classroom.id}),
            {
                'subject_slug': 'mathematics',
                'name': 'Brand new plan',
                'scope': QuestionSchedule.SCOPE_TERM,
                'term': self.term.pk,
                'release_weekday': 0,
                'release_time': '08:00',
                'due_days': 7,
                'lead_days': 3,
                'num_questions': 5,
                'avoid_repeat_weeks': 8,
                'is_active': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        created = QuestionSchedule.objects.get(name='Brand new plan')
        self.assertEqual(created.weeks.count(), 4)
        self.assertEqual(created.created_by, self.teacher)

    def test_custom_scope_requires_dates(self):
        resp = self.client.post(
            reverse('homework:schedule_create', kwargs={'classroom_id': self.classroom.id}),
            {
                'subject_slug': 'mathematics',
                'name': 'Dateless plan',
                'scope': QuestionSchedule.SCOPE_CUSTOM,
                'release_weekday': 0, 'release_time': '08:00',
                'due_days': 7, 'lead_days': 3, 'num_questions': 5,
                'avoid_repeat_weeks': 8,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(QuestionSchedule.objects.filter(name='Dateless plan').exists())

    def test_a_duplicate_name_is_a_form_error_not_a_500(self):
        resp = self.client.post(
            reverse('homework:schedule_create', kwargs={'classroom_id': self.classroom.id}),
            {
                'subject_slug': 'mathematics',
                'name': self.schedule.name,
                'scope': QuestionSchedule.SCOPE_TERM, 'term': self.term.pk,
                'release_weekday': 0, 'release_time': '08:00',
                'due_days': 7, 'lead_days': 3, 'num_questions': 5,
                'avoid_repeat_weeks': 8,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(QuestionSchedule.objects.filter(name=self.schedule.name).count(), 1)

    def test_saving_a_week_stores_topics_and_labels(self):
        week = self.schedule.weeks.get(week_number=1)
        resp = self.client.post(
            reverse('homework:schedule_week_save',
                    kwargs={'schedule_id': self.schedule.pk, 'week_id': week.pk}),
            {'topic_ids': [str(self.topic.pk)], 'num_questions': '', 'notes': 'Intro week',
             'is_active': 'on'},
        )
        self.assertEqual(resp.status_code, 302)
        week.refresh_from_db()
        self.assertEqual(week.topic_ids, [self.topic.pk])
        self.assertEqual(week.topic_labels, ['Fractions'])
        self.assertEqual(week.notes, 'Intro week')

    def test_generate_now_creates_the_set_and_redirects_to_it(self):
        week = self.plan_week(self.schedule, 1)
        resp = self.client.post(
            reverse('homework:schedule_week_generate',
                    kwargs={'schedule_id': self.schedule.pk, 'week_id': week.pk}),
        )
        week.refresh_from_db()
        self.assertIsNotNone(week.generated_homework_id)
        self.assertRedirects(
            resp,
            reverse('homework:teacher_detail',
                    kwargs={'homework_id': week.generated_homework_id}),
        )

    def test_the_detail_page_lists_the_weeks(self):
        resp = self.client.get(
            reverse('homework:schedule_detail', kwargs={'schedule_id': self.schedule.pk}),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['weeks']), 4)

    def test_pausing_stops_generation(self):
        self.client.post(
            reverse('homework:schedule_toggle', kwargs={'schedule_id': self.schedule.pk}),
        )
        self.schedule.refresh_from_db()
        self.assertFalse(self.schedule.is_active)

    def test_deleting_a_plan_keeps_the_homework_it_made(self):
        week = self.plan_week(self.schedule, 1)
        homework = svc.generate_week(week, force=True).homework

        self.client.post(
            reverse('homework:schedule_delete', kwargs={'schedule_id': self.schedule.pk}),
        )
        self.assertFalse(QuestionSchedule.objects.filter(pk=self.schedule.pk).exists())
        self.assertTrue(Homework.objects.filter(pk=homework.pk).exists())

    def test_copy_view_clones_onto_another_class(self):
        self.plan_week(self.schedule, 1)
        resp = self.client.post(
            reverse('homework:schedule_copy', kwargs={'schedule_id': self.schedule.pk}),
            {'target_classroom': self.other_classroom.pk},
        )
        self.assertEqual(resp.status_code, 302)
        clone = QuestionSchedule.objects.get(classroom=self.other_classroom)
        self.assertEqual(clone.weeks.get(week_number=1).topic_ids, [self.topic.pk])


class SchedulePermissionTest(ScheduleTestBase):
    def setUp(self):
        self.schedule = self.make_schedule()
        self.detail_url = reverse(
            'homework:schedule_detail', kwargs={'schedule_id': self.schedule.pk},
        )

    def test_a_teacher_of_another_class_gets_404(self):
        client = Client()
        client.login(username='sched_other', password='pass1234')
        self.assertEqual(client.get(self.detail_url).status_code, 404)

    def test_the_head_of_department_can_manage_the_plan(self):
        client = Client()
        client.login(username='sched_hod', password='pass1234')
        self.assertEqual(client.get(self.detail_url).status_code, 200)

    def test_the_head_of_institute_can_manage_the_plan(self):
        hoi = CustomUser.objects.create_user('sched_hoi', 'hoi@test.com', 'pass1234')
        hoi.roles.add(Role.objects.get(name='teacher'))
        SchoolTeacher.objects.create(
            school=self.school, teacher=hoi, role='head_of_institute',
        )
        client = Client()
        client.login(username='sched_hoi', password='pass1234')
        self.assertEqual(client.get(self.detail_url).status_code, 200)

    def test_a_foreign_teacher_cannot_write_to_a_week(self):
        week = self.schedule.weeks.get(week_number=1)
        client = Client()
        client.login(username='sched_other', password='pass1234')
        resp = client.post(
            reverse('homework:schedule_week_save',
                    kwargs={'schedule_id': self.schedule.pk, 'week_id': week.pk}),
            {'topic_ids': [str(self.topic.pk)], 'is_active': 'on'},
        )
        self.assertEqual(resp.status_code, 404)
        week.refresh_from_db()
        self.assertEqual(week.topic_ids, [])

    def test_a_student_cannot_reach_the_planner(self):
        client = Client()
        client.login(username='sched_student', password='pass1234')
        self.assertNotEqual(client.get(self.detail_url).status_code, 200)


# ---------------------------------------------------------------------------
# The other subject: a class can run a Coding plan alongside its Maths one
# ---------------------------------------------------------------------------

class CodingScheduleTest(ScheduleTestBase):
    """The whole point of routing through the plugin registry.

    Coding's curriculum is a different shape — Language › Topic › TopicLevel,
    with exercises hanging off the level rather off a Topic row — so a
    maths-shaped assumption anywhere in the generator would only ever show up
    here.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from coding.models import CodingExercise, CodingLanguage, CodingTopic
        from coding.models import TopicLevel as CodingTopicLevel

        language = CodingLanguage.objects.create(
            name='Python', slug=CodingLanguage.PYTHON, order=1,
        )
        coding_topic = CodingTopic.objects.create(
            language=language, name='Loops', slug='loops-sched',
        )
        cls.coding_level = CodingTopicLevel.objects.create(
            topic=coding_topic, level_choice=CodingTopicLevel.BEGINNER,
        )
        cls.coding_exercises = [
            CodingExercise.objects.create(
                topic_level=cls.coding_level,
                title=f'Loop exercise {i + 1}',
                description='Print the numbers 1 to 5.',
                is_active=True,
                order=i,
            )
            for i in range(6)
        ]

    def make_coding_schedule(self):
        return self.make_schedule(
            subject_slug='coding', name='Term 2 Coding plan', num_questions=4,
        )

    def test_a_class_can_run_a_maths_and_a_coding_plan_side_by_side(self):
        maths = self.make_schedule()
        coding = self.make_coding_schedule()
        self.assertEqual(
            QuestionSchedule.objects.filter(classroom=self.classroom).count(), 2,
        )
        self.assertNotEqual(maths.subject_slug, coding.subject_slug)

    def test_coding_topic_ids_are_topic_levels_and_resolve_to_labels(self):
        coding = self.make_coding_schedule()
        week = self.plan_week(coding, 1, topics=[self.coding_level])
        self.assertEqual(week.topic_ids, [self.coding_level.pk])
        self.assertIn('Python', week.topic_labels[0])
        self.assertIn('Loops', week.topic_labels[0])

    def test_generating_a_coding_week_writes_coding_homework_questions(self):
        coding = self.make_coding_schedule()
        week = self.plan_week(coding, 1, topics=[self.coding_level])

        result = svc.generate_week(week, force=True)

        self.assertTrue(result.created)
        homework = result.homework
        self.assertEqual(homework.subject_slug, 'coding')
        self.assertEqual(homework.homework_questions.count(), 4)

        rows = homework.homework_questions.all()
        self.assertTrue(all(r.subject_slug == 'coding' for r in rows))
        # The legacy maths FK stays empty for non-maths items, and the coding
        # M2M is what carries the topic — not homework.topics.
        self.assertTrue(all(r.question_id is None for r in rows))
        self.assertEqual(homework.topics.count(), 0)
        self.assertEqual(homework.coding_topics.count(), 1)

    def test_coding_repeat_avoidance_uses_the_coding_pool_only(self):
        coding = self.make_coding_schedule()
        week1 = self.plan_week(coding, 1, topics=[self.coding_level])
        week2 = self.plan_week(coding, 2, topics=[self.coding_level])

        first = svc.generate_week(week1, force=True)
        used = set(first.homework.homework_questions.values_list('content_id', flat=True))

        week2.refresh_from_db()
        second = svc.generate_week(week2, force=True)
        got = set(second.homework.homework_questions.values_list('content_id', flat=True))

        self.assertEqual(len(got), 4)
        # Only two fresh exercises are left, so two must be recycled — but the
        # set is still full rather than short.
        self.assertEqual(len(got - used), 2)
        week2.refresh_from_db()
        self.assertIn('reused', week2.generation_message)

    def test_maths_questions_never_leak_into_a_coding_set(self):
        coding = self.make_coding_schedule()
        week = self.plan_week(coding, 1, topics=[self.coding_level])
        result = svc.generate_week(week, force=True)
        coding_ids = {ex.pk for ex in self.coding_exercises}
        for row in result.homework.homework_questions.all():
            self.assertIn(row.content_id, coding_ids)


# ---------------------------------------------------------------------------
# Replacing a set the teacher threw away
# ---------------------------------------------------------------------------

class RegenerateAfterDeleteTest(ScheduleTestBase):
    def setUp(self):
        self.schedule = self.make_schedule()
        self.week = self.plan_week(self.schedule, 1)
        self.homework = svc.generate_week(self.week, force=True).homework
        self.week.refresh_from_db()

    def test_generate_now_replaces_a_deleted_set(self):
        self.homework.soft_delete(user=self.teacher)

        result = svc.generate_week(self.week, force=True)

        self.assertTrue(result.created)
        self.assertNotEqual(result.homework.pk, self.homework.pk)
        self.week.refresh_from_db()
        self.assertEqual(self.week.generated_homework_id, result.homework.pk)

    def test_the_nightly_run_does_not_resurrect_a_deleted_set(self):
        """Deleting the week's homework is how a teacher cancels that week."""
        self.homework.soft_delete(user=self.teacher)

        result = svc.generate_week(self.week, now=svc.build_at(self.week) + timedelta(days=1))

        self.assertFalse(result.created)
        self.assertEqual(result.status, ScheduleWeek.STATUS_SKIPPED)
        self.assertIn('Generate now', result.message)

    def test_a_live_set_is_never_replaced_even_with_force(self):
        result = svc.generate_week(self.week, force=True)
        self.assertFalse(result.created)
        self.assertEqual(
            Homework.objects.filter(classroom=self.classroom).count(), 1,
        )


# ---------------------------------------------------------------------------
# Coverage — telling the teacher, at planning time, whether a topic is enough
# ---------------------------------------------------------------------------

class TopicCountsTest(ScheduleTestBase):
    """The counts shown beside a topic must match the pool the generator uses.

    A number that over-promises is worse than no number: the teacher plans
    around it and the set arrives short or padded weeks later.
    """

    def test_counts_are_scoped_to_the_class_levels(self):
        from classroom.subject_registry import get as get_plugin

        plugin = get_plugin('mathematics')
        counts = plugin.topic_content_counts(
            self.classroom, [self.topic.pk, self.empty_topic.pk],
        )
        self.assertEqual(counts.get(self.topic.pk), 12)
        # A topic with no questions is absent rather than reported as zero.
        self.assertNotIn(self.empty_topic.pk, counts)

    def test_a_question_at_another_level_is_not_counted(self):
        from classroom.subject_registry import get as get_plugin

        other_level, _ = Level.objects.get_or_create(
            level_number=602, defaults={'display_name': 'Other Level'},
        )
        Question.objects.create(
            level=other_level, topic=self.topic, question_text='Off-level?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1,
        )
        plugin = get_plugin('mathematics')
        counts = plugin.topic_content_counts(self.classroom, [self.topic.pk])
        self.assertEqual(counts[self.topic.pk], 12)

    def test_the_question_type_filter_narrows_the_count(self):
        from classroom.subject_registry import get as get_plugin

        plugin = get_plugin('mathematics')
        counts = plugin.topic_content_counts(
            self.classroom, [self.topic.pk], question_type='short_answer',
        )
        self.assertEqual(counts, {})

    def test_excluding_recent_ids_reduces_the_count(self):
        from classroom.subject_registry import get as get_plugin

        plugin = get_plugin('mathematics')
        spent = [q.pk for q in self.questions[:5]]
        counts = plugin.topic_content_counts(
            self.classroom, [self.topic.pk], exclude_content_ids=spent,
        )
        self.assertEqual(counts[self.topic.pk], 7)

    def test_the_count_matches_what_pick_actually_draws(self):
        """The guarantee the whole feature rests on."""
        from classroom.subject_registry import get as get_plugin

        plugin = get_plugin('mathematics')
        counts = plugin.topic_content_counts(self.classroom, [self.topic.pk])
        picked = plugin.pick_homework_items(self.classroom, [self.topic.pk], 999)
        self.assertEqual(counts[self.topic.pk], len(picked))


class CoverageTest(ScheduleTestBase):
    def _coverage(self, schedule, week):
        total, fresh = svc.topic_counts_for_schedule(
            schedule, [self.topic.pk, self.empty_topic.pk],
        )
        return svc.coverage_for(week, total, fresh)

    def test_a_healthy_week_reports_ok(self):
        schedule = self.make_schedule(num_questions=5)
        week = self.plan_week(schedule, 1)
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.status, 'ok')
        self.assertEqual(cov.total, 12)
        self.assertEqual(cov.fresh, 12)
        self.assertEqual(cov.short_by, 0)
        self.assertEqual(cov.repeats, 0)

    def test_a_week_with_nothing_chosen_reads_as_unplanned_not_broken(self):
        """An untouched week must not shout at the teacher like a fault."""
        schedule = self.make_schedule()
        week = schedule.weeks.get(week_number=1)
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.status, 'unplanned')
        self.assertEqual(cov.message, 'No topics selected yet.')

    def test_a_topic_with_no_questions_reports_none(self):
        schedule = self.make_schedule()
        week = self.plan_week(schedule, 1, topics=[self.empty_topic])
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.status, 'none')
        self.assertIn('No questions available', cov.message)

    def test_a_bank_smaller_than_the_set_reports_short(self):
        schedule = self.make_schedule(num_questions=20)
        week = self.plan_week(schedule, 1)
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.status, 'short')
        self.assertEqual(cov.short_by, 8)
        self.assertIn('8 short of the 20', cov.message)

    def test_recently_used_questions_are_reported_as_repeats(self):
        """The exact case in the request: 10 questions, no repeats for 8 weeks."""
        schedule = self.make_schedule(num_questions=10, avoid_repeat_weeks=8)
        week1 = self.plan_week(schedule, 1)
        svc.generate_week(week1, force=True)   # spends 10 of the 12

        week2 = self.plan_week(schedule, 2)
        cov = self._coverage(schedule, week2)

        self.assertEqual(cov.status, 'repeats')
        self.assertEqual(cov.total, 12)
        self.assertEqual(cov.fresh, 2)
        self.assertEqual(cov.repeats, 8)
        self.assertIn('8 of the 10 would repeat', cov.message)

    def test_a_zero_repeat_window_never_reports_repeats(self):
        schedule = self.make_schedule(num_questions=10, avoid_repeat_weeks=0)
        week1 = self.plan_week(schedule, 1)
        svc.generate_week(week1, force=True)

        week2 = self.plan_week(schedule, 2)
        cov = self._coverage(schedule, week2)
        self.assertEqual(cov.status, 'ok')
        self.assertEqual(cov.fresh, 12)

    def test_the_per_week_override_sets_what_enough_means(self):
        schedule = self.make_schedule(num_questions=5)
        week = self.plan_week(schedule, 1, num_questions=20)
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.wanted, 20)
        self.assertEqual(cov.status, 'short')

    def test_multiple_topics_are_summed(self):
        schedule = self.make_schedule(num_questions=15)
        week = self.plan_week(schedule, 1, topics=[self.topic, self.empty_topic])
        cov = self._coverage(schedule, week)
        self.assertEqual(cov.total, 12)
        self.assertEqual(cov.status, 'short')

    def test_a_topic_whose_questions_are_all_spent_counts_zero_not_its_total(self):
        """The bug a plain dict lookup would hide: absent must mean 0, not total."""
        schedule = self.make_schedule(num_questions=12, avoid_repeat_weeks=8)
        week1 = self.plan_week(schedule, 1)
        svc.generate_week(week1, force=True)   # spends all 12

        total, fresh = svc.topic_counts_for_schedule(schedule, [self.topic.pk])
        self.assertEqual(total[self.topic.pk], 12)
        self.assertEqual(fresh[self.topic.pk], 0)


class CoverageInTheGridTest(ScheduleTestBase):
    """The numbers have to reach the page, on every shape of the topic tree."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='sched_teacher', password='pass1234')
        self.schedule = self.make_schedule(num_questions=10)
        self.url = reverse(
            'homework:schedule_detail', kwargs={'schedule_id': self.schedule.pk},
        )

    def test_each_week_carries_its_coverage(self):
        self.plan_week(self.schedule, 1)
        resp = self.client.get(self.url)
        week1 = next(w for w in resp.context['weeks'] if w.week_number == 1)
        self.assertEqual(week1.coverage.total, 12)
        self.assertEqual(week1.coverage.status, 'ok')

    def test_selectable_topics_are_annotated_with_counts(self):
        resp = self.client.get(self.url)
        found = {}
        for strand, mid_items in resp.context['topic_groups']:
            if not mid_items:
                found[strand.pk] = strand.fresh_count
                continue
            for mid, leaves in mid_items:
                for node in (leaves or [mid]):
                    found[node.pk] = node.fresh_count
        self.assertEqual(found.get(self.topic.pk), 12)

    def test_the_repeat_window_reaches_the_template(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['repeat_window'], 8)

    def test_the_shortfall_is_rendered_for_the_teacher_to_read(self):
        self.plan_week(self.schedule, 1, num_questions=30)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'short of the 30')


# ---------------------------------------------------------------------------
# Selecting a whole topic (CPP — parent/child topic picker)
# ---------------------------------------------------------------------------

class ParentTopicSelectionTest(ScheduleTestBase):
    """A parent topic is a real selection, not just a heading.

    Two things were wrong while a parent rendered as a bare heading: a teacher
    could not say "all of Multiplication" in one click, and any question hung
    on the parent topic itself rather than on one of its subtopics could not be
    reached from this picker at all.
    """

    def setUp(self):
        subject = self.topic.subject
        # strand > parent topic > two subtopics, with questions at BOTH the
        # parent level and the subtopic level.
        self.strand = Topic.objects.create(
            subject=subject, name='Number', slug='number-sched-parent',
        )
        self.parent = Topic.objects.create(
            subject=subject, parent=self.strand,
            name='Multiplication', slug='multiplication-sched-parent',
        )
        self.sub_a = Topic.objects.create(
            subject=subject, parent=self.parent,
            name='Multiplication (2x)', slug='mult-2x-sched-parent',
        )
        self.sub_b = Topic.objects.create(
            subject=subject, parent=self.parent,
            name='Multiplication (3x)', slug='mult-3x-sched-parent',
        )
        for topic, count in ((self.parent, 3), (self.sub_a, 4), (self.sub_b, 5)):
            for i in range(count):
                q = Question.objects.create(
                    level=self.level, topic=topic,
                    question_text=f'{topic.slug} Q{i + 1}?',
                    question_type=Question.MULTIPLE_CHOICE, difficulty=1,
                )
                Answer.objects.create(question=q, answer_text='Right',
                                      is_correct=True, order=0)
                Answer.objects.create(question=q, answer_text='Wrong',
                                      is_correct=False, order=1)

        self.client = Client()
        self.client.login(username='sched_teacher', password='pass1234')
        self.schedule = self.make_schedule(num_questions=5)
        self.url = reverse(
            'homework:schedule_detail', kwargs={'schedule_id': self.schedule.pk},
        )

    def _nodes(self, resp):
        """Flatten the rendered tree to {pk: node}."""
        found = {}
        for strand, mid_items in resp.context['topic_groups']:
            found[strand.pk] = strand
            for mid, leaves in mid_items:
                found[mid.pk] = mid
                for leaf in leaves:
                    found[leaf.pk] = leaf
        return found

    def test_a_parent_topic_is_selectable(self):
        from .views_schedule import _selectable_topic_ids

        resp = self.client.get(self.url)
        selectable = _selectable_topic_ids(resp.context['topic_groups'])
        self.assertIn(self.parent.pk, selectable)
        self.assertIn(self.strand.pk, selectable)
        self.assertIn(self.sub_a.pk, selectable)

    def test_a_parents_own_count_excludes_its_subtopics(self):
        """What ticking just that box adds — the number the tally sums."""
        node = self._nodes(self.client.get(self.url))[self.parent.pk]
        self.assertEqual(node.total_count, 3)

    def test_a_parents_group_count_is_the_whole_subtree(self):
        """What ticking it actually yields once the cascade has run."""
        nodes = self._nodes(self.client.get(self.url))
        self.assertEqual(nodes[self.parent.pk].group_total, 3 + 4 + 5)
        self.assertEqual(nodes[self.strand.pk].group_total, 3 + 4 + 5)

    def test_a_leaf_has_the_same_count_both_ways(self):
        node = self._nodes(self.client.get(self.url))[self.sub_a.pk]
        self.assertEqual((node.total_count, node.group_total), (4, 4))

    def test_the_teacher_can_save_a_whole_topic(self):
        week = self.schedule.weeks.get(week_number=1)
        resp = self.client.post(
            reverse('homework:schedule_week_save',
                    kwargs={'schedule_id': self.schedule.pk, 'week_id': week.pk}),
            {'topic_ids': [str(self.parent.pk), str(self.sub_a.pk),
                           str(self.sub_b.pk)],
             'is_active': 'on'},
        )
        self.assertEqual(resp.status_code, 302)
        week.refresh_from_db()
        self.assertEqual(
            sorted(week.topic_ids),
            sorted([self.parent.pk, self.sub_a.pk, self.sub_b.pk]),
        )

    def test_selecting_the_whole_topic_draws_the_parents_own_questions(self):
        """The gap that made a heading-only parent lossy.

        With all twelve in the subtree selected and twelve asked for, the set
        can only be filled if the parent's own three are in the pool.
        """
        week = self.plan_week(
            self.schedule, 1,
            topics=[self.parent, self.sub_a, self.sub_b], num_questions=12,
        )
        result = svc.generate_week(week, force=True)
        self.assertEqual(result.status, 'generated', result.message)

        homework = Homework.objects.get(pk=week.generated_homework_id)
        picked = set(
            HomeworkQuestion.objects.filter(homework=homework)
            .values_list('content_id', flat=True)
        )
        parent_own = set(
            Question.objects.filter(topic=self.parent).values_list('pk', flat=True)
        )
        self.assertEqual(len(picked), 12)
        self.assertTrue(parent_own <= picked)

    def test_the_subtree_count_never_double_counts_the_parent(self):
        """Sum of own-counts == the group count. The tally relies on it.

        The live tally adds the data- attributes of every ticked box. If a
        parent carried its subtree total there instead of its own, ticking a
        topic and its subtopics would promise roughly twice the questions that
        exist.
        """
        nodes = self._nodes(self.client.get(self.url))
        own = sum(nodes[t.pk].total_count
                  for t in (self.parent, self.sub_a, self.sub_b))
        self.assertEqual(own, nodes[self.parent.pk].group_total)

    def test_the_parent_checkbox_reaches_the_page(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'data-group-toggle')
        self.assertContains(
            resp, f'name="topic_ids" value="{self.parent.pk}"')

    def test_a_topic_with_no_questions_of_its_own_submits_nothing(self):
        """A pure grouping level is a control, not a selection.

        The strand here holds no questions directly. Letting it into
        ``topic_ids`` would store an id that contributes nothing to the set —
        and would silently start contributing if someone later filed a question
        against the strand itself.
        """
        resp = self.client.get(self.url)
        nodes = self._nodes(resp)
        self.assertEqual(nodes[self.strand.pk].total_count, 0)
        self.assertNotContains(
            resp, f'name="topic_ids" value="{self.strand.pk}"')


# ---------------------------------------------------------------------------
# The topic picker's accordion
# ---------------------------------------------------------------------------

class TopicAccordionTest(ScheduleTestBase):
    """Strands collapse, so the picker opens on names rather than a wall.

    Every group used to render open, which ran the strands together into one
    alphabetical list of sub-topics — the headings scrolled out of the box and
    the grouping stopped being visible at all.
    """

    OPEN_GROUP = re.compile(r'<details class="group" data-topic-group\s+open>')
    SHUT_GROUP = re.compile(r'<details class="group" data-topic-group\s*>')

    def setUp(self):
        subject = self.topic.subject
        self.strands = []
        for strand_name, sub_name, slug in (
            ('Number Acc', 'Decimals Acc', 'acc-number'),
            ('Algebra Acc', 'BODMAS Acc', 'acc-algebra'),
        ):
            strand = Topic.objects.create(
                subject=subject, name=strand_name, slug=f'{slug}-strand',
            )
            sub = Topic.objects.create(
                subject=subject, parent=strand, name=sub_name, slug=f'{slug}-sub',
            )
            q = Question.objects.create(
                level=self.level, topic=sub, question_text=f'{sub_name}?',
                question_type=Question.MULTIPLE_CHOICE, difficulty=1,
            )
            Answer.objects.create(question=q, answer_text='Right',
                                  is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text='Wrong',
                                  is_correct=False, order=1)
            self.strands.append((strand, sub))

        self.client = Client()
        self.client.login(username='sched_teacher', password='pass1234')
        self.schedule = self.make_schedule()
        self.url = reverse(
            'homework:schedule_detail', kwargs={'schedule_id': self.schedule.pk},
        )

    def _html(self):
        return self.client.get(self.url).content.decode()

    def test_several_strands_all_render_shut(self):
        html = self._html()
        self.assertEqual(len(self.OPEN_GROUP.findall(html)), 0)
        self.assertGreaterEqual(len(self.SHUT_GROUP.findall(html)), 2)

    def test_a_lone_strand_stays_open(self):
        """Collapsing the only group would be a click that buys nothing."""
        self.topic.is_active = False
        self.topic.save(update_fields=['is_active'])
        strand, _sub = self.strands[1]
        Topic.objects.filter(pk__in=[strand.pk, strand.subtopics.first().pk]).update(
            is_active=False)

        html = self._html()
        self.assertEqual(len(self.SHUT_GROUP.findall(html)), 0)
        self.assertGreaterEqual(len(self.OPEN_GROUP.findall(html)), 1)

    def test_a_shut_group_still_reports_what_it_holds(self):
        """A badge and the count, so a shut group never hides a selection."""
        html = self._html()
        self.assertIn('data-group-selected', html)
        self.assertIn('Number Acc', html)
