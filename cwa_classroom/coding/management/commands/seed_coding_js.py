"""
Management command: seed_coding_js
==================================
Seeds the JavaScript CodingExercise bank from the split JSON files in
``upload_splits_js/`` — the JavaScript port of the Python coding exercises.

Unlike the original ``seed_coding`` command (which only handles write_code
fields), this command also seeds quiz-style exercises: ``question_type``,
``correct_short_answer``, ``required_code_patterns`` and the related
``CodingAnswer`` rows for multiple_choice / true_false exercises.

The JavaScript language and most of its topics already exist in the DB
(Variables, If Conditions, Loops, Functions, Arrays, DOM Basics, Objects).
The one topic that has no direct Python twin — **Strings** (ported from the
Python "String Manipulation" topic) — is created on demand here.

Usage:
    python manage.py seed_coding_js              # create / update JS exercises
    python manage.py seed_coding_js --dry-run    # report only, write nothing
    python manage.py seed_coding_js --reset      # delete existing JS exercises first
"""
from __future__ import annotations

import glob as _glob
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from coding.models import (
    CodingAnswer,
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    TopicLevel,
)

_HERE = os.path.dirname(__file__)
_SPLITS_DIR = os.path.join(_HERE, 'upload_splits_js')

# Topics that may need creating because they have no Python original.
# (slug -> (display name, order)). Existing JS topics are left untouched.
_ENSURE_TOPICS = {
    'strings': ('Strings', 8),
}


def _load_json(path: str) -> dict:
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


class Command(BaseCommand):
    help = 'Seed the JavaScript CodingExercise bank from upload_splits_js/.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete existing JavaScript coding exercises before seeding.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        reset = options['reset']

        try:
            js = CodingLanguage.objects.get(slug=CodingLanguage.JAVASCRIPT)
        except CodingLanguage.DoesNotExist:
            raise CommandError(
                "JavaScript CodingLanguage (slug='javascript') not found. "
                "Seed languages first (migration 0003_seed_coding_languages)."
            )

        files = sorted(_glob.glob(os.path.join(_SPLITS_DIR, '*.json')))
        if not files:
            raise CommandError(f'No JSON split files found in {_SPLITS_DIR}')

        # Wrap the whole run in a transaction so a dry-run rolls back cleanly
        # and a real run is all-or-nothing.
        try:
            with transaction.atomic():
                self._run(js, files, reset, dry)
                if dry:
                    raise _Rollback()
        except _Rollback:
            self.stdout.write(self.style.WARNING('Dry run — rolled back, nothing written.'))

    # ------------------------------------------------------------------
    def _run(self, js, files, reset, dry):
        # Ensure on-demand topics (e.g. Strings) exist.
        for slug, (name, order) in _ENSURE_TOPICS.items():
            topic, created = CodingTopic.objects.get_or_create(
                language=js, slug=slug,
                defaults={'name': name, 'order': order, 'is_active': True},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  Created topic: {js.slug}/{slug}'))

        # Cache JS topics by slug.
        topic_map = {t.slug: t for t in CodingTopic.objects.filter(language=js)}

        if reset:
            qs = CodingExercise.objects.filter(topic_level__topic__language=js)
            n = qs.count()
            self.stdout.write(self.style.WARNING(
                f'Deleting {n} existing JavaScript exercises…'
            ))
            qs.delete()

        ex_created = ex_updated = ans_created = 0
        ans_total = 0

        for fpath in files:
            data = _load_json(fpath)
            if data.get('subject') != 'coding' or data.get('language') != 'javascript':
                self.stdout.write(self.style.WARNING(
                    f'  Skipping {os.path.basename(fpath)} (not a coding/javascript file)'
                ))
                continue

            topic_slug = data.get('topic', '')
            level = data.get('level', CodingExercise.BEGINNER)
            topic = topic_map.get(topic_slug)
            if not topic:
                self.stdout.write(self.style.ERROR(
                    f'  Topic not found: javascript/{topic_slug} '
                    f'({os.path.basename(fpath)}) — skipping file'
                ))
                continue

            topic_level, _ = TopicLevel.get_or_create_for(topic, level)

            for ex in data.get('exercises', []):
                qt = ex.get('question_type', CodingExercise.WRITE_CODE)
                defaults = {
                    'description':            ex.get('instructions', ''),
                    'starter_code':           ex.get('starter_code', ''),
                    'expected_output':        ex.get('expected_output', ''),
                    'hints':                  ex.get('hints', ''),
                    'required_code_patterns': ex.get('required_code_patterns') or None,
                    'correct_short_answer':   ex.get('correct_short_answer'),
                    'question_type':          qt,
                    'order':                  ex.get('display_order', 0),
                    'uses_browser_sandbox':   ex.get('uses_browser_sandbox', False),
                    'is_active':              True,
                }
                obj, created = CodingExercise.objects.update_or_create(
                    topic_level=topic_level,
                    title=ex['title'],
                    defaults=defaults,
                )
                ex_created += int(created)
                ex_updated += int(not created)

                # Rebuild answer rows for quiz-style exercises.
                answers = ex.get('answers') or []
                obj.answers.all().delete()
                for idx, a in enumerate(answers):
                    CodingAnswer.objects.create(
                        exercise=obj,
                        answer_text=a['text'],
                        is_correct=bool(a.get('is_correct', False)),
                        order=idx,
                    )
                    ans_created += 1
                ans_total += len(answers)

        self.stdout.write(
            f'  Exercises created: {ex_created}  updated: {ex_updated}'
        )
        self.stdout.write(f'  Answer rows written: {ans_created}')
        self.stdout.write(self.style.SUCCESS('JavaScript coding seed complete.'))


class _Rollback(Exception):
    """Internal sentinel used to roll back a --dry-run transaction."""
