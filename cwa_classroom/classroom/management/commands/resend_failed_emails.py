"""
Management command to resend failed parent invite emails.

Usage:
    python manage.py resend_failed_emails           # resend all
    python manage.py resend_failed_emails --dry-run # preview only
    python manage.py resend_failed_emails --type parent_invite
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Resend failed parent invite emails'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview what would be sent without actually sending',
        )
        parser.add_argument(
            '--type', default='parent_invite',
            choices=['parent_invite'],
            help='Notification type to resend (default: parent_invite)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        notif_type = options['type']

        if notif_type == 'parent_invite':
            self._resend_parent_invites(dry_run)

    def _resend_parent_invites(self, dry_run):
        from classroom.models import ParentInvite, EmailLog
        from classroom.email_service import send_templated_email, _get_email_logo_url
        from django.urls import reverse

        # Find all pending invites
        pending = ParentInvite.objects.filter(
            status='pending',
            expires_at__gt=timezone.now(),
        ).select_related('student', 'school')

        self.stdout.write(f'Found {pending.count()} pending invite(s) to check.')

        sent = 0
        skipped = 0

        for invite in pending:
            # Check if a successful send already exists
            already_sent = EmailLog.objects.filter(
                recipient_email=invite.parent_email,
                notification_type='parent_invite',
                status='sent',
            ).exists()

            if already_sent:
                skipped += 1
                continue

            student = invite.student
            school = invite.school
            registration_url = 'https://{}/accounts/register/parent/{}/'.format(
                'wizardslearninghub.co.nz', invite.token,
            )

            self.stdout.write(
                f'  {"[DRY RUN] " if dry_run else ""}Sending invite to '
                f'{invite.parent_email} for {student.get_full_name()} @ {school.name}'
            )

            if not dry_run:
                ok = send_templated_email(
                    recipient_email=invite.parent_email,
                    subject=f"You are invited to view {student.first_name}'s records at {school.name}",
                    template_name='email/transactional/parent_invite.html',
                    context={
                        'school_name': school.name,
                        'student_name': student.get_full_name(),
                        'registration_url': registration_url,
                        'expires_at': invite.expires_at,
                        'email_logo_url': _get_email_logo_url(school),
                        'recipient_name': invite.parent_email,
                    },
                    notification_type='parent_invite',
                    school=school,
                    fail_silently=True,
                )
                if ok:
                    sent += 1
                    self.stdout.write(self.style.SUCCESS(f'    Sent OK'))
                else:
                    self.stdout.write(self.style.ERROR(f'    Failed — check EmailLog for details'))
            else:
                sent += 1

        label = 'Would send' if dry_run else 'Sent'
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {label}: {sent}, Already sent (skipped): {skipped}.'
        ))
