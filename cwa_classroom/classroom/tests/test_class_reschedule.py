"""
Unit tests for CPP-241: class schedule change → orphaned session detection,
confirmation flow, and deletion/keep actions.
"""
import datetime
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, ClassRoom, ClassSession, StudentAttendance,
)
from classroom.views import _count_orphaned_sessions, _delete_orphaned_sessions


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

def _make_monday():
    """Return next Monday's date."""
    today = datetime.date.today()
    days_ahead = (0 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


def _make_friday():
    """Return next Friday's date."""
    today = datetime.date.today()
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=days_ahead)


class RescheduleTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'reschedule_admin', 'reschedule_admin@example.com', 'TestPass123!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.admin_user.roles.add(admin_role, owner_role)

        cls.school = School.objects.create(
            name='Reschedule School', slug='reschedule-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.admin_user,
            defaults={'role': 'admin'},
        )

        cls.classroom = ClassRoom.objects.create(
            name='Maths A', school=cls.school, day='monday',
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
        )

    def _session(self, date, status='scheduled'):
        return ClassSession.objects.create(
            classroom=self.classroom,
            date=date,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status=status,
            created_by=self.admin_user,
        )


# ---------------------------------------------------------------------------
# _count_orphaned_sessions
# ---------------------------------------------------------------------------

