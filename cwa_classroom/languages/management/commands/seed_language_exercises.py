"""
Management command: seed_language_exercises

Seeds letter-writing and phonics-MCQ exercises for English, Sinhala, and Tamil.
Safe to run multiple times — uses get_or_create throughout.

Usage:
    python manage.py seed_language_exercises
    python manage.py seed_language_exercises --lang en      # English only
    python manage.py seed_language_exercises --lang si      # Sinhala only
    python manage.py seed_language_exercises --lang ta      # Tamil only
    python manage.py seed_language_exercises --clear        # wipe exercises first
"""

import random
from django.core.management.base import BaseCommand
from languages.models import (
    Language, LanguageTopic, LanguageTopicLevel,
    LanguageExercise, LanguageAnswer,
)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED = {
    'en': {
        'name': 'English',
        'script_type': 'latin',
        'topics': [
            {
                'name': 'Animals',
                'order': 0,
                'level': 'beginner',
                'letter_writing': [],
                'phonics_mcq': [],
                'spelling_mcq': [
                    # (correct_word, [wrong1, wrong2, wrong3])
                    ('CAT',  ['KAT',  'CAD',  'KAD']),
                    ('DOG',  ['DOK',  'DUG',  'BOG']),
                    ('HEN',  ['HAN',  'HIN',  'HEM']),
                    ('COW',  ['COV',  'KOW',  'COQ']),
                    ('PIG',  ['BIG',  'PIK',  'PEG']),
                    ('RAT',  ['BAT',  'RAD',  'LAT']),
                ],
                'spelling_type': [
                    # (word, clue/prompt shown to student)
                    ('ANT',  'A tiny insect that lives in colonies'),
                    ('COD',  'A popular white saltwater fish'),
                    ('YAK',  'A large long-haired ox found in Asia'),
                    ('GNU',  'A large African antelope, also called wildebeest'),
                ],
                'crossword': {
                    'prompt': 'Animals Crossword',
                    'points': 10,
                    'puzzle_data': {
                        'width': 5,
                        'height': 5,
                        'words': [
                            {
                                'index': 0, 'number': 1, 'direction': 'down',
                                'row': 0, 'col': 2, 'answer': 'ANT',
                                'clue': 'A tiny insect (3)',
                            },
                            {
                                'index': 1, 'number': 2, 'direction': 'across',
                                'row': 2, 'col': 0, 'answer': 'CAT',
                                'clue': 'A small domestic pet (3)',
                            },
                            {
                                'index': 2, 'number': 2, 'direction': 'down',
                                'row': 2, 'col': 0, 'answer': 'COD',
                                'clue': 'A type of fish (3)',
                            },
                            {
                                'index': 3, 'number': 3, 'direction': 'across',
                                'row': 4, 'col': 0, 'answer': 'DOG',
                                'clue': "Man's best friend (3)",
                            },
                        ],
                    },
                },
            },
            {
                'name': 'Grammar Basics',
                'order': 3,
                'level': 'intermediate',
                'letter_writing': [],
                'phonics_mcq': [],
                'grammar_fill_blank': [
                    # (sentence_with_blank, correct_answer, [wrong1, wrong2, wrong3], explanation, blank_position)
                    (
                        'The dog ___ loudly at night.',
                        'barks',
                        ['bark', 'barked', 'barking'],
                        'With a singular subject (the dog), use the third-person singular: "barks".',
                        2,
                    ),
                    (
                        'She ___ to school every day.',
                        'walks',
                        ['walk', 'walked', 'walking'],
                        '"She" is a singular subject, so the verb needs the -s ending: "walks".',
                        1,
                    ),
                    (
                        'They ___ football on Saturdays.',
                        'play',
                        ['plays', 'played', 'playing'],
                        'With a plural subject (they), use the base form without -s: "play".',
                        1,
                    ),
                    (
                        'The cat is ___ on the sofa.',
                        'sitting',
                        ['sit', 'sits', 'sat'],
                        'The present progressive (is + verb-ing) describes an ongoing action.',
                        3,
                    ),
                    (
                        'I ___ my homework yesterday.',
                        'finished',
                        ['finish', 'finishes', 'finishing'],
                        '"Yesterday" signals past tense — use the past simple form.',
                        1,
                    ),
                    (
                        'There ___ three apples on the table.',
                        'are',
                        ['is', 'was', 'were'],
                        '"Three apples" is plural, so the present-tense verb is "are".',
                        1,
                    ),
                ],
                'sentence_order': [
                    # (correct_sentence, word_order_list)
                    (
                        'The cat sat on the mat.',
                        ['The', 'cat', 'sat', 'on', 'the', 'mat.'],
                    ),
                    (
                        'She likes to read books.',
                        ['She', 'likes', 'to', 'read', 'books.'],
                    ),
                    (
                        'We went to the park yesterday.',
                        ['We', 'went', 'to', 'the', 'park', 'yesterday.'],
                    ),
                    (
                        'The children are playing outside.',
                        ['The', 'children', 'are', 'playing', 'outside.'],
                    ),
                ],
            },
            {
                'name': 'Vowels',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('AEIOU') + list('aeiou'),
                'phonics_mcq': [
                    # (correct, [wrong1, wrong2, wrong3])
                    ('A', ['B', 'C', 'D']),
                    ('E', ['A', 'F', 'G']),
                    ('I', ['J', 'K', 'L']),
                    ('O', ['M', 'N', 'P']),
                    ('U', ['Q', 'R', 'S']),
                ],
            },
            {
                'name': 'Consonants',
                'order': 2,
                'level': 'beginner',
                'letter_writing': list('BCDFGHJKLMNPQRSTVWXYZ'),
                'phonics_mcq': [
                    ('B', ['D', 'P', 'Q']),
                    ('C', ['G', 'K', 'S']),
                    ('D', ['B', 'P', 'T']),
                    ('F', ['V', 'P', 'S']),
                    ('G', ['J', 'C', 'Q']),
                    ('H', ['M', 'N', 'K']),
                    ('L', ['R', 'I', 'J']),
                    ('M', ['N', 'H', 'W']),
                    ('N', ['M', 'H', 'R']),
                    ('R', ['L', 'N', 'W']),
                    ('S', ['C', 'Z', 'X']),
                    ('T', ['D', 'P', 'F']),
                ],
            },
            {
                'name': 'Consonants',
                'order': 2,
                'level': 'intermediate',
                'letter_writing': list('bcdfghjklmnpqrstvwxyz'),
                'phonics_mcq': [
                    ('b', ['d', 'p', 'q']),
                    ('d', ['b', 'p', 'q']),
                    ('p', ['b', 'd', 'q']),
                    ('q', ['p', 'b', 'd']),
                    ('m', ['n', 'h', 'w']),
                    ('n', ['m', 'r', 'u']),
                    ('v', ['u', 'w', 'f']),
                    ('w', ['v', 'm', 'n']),
                ],
            },
        ],
    },

    'si': {
        'name': 'Sinhala',
        'script_type': 'sinhala',
        'topics': [
            {
                'name': 'සතුන් (Animals)',
                'order': 0,
                'level': 'beginner',
                'letter_writing': [],
                'phonics_mcq': [],
                'spelling_mcq': [
                    # (correct_word, [wrong1, wrong2, wrong3])
                    ('ඇතා',    ['ඇදා',    'ඇටා',    'ඇනා']),     # elephant
                    ('නරියා',  ['නරිය',   'නරීයා',  'නරිඅ']),    # fox
                    ('ගොනා',   ['ගෝනා',   'ගොණා',   'ගොලා']),    # bull
                    ('ලේනා',   ['ලෙනා',   'ළේනා',   'ලෙනු']),    # squirrel
                    ('කුකුළා', ['කුකළා',  'කූකුළා', 'කුකල']),    # rooster
                    ('කකුළා',  ['කකළා',   'කකුල',   'කකුළු']),   # spider
                ],
                'spelling_type': [
                    ('ගවයා',   'A large farm animal that gives milk (cow)'),      # cow
                    ('ඌරා',    'A farm animal known for its pink colour (pig)'),   # pig
                    ('සිංහයා', 'The king of the jungle (lion)'),                  # lion
                    ('වලසා',   'A large furry animal that loves honey (bear)'),    # bear
                ],
                'crossword': None,
            },
            {
                'name': 'ස්වර (Vowels)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': ['අ', 'ආ', 'ඉ', 'ඊ', 'උ', 'ඌ', 'එ', 'ඒ', 'ඔ', 'ඕ'],
                'phonics_mcq': [
                    ('අ', ['ආ', 'ඉ', 'උ']),
                    ('ආ', ['අ', 'ඊ', 'ඌ']),
                    ('ඉ', ['ඊ', 'අ', 'එ']),
                    ('ඊ', ['ඉ', 'උ', 'ඒ']),
                    ('උ', ['ඌ', 'අ', 'ඉ']),
                    ('ඌ', ['උ', 'ආ', 'ඒ']),
                    ('එ', ['ඒ', 'ඔ', 'අ']),
                    ('ඒ', ['එ', 'ඕ', 'ඉ']),
                    ('ඔ', ['ඕ', 'එ', 'උ']),
                    ('ඕ', ['ඔ', 'ඒ', 'ඌ']),
                ],
            },
            {
                'name': 'ව්‍යංජන (Consonants)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['ක', 'ග', 'ච', 'ජ', 'ට', 'ත', 'ද', 'න', 'ප', 'බ', 'ම', 'ය', 'ර', 'ල', 'ව', 'ස'],
                'phonics_mcq': [
                    ('ක', ['ග', 'ට', 'ත']),
                    ('ග', ['ක', 'ජ', 'ද']),
                    ('ච', ['ජ', 'ක', 'ස']),
                    ('ජ', ['ච', 'ග', 'ස']),
                    ('ට', ['ත', 'ක', 'ද']),
                    ('ත', ['ද', 'ට', 'ප']),
                    ('ද', ['ත', 'ග', 'බ']),
                    ('න', ['ම', 'ල', 'ර']),
                    ('ප', ['බ', 'ත', 'ක']),
                    ('බ', ['ප', 'ද', 'ග']),
                    ('ම', ['න', 'ල', 'ව']),
                    ('ය', ['ල', 'ව', 'ර']),
                    ('ර', ['ල', 'ය', 'ව']),
                    ('ල', ['ර', 'ය', 'ව']),
                    ('ව', ['ම', 'ල', 'ය']),
                    ('ස', ['ශ', 'ච', 'ජ']),
                ],
            },
            {
                'name': 'ව්‍යංජන (Consonants)',
                'order': 2,
                'level': 'intermediate',
                'letter_writing': ['ශ', 'ෂ', 'හ', 'ළ', 'ෆ', 'ඟ', 'ඤ', 'ඦ', 'ණ', 'ඳ', 'ඬ'],
                'phonics_mcq': [
                    ('ශ', ['ෂ', 'ස', 'හ']),
                    ('ෂ', ['ශ', 'ස', 'හ']),
                    ('හ', ['ශ', 'ළ', 'ෆ']),
                    ('ළ', ['ල', 'ර', 'ය']),
                    ('ෆ', ['ප', 'බ', 'හ']),
                ],
            },
        ],
    },

    'ta': {
        'name': 'Tamil',
        'script_type': 'tamil',
        'topics': [
            {
                'name': 'விலங்குகள் (Animals)',
                'order': 0,
                'level': 'beginner',
                'letter_writing': [],
                'phonics_mcq': [],
                'spelling_mcq': [
                    # (correct_word, [wrong1, wrong2, wrong3])
                    ('நாய்',    ['நாஇ',    'நாயி',   'னாய்']),    # dog
                    ('பூனை',   ['பூனி',   'பூணை',   'பூனே']),    # cat
                    ('மாடு',   ['மாட',    'மாது',   'மாடூ']),    # cow
                    ('குதிரை', ['குதிரி', 'குதிரே', 'குதிர']),   # horse
                    ('யானை',   ['யாணை',  'யானி',   'யனை']),     # elephant
                    ('புலி',   ['பூலி',   'புளி',   'புலே']),    # tiger
                ],
                'spelling_type': [
                    ('நரி',     'A clever wild animal that looks like a dog (fox)'),    # fox
                    ('கரடி',   'A large furry animal that loves honey (bear)'),         # bear
                    ('சிங்கம்', 'The king of the jungle (lion)'),                      # lion
                    ('முயல்',   'A small animal with long ears that hops (rabbit)'),    # rabbit
                ],
                'crossword': None,
            },
            {
                'name': 'உயிரெழுத்துகள் (Vowels)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': ['அ', 'ஆ', 'இ', 'ஈ', 'உ', 'ஊ', 'எ', 'ஏ', 'ஐ', 'ஒ', 'ஓ', 'ஔ'],
                'phonics_mcq': [
                    ('அ', ['ஆ', 'இ', 'உ']),
                    ('ஆ', ['அ', 'ஈ', 'ஊ']),
                    ('இ', ['ஈ', 'அ', 'எ']),
                    ('ஈ', ['இ', 'உ', 'ஏ']),
                    ('உ', ['ஊ', 'அ', 'இ']),
                    ('ஊ', ['உ', 'ஆ', 'ஏ']),
                    ('எ', ['ஏ', 'ஒ', 'அ']),
                    ('ஏ', ['எ', 'ஓ', 'இ']),
                    ('ஐ', ['ஔ', 'ஏ', 'ஈ']),
                    ('ஒ', ['ஓ', 'எ', 'உ']),
                    ('ஓ', ['ஒ', 'ஏ', 'ஊ']),
                    ('ஔ', ['ஐ', 'ஓ', 'ஆ']),
                ],
            },
            {
                'name': 'மெய்யெழுத்துகள் (Consonants)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['க', 'ங', 'ச', 'ஞ', 'ட', 'ண', 'த', 'ந', 'ப', 'ம'],
                'phonics_mcq': [
                    ('க', ['ச', 'ட', 'த']),
                    ('ங', ['ஞ', 'ண', 'ந']),
                    ('ச', ['க', 'ட', 'த']),
                    ('ஞ', ['ங', 'ண', 'ந']),
                    ('ட', ['த', 'க', 'ச']),
                    ('ண', ['ந', 'ங', 'ஞ']),
                    ('த', ['ட', 'ச', 'ப']),
                    ('ந', ['ண', 'ம', 'ஞ']),
                    ('ப', ['ம', 'த', 'க']),
                    ('ம', ['ந', 'ப', 'ண']),
                ],
            },
            {
                'name': 'மெய்யெழுத்துகள் (Consonants)',
                'order': 2,
                'level': 'intermediate',
                'letter_writing': ['ய', 'ர', 'ல', 'வ', 'ழ', 'ள', 'ற', 'ன'],
                'phonics_mcq': [
                    ('ய', ['ர', 'ல', 'வ']),
                    ('ர', ['ல', 'ற', 'ய']),
                    ('ல', ['ள', 'ழ', 'ர']),
                    ('வ', ['ய', 'ர', 'ம']),
                    ('ழ', ['ள', 'ல', 'ண']),
                    ('ள', ['ழ', 'ல', 'ண']),
                    ('ற', ['ர', 'ல', 'ன']),
                    ('ன', ['ந', 'ண', 'ற']),
                ],
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Seed letter-writing and phonics-MCQ exercises for English, Sinhala, and Tamil'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lang', type=str, default=None,
            help='Seed only this language code (en / si / ta). Omit for all.',
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
