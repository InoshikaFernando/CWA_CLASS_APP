"""
Email re-gated school students' guardians that they must add payment on next
login (the "action needed" notice for CPP-300 / CPP-341 cleanup).

Targets only students who have ALREADY logged in — i.e. active families who
need a nudge to come back and pay. Dormant (never-logged-in) students are
intentionally skipped: they meet the payment gate naturally on first login and
do not need a separate email.

Predicate (per recipient)
-------------------------
Email a CustomUser iff ALL of:
  * has Role.STUDENT and NOT Role.INDIVIDUAL_STUDENT
  * profile_completed=False        (already re-gated)
  * last_login IS NOT NULL         (has logged in before — active)
  * has NO active/trialing Subscription
  * (if --school given) has an active enrolment in that school

Run AFTER ``reset_imported_student_gating`` so the re-gated flag is set.

Usage
-----
    python manage.py notify_payment_required --school 4 --discount-code MHMEBC75 \
        --discount-percent 75 --dry-run     # preview recipients
    python manage.py notify_payment_required --school 4 --discount-code MHMEBC75 \
        --discount-percent 75               # send
"""
import logging
import time

from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser, Role
from billing.models import Subscription
from notifications.services import NOTIF_PAYMENT_REQUIRED

logger = logging.getLogger(__name__)

_ACTIVE_SUB_STATUSES = (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING)
# Resend allows 2 req/sec; pace below that so a batch never trips the limit.
_DEFAULT_SLEEP = 0.6


class Command(BaseCommand):
    help = (
        'Email re-gated, already-logged-in school students that they must add '
        'payment (and may apply a discount code) on next login.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='List recipients without sending any email.')
        parser.add_argument('--school', type=int, default=None, metavar='SCHOOL_ID',
                            help='Restrict to students actively enrolled in this school.')
        parser.add_argument('--discount-code', default='', help='Discount code to show (e.g. MHMEBC75).')
        parser.add_argument('--discount-percent', type=int, default=0, help='Discount percent (e.g. 75).')
        parser.add_argument('--monthly-price', default='19.90', help='Full monthly price shown in the email.')
        parser.add_argument('--plan-name', default='Wizard', help='Plan label shown in the email.')
        parser.add_argument('--currency', default='$', help='Currency symbol.')
        parser.add_argument('--support-email', default='', help='Support email shown in the footer.')
        parser.add_argument('--sleep', type=float, default=_DEFAULT_SLEEP,
                            help=f'Seconds to pause between sends (default {_DEFAULT_SLEEP}; '
                                 'keeps under Resend\'s 2/sec limit).')
        parser.add_argument('--resend', action='store_true',
                            help='Also email recipients who already received this notice '
                                 '(by default they are skipped, so re-runs are safe).')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        school_id = options['school']

        school = None
        if school_id is not None:
            from classroom.models import School, SchoolStudent
            school = School.objects.filter(id=school_id).first()
            if school is None:
                raise CommandError(f'No School with id={school_id} exists.')

        subscribed_ids = set(
            Subscription.objects.filter(status__in=_ACTIVE_SUB_STATUSES)
            .values_list('user_id', flat=True)
        )

        recipients = (
            CustomUser.objects.filter(
                roles__name=Role.STUDENT,
                profile_completed=False,
                last_login__isnull=False,
            )
            .exclude(roles__name=Role.INDIVIDUAL_STUDENT)
            .exclude(id__in=subscribed_ids)
        )

        if school_id is not None:
            from classroom.models import SchoolStudent
            enrolled_ids = SchoolStudent.objects.filter(
                school_id=school_id, is_active=True,
            ).values_list('student_id', flat=True)
            recipients = recipients.filter(id__in=enrolled_ids)

        recipients = list(recipients.distinct())
        scope_note = f' in school id={school_id}' if school_id is not None else ''

        # Idempotency: skip anyone who already got a successful payment-required
        # email, so a re-run (e.g. after a partial rate-limit failure) never
        # double-sends to real families. --resend overrides this.
        skipped_already = 0
        if not options['resend']:
            from classroom.models import EmailLog
            already_sent_ids = set(
                EmailLog.objects.filter(
                    notification_type=NOTIF_PAYMENT_REQUIRED, status='sent',
                    recipient__isnull=False,
                ).values_list('recipient_id', flat=True)
            )
            before = len(recipients)
            recipients = [u for u in recipients if u.id not in already_sent_ids]
            skipped_already = before - len(recipients)

        if not recipients:
            msg = f'No re-gated, logged-in students{scope_note} to notify.'
            if skipped_already:
                msg += f' ({skipped_already} already emailed — use --resend to include them.)'
            self.stdout.write(self.style.SUCCESS(msg))
            return

        self.stdout.write(
            f'{len(recipients)} student(s){scope_note} will be emailed '
            f'(code={options["discount_code"] or "none"}, '
            f'{options["discount_percent"]}% off)'
            + (f'; {skipped_already} already emailed (skipped).' if skipped_already else '.')
        )
        for u in recipients:
            self.stdout.write(f'  - {u.get_full_name() or u.username} <{u.email or "no email"}>')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no emails sent.'))
            return

        from notifications.services import send_payment_required_notification
        sleep_s = options['sleep']
        sent = 0
        failed = []
        for i, u in enumerate(recipients):
            if i and sleep_s > 0:
                time.sleep(sleep_s)   # pace under Resend's 2/sec limit
            ok = send_payment_required_notification(
                u, school=school,
                plan_name=options['plan_name'],
                monthly_price=options['monthly_price'],
                discount_code=options['discount_code'],
                discount_percent=options['discount_percent'],
                currency_symbol=options['currency'],
                support_email=options['support_email'],
            )
            if ok:
                sent += 1
            else:
                failed.append(u.email or u.username)
        style = self.style.SUCCESS if not failed else self.style.WARNING
        self.stdout.write(style(
            f'Sent {sent}/{len(recipients)} payment-required email(s).'
        ))
        if failed:
            self.stdout.write(self.style.ERROR(
                f'{len(failed)} failed (re-run to retry — already-sent are skipped): '
                + ', '.join(failed[:10]) + ('…' if len(failed) > 10 else '')
            ))
        logger.info(
            'notify_payment_required: sent %d/%d, %d failed, %d skipped%s.',
            sent, len(recipients), len(failed), skipped_already, scope_note,
        )