class TestCountOrphanedSessions(RescheduleTestBase):

    def setUp(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()

    def test_no_sessions_returns_zero(self):
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'  # restore

    def test_sessions_matching_new_day_not_counted(self):
        # class now on friday, session is also on a friday
        friday = _make_friday()
        self._session(friday)
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'

    def test_sessions_on_old_day_counted_as_orphans(self):
        monday = _make_monday()
        self._session(monday)
        # class switched to friday, but session is on monday
        self.classroom.day = 'friday'
        count = _count_orphaned_sessions(self.classroom)
        self.assertEqual(count, 1)
        self.classroom.day = 'monday'

    def test_completed_sessions_not_counted(self):
        monday = _make_monday()
        self._session(monday, status='completed')
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'

    def test_cancelled_sessions_not_counted(self):
        monday = _make_monday()
        self._session(monday, status='cancelled')
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'

    def test_past_sessions_not_counted(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        ClassSession.objects.create(
            classroom=self.classroom,
            date=yesterday,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            status='scheduled',
            created_by=self.admin_user,
        )
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'

    def test_invalid_day_returns_zero(self):
        monday = _make_monday()
        self._session(monday)
        self.classroom.day = ''
        self.assertEqual(_count_orphaned_sessions(self.classroom), 0)
        self.classroom.day = 'monday'

    def test_multiple_orphans_counted(self):
        next_monday = _make_monday()
        self._session(next_monday)
        self._session(next_monday + datetime.timedelta(weeks=1))
        self._session(next_monday + datetime.timedelta(weeks=2))
        self.classroom.day = 'friday'
        self.assertEqual(_count_orphaned_sessions(self.classroom), 3)
        self.classroom.day = 'monday'


# ---------------------------------------------------------------------------
# _delete_orphaned_sessions
# ---------------------------------------------------------------------------

class TestDeleteOrphanedSessions(RescheduleTestBase):

    def setUp(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()

    def test_deletes_orphaned_sessions(self):
        monday = _make_monday()
        self._session(monday)
        self.classroom.day = 'friday'
        deleted = _delete_orphaned_sessions(self.classroom)
        self.assertEqual(deleted, 1)
        self.assertEqual(ClassSession.objects.filter(classroom=self.classroom).count(), 0)
        self.classroom.day = 'monday'

    def test_skips_sessions_with_attendance(self):
        student = CustomUser.objects.create_user(
            'stud_del', 'stud_del@example.com', 'TestPass123!',
        )
        monday = _make_monday()
        session = self._session(monday)
        StudentAttendance.objects.create(
            session=session, student=student,
            status='present', marked_by=self.admin_user,
        )
        self.classroom.day = 'friday'
        deleted = _delete_orphaned_sessions(self.classroom)
        # session has attendance → must not be deleted
        self.assertEqual(deleted, 0)
        self.assertTrue(ClassSession.objects.filter(id=session.id).exists())
        self.classroom.day = 'monday'

    def test_returns_zero_when_no_orphans(self):
        friday = _make_friday()
        self._session(friday)
        self.classroom.day = 'friday'
        deleted = _delete_orphaned_sessions(self.classroom)
        self.assertEqual(deleted, 0)
        self.classroom.day = 'monday'

    def test_mixed_attended_and_safe_sessions(self):
        student = CustomUser.objects.create_user(
            'stud_mix', 'stud_mix@example.com', 'TestPass123!',
        )
        monday = _make_monday()
        attended_session = self._session(monday)
        safe_session = self._session(monday + datetime.timedelta(weeks=1))
        StudentAttendance.objects.create(
            session=attended_session, student=student,
            status='present', marked_by=self.admin_user,
        )
        self.classroom.day = 'friday'
        deleted = _delete_orphaned_sessions(self.classroom)
        self.assertEqual(deleted, 1)
        self.assertTrue(ClassSession.objects.filter(id=attended_session.id).exists())
        self.assertFalse(ClassSession.objects.filter(id=safe_session.id).exists())
        self.classroom.day = 'monday'


# ---------------------------------------------------------------------------
# EditClassView — schedule change detection
# ---------------------------------------------------------------------------

class TestEditClassViewScheduleDetection(RescheduleTestBase):

    def setUp(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.client = Client()
        self.client.force_login(self.admin_user)
        self.url = reverse('edit_class', args=[self.classroom.id])

    def _post(self, day, extra=None):
        data = {
            'name': self.classroom.name,
            'day': day,
            'start_time': '09:00',
            'end_time': '10:00',
            'levels': [],
        }
        if extra:
            data.update(extra)
        return self.client.post(self.url, data)

    def test_no_orphans_no_redirect(self):
        """Day change with no future sessions → normal save, redirects but not to confirm page."""
        response = self._post('friday')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('confirm-reschedule', response.get('Location', ''))
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.day, 'friday')
        self.classroom.day = 'monday'
        self.classroom.save(update_fields=['day'])

    def test_orphans_trigger_redirect(self):
        """Day change with future sessions → redirect to confirm_reschedule."""
        monday = _make_monday()
        ClassSession.objects.create(
            classroom=self.classroom, date=monday,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.admin_user,
        )
        response = self._post('friday')
        self.assertEqual(response.status_code, 302)
        self.assertIn('confirm-reschedule', response['Location'])
        # cleanup
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.classroom.day = 'monday'
        self.classroom.save(update_fields=['day'])

    def test_session_data_stored_in_session(self):
        """Old day and orphan count must be stored in request.session."""
        monday = _make_monday()
        ClassSession.objects.create(
            classroom=self.classroom, date=monday,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.admin_user,
        )
        self._post('friday')
        session = self.client.session
        key_old = f'reschedule_{self.classroom.id}_old_day'
        key_count = f'reschedule_{self.classroom.id}_count'
        self.assertEqual(session.get(key_old), 'monday')
        self.assertEqual(session.get(key_count), 1)
        # cleanup
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.classroom.day = 'monday'
        self.classroom.save(update_fields=['day'])

    def test_same_day_no_redirect(self):
        """Saving with same day but different name → no reschedule confirmation."""
        monday = _make_monday()
        ClassSession.objects.create(
            classroom=self.classroom, date=monday,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.admin_user,
        )
        response = self.client.post(self.url, {
            'name': 'Maths A Renamed',
            'day': 'monday',
            'start_time': '09:00',
            'end_time': '10:00',
            'levels': [],
        })
        self.assertNotIn('confirm-reschedule', response.get('Location', ''))
        # cleanup
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.classroom.name = 'Maths A'
        self.classroom.save(update_fields=['name'])


# ---------------------------------------------------------------------------
# ConfirmRescheduleView — GET
# ---------------------------------------------------------------------------

class TestConfirmRescheduleViewGet(RescheduleTestBase):

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)
        self.url = reverse('confirm_reschedule', args=[self.classroom.id])

    def test_get_renders_template(self):
        session = self.client.session
        session[f'reschedule_{self.classroom.id}_old_day'] = 'monday'
        session[f'reschedule_{self.classroom.id}_count'] = 3
        session.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'teacher/confirm_reschedule.html')

    def test_context_contains_old_day_and_count(self):
        session = self.client.session
        session[f'reschedule_{self.classroom.id}_old_day'] = 'wednesday'
        session[f'reschedule_{self.classroom.id}_count'] = 5
        session.save()
        response = self.client.get(self.url)
        self.assertEqual(response.context['old_day'], 'wednesday')
        self.assertEqual(response.context['orphan_count'], 5)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# ConfirmRescheduleView — POST delete_old
# ---------------------------------------------------------------------------

class TestConfirmRescheduleDeleteOld(RescheduleTestBase):

    def setUp(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.client = Client()
        self.client.force_login(self.admin_user)
        self.url = reverse('confirm_reschedule', args=[self.classroom.id])
        # Classroom is now on friday (was changed to friday before this view)
        self.classroom.day = 'friday'
        self.classroom.save(update_fields=['day'])
        # Create a monday session (orphaned)
        monday = _make_monday()
        self.orphan = ClassSession.objects.create(
            classroom=self.classroom, date=monday,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.admin_user,
        )
        # Seed session state
        s = self.client.session
        s[f'reschedule_{self.classroom.id}_old_day'] = 'monday'
        s[f'reschedule_{self.classroom.id}_count'] = 1
        s.save()

    def tearDown(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.classroom.day = 'monday'
        self.classroom.save(update_fields=['day'])

    def test_delete_old_removes_orphan(self):
        self.client.post(self.url, {'action': 'delete_old'})
        self.assertFalse(ClassSession.objects.filter(id=self.orphan.id).exists())

    def test_delete_old_clears_session_keys(self):
        self.client.post(self.url, {'action': 'delete_old'})
        s = self.client.session
        self.assertNotIn(f'reschedule_{self.classroom.id}_old_day', s)
        self.assertNotIn(f'reschedule_{self.classroom.id}_count', s)

    def test_delete_old_redirects_to_class_detail(self):
        response = self.client.post(self.url, {'action': 'delete_old'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.classroom.id), response['Location'])

    def test_delete_old_follows_next_url(self):
        s = self.client.session
        s[f'reschedule_{self.classroom.id}_next'] = '/custom-return/'
        s.save()
        response = self.client.post(self.url, {'action': 'delete_old'})
        self.assertRedirects(response, '/custom-return/', fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# ConfirmRescheduleView — POST keep_old
# ---------------------------------------------------------------------------

class TestConfirmRescheduleKeepOld(RescheduleTestBase):

    def setUp(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.client = Client()
        self.client.force_login(self.admin_user)
        self.url = reverse('confirm_reschedule', args=[self.classroom.id])
        # Classroom on friday, orphan on monday
        self.classroom.day = 'friday'
        self.classroom.save(update_fields=['day'])
        monday = _make_monday()
        self.orphan = ClassSession.objects.create(
            classroom=self.classroom, date=monday,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
            status='scheduled', created_by=self.admin_user,
        )
        s = self.client.session
        s[f'reschedule_{self.classroom.id}_old_day'] = 'monday'
        s[f'reschedule_{self.classroom.id}_count'] = 1
        s.save()

    def tearDown(self):
        ClassSession.objects.filter(classroom=self.classroom).delete()
        self.classroom.day = 'monday'
        self.classroom.save(update_fields=['day'])

    def test_keep_old_does_not_delete_sessions(self):
        self.client.post(self.url, {'action': 'keep_old'})
        self.assertTrue(ClassSession.objects.filter(id=self.orphan.id).exists())

    def test_keep_old_clears_session_keys(self):
        self.client.post(self.url, {'action': 'keep_old'})
        s = self.client.session
        self.assertNotIn(f'reschedule_{self.classroom.id}_old_day', s)

    def test_keep_old_redirects(self):
        response = self.client.post(self.url, {'action': 'keep_old'})
        self.assertEqual(response.status_code, 302)
