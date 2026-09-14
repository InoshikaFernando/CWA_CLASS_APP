"""
Email families who are not paying, with the code and the link to start.

Two audiences, because the same email serves two jobs and the lists are not the
same people.

``--audience regated`` (the default, and the original behaviour)
    Students the re-gating pass put back behind the payment wall, who have
    logged in at least once. A nudge to families who were already using the app
    — see ``reset_imported_student_gating``, which must run first to set the
    flag. Dormant accounts are skipped on purpose: they meet the payment gate
    naturally on first login.

``--audience unsubscribed``
    Anybody with no live subscription of their own. **Including students who
    have never subscribed at all** — they are the larger half of any
    recruitment list, and every one of them is invisible to ``regated``, which
    requires ``profile_completed=False`` and a previous login. A student who
    finished a free promotion is invisible to it twice over: their profile IS
    complete and their subscription IS expired.

    This is the list a promotion goes to.

``--include-parents`` adds the linked parent or guardian of each student. Worth
saying out loud: the student is the one with the account, the parent is the one
with the card. Reaching only the child is how a campaign gets read by somebody
who cannot act on it.

Predicate (per student)
-----------------------
  * has Role.STUDENT and NOT Role.INDIVIDUAL_STUDENT
  * has NO active/trialing Subscription  (their OWN — a school plan is not
    consulted, or every student of a subscribed institute would be excluded)
  * (if --school given) has an active enrolment in that school
  * plus, for ``regated`` only: profile_completed=False AND last_login IS NOT NULL

Anyone who already received this email is skipped so a re-run never
double-sends to a real family; ``--resend`` overrides that.

Usage
-----
    # Preview, always, before sending anything to real families
    python manage.py notify_payment_required --school 4 \
        --audience unsubscribed --include-parents --dry-run

    # The MHM promotion: everyone not paying, plus their parents
    python manage.py notify_payment_required --school 4 \
        --audience unsubscribed --include-parents \
        --discount-code MHM2WEEKS --discount-percent 100 \
        --link-url https://www.wizardslearninghub.co.nz/accounts/complete-profile/

    # The original re-gating nudge, unchanged
    python manage.py notify_payment_required --school 4 \
        --discount-code MHMEBC75 --discount-percent 75
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

AUDIENCE_REGATED = 'regated'
AUDIENCE_UNSUBSCRIBED = 'unsubscribed'


class Command(BaseCommand):
    help = (
        'Email families who are not paying, with the code and the link to '
        'start. --audience regated (default) is the re-gating nudge; '
        '--audience unsubscribed is everybody with no live subscription, '
        'including students who never had one.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='List recipients without sending any email.')
        parser.add_argument('--school', type=int, default=None, metavar='SCHOOL_ID',
                            help='Restrict to students actively enrolled in this school.')
        parser.add_argument('--audience', default=AUDIENCE_REGATED,
                            choices=(AUDIENCE_REGATED, AUDIENCE_UNSUBSCRIBED),
                            help='Who to email. "regated" (default) is the '
                                 'original re-gating nudge: already-logged-in '
                                 'students put back behind the wall. '
                                 '"unsubscribed" is everybody with no live '
                                 'subscription, including students who never '
                                 'had one — the list a promotion goes to.')
        parser.add_argument('--include-parents', action='store_true',
                            dest='include_parents',
                            help='Also email each student\'s linked parent or '
                                 'guardian. The parent is the one who can pay.')
        parser.add_argument('--link-url', default='', dest='link_url',
                            help='Where the email\'s button goes. Defaults to '
                                 'the site login, which is right for a student '
                                 'who just needs to come back and pay; a '
                                 'promotion usually wants its own page.')
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

        audience = options['audience']

        # "No live subscription" is one set, computed once and reused, rather
        # than a join per branch — a student may hold a cancelled or expired
        # row, so "has a Subscription" is the wrong question and an inner join
        # on the wrong statuses silently drops everyone who never had one.
        subscribed_ids = set(
            Subscription.objects.filter(status__in=_ACTIVE_SUB_STATUSES)
            .values_list('user_id', flat=True)
        )

        students = (
            CustomUser.objects.filter(roles__name=Role.STUDENT)
            .exclude(roles__name=Role.INDIVIDUAL_STUDENT)
            .exclude(id__in=subscribed_ids)
        )
        if audience == AUDIENCE_REGATED:
            # The original nudge: put back behind the wall, and active enough
            # to have logged in. Both conditions EXCLUDE a student who finished
            # a free promotion — their profile is complete and they have logged
            # in — which is why the promotion audience is a separate list.
            students = students.filter(
                profile_completed=False, last_login__isnull=False)

        if school_id is not None:
            from classroom.models import SchoolStudent
            enrolled_ids = SchoolStudent.objects.filter(
                school_id=school_id, is_active=True,
            ).values_list('student_id', flat=True)
            students = students.filter(id__in=enrolled_ids)

        students = list(students.distinct())

        # Recipients are (user, school) pairs from here on. A parent belongs to
        # no school of their own, so ``_resolve_school`` returns None for them
        # and the email would go out with the school's name missing from the
        # subject line and the body. The child's school is carried across.
        recipients = [(student, school) for student in students]
        parent_count = 0
        if options['include_parents']:
            for parent, parent_school in self._parents_of(students, school):
                recipients.append((parent, parent_school))
                parent_count += 1

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
            recipients = [(u, sch) for u, sch in recipients
                          if u.id not in already_sent_ids]
            skipped_already = before - len(recipients)

        label = ('re-gated, logged-in students' if audience == AUDIENCE_REGATED
                 else 'unsubscribed students')
        if not recipients:
            msg = f'No {label}{scope_note} to notify.'
            if skipped_already:
                msg += f' ({skipped_already} already emailed — use --resend to include them.)'
            self.stdout.write(self.style.SUCCESS(msg))
            return

        self.stdout.write(
            f'{len(recipients)} recipient(s){scope_note} will be emailed — '
            f'{len(students)} {label}'
            + (f' and {parent_count} parent(s)' if parent_count else '')
            + f' (code={options["discount_code"] or "none"}, '
            f'{options["discount_percent"]}% off'
            + (f', link={options["link_url"]}' if options['link_url'] else '')
            + ')'
            + (f'; {skipped_already} already emailed (skipped).' if skipped_already else '.')
        )
        for u, _sch in recipients:
            self.stdout.write(f'  - {u.get_full_name() or u.username} <{u.email or "no email"}>')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no emails sent.'))
            return

        from notifications.services import send_payment_required_notification
        sleep_s = options['sleep']
        sent = 0
        failed = []
        for i, (u, recipient_school) in enumerate(recipients):
            if i and sleep_s > 0:
                time.sleep(sleep_s)   # pace under Resend's 2/sec limit
            ok = send_payment_required_notification(
                u, school=recipient_school,
                plan_name=options['plan_name'],
                monthly_price=options['monthly_price'],
                discount_code=options['discount_code'],
                discount_percent=options['discount_percent'],
                currency_symbol=options['currency'],
                support_email=options['support_email'],
                login_url=options['link_url'],
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

    # ------------------------------------------------------------------

    @staticmethod
    def _parents_of(students, default_school):
        """``(parent, school)`` for each student in *students*, each parent once.

        The school comes from the link row rather than from the parent, because
        a parent has no school of their own — ``_resolve_school`` returns None
        for them, and the email would then go out addressed from "Wizards
        Learning Hub" with the school's name missing from a message whose whole
        point is that it comes from their child's school.

        A parent with two unsubscribed children is emailed once. Two copies of
        the same offer reads as a mistake and invites them to pay twice.
        """
        from classroom.models import ParentStudent

        if not students:
            return []

        links = (ParentStudent.objects
                 .filter(student_id__in=[s.id for s in students], is_active=True)
                 .filter(parent__email__isnull=False)
                 .exclude(parent__email='')
                 .select_related('parent', 'school')
                 .order_by('parent__first_name', 'parent__last_name'))

        out = []
        seen = set()
        for link in links:
            if link.parent_id in seen:
                continue
            seen.add(link.parent_id)
            out.append((link.parent, link.school or default_school))
        return out
