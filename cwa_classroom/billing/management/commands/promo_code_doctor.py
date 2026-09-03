"""Did Student (Promo) codes ever actually do anything? Read-only.

A ``PromoCode`` is redeemed on the Select Classes page and its only effect is
to raise the student's CLASS limit — ``accounts.views._effective_class_limit``
prefers a redeemed promo's ``class_limit`` over the package's. It never touches
a subscription, so it changes nothing about what the student pays or which
questions they are shown.

That makes "did it work?" a question about data rather than code, and the honest
answer needs the live database. This reports it. It writes nothing.

Three things it separates, because they fail differently:

``uses`` vs redeemed_by
    ``uses`` is a counter; ``redeemed_by`` is the membership that actually does
    the work. Only ``redeemed_by`` is read when the limit is computed, so a code
    with a high counter and no members did nothing at all — the counter was
    bumped by an import or by a redemption path that never added the member.

Redeemed but changed nothing
    A promo whose ``class_limit`` is no better than the package the student is
    already on is a no-op for them. Worth knowing before concluding the feature
    is broken: it may simply have granted what they already had.

Redeemed and load-bearing
    Students whose current class access exists BECAUSE of the promo. Removing
    or deactivating the code would take enrolments away from them.

Usage::

    python manage.py promo_code_doctor
    python manage.py promo_code_doctor --code FULLACCESS2026
    python manage.py promo_code_doctor --students      # name every redeemer
"""
from django.core.management.base import BaseCommand

from billing.models import PromoCode


class Command(BaseCommand):
    help = ('Report whether each Student (Promo) code has actually taken '
            'effect for anybody. Read-only.')

    def add_arguments(self, parser):
        parser.add_argument('--code', help='Only this promo code.')
        parser.add_argument(
            '--students', action='store_true',
            help='List every redeemer, not just the counts.')

    def handle(self, *args, **options):
        from accounts.views import _effective_class_limit
        from classroom.models import ClassRoom

        codes = PromoCode.objects.all().order_by('code')
        if options['code']:
            codes = codes.filter(code=options['code'].strip().upper())
        codes = list(codes.prefetch_related('redeemed_by'))

        if not codes:
            self.stdout.write('No promo codes found.')
            return

        def limit_text(value):
            return 'unlimited' if value == 0 else str(value)

        totals = {'codes': 0, 'phantom': 0, 'effective': 0}

        for promo in codes:
            members = list(promo.redeemed_by.all())
            state = 'active' if promo.is_active else 'INACTIVE'
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'{promo.code}  ({state}, class limit '
                f'{limit_text(promo.class_limit)})'))
            self.stdout.write(
                f'  uses counter: {promo.uses}     '
                f'redeemed_by rows: {len(members)}')

            # The counter is decoration; redeemed_by is what the limit reads.
            if promo.uses and not members:
                self.stdout.write(self.style.ERROR(
                    '  ** counter says redeemed, but NOBODY is a member — this '
                    'code has never taken effect for anyone. **'))
                totals['phantom'] += 1
            elif promo.uses != len(members):
                self.stdout.write(self.style.WARNING(
                    f'  ** counter and membership disagree ({promo.uses} vs '
                    f'{len(members)}) — the counter is not the truth here. **'))

            changed_something = 0
            for user in members:
                package_limit = (user.package.class_limit
                                 if user.package else 1)
                effective = _effective_class_limit(user)
                enrolled = ClassRoom.objects.filter(
                    students=user, is_active=True).count()
                # "Better" means the student can join classes they could not
                # otherwise. A package that is ALREADY unlimited cannot be
                # improved on, so an unlimited promo adds nothing there —
                # getting this backwards would report a dead code as working.
                helps = package_limit != 0 and (
                    promo.class_limit == 0
                    or promo.class_limit > package_limit)
                if helps:
                    changed_something += 1
                if options['students']:
                    self.stdout.write(
                        f'    {user.username:<24} package '
                        f'{limit_text(package_limit):<9} effective '
                        f'{limit_text(effective):<9} enrolled {enrolled}'
                        f'{"" if helps else "   (promo adds nothing)"}')

            if members:
                self.stdout.write(
                    f'  gives more than their package to: '
                    f'{changed_something} of {len(members)}')
                if changed_something:
                    totals['effective'] += 1

            totals['codes'] += 1

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Summary'))
        self.stdout.write(f'  promo codes checked:              {totals["codes"]}')
        self.stdout.write(f'  codes doing real work for someone: {totals["effective"]}')
        if totals['phantom']:
            self.stdout.write(self.style.ERROR(
                f'  codes with a counter but no members: {totals["phantom"]}'))
        if not totals['effective']:
            self.stdout.write(self.style.WARNING(
                '  No promo code is currently raising anyone\'s class access '
                'above what their package already gives. That is consistent '
                'with "it never worked" — but it is also what you would see if '
                'every package already allowed unlimited classes, so check the '
                'package limits above before concluding.'))
