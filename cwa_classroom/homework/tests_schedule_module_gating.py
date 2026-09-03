"""Question automation is a paid add-on (``question_automation``).

Two doors, and the second is the one a view mixin cannot reach:

  * the nine teacher-facing schedule pages, gated by ModuleRequiredMixin;
  * ``schedule_services.due_weeks``, which the nightly cron calls with no
    request at all — no request means no user, no user means no school, and
    a mixin has nothing to hang off. A gate on the pages alone would leave
    every existing schedule quietly building sets forever.

The downgrade is deliberately soft: a school that stops paying keeps its
schedules and every set already generated. What stops is the unattended build,
which is the thing the module actually sells.
"""

from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
from classroom.models import (
    AcademicYear, ClassRoom, ClassTeacher, School, SchoolTeacher, Subject,
)

from . import schedule_services as svc
from .models import QuestionSchedule, ScheduleWeek


class ScheduleGatingTest(TestCase):
    """A school with a live schedule, whose module we switch on and off."""

    @classmethod
    def setUpTestData(cls):
        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})

        cls.teacher = CustomUser.objects.create_user(
            'gate_teacher', 'gt@test.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)
        admin = CustomUser.objects.create_user('gate_admin', 'ga@test.com', 'pass1234')

        cls.school = School.objects.create(
            name='Gate School', slug='gate-school', admin=admin)
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.teacher, role='teacher')

        cls.subscription = SchoolSubscription.objects.create(
            school=cls.school,
            plan=InstitutePlan.objects.create(
                name='Standard', slug='standard', price=Decimal('99.00'),
                class_limit=0, student_limit=0, invoice_limit_yearly=100,
                extra_invoice_rate=Decimal('0.50'),
            ),
            status=SchoolSubscription.STATUS_ACTIVE,
        )

        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.classroom = ClassRoom.objects.create(
            name='Gate Class', code='GATE0001', school=cls.school,
            subject=cls.subject,
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        today = date.today()
        cls.year = AcademicYear.objects.create(
            school=cls.school, year=today.year,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=300),
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)

    # -- helpers ---------------------------------------------------------

    def _grant(self):
        return ModuleSubscription.objects.create(
            school_subscription=self.subscription,
            module=ModuleSubscription.MODULE_QUESTION_AUTOMATION,
            is_active=True,
        )

    def _schedule(self):
        today = date.today()
        schedule = QuestionSchedule.objects.create(
            classroom=self.classroom, name='Gate Plan',
            scope=QuestionSchedule.SCOPE_CUSTOM,
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=60),
            release_weekday=0, release_time=time(8, 0),
            is_active=True,
        )
        return schedule

    # -- the pages -------------------------------------------------------

    def test_the_schedule_list_is_denied_without_the_module(self):
        url = reverse('homework:schedule_list',
                      kwargs={'classroom_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('module-required', resp['Location'])

    def test_the_schedule_list_opens_once_the_module_is_bought(self):
        self._grant()
        url = reverse('homework:schedule_list',
                      kwargs={'classroom_id': self.classroom.id})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_creating_a_schedule_is_denied_without_the_module(self):
        """The write path needs its own gate, not just the page that links to it."""
        url = reverse('homework:schedule_create',
                      kwargs={'classroom_id': self.classroom.id})
        resp = self.client.post(url, {
            'name': 'Sneaky Plan',
            'subject_slug': 'mathematics',
            'scope': QuestionSchedule.SCOPE_CUSTOM,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=30)).isoformat(),
            'release_weekday': 0,
            'release_time': '08:00',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('module-required', resp['Location'])
        self.assertFalse(QuestionSchedule.objects.filter(name='Sneaky Plan').exists())

    # -- the cron --------------------------------------------------------

    def test_due_weeks_skips_a_school_without_the_module(self):
        """The gate the mixin cannot reach.

        due_weeks runs from cron. If only the pages were gated, a schedule
        created while the module was active would keep building sets after it
        lapsed, forever, with nobody looking at a page.
        """
        schedule = self._schedule()
        ScheduleWeek.objects.create(
            schedule=schedule, week_number=1,
            week_start_date=date.today() - timedelta(days=7),
            week_end_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        self.assertEqual(svc.due_weeks(timezone.now()), [])

    def test_due_weeks_returns_the_week_once_the_module_is_bought(self):
        """The same week, same dates — only the entitlement differs."""
        schedule = self._schedule()
        week = ScheduleWeek.objects.create(
            schedule=schedule, week_number=1,
            week_start_date=date.today() - timedelta(days=7),
            week_end_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        self._grant()
        self.assertEqual(
            [w.pk for w in svc.due_weeks(timezone.now())], [week.pk])

    def test_a_lapsed_module_keeps_the_schedules_it_already_made(self):
        """The downgrade is soft: the plan survives, the unattended build stops."""
        module = self._grant()
        schedule = self._schedule()
        ScheduleWeek.objects.create(
            schedule=schedule, week_number=1,
            week_start_date=date.today() - timedelta(days=7),
            week_end_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        self.assertEqual(len(svc.due_weeks(timezone.now())), 1)

        module.is_active = False
        module.save(update_fields=['is_active'])

        self.assertEqual(svc.due_weeks(timezone.now()), [])
        self.assertTrue(QuestionSchedule.objects.filter(pk=schedule.pk).exists())
