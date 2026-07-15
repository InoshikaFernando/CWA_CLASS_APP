"""
Management command: find_dangling_homework_items
================================================
Diagnostic (read-only): report ``HomeworkQuestion`` rows whose backing content
row no longer exists. A dangling item is exactly what makes the student "take"
page 500 — the view resolves each item's content by ``(subject_slug, content_id)``
and a missing row raises ``DoesNotExist``.

Why a row can dangle
--------------------
* Maths items keep a ``question`` FK with ``on_delete=CASCADE``, so a *deleted
  maths Question* takes its HomeworkQuestion rows with it — those never dangle.
  A dangling *maths* row therefore means the row was written with a NULL FK
  (content_id only) pointing at an id that isn't in the table.
* Non-maths items (e.g. coding) store only ``content_id`` with **no FK**, so
  deleting the underlying content leaves the HomeworkQuestion behind → dangling.

Usage
-----
# Every affected homework across the site
python manage.py find_dangling_homework_items

# Just one homework (e.g. the one 500-ing in prod)
python manage.py find_dangling_homework_items --homework 74
"""
from django.core.management.base import BaseCommand

from classroom.subject_registry import get as get_plugin
from homework.models import HomeworkQuestion


class Command(BaseCommand):
    help = 'Report homework items whose backing content row is missing (read-only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--homework', type=int, default=None,
            help='Limit the scan to a single homework id.',
        )

    def handle(self, *args, **options):
        qs = HomeworkQuestion.objects.select_related('homework').order_by(
            'homework_id', 'order',
        )
        if options['homework'] is not None:
            qs = qs.filter(homework_id=options['homework'])

        # Resolve each item the same way the take page does; a plugin whose
        # content_id doesn't resolve is a dangling item.
        dangling = []
        for hwq in qs:
            plugin = get_plugin(hwq.subject_slug)
            if plugin is None:
                dangling.append((hwq, 'no plugin registered for subject_slug'))
                continue
            try:
                plugin.take_item_context(hwq.content_id)
            except Exception as exc:  # noqa: BLE001 — we want any resolution failure
                dangling.append((hwq, f'{type(exc).__name__}: {exc}'))

        if not dangling:
            self.stdout.write(self.style.SUCCESS(
                'No dangling homework items found — every item resolves.'))
            return

        self.stdout.write(self.style.WARNING(
            f'Found {len(dangling)} dangling item(s):'))
        for hwq, reason in dangling:
            hw = hwq.homework
            self.stdout.write(
                f'  homework #{hw.id} "{hw.title}" (class={hw.classroom_id}, '
                f'type={hw.homework_type}) — item order={hwq.order} '
                f'subject={hwq.subject_slug} content_id={hwq.content_id} '
                f'legacy_fk={hwq.question_id} → {reason}'
            )
        self.stdout.write('')
        self.stdout.write(
            'These items make the take page 500 on affected homework. The take '
            'view now skips them at render time; run with a specific --homework '
            'to confirm which item is the culprit.'
        )
