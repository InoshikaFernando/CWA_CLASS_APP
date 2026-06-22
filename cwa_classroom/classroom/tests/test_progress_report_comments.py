"""Tests for progress-report teacher comments and the generate/send-to-parent flow."""

import datetime

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import Role
from classroom.models import (
    ProgressCriteria, ProgressRecord, ProgressReportComment, ProgressReport,
    ParentStudent, Term,
)

from .test_e2e_attendance_progress import (
    _BaseAttendanceProgressTest, _create_user, _assign_role,
)


pytestmark = pytest.mark.progress


class _CommentBase(_BaseAttendanceProgressTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.criteria = ProgressCriteria.objects.create(
            school=cls.school, subject=cls.subject, level=cls.level,
            name='Addition Facts', status='approved',
            created_by=cls.teacher_user, approved_by=cls.teacher_user,
        )
        ProgressRecord.objects.create(
            student=cls.student_user, criteria=cls.criteria,
            status='achieved', recorded_by=cls.teacher_user,
        )
        cls.term = Term.objects.create(
            school=cls.school, name='Term 1',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 4, 1),
        )
        # Parent linked to the student
        cls.parent_user = _create_user('parent_one', first_name='Pat', last_name='Parent',
                                       email='wlhtestmails+parent_one@gmail.com')
        _assign_role(cls.parent_user, Role.PARENT)
        ParentStudent.objects.create(
            parent=cls.parent_user, student=cls.student_user,
            school=cls.school, is_active=True,
        )

    def _login_teacher(self):
        self.client.force_login(self.teacher_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()


class ProgressCommentTest(_CommentBase):
    def test_teacher_can_add_comment(self):
        self._login_teacher()
        url = reverse('progress_comment_add', kwargs={'student_id': self.student_user.id})
        resp = self.client.post(url, {
            'body': 'Great improvement this term.',
            'term': self.term.id,
            'subject': self.subject.id,
        })
        self.assertEqual(resp.status_code, 302)
        comment = ProgressReportComment.objects.get(student=self.student_user)
        self.assertEqual(comment.body, 'Great improvement this term.')
        self.assertEqual(comment.created_by, self.teacher_user)
        self.assertEqual(comment.term, self.term)

    def test_empty_comment_rejected(self):
        self._login_teacher()
        url = reverse('progress_comment_add', kwargs={'student_id': self.student_user.id})
        self.client.post(url, {'body': '   '})
        self.assertFalse(ProgressReportComment.objects.exists())

    def test_teacher_can_edit_old_comment(self):
        self._login_teacher()
        comment = ProgressReportComment.objects.create(
            student=self.student_user, school=self.school, body='Old text',
            created_by=self.teacher_user,
        )
        url = reverse('progress_comment_edit', kwargs={'comment_id': comment.id})
        self.client.post(url, {'body': 'Updated text'})
        comment.refresh_from_db()
        self.assertEqual(comment.body, 'Updated text')
        self.assertEqual(comment.updated_by, self.teacher_user)

    def test_teacher_can_delete_comment(self):
        self._login_teacher()
        comment = ProgressReportComment.objects.create(
            student=self.student_user, school=self.school, body='x',
            created_by=self.teacher_user,
        )
        url = reverse('progress_comment_delete', kwargs={'comment_id': comment.id})
        self.client.post(url)
        self.assertFalse(ProgressReportComment.objects.filter(id=comment.id).exists())

    def test_student_cannot_add_comment(self):
        self.client.force_login(self.student_user)
        s = self.client.session
        s['current_school_id'] = self.school.id
        s.save()
        url = reverse('progress_comment_add', kwargs={'student_id': self.student_user.id})
        self.client.post(url, {'body': 'I am great'})
        self.assertFalse(ProgressReportComment.objects.exists())


class ProgressReportSendTest(_CommentBase):
    def test_generate_creates_draft_report(self):
        self._login_teacher()
        url = reverse('progress_report_generate', kwargs={'student_id': self.student_user.id})
        resp = self.client.post(url, {'term': self.term.id})
        self.assertEqual(resp.status_code, 302)
        report = ProgressReport.objects.get(student=self.student_user)
        self.assertEqual(report.status, ProgressReport.STATUS_DRAFT)
        self.assertEqual(report.term, self.term)

    def test_generate_reuses_existing_draft(self):
        self._login_teacher()
        url = reverse('progress_report_generate', kwargs={'student_id': self.student_user.id})
        self.client.post(url, {'term': self.term.id})
        self.client.post(url, {'term': self.term.id})
        self.assertEqual(
            ProgressReport.objects.filter(student=self.student_user, term=self.term).count(), 1,
        )

    def test_send_report_emails_parent(self):
        self._login_teacher()
        ProgressReportComment.objects.create(
            student=self.student_user, school=self.school, term=self.term,
            body='Doing well.', created_by=self.teacher_user,
        )
        report = ProgressReport.objects.create(
            student=self.student_user, school=self.school, term=self.term,
            generated_by=self.teacher_user,
        )
        url = reverse('progress_report_send', kwargs={'report_id': report.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        report.refresh_from_db()
        self.assertEqual(report.status, ProgressReport.STATUS_SENT)
        self.assertEqual(report.recipient_count, 1)
        self.assertIsNotNone(report.sent_at)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.parent_user.email, mail.outbox[0].to)

    def test_report_detail_renders(self):
        self._login_teacher()
        report = ProgressReport.objects.create(
            student=self.student_user, school=self.school, term=self.term,
            generated_by=self.teacher_user,
        )
        resp = self.client.get(reverse('progress_report_detail', kwargs={'report_id': report.id}))
        self.assertEqual(resp.status_code, 200)
