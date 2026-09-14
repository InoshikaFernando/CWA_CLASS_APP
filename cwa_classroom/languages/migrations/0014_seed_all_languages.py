# -*- coding: utf-8 -*-
"""
Data migration: reconcile every language in ``languages/seed_data.py``.

WHAT WAS WRONG
--------------
Seed data only reaches a server through a migration. ``scripts/deploy.sh`` runs
``migrate``, ``collectstatic`` and a restart — never a management command. So
anything added to ``seed_language_exercises`` alone is code that nothing ever
executes on dev, test or production.

That happened twice over:

  * French, Mandarin, Japanese and Korean (2026-09) were added to the command
    with no migration at all. Migrations 0012/0013 widened ``script_type`` to
    accept cjk/kana/hangul, so the schema was ready and the ``Language`` rows
    were never created. The hub kept showing English/Sinhala/Tamil, which read
    as "the deploy didn't run migrations" — it did, there was nothing to run.

  * English, Sinhala and Tamil were seeded by 0010 back in June, and everything
    added to them since went the same way: an English 'Vowels (intermediate)'
    topic, a Sinhala 'Consonants (advanced)' topic, 22 further English
    consonant prompts, 22 further Sinhala prompts, and seven entire Tamil
    topics — short vowels, long vowels, diphthongs, hard/soft/medium
    consonants and the special character — none of which any server has ever
    had.

WHY IT SEEDS EVERYTHING
-----------------------
Seeding only the four new codes would fix the visible half and leave the quiet
half in place. Every write here is get_or_create, so running over all of SEED
costs one pass and reconciles whatever a given database happens to be missing:
a fresh build gets the lot, a server that already has 0010's content gets only
the top-up, and a database where someone ran the management command by hand to
unblock themselves gets nothing. It is safe to replay for the same reason.

Answers are written in a fixed deterministic order, matching 0010 — the
frontend shuffles display order at render time. This deliberately differs from
the management command, which shuffles at write time; a migration takes the
reproducible one.

Ordering note: this runs after 0011, which switches the prompt columns to
utf8mb4_bin. That matters. Under MySQL's default accent- and case-insensitive
collation, get_or_create treats 'e' == 'é' == 'è' and 'A' == 'a', which is how
French lost 3 of 4 'e' variants and Sinhala lost its lowercase vowels the first
time around. Seeding before 0011 would silently repeat it.
"""
from django.db import migrations

from languages.seed_data import SEED


def seed_all_languages(apps, schema_editor):
    Language           = apps.get_model('languages', 'Language')
    LanguageTopic      = apps.get_model('languages', 'LanguageTopic')
    LanguageTopicLevel = apps.get_model('languages', 'LanguageTopicLevel')
    LanguageExercise   = apps.get_model('languages', 'LanguageExercise')
    LanguageAnswer     = apps.get_model('languages', 'LanguageAnswer')

    def _answers(exercise, correct, wrongs):
        for display_order, (text, is_correct) in enumerate(
            [(correct, True)] + [(wrong, False) for wrong in wrongs]
        ):
            LanguageAnswer.objects.create(
                exercise=exercise, answer_text=text,
                is_correct=is_correct, display_order=display_order,
            )

    for order_idx, (code, data) in enumerate(SEED.items()):
        lang, _ = Language.objects.get_or_create(
            code=code,
            defaults={
                'name': data['name'],
                'script_type': data['script_type'],
                'is_active': True,
                'order': order_idx,
            },
        )

        for topic_data in data['topics']:
            # Topics key on (language, name): a name appearing at more than one
            # level — French 'Alphabet', Japanese 'ひらがな', Korean '자음' —
            # is ONE topic carrying several LanguageTopicLevel rows.
            topic, _ = LanguageTopic.objects.get_or_create(
                language=lang,
                name=topic_data['name'],
                defaults={'order': topic_data['order'], 'is_active': True},
            )

            level, _ = LanguageTopicLevel.objects.get_or_create(
                topic=topic,
                level_choice=topic_data['level'],
            )

            # Letter writing
            for i, char in enumerate(topic_data.get('letter_writing', [])):
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='letter_writing',
                    prompt=char,
                    defaults={'points': 1, 'order': i, 'is_active': True},
                )

            # Phonics MCQ
            for i, (correct_text, wrong_texts) in enumerate(topic_data.get('phonics_mcq', [])):
                ex, created = LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='phonics_mcq',
                    prompt=correct_text,
                    defaults={'points': 2, 'order': i, 'is_active': True},
                )
                if created:
                    _answers(ex, correct_text, wrong_texts)

            # Spelling MCQ
            for i, (correct_word, wrong_words) in enumerate(topic_data.get('spelling_mcq', [])):
                ex, created = LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='spelling_mcq',
                    prompt=correct_word,
                    defaults={'points': 3, 'order': i, 'is_active': True},
                )
                if created:
                    _answers(ex, correct_word, wrong_words)

            # Spelling — type the answer
            for i, (word, _clue) in enumerate(topic_data.get('spelling_type', [])):
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='spelling_type',
                    prompt=word,
                    defaults={'points': 3, 'order': i, 'is_active': True},
                )

            # Crossword
            crossword = topic_data.get('crossword')
            if crossword:
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='crossword',
                    prompt=crossword['prompt'],
                    defaults={
                        'puzzle_data': crossword['puzzle_data'],
                        'points': crossword.get('points', 10),
                        'is_active': True,
                    },
                )

            # Grammar fill-in-the-blank
            for i, (sentence, correct, wrongs, explanation, blank_pos) in enumerate(
                topic_data.get('grammar_fill_blank', [])
            ):
                ex, created = LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='grammar_fill_blank',
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
                    _answers(ex, correct, wrongs)

            # Sentence ordering
            for i, (sentence, word_order) in enumerate(topic_data.get('sentence_order', [])):
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='sentence_order',
                    prompt=sentence,
                    defaults={
                        'puzzle_data': {'word_order': word_order},
                        'points': 5,
                        'order': i,
                        'is_active': True,
                    },
                )


# Reverse is a no-op, matching 0010. Cascading a delete off Language would take
# LanguageStudentAnswer / LanguageProgress with it, so a rollback to 0013 would
# destroy real student work to undo what is only reference data. Reference rows
# left behind after a rollback are harmless; lost answers are not.


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0013_alter_language_script_type'),
    ]

    operations = [
        migrations.RunPython(seed_all_languages, migrations.RunPython.noop),
    ]
