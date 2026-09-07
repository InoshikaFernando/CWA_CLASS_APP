"""Tell the families whose payment failed while nobody was telling them.

Why this exists
---------------
`invoice.payment_failed` had been arriving and being processed for a long time
— 41 events on production — but the handler read `invoice.subscription`, a key
recent Stripe API versions no longer set. It resolved to None every time, so no
user was found and `notify_payment_failed` was called with nobody to write to.
Result: students correctly locked out of the app, and not one family told why.
One of them had been in that state for nearly a month.

The reader is fixed, but that only helps the NEXT failure. Stripe will not
resend a spent event, and its retry schedule for these subscriptions may be
exhausted — so without this command the backlog is simply never told.

This is deliberately a one-off, run by a person, rather than a cron: it exists
to clear a backlog created by a defect, not to become a second dunning system
running alongside Stripe's.

Safety
------
* Sending is opt-in. The default prints who WOULD be written to and sends
  nothing, because the failure mode here is mailing real families by accident.
* Idempotent: a student already notified since their subscription went
  past_due is skipped, so a second run does not double-send. The marker is an
  audit event, so this needs no migration and leaves a trail.
* Only `past_due`. `cancelled` and `expired` are not "your card failed, please
  update it" — telling someone who deliberately cancelled to fix their payment
  is worse than saying nothing.

Usage
-----
    python manage.py notify_past_due                # dry run, writes nothing
    python manage.py notify_past_due --send         # actually email
    python manage.py notify_past_due --send --force # ignore the "already told" marker
"""
from django.core.management.base import BaseCommand

NOTICE_ACTION = 'payment_failed_notice_sent'


class Command(BaseCommand):
    help = ('Email the families of students whose subscription is past_due and '
            'who were never told, because the failed-payment handler could not '
            'resolve them. Dry run unless --send is given.')

    def add_arguments(self, parser):
        parser.add_argument('--send', action='store_true',
                            help='Actually send. Without this, nothing is sent.')
        parser.add_argument('--force', action='store_true',
                            help='Send even to someone already notified.')

    def handle(self, *args, **opts):
        from audit.models import AuditLog
        from audit.services import log_event
        from billing.email_utils import _parent_emails, notify_past_due_backlog
        from billing.models import Subscription

        send = opts['send']
        force = opts['force']

        self.stdout.write(self.style.MIGRATE_HEADING(
            '=== notify_past_due' + ('' if send else '  [DRY RUN — nothing sent]')
            + ' ==='))

        rows = (Subscription.objects
                .filter(status=Subscription.STATUS_PAST_DUE)
                .select_related('user', 'package')
                .order_by('user__username'))

        sent = skipped = unreachable = 0
        for sub in rows:
            user = sub.user
            # "Already told" means told since THIS lapse began, not ever: a
            # student who failed, paid, and failed again months later is owed a
            # second notice.
            already = AuditLog.objects.filter(
                user=user, action=NOTICE_ACTION,
                created_at__gte=sub.updated_at,
            ).exists()
            if already and not force:
                self.stdout.write(
                    f'  skip  {user.username} — already notified since this lapse')
                skipped += 1
                continue

            to = ([user.email] if user.email else []) + [
                e for e in _parent_emails(user) if e != user.email]
            if not to:
                self.stdout.write(self.style.WARNING(
                    f'  NOBODY {user.username} — no address for the student or '
                    f'any linked parent'))
                unreachable += 1
                continue

            self.stdout.write(f'  {"send " if send else "would"} {user.username}'
                              f' -> {", ".join(to)}')
            if not send:
                sent += 1
                continue

            # No amount is quoted. The figure would have to carry a currency,
            # and this app serves schools in more than one — a New Zealand sum
            # shown to a Melbourne family is worse than no sum at all. Stripe's
            # own portal shows what is owed, in the currency it will charge.
            notify_past_due_backlog(user, since=sub.updated_at)
            # Written AFTER the send, so a crash mid-send leaves the student
            # un-marked and a re-run picks them up rather than skipping someone
            # who was never actually written to.
            log_event(
                user=user, category='billing', action=NOTICE_ACTION,
                detail={'recipients': to, 'sub_status': sub.status,
                        'why': 'backlog cleared by notify_past_due'},
            )
            sent += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{"Sent" if send else "Would send"} {sent}; '
            f'{skipped} already notified; {unreachable} with no address.'))
        if not send:
            self.stdout.write('Nothing was sent. Re-run with --send to do it.')
