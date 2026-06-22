"""Tests for the reap_stuck_uploads command (stuck-session self-heal)."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import School


class ReapStuckUploadsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('reap_u', 'reap_u@test.internal', 'pw1!')
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'})
        cls.user.roles.add(admin_role)
        cls.school = School.objects.create(name='Reap School', slug='reap-school', admin=cls.user)

    def _age(self, obj, minutes):
        type(obj).objects.filter(pk=obj.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes))

    def test_old_processing_worksheet_is_failed(self):
        from worksheets.models import WorksheetUploadSession
        s = WorksheetUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_PROCESSING)
        self._age(s, 30)

        call_command('reap_stuck_uploads', '--minutes', '10', stdout=StringIO())

        s.refresh_from_db()
        self.assertEqual(s.status, WorksheetUploadSession.STATUS_FAILED)
        self.assertIn('try again', s.error_message)

    def test_recent_processing_is_left_alone(self):
        from worksheets.models import WorksheetUploadSession
        s = WorksheetUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_PROCESSING)
        self._age(s, 2)  # only 2 min old

        call_command('reap_stuck_uploads', '--minutes', '10', stdout=StringIO())

        s.refresh_from_db()
        self.assertEqual(s.status, WorksheetUploadSession.STATUS_PROCESSING)

    def test_homework_uses_error_status(self):
        from homework.models import HomeworkUploadSession
        s = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='h.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING)
        self._age(s, 30)

        call_command('reap_stuck_uploads', '--minutes', '10', stdout=StringIO())

        s.refresh_from_db()
        self.assertEqual(s.status, HomeworkUploadSession.STATUS_ERROR)

    def test_ai_import_processing_is_failed(self):
        from ai_import.models import AIImportSession
        s = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_PROCESSING)
        self._age(s, 30)

        call_command('reap_stuck_uploads', '--minutes', '10', stdout=StringIO())

        s.refresh_from_db()
        self.assertEqual(s.status, AIImportSession.STATUS_FAILED)

    def test_dry_run_changes_nothing(self):
        from worksheets.models import WorksheetUploadSession
        s = WorksheetUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='w.pdf',
            status=WorksheetUploadSession.STATUS_PROCESSING)
        self._age(s, 30)

        call_command('reap_stuck_uploads', '--minutes', '10', '--dry-run', stdout=StringIO())

        s.refresh_from_db()
        self.assertEqual(s.status, WorksheetUploadSession.STATUS_PROCESSING)
