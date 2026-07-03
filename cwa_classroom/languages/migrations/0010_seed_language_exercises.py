"""
Data migration: seed language exercises for English, Sinhala, and Tamil.

Safe to re-run (uses get_or_create throughout). Answers are stored in a fixed
deterministic order — the frontend shuffles display order at render time.
"""
from django.db import migrations


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
                    ('CAT',  ['KAT',  'CAD',  'KAD']),
                    ('DOG',  ['DOK',  'DUG',  'BOG']),
                    ('HEN',  ['HAN',  'HIN',  'HEM']),
                    ('COW',  ['COV',  'KOW',  'COQ']),
                    ('PIG',  ['BIG',  'PIK',  'PEG']),
                    ('RAT',  ['BAT',  'RAD',  'LAT']),
                ],
                'spelling_type': [
                    ('ANT', 'A tiny insect that lives in colonies'),
                    ('COD', 'A popular white saltwater fish'),
                    ('YAK', 'A large long-haired ox found in Asia'),
                    ('GNU', 'A large African antelope, also called wildebeest'),
                ],
                'crossword': {
                    'prompt': 'Animals Crossword',
                    'points': 10,
                    'puzzle_data': {
                        'width': 5,
                        'height': 5,
                        'words': [
                            {'index': 0, 'number': 1, 'direction': 'down',
                             'row': 0, 'col': 2, 'answer': 'ANT', 'clue': 'A tiny insect (3)'},
                            {'index': 1, 'number': 2, 'direction': 'across',
                             'row': 2, 'col': 0, 'answer': 'CAT', 'clue': 'A small domestic pet (3)'},
                            {'index': 2, 'number': 2, 'direction': 'down',
                             'row': 2, 'col': 0, 'answer': 'COD', 'clue': 'A type of fish (3)'},
                            {'index': 3, 'number': 3, 'direction': 'across',
                             'row': 4, 'col': 0, 'answer': 'DOG', 'clue': "Man's best friend (3)"},
                        ],
                    },
                },
            },
            {
                'name': 'Vowels',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('AEIOU') + list('aeiou'),
                'phonics_mcq': [
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
            {
                'name': 'Grammar Basics',
                'order': 3,
                'level': 'intermediate',
                'letter_writing': [],
                'phonics_mcq': [],
                'grammar_fill_blank': [
                    (
                        'The dog ___ loudly at night.',
                        'barks', ['bark', 'barked', 'barking'],
                        'With a singular subject (the dog), use the third-person singular: "barks".',
                        2,
                    ),
                    (
                        'She ___ to school every day.',
                        'walks', ['walk', 'walked', 'walking'],
                        '"She" is a singular subject, so the verb needs the -s ending: "walks".',
                        1,
                    ),
                    (
                        'They ___ football on Saturdays.',
                        'play', ['plays', 'played', 'playing'],
                        'With a plural subject (they), use the base form without -s: "play".',
                        1,
                    ),
                    (
                        'The cat is ___ on the sofa.',
                        'sitting', ['sit', 'sits', 'sat'],
                        'The present progressive (is + verb-ing) describes an ongoing action.',
                        3,
                    ),
                    (
                        'I ___ my homework yesterday.',
                        'finished', ['finish', 'finishes', 'finishing'],
                        '"Yesterday" signals past tense — use the past simple form.',
                        1,
                    ),
                    (
                        'There ___ three apples on the table.',
                        'are', ['is', 'was', 'were'],
                        '"Three apples" is plural, so the present-tense verb is "are".',
                        1,
                    ),
                ],
                'sentence_order': [
                    ('The cat sat on the mat.',     ['The', 'cat', 'sat', 'on', 'the', 'mat.']),
                    ('She likes to read books.',     ['She', 'likes', 'to', 'read', 'books.']),
                    ('We went to the park yesterday.', ['We', 'went', 'to', 'the', 'park', 'yesterday.']),
                    ('The children are playing outside.', ['The', 'children', 'are', 'playing', 'outside.']),
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
                    ('ඇතා',    ['ඇදා',    'ඇටා',    'ඇනා']),
                    ('නරියා',  ['නරිය',   'නරීයා',  'නරිඅ']),
                    ('ගොනා',   ['ගෝනා',   'ගොණා',   'ගොලා']),
                    ('ලේනා',   ['ලෙනා',   'ළේනා',   'ලෙනු']),
                    ('කුකුළා', ['කුකළා',  'කූකුළා', 'කුකල']),
                    ('කකුළා',  ['කකළා',   'කකුල',   'කකුළු']),
                ],
                'spelling_type': [
                    ('ගවයා',   'A large farm animal that gives milk (cow)'),
                    ('ඌරා',    'A farm animal known for its pink colour (pig)'),
                    ('සිංහයා', 'The king of the jungle (lion)'),
                    ('වලසා',   'A large furry animal that loves honey (bear)'),
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
                    ('நாய்',    ['நாஇ',    'நாயி',   'னாய்']),
                    ('பூனை',   ['பூனி',   'பூணை',   'பூனே']),
                    ('மாடு',   ['மாட',    'மாது',   'மாடூ']),
                    ('குதிரை', ['குதிரி', 'குதிரே', 'குதிர']),
                    ('யானை',   ['யாணை',  'யானி',   'யனை']),
                    ('புலி',   ['பூலி',   'புளி',   'புலே']),
                ],
                'spelling_type': [
                    ('நரி',     'A clever wild animal that looks like a dog (fox)'),
                    ('கரடி',   'A large furry animal that loves honey (bear)'),
                    ('சிங்கம்', 'The king of the jungle (lion)'),
                    ('முயல்',   'A small animal with long ears that hops (rabbit)'),
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
# Migration function
# ---------------------------------------------------------------------------

def seed_exercises(apps, schema_editor):
    Language         = apps.get_model('languages', 'Language')
    LanguageTopic    = apps.get_model('languages', 'LanguageTopic')
    LanguageTopicLevel = apps.get_model('languages', 'LanguageTopicLevel')
    LanguageExercise = apps.get_model('languages', 'LanguageExercise')
    LanguageAnswer   = apps.get_model('languages', 'LanguageAnswer')

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
                    for d_order, (text, is_correct) in enumerate(
                        [(correct_text, True)] + [(w, False) for w in wrong_texts]
                    ):
                        LanguageAnswer.objects.create(
                            exercise=ex, answer_text=text,
                            is_correct=is_correct, display_order=d_order,
                        )

            # Spelling MCQ
            for i, (correct_word, wrong_words) in enumerate(topic_data.get('spelling_mcq', [])):
                ex, created = LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='spelling_mcq',
                    prompt=correct_word,
                    defaults={'points': 3, 'order': i, 'is_active': True},
                )
                if created:
                    for d_order, (text, is_correct) in enumerate(
                        [(correct_word, True)] + [(w, False) for w in wrong_words]
                    ):
                        LanguageAnswer.objects.create(
                            exercise=ex, answer_text=text,
                            is_correct=is_correct, display_order=d_order,
                        )

            # Spelling Type
            for i, (word, clue) in enumerate(topic_data.get('spelling_type', [])):
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='spelling_type',
                    prompt=word,
                    defaults={'points': 3, 'order': i, 'is_active': True},
                )

            # Crossword
            cw_data = topic_data.get('crossword')
            if cw_data:
                LanguageExercise.objects.get_or_create(
                    topic_level=level,
                    exercise_type='crossword',
                    prompt=cw_data['prompt'],
                    defaults={
                        'puzzle_data': cw_data['puzzle_data'],
                        'points': cw_data.get('points', 10),
                        'is_active': True,
                    },
                )

            # Grammar Fill-in-the-Blank
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
                    for d_order, (text, is_correct) in enumerate(
                        [(correct, True)] + [(w, False) for w in wrongs]
                    ):
                        LanguageAnswer.objects.create(
                            exercise=ex, answer_text=text,
                            is_correct=is_correct, display_order=d_order,
                        )

            # Sentence Order
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


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0009_seed_languages_subject_app'),
    ]

    operations = [
        migrations.RunPython(seed_exercises, migrations.RunPython.noop),
    ]
