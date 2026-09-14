"""
Read and set feature flags from the command line.

The admin is the usual place; this is for the times a browser is not — a deploy
script, an SSH session during an incident, or checking what production actually
has switched on without trusting anyone's memory.

    python manage.py feature_flag                          # list everything
    python manage.py feature_flag language                 # one flag, in detail
    python manage.py feature_flag language --off
    python manage.py feature_flag language --pilot --school 1
    python manage.py feature_flag language --on

Creating: a slug with no row is created on first write, off by default, so
`--pilot --school 1` on a fresh environment is one command rather than two.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'List or set feature flags.'

    def add_arguments(self, parser):
        parser.add_argument('slug', nargs='?', help='Flag to show or change.')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--off', action='store_true', help='Nobody.')
        group.add_argument('--pilot', action='store_true',
                           help='Only the schools named with --school.')
        group.add_argument('--on', action='store_true', help='Every school.')
        parser.add_argument(
            '--school', type=int, action='append', dest='schools', default=None,
            help='School id for --pilot. Repeatable. Replaces the existing list.',
        )
        parser.add_argument('--description', default=None,
                            help='Set the description when creating or updating.')

    def handle(self, *args, **options):
        from classroom.models import School
        from ops import flags as flags_api
        from ops.models import FeatureFlag

        slug = options['slug']
        wants_write = any(options[k] for k in ('off', 'pilot', 'on')) or \
            options['schools'] is not None or options['description'] is not None

        if not slug:
            if wants_write:
                raise CommandError('Name a flag to change.')
            return self._list(FeatureFlag)

        if not wants_write:
            try:
                return self._show(FeatureFlag.objects.get(slug=slug))
            except FeatureFlag.DoesNotExist:
                raise CommandError(
                    f'No flag "{slug}". It reads as OFF everywhere until it '
                    f'exists; create it with --off, --pilot or --on.'
                )

        flag, created = FeatureFlag.objects.get_or_create(slug=slug)
        if created:
            self.stdout.write(f'Created flag "{slug}" (was off by default).')

        if options['description'] is not None:
            flag.description = options['description']
        if options['off']:
            flag.rollout = FeatureFlag.OFF
        elif options['pilot']:
            flag.rollout = FeatureFlag.PILOT
        elif options['on']:
            flag.rollout = FeatureFlag.ON
        flag.save()

        if options['schools'] is not None:
            schools = list(School.objects.filter(pk__in=options['schools']))
            missing = set(options['schools']) - {s.pk for s in schools}
            if missing:
                raise CommandError(
                    f'No school with id {", ".join(str(m) for m in sorted(missing))}'
                )
            flag.schools.set(schools)

        flags_api.invalidate()
        self._show(flag)

        if flag.rollout == FeatureFlag.PILOT and not flag.schools.exists():
            self.stdout.write(self.style.WARNING(
                '  Pilot with no schools — this is on for nobody. '
                'Add one with --school <id>.'
            ))

    def _list(self, FeatureFlag):
        flags = FeatureFlag.objects.prefetch_related('schools')
        if not flags:
            self.stdout.write('No feature flags in this environment.')
            return
        for flag in flags:
            names = ', '.join(flag.schools.values_list('name', flat=True))
            extra = f'  [{names}]' if flag.rollout == FeatureFlag.PILOT else ''
            self.stdout.write(f'  {flag.slug:28} {flag.rollout:6}{extra}')

    def _show(self, flag):
        self.stdout.write(f'\n{flag.slug}')
        self.stdout.write(f'  rollout:     {flag.rollout}')
        if flag.rollout == flag.PILOT:
            names = list(flag.schools.values_list('name', flat=True))
            self.stdout.write(f'  schools:     {", ".join(names) or "(none)"}')
        if flag.description:
            self.stdout.write(f'  description: {flag.description}')
