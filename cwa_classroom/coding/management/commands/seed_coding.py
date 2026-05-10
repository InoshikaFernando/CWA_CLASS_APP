"""
Management command: seed_coding
================================
Creates / updates CodingExercise, CodingProblem, and ProblemTestCase records
from the split JSON files in upload_splits/ and upload_splits/challenges/.

Languages and Topics must already exist in the DB (created via admin or migration).
This command does NOT create languages or topics — it only upserts exercises and problems.

Usage:
    python manage.py seed_coding            # create / update from split files
    python manage.py seed_coding --reset    # wipe all coding data first, then seed
"""
from __future__ import annotations

import json
import os
import glob as _glob

from django.core.management.base import BaseCommand

from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    TopicLevel,
    ProblemTestCase,
)

_HERE = os.path.dirname(__file__)
_SPLITS_DIR = os.path.join(_HERE, 'upload_splits')
_CHALLENGES_DIR = os.path.join(_SPLITS_DIR, 'challenges')


def _load_json(path: str) -> dict:
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


class Command(BaseCommand):
    help = (
        'Seed CodingExercise and CodingProblem records from split JSON files '
        'in upload_splits/ and upload_splits/challenges/.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete ALL coding exercises and problems before seeding.',
        )

    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write(self.style.WARNING('Deleting all coding exercises and problems…'))
            ProblemTestCase.objects.all().delete()
            CodingProblem.objects.all().delete()
            CodingExercise.objects.all().delete()
            TopicLevel.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Deleted.'))

        # Build lookup caches from DB
        lang_map: dict[str, CodingLanguage] = {
            lang.slug: lang for lang in CodingLanguage.objects.all()
        }
        # topic keyed by (language_slug, slug) AND (language_slug, name_lower) for flexibility
        topic_map: dict[tuple[str, str], CodingTopic] = {}
        for t in CodingTopic.objects.select_related('language').all():
            topic_map[(t.language.slug, t.slug)] = t
            topic_map[(t.language.slug, t.name.lower())] = t

        # ── Exercises ─────────────────────────────────────────────────────────
        ex_created = ex_updated = 0
        exercise_files = sorted(_glob.glob(os.path.join(_SPLITS_DIR, '*.json')))

        for fpath in exercise_files:
            data = _load_json(fpath)
            if data.get('subject') != 'coding':
                continue

            lang_slug  = data.get('language', '')
            topic_slug = data.get('topic', '')
            level      = data.get('level', CodingExercise.BEGINNER)

            topic = topic_map.get((lang_slug, topic_slug)) or topic_map.get((lang_slug, topic_slug.lower()))
            if not topic:
                self.stdout.write(
                    self.style.WARNING(
                        f'  Topic not found in DB: {lang_slug}/{topic_slug} '
                        f'({os.path.basename(fpath)}) — skipping'
                    )
                )
                continue

            topic_level, _ = TopicLevel.get_or_create_for(topic, level)

            for ex in data.get('exercises', []):
                _, created = CodingExercise.objects.update_or_create(
                    topic_level=topic_level,
                    title=ex['title'],
                    defaults={
                        'description':          ex.get('instructions', ''),
                        'starter_code':         ex.get('starter_code', ''),
                        'expected_output':      ex.get('expected_output', ''),
                        'hints':                ex.get('hints', ''),
                        'order':                ex.get('display_order', 0),
                        'uses_browser_sandbox': ex.get('uses_browser_sandbox', False),
                        'is_active':            True,
                    },
                )
                if created:
                    ex_created += 1
                else:
                    ex_updated += 1

        self.stdout.write(f'  Exercises created: {ex_created}  updated: {ex_updated}')

        # ── Problems ──────────────────────────────────────────────────────────
        prob_created = prob_updated = tc_created = 0
        problem_files = sorted(_glob.glob(os.path.join(_CHALLENGES_DIR, '*.json')))

        for fpath in problem_files:
            data = _load_json(fpath)
            lang_slug = data.get('language', '')
            language = lang_map.get(lang_slug)
            if not language:
                self.stdout.write(
                    self.style.WARNING(
                        f'  Language not found in DB: {lang_slug} '
                        f'({os.path.basename(fpath)}) — skipping'
                    )
                )
                continue

            for prob_data in data.get('problems', []):
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

                test_cases_data = prob_data.get('test_cases', [])
                if test_cases_data:
                    problem.test_cases.all().delete()
                    for order, tc in enumerate(test_cases_data, start=1):
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
