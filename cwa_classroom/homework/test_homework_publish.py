"""
Tests for the homework publish-date feature: scheduling, status lifecycle,
student/parent visibility gating, the scheduled-publish command, and the manual
"Publish now" action.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from classroom.models import Notification

from .models import Homework, HomeworkQuestion
from .tests import HomeworkTestBase


def _student_notification_count(homework):
    return Notification.objects.filter(
        notification_type='homework_assigned',
        link=reverse('homework:student_take', kwargs={'homework_id': homework.id}),
    ).count()


class CreatePublishOptionTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})

    def _post(self, **overrides):
        data = {
            'title': 'Scheduling HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'),
            'max_attempts': 1,
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_publish_now_when_blank_publish_at(self):
        resp = self._post(title='Now HW')
        self.assertEqual(resp.status_code, 302)
        hw = Homework.objects.get(title='Now HW')
        self.assertIsNotNone(hw.published_at)
        self.assertEqual(hw.status, Homework.STATUS_PUBLISHED)
        # Both active students were notified on publish.
        self.assertEqual(_student_notification_count(hw), 2)

    def test_schedule_for_later_hides_and_does_not_notify(self):
        publish_at = (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        resp = self._post(title='Later HW', publish_at=publish_at)
        self.assertEqual(resp.status_code, 302)
        hw = Homework.objects.get(title='Later HW')
        self.assertIsNone(hw.published_at)
        self.assertIsNotNone(hw.publish_at)
        self.assertEqual(hw.status, Homework.STATUS_CREATED)
        # No email/notification until it actually publishes.
        self.assertEqual(_student_notification_count(hw), 0)

    def test_publish_at_after_due_date_rejected(self):
        publish_at = (timezone.now() + timedelta(days=10)).strftime('%Y-%m-%dT%H:%M')
        resp = self._post(title='Bad Schedule HW', publish_at=publish_at)
        self.assertEqual(resp.status_code, 200)  # re-renders with error
        self.assertFalse(Homework.objects.filter(title='Bad Schedule HW').exists())

    def test_past_publish_at_publishes_immediately(self):
        past = (timezone.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        # A past publish_at fails clean_publish_at (must be future) — the teacher
        # should leave it blank to publish now. Assert the form rejects it
        # rather than silently scheduling in the past.
        resp = self._post(title='Past Publish HW', publish_at=past)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Homework.objects.filter(title='Past Publish HW').exists())


class StudentVisibilityTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        # A scheduled (unpublished) homework for the class.
        self.scheduled = Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title='Hidden Scheduled HW',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
            publish_at=timezone.now() + timedelta(days=2),
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=self.scheduled, question=q, order=i)

    def test_scheduled_homework_excluded_from_student_list(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Hidden Scheduled HW')
        # The auto-published base fixture homework is still visible.
        self.assertContains(resp, 'Test Homework')

    def test_take_blocks_unpublished_homework(self):
        url = reverse('homework:student_take', kwargs={'homework_id': self.scheduled.id})
        resp = self.client.get(url)
        self.assertRedirects(resp, reverse('homework:student_list'))

    def test_take_post_blocks_unpublished_homework(self):
        url = reverse('homework:student_take', kwargs={'homework_id': self.scheduled.id})
        resp = self.client.post(url, {'time_taken_seconds': 5})
        self.assertRedirects(resp, reverse('homework:student_list'))


class PublishScheduledCommandTest(HomeworkTestBase):
    def _make_scheduled(self, title, publish_at):
        hw = Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title=title,
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
            publish_at=publish_at,
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=hw, question=q, order=i)
        return hw

    def test_command_publishes_due_and_skips_future(self):
        due = self._make_scheduled('Due Now HW', timezone.now() - timedelta(minutes=5))
        future = self._make_scheduled('Future HW', timezone.now() + timedelta(days=3))
        self.assertIsNone(due.published_at)

        out = StringIO()
        call_command('publish_scheduled_homework', stdout=out)

        due.refresh_from_db()
        future.refresh_from_db()
        self.assertIsNotNone(due.published_at)
        self.assertEqual(due.status, Homework.STATUS_PUBLISHED)
        self.assertIsNone(future.published_at)  # not yet due
        self.assertEqual(_student_notification_count(due), 2)
        self.assertEqual(_student_notification_count(future), 0)
        self.assertIn('Published 1', out.getvalue())

    def test_command_is_idempotent(self):
        due = self._make_scheduled('Due HW', timezone.now() - timedelta(minutes=5))
        call_command('publish_scheduled_homework', stdout=StringIO())
        first_published = Homework.objects.get(pk=due.pk).published_at
        # Second run must not re-notify or change published_at.
        call_command('publish_scheduled_homework', stdout=StringIO())
        due.refresh_from_db()
        self.assertEqual(due.published_at, first_published)
        self.assertEqual(_student_notification_count(due), 2)


class ManualPublishViewTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.scheduled = Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title='Manual Publish HW',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
            publish_at=timezone.now() + timedelta(days=2),
        )
        self.url = reverse('homework:publish', kwargs={'homework_id': self.scheduled.id})

    def test_teacher_can_publish_now(self):
        self.client.login(username='teacher1', password='pass1234')
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        self.scheduled.refresh_from_db()
        self.assertIsNotNone(self.scheduled.published_at)
        self.assertEqual(_student_notification_count(self.scheduled), 2)

    def test_publish_already_published_is_noop(self):
        self.scheduled.publish()
        before = Homework.objects.get(pk=self.scheduled.pk).published_at
        self.client.login(username='teacher1', password='pass1234')
        self.client.post(self.url)
        self.scheduled.refresh_from_db()
        self.assertEqual(self.scheduled.published_at, before)
        self.assertEqual(_student_notification_count(self.scheduled), 2)  # not doubled

    def test_other_teacher_cannot_publish(self):
        self.client.login(username='teacher2', password='pass1234')
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 404)
        self.scheduled.refresh_from_db()
        self.assertIsNone(self.scheduled.published_at)


class EditViewTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.scheduled = Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher,
            title='Editable Scheduled HW',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
            publish_at=timezone.now() + timedelta(days=2),
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=self.scheduled, question=q, order=i)

    def _url(self, hw):
        return reverse('homework:teacher_edit', kwargs={'homework_id': hw.id})

    def test_edit_form_renders(self):
        resp = self.client.get(self._url(self.scheduled))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Edit Homework')

    def test_edit_changes_due_date(self):
        # datetime-local inputs carry local wall-clock time; build and compare
        # in local time so the round-trip through make_aware matches exactly.
        new_due = timezone.localtime(timezone.now()) + timedelta(days=14)
        new_publish = timezone.localtime(timezone.now()) + timedelta(days=3)
        fmt = '%Y-%m-%dT%H:%M'
        resp = self.client.post(self._url(self.scheduled), {
            'title': self.scheduled.title,
            'description': '',
            'due_date': new_due.strftime(fmt),
            'publish_at': new_publish.strftime(fmt),
            'max_attempts': 1,
        })
        self.assertEqual(resp.status_code, 302)
        self.scheduled.refresh_from_db()
        self.assertEqual(timezone.localtime(self.scheduled.due_date).strftime(fmt), new_due.strftime(fmt))
        self.assertEqual(timezone.localtime(self.scheduled.publish_at).strftime(fmt), new_publish.strftime(fmt))
        self.assertIsNone(self.scheduled.published_at)  # still scheduled

    def test_edit_blank_publish_publishes_now(self):
        resp = self.client.post(self._url(self.scheduled), {
            'title': self.scheduled.title,
            'description': '',
            'due_date': (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'),
            'publish_at': '',
            'max_attempts': 1,
        })
        self.assertEqual(resp.status_code, 302)
        self.scheduled.refresh_from_db()
        self.assertIsNotNone(self.scheduled.published_at)
        self.assertEqual(self.scheduled.status, Homework.STATUS_PUBLISHED)
        self.assertEqual(_student_notification_count(self.scheduled), 2)

    def test_published_homework_due_date_editable_publish_field_hidden(self):
        self.scheduled.publish()  # now published
        notif_before = _student_notification_count(self.scheduled)
        resp = self.client.get(self._url(self.scheduled))
        self.assertNotContains(resp, 'name="publish_at"')
        fmt = '%Y-%m-%dT%H:%M'
        new_due = timezone.localtime(timezone.now()) + timedelta(days=30)
        self.client.post(self._url(self.scheduled), {
            'title': 'Renamed Published HW',
            'description': '',
            'due_date': new_due.strftime(fmt),
            'max_attempts': 2,
        })
        self.scheduled.refresh_from_db()
        self.assertEqual(self.scheduled.title, 'Renamed Published HW')
        self.assertEqual(timezone.localtime(self.scheduled.due_date).strftime(fmt), new_due.strftime(fmt))
        # Editing a published homework must not re-notify students.
        self.assertEqual(_student_notification_count(self.scheduled), notif_before)

    def test_other_teacher_cannot_edit(self):
        self.client.login(username='teacher2', password='pass1234')
        resp = self.client.get(self._url(self.scheduled))
        self.assertEqual(resp.status_code, 404)


class AssignToClassPreservesScheduleTest(HomeworkTestBase):
    """Assigning a scheduled homework to another class must keep it scheduled,
    not auto-publish the copy via the save() publish-on-create default."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        # A second classroom owned by the same teacher.
        from classroom.models import ClassRoom, ClassTeacher
        self.classroom2 = ClassRoom.objects.create(
            name='Year 6 Maths', code='HWTEST02', school=self.school,
        )
        ClassTeacher.objects.create(classroom=self.classroom2, teacher=self.teacher)

    def _assign(self, hw):
        return self.client.post(
            reverse('homework:assign_to_class', kwargs={'homework_id': hw.id}),
            {'classroom_ids': [str(self.classroom2.id)]},
        )

    def test_scheduled_homework_copy_stays_scheduled(self):
        publish_at = timezone.now() + timedelta(days=2)
        scheduled = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Sched Assign HW', homework_type='topic', num_questions=3,
            due_date=timezone.now() + timedelta(days=7), publish_at=publish_at,
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=scheduled, question=q, order=i)
        self.assertIsNone(scheduled.published_at)

        self._assign(scheduled)
        copy = Homework.objects.get(title='Sched Assign HW', classroom=self.classroom2)
        self.assertIsNone(copy.published_at)  # not auto-published
        self.assertIsNotNone(copy.publish_at)
        self.assertEqual(copy.status, Homework.STATUS_CREATED)

    def test_published_homework_copy_stays_published(self):
        published = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Pub Assign HW', homework_type='topic', num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=published, question=q, order=i)
        self.assertIsNotNone(published.published_at)

        self._assign(published)
        copy = Homework.objects.get(title='Pub Assign HW', classroom=self.classroom2)
        self.assertIsNotNone(copy.published_at)
        self.assertEqual(copy.status, Homework.STATUS_PUBLISHED)


class StatusPropertyTest(HomeworkTestBase):
    def _hw(self, **kwargs):
        defaults = dict(
            classroom=self.classroom, created_by=self.teacher,
            title='S', homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=5),
        )
        defaults.update(kwargs)
        return Homework.objects.create(**defaults)

    def test_created_when_scheduled_future(self):
        hw = self._hw(publish_at=timezone.now() + timedelta(days=1))
        self.assertEqual(hw.status, Homework.STATUS_CREATED)
        self.assertFalse(hw.is_published)

    def test_published_when_live_before_due(self):
        hw = self._hw()  # auto-published on create
        self.assertEqual(hw.status, Homework.STATUS_PUBLISHED)

    def test_expired_when_past_due(self):
        hw = self._hw(due_date=timezone.now() - timedelta(days=1))
        self.assertEqual(hw.status, Homework.STATUS_EXPIRED)

    def test_default_publishes_on_create(self):
        hw = self._hw()
        self.assertIsNotNone(hw.published_at)
