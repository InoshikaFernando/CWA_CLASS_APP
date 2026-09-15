"""Mint the code that gives a cohort a fixed, free, card-free run of the app.

The MHM promotion is the reason this exists: two weeks of real work — homework,
quizzes, the lot — with no card asked for at any point, on the edition without
the AI-graded questions, and then it stops and asks them to subscribe.

Every part of that is already in the model; what was missing was a way to set
all of it at once and get it right. The three fields have to agree, and each
disagreement fails quietly rather than loudly:

``discount_percent = 100``
    The whole price. Anything less sends the student to Stripe for the
    remainder, which means a card — and the model refuses to put a paying
    student on the reduced tier anyway (``StudentBasicGrantMixin``).
``grant_days``
    How long it lasts. Leave it blank and the access never ends: there is no
    date for anything to expire against, so "two weeks free" becomes free
    forever, and nothing anywhere complains.
``grants_student_basic = True``
    The no-AI edition. Leave it off and the cohort gets the AI-graded questions
    free for a fortnight, at the vendor's per-question cost.

Usage::

    # Rehearse — writes nothing
    python manage.py free_trial_code --code MHM2WEEKS --dry-run

    # Mint it: 14 days, no AI, no card, 200 students
    python manage.py free_trial_code --code MHM2WEEKS --max-uses 200

    # A different window, and a date after which nobody new can start
    python manage.py free_trial_code --code MHM-TERM4 --days 21 \\
        --expires 2026-12-19

    # Stop handing it out (students already on it keep their remaining days)
    python manage.py free_trial_code --code MHM2WEEKS --deactivate

Re-running is safe: an existing code is updated in place, and the students
already holding it are not touched. What CANNOT be done here is turning the
Student Basic flag on for a code somebody has already redeemed — that reaches
backwards and changes what those students get the next time their subscription
is activated, so the model refuses it and this command reports the refusal and
tells you to mint a new code.
"""
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import DiscountCode

#: Two weeks, because that is what the promotion this was built for offers.
#: Pass ``--days`` for anything else.
DEFAULT_GRANT_DAYS = 14


