"""
Management command: seed_language_exercises

Seeds letter-writing, phonics-MCQ, spelling, crossword, grammar and
sentence-ordering exercises for every language in ``languages.seed_data.SEED``
(currently English, Sinhala, Tamil, French, Mandarin, Japanese and Korean).
Safe to run multiple times — uses get_or_create throughout.

The seed data itself lives in ``languages/seed_data.py`` so that this command
and the ``0014_seed_fr_zh_ja_ko`` data migration read the SAME source. They
used to hold separate copies, which is how French/Mandarin/Japanese/Korean
reached dev as command-only data that no deploy ever ran — deploy.sh runs
``migrate``, not management commands. Add a language to seed_data.py and give
it a migration; never to one caller alone.

Usage:
    python manage.py seed_language_exercises
    python manage.py seed_language_exercises --lang en      # English only
    python manage.py seed_language_exercises --lang ko      # Korean only
    python manage.py seed_language_exercises --clear        # wipe exercises first
"""

import random
from django.core.management.base import BaseCommand
from languages.models import (
    Language, LanguageTopic, LanguageTopicLevel,
    LanguageExercise, LanguageAnswer,
)

# Re-exported: languages/tests/ and other callers import SEED from this module.
from languages.seed_data import SEED  # noqa: F401


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Seed language exercises for every language in languages/seed_data.py'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lang', type=str, default=None,
            help='Seed only this language code (see SEED in languages/seed_data.py). Omit for all.',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete all existing language exercises before seeding.',
        )

    def handle(self, *args, **options):
        lang_filter = options['lang']
        do_clear    = options['clear']

        langs_to_seed = {lang_filter: SEED[lang_filter]} if lang_filter else SEED
        if lang_filter and lang_filter not in SEED:
            self.stderr.write(f'Unknown lang code: {lang_filter}. Choose from: {list(SEED.keys())}')
            return

        if do_clear:
            count = LanguageExercise.objects.filter(
                topic_level__topic__language__code__in=langs_to_seed.keys()
            ).count()
            LanguageExercise.objects.filter(
                topic_level__topic__language__code__in=langs_to_seed.keys()
            ).delete()
            self.stdout.write(self.style.WARNING(f'Cleared {count} existing exercises.'))

        total_lw = total_ph = total_sp = total_cw = total_gfb = total_so = 0

        for code, data in langs_to_seed.items():
            self.stdout.write(f'\nSeeding {data["name"]} ({code})...')

            lang, _ = Language.objects.get_or_create(
                code=code,
                defaults={
                    'name': data['name'],
                    'script_type': data['script_type'],
                    'is_active': True,
                    'order': list(SEED.keys()).index(code),
                },
            )

            for topic_data in data['topics']:
                level_code = topic_data['level']

                topic, _ = LanguageTopic.objects.get_or_create(
                    language=lang,
                    name=topic_data['name'],
                    defaults={'order': topic_data['order'], 'is_active': True},
                )

                level_map = {'beginner': 'beginner', 'intermediate': 'intermediate', 'advanced': 'advanced'}
                level, _ = LanguageTopicLevel.objects.get_or_create(
                    topic=topic,
                    level_choice=level_map[level_code],
                )

                # --- Letter writing ---
                for i, char in enumerate(topic_data.get('letter_writing', [])):
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.LETTER_WRITING,
                        prompt=char,
                        defaults={'points': 1, 'order': i, 'is_active': True},
                    )
                    if created:
                        total_lw += 1

                # --- Phonics MCQ ---
                for i, (correct_text, wrong_texts) in enumerate(topic_data.get('phonics_mcq', [])):
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.PHONICS_MCQ,
                        prompt=correct_text,
                        defaults={'points': 2, 'order': i, 'is_active': True},
                    )
                    if created:
                        total_ph += 1
                        answers = [(correct_text, True)] + [(w, False) for w in wrong_texts]
                        random.shuffle(answers)
                        for display_order, (text, is_correct) in enumerate(answers):
                            LanguageAnswer.objects.create(
                                exercise=ex,
                                answer_text=text,
                                is_correct=is_correct,
                                display_order=display_order,
                            )

                # --- Spelling MCQ ---
                for i, (correct_word, wrong_words) in enumerate(topic_data.get('spelling_mcq', [])):
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.SPELLING_MCQ,
                        prompt=correct_word,
                        defaults={'points': 3, 'order': i, 'is_active': True},
                    )
                    if created:
                        total_sp += 1
                        answers = [(correct_word, True)] + [(w, False) for w in wrong_words]
                        random.shuffle(answers)
                        for display_order, (text, is_correct) in enumerate(answers):
                            LanguageAnswer.objects.create(
                                exercise=ex,
                                answer_text=text,
                                is_correct=is_correct,
                                display_order=display_order,
                            )

                # --- Spelling Type ---
                for i, item in enumerate(topic_data.get('spelling_type', [])):
                    word, clue = item if isinstance(item, tuple) else (item, item)
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.SPELLING_TYPE,
                        prompt=word,
                        defaults={'points': 3, 'order': i, 'is_active': True},
                    )
                    if created:
                        total_sp += 1

                # --- Crossword ---
                cw_data = topic_data.get('crossword')
                if cw_data:
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.CROSSWORD,
                        prompt=cw_data['prompt'],
                        defaults={
                            'puzzle_data': cw_data['puzzle_data'],
                            'points': cw_data.get('points', 10),
                            'is_active': True,
                        },
                    )
                    if created:
                        total_cw += 1

                # --- Grammar Fill-in-the-Blank ---
                for i, item in enumerate(topic_data.get('grammar_fill_blank', [])):
                    sentence, correct, wrongs, explanation, blank_pos = item
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
                        prompt=sentence,
                        defaults={
                            'puzzle_data': {
                                'blank_position': blank_pos,
                                'grammar_explanation': explanation,
                            },
                            'points': 5,
                            'order': i,
                            'is_active': True,
                        },
                    )
                    if created:
                        total_gfb += 1
                        answers = [(correct, True)] + [(w, False) for w in wrongs]
                        random.shuffle(answers)
                        for display_order, (text, is_correct) in enumerate(answers):
                            LanguageAnswer.objects.create(
                                exercise=ex,
                                answer_text=text,
                                is_correct=is_correct,
                                display_order=display_order,
                            )

                # --- Sentence Order ---
                for i, item in enumerate(topic_data.get('sentence_order', [])):
                    sentence, word_order = item
                    ex, created = LanguageExercise.objects.get_or_create(
                        topic_level=level,
                        exercise_type=LanguageExercise.SENTENCE_ORDER,
                        prompt=sentence,
                        defaults={
                            'puzzle_data': {'word_order': word_order},
                            'points': 5,
                            'order': i,
                            'is_active': True,
                        },
                    )
                    if created:
                        total_so += 1

            self.stdout.write(self.style.SUCCESS(
                f'  {data["name"]}: done'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Created {total_lw} letter-writing + {total_ph} phonics-MCQ'
            f' + {total_sp} spelling + {total_cw} crossword'
            f' + {total_gfb} grammar fill-blank + {total_so} sentence-order exercises.'
        ))
