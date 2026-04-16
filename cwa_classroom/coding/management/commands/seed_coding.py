"""
Management command: seed_coding
================================
Creates / updates CodingLanguage, CodingTopic, CodingExercise,
CodingProblem, and ProblemTestCase records from seed_coding.json.

seed_coding.json is the single source of truth for all coding seed data.
This command reads it and upserts every record.

Usage:
    python manage.py seed_coding            # create / update missing records
    python manage.py seed_coding --reset    # wipe all coding data first, then seed
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    TopicLevel,
    ProblemTestCase,
)

_HERE = os.path.dirname(__file__)
_SEED_FILE = os.path.join(_HERE, 'seed_coding.json')


def _load_seed() -> dict:
    with open(_SEED_FILE, encoding='utf-8') as fh:
        return json.load(fh)


class Command(BaseCommand):
    help = (
        'Seed CodingLanguage, CodingTopic, CodingExercise, and CodingProblem '
        'records from seed_coding.json.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete ALL coding data before seeding.',
        )

    def handle(self, *args, **options):
        seed = _load_seed()

        if options['reset']:
            self.stdout.write(self.style.WARNING('Deleting all coding data…'))
            ProblemTestCase.objects.all().delete()
            CodingProblem.objects.all().delete()
            CodingExercise.objects.all().delete()
            TopicLevel.objects.all().delete()
            CodingTopic.objects.all().delete()
            CodingLanguage.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Deleted.'))

        # ── Languages ────────────────────────────────────────────────────────
        lang_objects: dict[str, CodingLanguage] = {}
        for lang_data in seed['languages']:
            lang, created = CodingLanguage.objects.update_or_create(
                slug=lang_data['slug'],
                defaults={k: v for k, v in lang_data.items() if k != 'slug'},
            )
            lang_objects[lang.slug] = lang
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} language: {lang.name}')

        # ── Topics ───────────────────────────────────────────────────────────
        topic_objects: dict[tuple[str, str], CodingTopic] = {}
        for t in seed['topics']:
            lang_slug = t['language_slug']
            language = lang_objects.get(lang_slug)
            if not language:
                self.stdout.write(
                    self.style.WARNING(f'  Unknown language slug "{lang_slug}" — skipping topic {t["name"]}')
                )
                continue
            topic, created = CodingTopic.objects.update_or_create(
                language=language,
                slug=slugify(t['name']),
                defaults={
                    'name': t['name'],
                    'description': t.get('description', ''),
                    'order': t.get('order', 0),
                    'is_active': True,
                },
            )
            topic_objects[(lang_slug, t['name'])] = topic
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'    {status} topic: {language.name} / {topic.name}')

        # ── Exercises ─────────────────────────────────────────────────────────
        # exercises is a list of groups: {subject, language, topic, level, exercises[]}
        # Each exercise uses "instructions" (-> description) and "display_order" (-> order).
        ex_created = ex_updated = 0
        for group in seed['exercises']:
            lang_slug  = group['language']
            topic_name = group['topic']
            level      = group.get('level', CodingExercise.BEGINNER)
            topic = topic_objects.get((lang_slug, topic_name))
            if not topic:
                self.stdout.write(
                    self.style.WARNING(
                        f'  Topic not found: {lang_slug} / {topic_name} — skipping group'
                    )
                )
                continue
            topic_level, _ = TopicLevel.get_or_create_for(topic, level)
            for ex in group.get('exercises', []):
                _, created = CodingExercise.objects.update_or_create(
                    topic_level=topic_level,
                    title=ex['title'],
                    defaults={
                        'description':     ex.get('instructions', ''),
                        'starter_code':    ex.get('starter_code', ''),
                        'expected_output': ex.get('expected_output', ''),
                        'hints':           ex.get('hints', ''),
                        'order':           ex.get('display_order', 0),
                        'is_active':       True,
                    },
                )
                if created:
                    ex_created += 1
                else:
                    ex_updated += 1

        self.stdout.write(f'  Exercises created: {ex_created}  updated: {ex_updated}')

        # ── Problems ──────────────────────────────────────────────────────────
        prob_created = prob_updated = tc_created = 0
        for prob_data in seed.get('problems', []):
            language = lang_objects.get(prob_data['language'])
            if not language:
                continue

            problem, created = CodingProblem.objects.update_or_create(
                language=language,
                title=prob_data['title'],
                defaults={
                    'description':             prob_data.get('description', ''),
                    'starter_code':            prob_data.get('starter_code', ''),
                    'difficulty':              prob_data.get('difficulty', 1),
                    'category':                prob_data.get('category', CodingProblem.ALGORITHM),
                    'constraints':             prob_data.get('constraints', ''),
                    'time_limit_seconds':      prob_data.get('time_limit_seconds', 5),
                    'memory_limit_mb':         prob_data.get('memory_limit_mb', 256),
                    'forbidden_code_patterns': prob_data.get('forbidden_code_patterns', []),
                    'is_active':               True,
                },
            )
            if created:
                prob_created += 1
            else:
                prob_updated += 1

            # Re-seed test cases only on fresh creation to avoid duplicates on re-run.
            # Use --reset to force a full re-seed.
            if created:
                for order, tc in enumerate(prob_data.get('test_cases', []), start=1):
                    ProblemTestCase.objects.create(
                        problem=problem,
                        input_data=tc['input'],
                        expected_output=tc['expected'],
                        is_visible=tc.get('visible', False),
                        is_boundary_test=tc.get('boundary', False),
                        description=tc.get('description', ''),
                        display_order=order,
                    )
                    tc_created += 1

        self.stdout.write(f'  Problems created: {prob_created}  updated: {prob_updated}')
        self.stdout.write(f'  Test cases created: {tc_created}')
        self.stdout.write(self.style.SUCCESS('Coding seed complete.'))
