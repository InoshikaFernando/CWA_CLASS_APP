"""
Management command: fix_topic_hierarchy
========================================
One-time data-fix utility for renaming topics and re-parenting them in the
Topic tree.

Usage examples
--------------
# Dry-run — show what WOULD change, touch nothing
python manage.py fix_topic_hierarchy --dry-run

# Rename "Measurement" (slug: measurement) to "Measurements" and make it a
# child of a strand whose slug is "number"
python manage.py fix_topic_hierarchy \\
    --slug measurement \\
    --new-name "Measurements" \\
    --parent-slug number

# Just rename, keep current parent unchanged
python manage.py fix_topic_hierarchy --slug measurements --new-name "Measurement"

# Move a topic under a new parent without renaming
python manage.py fix_topic_hierarchy --slug measurement --parent-slug geometry

# Remove parent (make top-level strand)
python manage.py fix_topic_hierarchy --slug measurement --remove-parent
"""

from django.core.management.base import BaseCommand, CommandError
from classroom.models import Topic


class Command(BaseCommand):
    help = 'Rename a Topic and/or change its parent in the hierarchy.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug',
            required=True,
            help='Slug of the topic to change.',
        )
        parser.add_argument(
            '--new-name',
            dest='new_name',
            default=None,
            help='New display name for the topic (leave out to keep current).',
        )
        parser.add_argument(
            '--new-slug',
            dest='new_slug',
            default=None,
            help='New slug for the topic (leave out to keep current).',
        )
        parser.add_argument(
            '--parent-slug',
            dest='parent_slug',
            default=None,
            help='Slug of the new parent topic.',
        )
        parser.add_argument(
            '--remove-parent',
            dest='remove_parent',
            action='store_true',
            default=False,
            help='Make this topic a top-level strand (no parent).',
        )
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            default=False,
            help='Print what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        slug        = options['slug']
        new_name    = options['new_name']
        new_slug    = options['new_slug']
        parent_slug = options['parent_slug']
        remove_parent = options['remove_parent']
        dry_run     = options['dry_run']

        # ── Locate target topic ────────────────────────────────────────────
        try:
            topic = Topic.objects.select_related('subject', 'parent').get(slug=slug)
        except Topic.DoesNotExist:
            raise CommandError(
                f"No Topic with slug '{slug}' found.  "
                f"Available slugs:\n"
                + "\n".join(
                    f"  {t.slug!r:30s} → {t.subject.name} — "
                    f"{'(strand)' if not t.parent else t.parent.name + ' › '}{t.name}"
                    for t in Topic.objects.select_related('subject', 'parent').order_by('subject__name', 'name')
                )
            )

        self.stdout.write('\nCurrent state:')
        self._print_topic(topic)

        # ── Resolve new parent ─────────────────────────────────────────────
        new_parent = topic.parent  # default: no change

        if remove_parent and parent_slug:
            raise CommandError('Cannot use --remove-parent and --parent-slug together.')

        if remove_parent:
            new_parent = None

        if parent_slug:
            try:
                new_parent = Topic.objects.select_related('subject').get(slug=parent_slug)
            except Topic.DoesNotExist:
                raise CommandError(f"No Topic with slug '{parent_slug}' found for --parent-slug.")

            # Guard against circular reference
            if new_parent.pk == topic.pk:
                raise CommandError('A topic cannot be its own parent.')

        # ── Preview ────────────────────────────────────────────────────────
        changes = []
        if new_name and new_name != topic.name:
            changes.append(f"  name:   {topic.name!r} → {new_name!r}")
        if new_slug and new_slug != topic.slug:
            changes.append(f"  slug:   {topic.slug!r} → {new_slug!r}")
        if new_parent != topic.parent:
            old_p = topic.parent.name if topic.parent else '(strand — no parent)'
            new_p = new_parent.name   if new_parent  else '(strand — no parent)'
            changes.append(f"  parent: {old_p!r} → {new_p!r}")

        if not changes:
            self.stdout.write(self.style.WARNING('\nNothing to change.'))
            return

        self.stdout.write('\nProposed changes:')
        for c in changes:
            self.stdout.write(self.style.MIGRATE_HEADING(c))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] No changes written.'))
            return

        # ── Apply ──────────────────────────────────────────────────────────
        if new_name:
            topic.name = new_name
        if new_slug:
            topic.slug = new_slug
        topic.parent = new_parent
        topic.save()

        self.stdout.write('\nAfter change:')
        topic.refresh_from_db()
        self._print_topic(topic)
        self.stdout.write(self.style.SUCCESS('\nDone.'))

    # ── Helper ─────────────────────────────────────────────────────────────

    def _print_topic(self, topic):
        parent_str = f"{topic.parent.name} (id={topic.parent_id})" if topic.parent else '(top-level strand)'
        self.stdout.write(
            f"  id={topic.pk}  slug={topic.slug!r}\n"
            f"  name={topic.name!r}  subject={topic.subject.name!r}\n"
            f"  parent={parent_str}"
        )
