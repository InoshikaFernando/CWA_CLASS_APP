"""Put individual students on a module — or take them off one.

Student Basic (the free promotional edition, without the AI-graded questions)
is **granted, never chosen**. There is no student-facing route onto it: this
command and the Django admin are the only two ways a student ends up there, and
both need an operator. That is the point — a student with no module rows is on
no tier at all and keeps the app in full, which is every student on the site
until somebody is named here.

Usage::

    # Who is on what
    python manage.py student_modules --list

    # Put a promotion cohort on the free, non-AI edition
    python manage.py student_modules --grant basic --user ada --user grace
    python manage.py student_modules --grant basic --file promo_cohort.txt

    # Sell one of them the AI-graded questions back
    python manage.py student_modules --grant ai_grading --user ada

    # End the promotion for a student
    python manage.py student_modules --revoke basic --user ada

Always rehearse with ``--dry-run`` first; it reports exactly what would change
and writes nothing. Re-running a grant is a no-op, so a partly-applied cohort
can simply be run again.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from billing.entitlements import (
    active_student_modules, get_student_subscription, grant_student_module,
    revoke_student_module,
)
from billing.models import StudentModule

User = get_user_model()

# Short names on the command line, real slugs in the database.
ALIASES = {
    'basic': StudentModule.MODULE_BASIC,
    'student_basic': StudentModule.MODULE_BASIC,
    'ai_grading': StudentModule.MODULE_AI_GRADING,
    'student_ai_grading': StudentModule.MODULE_AI_GRADING,
}


class Command(BaseCommand):
    help = 'Grant or revoke a per-student module (Student Basic / AI grading).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--grant', choices=sorted(ALIASES),
            help='Module to switch on for the named students.',
        )
        parser.add_argument(
            '--revoke', choices=sorted(ALIASES),
            help='Module to switch off for the named students.',
        )
        parser.add_argument(
            '--user', action='append', default=[], dest='users',
            metavar='USERNAME_OR_EMAIL',
            help='A student to act on. Repeat for several.',
        )
        parser.add_argument(
            '--file', dest='file',
            help='Path to a text file of usernames/emails, one per line. '
                 'Blank lines and lines starting with # are ignored.',
        )
        parser.add_argument(
            '--note', default='',
            help='Why — recorded on the module row and shown in the admin.',
        )
        parser.add_argument(
            '--list', action='store_true', dest='do_list',
            help='List every student currently carrying a module and exit.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without saving anything.',
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        if options['do_list']:
            return self._list()

        grant, revoke = options['grant'], options['revoke']
        if bool(grant) == bool(revoke):
            raise CommandError(
                'Give exactly one of --grant or --revoke (or --list).')

        module = ALIASES[grant or revoke]
        identifiers = self._identifiers(options)
        if not identifiers:
            raise CommandError('No students named — use --user and/or --file.')

        dry_run = options['dry_run']
        changed = unchanged = skipped = 0

        with transaction.atomic():
            for identifier in identifiers:
                user = self._resolve(identifier)
                if user is None:
                    self.stderr.write(self.style.ERROR(
                        f'  [NOT FOUND] {identifier}'))
                    skipped += 1
                    continue

                # A module hangs off a subscription. Say so plainly rather than
                # reporting a silent success for a student who did not get it.
                if get_student_subscription(user) is None:
                    self.stderr.write(self.style.ERROR(
                        f'  [NO SUBSCRIPTION] {user.username} — cannot carry a '
                        f'module until they have one'))
                    skipped += 1
                    continue

                if dry_run:
                    holds = module in active_student_modules(user)
                    wanted = bool(grant)
                    if holds == wanted:
                        self.stdout.write(
                            f'  [NO CHANGE] {user.username} — already '
                            f'{"has" if holds else "without"} {module}')
                        unchanged += 1
                    else:
                        self.stdout.write(self.style.WARNING(
                            f'  [DRY RUN] would '
                            f'{"grant" if wanted else "revoke"} {module} '
                            f'{"to" if wanted else "from"} {user.username}'))
                        changed += 1
                    continue

                if grant:
                    _row, did = grant_student_module(
                        user, module, granted_by=None,
                        note=options['note'] or '',
                    )
                    verb = 'GRANTED'
                else:
                    _row, did = revoke_student_module(user, module)
                    verb = 'REVOKED'

                if did:
                    self.stdout.write(self.style.SUCCESS(
                        f'  [{verb}] {user.username} — {module}'))
                    changed += 1
                else:
                    self.stdout.write(
                        f'  [NO CHANGE] {user.username} — {module}')
                    unchanged += 1

            if dry_run:
                # Nothing was written, but roll back anyway so a future edit
                # that forgets the dry-run branch cannot leak a write.
                transaction.set_rollback(True)

        self.stdout.write('')
        self.stdout.write(
            f'{"Would change" if dry_run else "Changed"}: {changed}   '
            f'Already correct: {unchanged}   Skipped: {skipped}')

    # ------------------------------------------------------------------

    def _identifiers(self, options):
        names = list(options['users'])
        path = options.get('file')
        if path:
            try:
                with open(path) as handle:
                    for line in handle:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            names.append(line)
            except OSError as exc:
                raise CommandError(f'Could not read {path}: {exc}')
        # Preserve order, drop repeats — a cohort file often has duplicates.
        seen, ordered = set(), []
        for name in names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _resolve(self, identifier):
        return (User.objects.filter(username=identifier).first()
                or User.objects.filter(email__iexact=identifier).first())

    def _list(self):
        rows = (StudentModule.objects
                .select_related('subscription__user')
                .order_by('module', 'subscription__user__username'))
        if not rows:
            self.stdout.write(
                'No student is on any module — every student has the app in '
                'full, which is the default.')
            return
        for row in rows:
            state = 'on ' if row.is_active else 'off'
            source = f'  (code {row.source_code})' if row.source_code else ''
            self.stdout.write(
                f'  [{state}] {row.subscription.user.username:<24} '
                f'{row.module}{source}')
