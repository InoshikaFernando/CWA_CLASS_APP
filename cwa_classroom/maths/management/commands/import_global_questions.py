"""Import a rich question export into the GLOBAL maths bank (school = NULL).

Consumes the JSON produced by either:
  * ``manage.py export_school_questions --school <id> -o out.json`` (live DB), or
  * ``scripts/export_school_questions_from_dump.py`` (offline, from a SQL dump).

For every group it resolves / creates the global Year (``classroom.Level``),
Topic (title) and Subtopic (sub-title) under the global ``mathematics`` subject,
then creates a global ``maths.Question`` (school=None) with its answers, image,
and all type-specific fields (operands, dividend/divisor, grid_spec, …).

Idempotent: a global question with the same ``question_text`` + ``level`` is
skipped unless ``--overwrite`` is given.

Usage
-----
    python manage.py import_global_questions mhm_global_questions.json
    python manage.py import_global_questions mhm_global_questions.json --dry-run
    python manage.py import_global_questions mhm_global_questions.json --overwrite
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from maths.models import QUESTION_IMAGE_PATH_RE

# Plain (non type-specific) Question columns copied straight through.
SCALAR_FIELDS = (
    'question_text', 'question_type', 'difficulty', 'points', 'explanation',
    'validation_type', 'answer_format', 'grading_rubric',
    'dividend', 'divisor', 'target_number', 'operands', 'operator',
    'numeric_answer', 'answer_tolerance', 'answer_unit', 'grid_spec', 'shape_spec',
)


class Command(BaseCommand):
    help = 'Import a JSON question export into the global bank (school=NULL).'

    def add_arguments(self, parser):
        parser.add_argument('json_file', type=str)
        parser.add_argument('--dry-run', action='store_true',
                            help='Resolve and report without writing to the DB.')
        parser.add_argument('--overwrite', action='store_true',
                            help='Update an existing global question (and its '
                                 'answers) instead of skipping it.')

    def handle(self, *args, **opts):
        from classroom.models import Subject

        dry_run = opts['dry_run']
        overwrite = opts['overwrite']

        try:
            with open(opts['json_file'], encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {opts['json_file']}")
        except json.JSONDecodeError as exc:
            raise CommandError(f'Invalid JSON: {exc}')

        try:
            self.subject = Subject.objects.get(slug='mathematics', school__isnull=True)
        except Subject.DoesNotExist:
            raise CommandError('Global mathematics subject (slug=mathematics, '
                               'school=NULL) not found.')

        meta = data.get('meta', {})
        groups = data.get('groups', [])
        self.stdout.write(
            f"Importing {meta.get('question_count', '?')} questions in "
            f"{len(groups)} groups from {meta.get('source_school', '?')}…"
        )

        self._topic_cache = {}   # (slug, parent_id) -> Topic
        self._level_cache = {}   # level_number -> Level
        created = updated = skipped = img_warn = 0

        # One transaction; --dry-run rolls it back so nothing persists.
        with transaction.atomic():
            for g in groups:
                level = self._resolve_level(g.get('level_number'), g.get('year'))
                if level is None:
                    n = len(g.get('questions', []))
                    skipped += n
                    self.stderr.write(self.style.WARNING(
                        f"  Skipped {n} questions — no level for "
                        f"year={g.get('year')!r} (level_number={g.get('level_number')!r})"))
                    continue

                topic = self._resolve_topic(g.get('title'), g.get('subtitle'))

                for q in g.get('questions', []):
                    text = (q.get('question_text') or '').strip()
                    if not text:
                        skipped += 1
                        continue

                    existing = self.Question.objects.filter(
                        school__isnull=True, question_text=text, level=level,
                    ).first()
                    if existing and not overwrite:
                        skipped += 1
                        continue

                    image = q.get('image') or None
                    if image and not QUESTION_IMAGE_PATH_RE.match(image):
                        img_warn += 1
                        self.stderr.write(self.style.WARNING(
                            f"  Image path not in questions/year<N>/<topic>/ form: {image}"))

                    fields = {f: q.get(f) for f in SCALAR_FIELDS if q.get(f) is not None}
                    fields.update(
                        school=None, department=None, classroom=None,
                        level=level, topic=topic, image=image,
                        video=q.get('video') or None,
                    )

                    if existing:
                        for k, v in fields.items():
                            setattr(existing, k, v)
                        existing.save()
                        existing.answers.all().delete()
                        question = existing
                        updated += 1
                    else:
                        question = self.Question.objects.create(**fields)
                        created += 1

                    self._make_answers(question, q.get('answers', []))

            if dry_run:
                transaction.set_rollback(True)

        verb = 'Would import' if dry_run else 'Imported'
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb}: {created} created, {updated} updated, {skipped} skipped"
            + (f", {img_warn} image-path warning(s)" if img_warn else '')
            + (' (dry run — rolled back)' if dry_run else '')))

    # ── lazy model handles (kept off import time for testability) ──────────────
    @property
    def Question(self):
        from maths.models import Question
        return Question

    # ── resolvers ──────────────────────────────────────────────────────────────
    def _resolve_level(self, level_number, year_name):
        if level_number is None:
            return None
        if level_number in self._level_cache:
            return self._level_cache[level_number]
        from classroom.models import Level
        # Prefer the global level; fall back to any with that number (legacy
        # prod has school-scoped levels sharing a number — schema drift).
        lvl = (Level.objects.filter(level_number=level_number, school__isnull=True).first()
               or Level.objects.filter(level_number=level_number).first())
        if lvl is None:
            lvl = Level.objects.create(
                level_number=level_number, school=None,
                display_name=year_name or f'Year {level_number}',
            )
            self.stdout.write(f"  Created global Level {level_number} ({lvl.display_name})")
        self._level_cache[level_number] = lvl
        return lvl

    def _resolve_topic(self, title, subtitle):
        title = (title or '').strip()
        subtitle = (subtitle or '').strip()
        if not title or title == '(no topic)':
            return None
        title_topic = self._get_or_create_topic(title, parent=None)
        # No sub-title given: mirror the topic name as its own sub-topic so every
        # question lands at the title › sub-title level.
        if not subtitle:
            subtitle = title
        return self._get_or_create_topic(subtitle, parent=title_topic)

    def _get_or_create_topic(self, name, parent):
        from classroom.models import Topic
        key = (name, parent.id if parent else None)
        if key in self._topic_cache:
            return self._topic_cache[key]
        # Match on (name, parent) so a mirrored sub-topic (same name as its
        # parent) is its own row. unique_together is (subject, slug), so derive a
        # free slug — the obvious one is taken by the parent in the mirror case.
        topic = Topic.objects.filter(
            subject=self.subject, name=name, parent=parent,
        ).first()
        if topic is None:
            base = slugify(name) or 'topic'
            slug, n = base, 1
            while Topic.objects.filter(subject=self.subject, slug=slug).exists():
                n += 1
                slug = f'{base}-{n}'
            topic = Topic.objects.create(
                subject=self.subject, name=name, slug=slug, parent=parent,
            )
            self.stdout.write(
                f"  Created topic '{name}'"
                + (f" under '{parent.name}'" if parent else ' (top-level)'))
        self._topic_cache[key] = topic
        return topic

    def _make_answers(self, question, answers):
        from maths.models import Answer
        Answer.objects.bulk_create([
            Answer(
                question=question,
                answer_text=a.get('answer_text') or '',
                is_correct=bool(a.get('is_correct')),
                order=a.get('order') or 0,
                answer_image=a.get('answer_image') or None,
            )
            for a in answers
        ])