class Command(BaseCommand):
    help = ('Create or update a 100%-off, time-limited, no-AI promotion code '
            '(the MHM-style free trial).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--code', required=True,
            help='The code students will type, e.g. MHM2WEEKS.',
        )
        parser.add_argument(
            '--days', type=int, default=DEFAULT_GRANT_DAYS,
            help=f'Days of access the code grants (default: {DEFAULT_GRANT_DAYS}).',
        )
        parser.add_argument(
            '--max-uses', type=int, default=None, dest='max_uses',
            help='How many students may redeem it. Omit for unlimited.',
        )
        parser.add_argument(
            '--expires', default='', dest='expires',
            help='YYYY-MM-DD after which the code can no longer be redeemed. '
                 'This is the LAST DAY TO START, not when access ends — a '
                 'student who starts on the final day still gets the full '
                 'window.',
        )
        parser.add_argument(
            '--with-ai', action='store_true', dest='with_ai',
            help='Grant the app in full, AI-graded questions included. Off by '
                 'default: this command exists to mint the no-AI edition, and '
                 'the AI questions cost real money per answer.',
        )
        parser.add_argument(
            '--deactivate', action='store_true',
            help='Switch an existing code off so nobody new can redeem it. '
                 'Students already on it keep the days they were granted.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change and write nothing.',
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        code_str = options['code'].strip().upper()
        if not code_str:
            raise CommandError('--code cannot be blank.')

        days = options['days']
        if days < 1:
            raise CommandError('--days must be at least 1.')

        max_uses = options['max_uses']
        if max_uses is not None and max_uses < 1:
            raise CommandError('--max-uses must be at least 1, or omitted.')

        expires_at = self._parse_expiry(options['expires'])
        dry_run = options['dry_run']

        existing = DiscountCode.objects.filter(code__iexact=code_str).first()

        if options['deactivate']:
            return self._deactivate(existing, code_str, dry_run)

        with transaction.atomic():
            code = existing or DiscountCode(code=code_str)
            was_new = existing is None
            before = self._snapshot(code) if existing else None

            code.discount_percent = 100
            code.grant_days = days
            code.grants_student_basic = not options['with_ai']
            code.max_uses = max_uses
            code.expires_at = expires_at
            code.is_active = True
            # A 100% code never reaches Stripe, so a coupon id on it would be
            # a dead field that reads as if a discount were being applied
            # somewhere. Say plainly that there is nothing to apply.
            code.stripe_coupon_id = ''

            try:
                code.full_clean(exclude=['applicable_packages'])
            except ValidationError as exc:
                raise CommandError(self._explain(code_str, exc))

            if dry_run:
                transaction.set_rollback(True)
            else:
                code.save()

        self._report(code, was_new, before, dry_run)

    # ------------------------------------------------------------------

    def _deactivate(self, existing, code_str, dry_run):
        if existing is None:
            raise CommandError(f'No code called {code_str} to deactivate.')
        if not existing.is_active:
            self.stdout.write(f'{code_str} is already inactive — nothing to do.')
            return
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] would deactivate {code_str}'))
            return
        existing.is_active = False
        existing.save(update_fields=['is_active'])
        self.stdout.write(self.style.SUCCESS(
            f'Deactivated {code_str}. Nobody new can redeem it; the '
            f'{existing.uses} student(s) already on it keep the days they '
            f'were granted.'))

    def _parse_expiry(self, raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            day = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            raise CommandError(
                f'--expires must be YYYY-MM-DD, got {raw!r}.')
        # End of that day in the site's timezone, so "expires 2026-12-19" means
        # a student can still start on the 19th rather than losing it at
        # midnight the night before.
        return timezone.make_aware(
            datetime.combine(day, time.max),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def _snapshot(code):
        return {
            'discount_percent': code.discount_percent,
            'grant_days': code.grant_days,
            'grants_student_basic': code.grants_student_basic,
            'max_uses': code.max_uses,
            'expires_at': code.expires_at,
            'is_active': code.is_active,
        }

    @staticmethod
    def _explain(code_str, exc):
        """Turn the model's refusal into something a person can act on."""
        lines = [f'Refused to write {code_str}:']
        for field, messages in exc.message_dict.items():
            for message in messages:
                lines.append(f'  - {field}: {message}')
        return '\n'.join(lines)

    def _report(self, code, was_new, before, dry_run):
        verb = 'Would create' if (was_new and dry_run) else \
               'Created' if was_new else \
               'Would update' if dry_run else 'Updated'
        tier = ('the app in full (AI-graded questions included)'
                if not code.grants_student_basic
                else 'Student Basic — no AI-graded questions')
        expiry = (timezone.localtime(code.expires_at).date().isoformat()
                  if code.expires_at else 'never')

        self.stdout.write(self.style.SUCCESS(f'{verb} {code.code}'))
        self.stdout.write(f'  Price to the student  100% off — no card is collected')
        self.stdout.write(f'  Access granted        {code.grant_days} days from redemption')
        self.stdout.write(f'  Tier                  {tier}')
        self.stdout.write(
            f'  Redemptions           '
            f'{code.uses} used, '
            f'{"unlimited" if code.max_uses is None else code.max_uses} allowed')
        self.stdout.write(f'  Last day to start     {expiry}')

        if before:
            changed = {k: v for k, v in self._snapshot(code).items()
                       if before[k] != v}
            if changed:
                self.stdout.write('')
                self.stdout.write('  Changed from:')
                for field, value in changed.items():
                    self.stdout.write(f'    {field}: {before[field]!r} -> {value!r}')
            else:
                self.stdout.write('')
                self.stdout.write('  Already exactly this — nothing changed.')

        self.stdout.write('')
        self.stdout.write(
            f'  When the {code.grant_days} days are up the student is walled '
            f'and asked to subscribe. Paying revokes Student Basic and hands '
            f'them the AI-graded questions automatically.'
            if code.grants_student_basic else
            f'  When the {code.grant_days} days are up the student is walled '
            f'and asked to subscribe.')
        if dry_run:
            self.stdout.write(self.style.WARNING('  DRY RUN — nothing was written.'))
