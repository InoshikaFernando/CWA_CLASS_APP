"""Grant a module to schools without charging for it.

Two jobs, both of which are otherwise a hand-edit in the admin per school:

1. **Grandfathering.** Closing an entitlement leak takes a feature away from
   every school that was quietly using it while it was ungated. Whether that
   is acceptable is a commercial decision, not an engineering one, so this
   command exists to make the generous answer a one-liner:

       manage.py grant_module student_progress_reports --all --reason "used pre-CPP-4xx"

2. **Comped access.** An institute on a bespoke deal, a pilot, a school the
   owner has simply decided to give something to.

The row it writes is an ordinary ``ModuleSubscription`` with no
``stripe_subscription_item_id``, which is what "active but not billed" already
means everywhere else in this app — the Stripe sync reads that field, so a
blank one is never invoiced. Nothing here talks to Stripe.

Idempotent: running it twice grants nothing twice, and it reactivates a row
that was previously switched off rather than creating a duplicate (the model's
unique_together would reject one anyway).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import ModuleSubscription, SchoolSubscription

VALID = {slug for slug, _label in ModuleSubscription.MODULE_CHOICES}


class Command(BaseCommand):
    help = 'Grant a module to one or more schools without billing for it.'

    def add_arguments(self, parser):
        parser.add_argument('module', help=f'Module slug. One of: {", ".join(sorted(VALID))}')
        parser.add_argument(
            '--school', type=int, action='append', dest='schools', default=None,
            help='School id to grant to. Repeatable. Omit with --all for every school.',
        )
        parser.add_argument(
            '--all', action='store_true',
            help='Grant to every school that has a subscription.',
        )
        parser.add_argument(
            '--reason', default='',
            help='Why this was granted. Recorded in the audit log.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change and write nothing.',
        )

    def handle(self, *args, **options):
        module = options['module']
        if module not in VALID:
            raise CommandError(
                f'Unknown module {module!r}. Valid slugs: {", ".join(sorted(VALID))}')

        school_ids = options['schools']
        if bool(school_ids) == bool(options['all']):
            raise CommandError('Pass either --school (repeatable) or --all, not both/neither.')

        subs = SchoolSubscription.objects.select_related('school')
        if school_ids:
            subs = subs.filter(school_id__in=school_ids)
            found = set(subs.values_list('school_id', flat=True))
            missing = sorted(set(school_ids) - found)
            if missing:
                # A school id that matches nothing is a typo, and silently
                # granting to the rest would hide it.
                raise CommandError(
                    f'No SchoolSubscription for school id(s): {missing}. '
                    'A school with no subscription cannot hold a module.')

        subs = list(subs)
        if not subs:
            self.stdout.write('No matching school subscriptions — nothing to do.')
            return

        dry_run = options['dry_run']
        granted, already = [], []

        with transaction.atomic():
            for sub in subs:
                row = ModuleSubscription.objects.filter(
                    school_subscription=sub, module=module).first()
                if row and row.is_active:
                    already.append(sub.school.name)
                    continue

                if dry_run:
                    granted.append(sub.school.name)
                    continue

                if row:
                    # Reactivate rather than insert — unique_together would
                    # reject a second row, and the history is worth keeping.
                    row.is_active = True
                    row.deactivated_at = None
                    row.save(update_fields=['is_active', 'deactivated_at'])
                else:
                    ModuleSubscription.objects.create(
                        school_subscription=sub, module=module, is_active=True,
                    )
                granted.append(sub.school.name)

                self._log(sub, module, options['reason'])

            if dry_run:
                transaction.set_rollback(True)

        prefix = 'Would grant' if dry_run else 'Granted'
        self.stdout.write(self.style.SUCCESS(
            f'{prefix} {module} to {len(granted)} school(s).'))
        for name in granted:
            self.stdout.write(f'  + {name}')
        if already:
            self.stdout.write(f'{len(already)} school(s) already had it:')
            for name in already:
                self.stdout.write(f'  = {name}')

    def _log(self, sub, module, reason):
        """Record the grant. A comped module with no trail is one nobody can
        later explain, and these rows are deliberately not billed."""
        try:
            from audit.services import log_event
            log_event(
                user=None, school=sub.school,
                category='entitlement', action='module_granted',
                result='success',
                detail={'module': module, 'reason': reason, 'billed': False},
            )
        except Exception:  # noqa: BLE001
            # An audit backend that is unavailable must not roll back a grant
            # the operator asked for; the stdout report is still the record.
            self.stderr.write(self.style.WARNING(
                f'  (audit log failed for {sub.school.name} — grant still applied)'))
