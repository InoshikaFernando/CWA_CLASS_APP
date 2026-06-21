"""Repair global Question.image paths that violate the naming convention
because the <topic> segment contains characters the slug rule disallows
(apostrophes, spaces, etc.) — e.g.

    questions/year8/pythagoras'_theorem/pyth_name_hyp.png

The apostrophe breaks QUESTION_IMAGE_PATH_RE, so audit_question_image_paths
flags the row. This command:

  1. sanitises the topic segment to the allowed [a-zA-Z0-9_-] set
     (pythagoras'_theorem -> pythagoras_theorem),
  2. copies the underlying object in the storage backend (DO Spaces) from
     the old key to the new key, and
  3. repoints Question.image at the new path.

It only touches GLOBAL questions (school IS NULL) — school-scoped media is
unconstrained — and only rows whose path fails the regex *and* can be made
valid by cleaning the topic segment alone. Paths broken in other ways
(missing year/topic structure) are reported and left for manual handling.

DRY-RUN BY DEFAULT. Pass --apply to mutate storage + the database. The
operation is idempotent: once a row points at the valid path it is no longer
selected, and a half-finished run (object copied, DB not yet updated) is
safely resumed.

    python manage.py fix_question_image_paths            # preview only
    python manage.py fix_question_image_paths --apply     # copy + update
    python manage.py fix_question_image_paths --apply --delete-old  # also remove source objects
"""
import re

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from maths.models import QUESTION_IMAGE_PATH_RE


def sanitize_topic_segment(topic):
    """Strip any character outside the convention's [a-zA-Z0-9_-] class.

    ``pythagoras'_theorem`` -> ``pythagoras_theorem``. Returns '' if nothing
    survives (caller treats that as un-fixable).
    """
    return re.sub(r'[^a-zA-Z0-9_-]', '', topic)


def proposed_path(path):
    """Return a convention-conformant path by cleaning only the topic
    segment, or None if the path can't be repaired that way.
    """
    parts = path.split('/')
    # questions / year<N> / <topic> / <filename...>
    if len(parts) < 4 or parts[0] != 'questions' or not re.fullmatch(r'year[0-9]+', parts[1]):
        return None
    clean_topic = sanitize_topic_segment(parts[2])
    if not clean_topic:
        return None
    candidate = '/'.join(['questions', parts[1], clean_topic, *parts[3:]])
    if candidate == path or not QUESTION_IMAGE_PATH_RE.match(candidate):
        return None
    return candidate


class Command(BaseCommand):
    help = (
        'Rename global Question images whose <topic> segment contains '
        'disallowed characters (e.g. apostrophes) and repoint the DB rows.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually copy objects and update the DB. Default is a dry run.',
        )
        parser.add_argument(
            '--delete-old', action='store_true',
            help='After a successful copy + DB update, delete the old storage object. '
                 'Default keeps the source object (safer / reversible).',
        )

    def handle(self, *args, **options):
        from maths.models import Question

        apply = options['apply']
        delete_old = options['delete_old']

        rows = (
            Question.objects
            .filter(school__isnull=True)
            .exclude(image__isnull=True).exclude(image='')
            .values_list('id', 'image')
            .order_by('id')
        )

        fixable, unfixable = [], []
        for pk, image in rows:
            path = str(image)
            if QUESTION_IMAGE_PATH_RE.match(path):
                continue  # already conformant
            new_path = proposed_path(path)
            if new_path is None:
                unfixable.append((pk, path))
            else:
                fixable.append((pk, path, new_path))

        if not fixable and not unfixable:
            self.stdout.write(self.style.SUCCESS('No violating global image paths found — nothing to do.'))
            return

        mode = 'APPLY' if apply else 'DRY RUN'
        self.stdout.write(self.style.WARNING(f'[{mode}] {len(fixable)} fixable, {len(unfixable)} un-fixable.'))

        copied = updated = skipped = errors = 0
        for pk, old_path, new_path in fixable:
            self.stdout.write(f'  Q{pk}: {old_path}')
            self.stdout.write(f'       -> {new_path}')
            if not apply:
                continue
            try:
                # 1. Ensure the object exists under the new key.
                if default_storage.exists(new_path):
                    self.stdout.write('       (storage object already at new key — skipping copy)')
                elif default_storage.exists(old_path):
                    with default_storage.open(old_path) as fh:
                        default_storage.save(new_path, ContentFile(fh.read()))
                    copied += 1
                    self.stdout.write('       copied storage object')
                else:
                    # Source missing and new key absent — repoint DB anyway so
                    # the path is valid, but warn loudly (image will 404).
                    self.stderr.write(self.style.WARNING(
                        '       WARNING: no storage object at old OR new key — '
                        'updating DB path only (image may be missing)'
                    ))

                # 2. Repoint the DB row (bypasses save()/signals deliberately).
                Question.objects.filter(pk=pk).update(image=new_path)
                updated += 1

                # 3. Optionally remove the orphaned source object.
                if delete_old and new_path != old_path and default_storage.exists(old_path):
                    default_storage.delete(old_path)
                    self.stdout.write('       deleted old storage object')
            except Exception as exc:  # noqa: BLE001 — report & continue, don't abort the batch
                errors += 1
                self.stderr.write(self.style.ERROR(f'       ERROR on Q{pk}: {exc!r}'))

        for pk, path in unfixable:
            self.stderr.write(self.style.ERROR(f'  Q{pk}: UN-FIXABLE (manual review): {path}'))

        if apply:
            self.stdout.write(self.style.SUCCESS(
                f'Done — {copied} object(s) copied, {updated} row(s) updated, '
                f'{errors} error(s), {len(unfixable)} left un-fixable.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'Dry run only — re-run with --apply to copy objects and update the DB.'
            ))
        if skipped:
            self.stdout.write(f'{skipped} skipped.')
