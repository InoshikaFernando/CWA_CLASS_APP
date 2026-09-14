"""
Seed data for the Languages subject.

The single source of truth for the built-in languages, their topics and their
exercises. Two callers share it, and they MUST keep sharing it:

  * ``languages.management.commands.seed_language_exercises`` — the manual
    re-seed / top-up command.
  * ``languages.migrations.0014_seed_all_languages`` — the data migration that
    puts this content into every deployed database.

That split is the whole point of this module. French, Mandarin, Japanese and
Korean were originally added to the management command ONLY, with no data
migration. ``scripts/deploy.sh`` runs ``migrate``, never a management command,
so the four languages shipped to dev as code that nothing ever executed: the
schema gained the new ``script_type`` choices (migrations 0012/0013) while the
``Language`` rows themselves were never created. Anything seeded here has to be
reachable from a migration, or it does not exist on a server.

It was not only the four new languages. ``0010_seed_language_exercises`` froze
its own copy of English/Sinhala/Tamil in June, and everything added to those
three afterwards went the same way — an English 'Vowels (intermediate)' topic,
a Sinhala 'Consonants (advanced)' topic, 22 more English consonant prompts, 22
more Sinhala prompts, and SEVEN entire Tamil topics (short vowels, long vowels,
diphthongs, hard/soft/medium consonants, the special character) that no server
has ever had. 0014 reconciles every language in this file, not just the new
ones, which is why it is worth running over all of SEED rather than a subset.

0010 itself is deliberately left alone — rewriting an applied migration changes
what a fresh-database replay does. 0010 is history; this module is the live
copy, and 0014 is what puts it on a server.
"""

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
                'letter_writing': list('AEIOU'),
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
                # Split from the beginner level (not merged into one list) because
                # MySQL's default case-insensitive collation makes get_or_create's
                # prompt lookup treat 'A' and 'a' as the same row, silently
                # dropping the lowercase half if both share a topic level — see
                # the Consonants beginner/intermediate split below for the same
                # pattern.
                'name': 'Vowels',
                'order': 1,
                'level': 'intermediate',
                'letter_writing': list('aeiou'),
                'phonics_mcq': [
                    ('a', ['b', 'c', 'd']),
                    ('e', ['a', 'f', 'g']),
                    ('i', ['j', 'k', 'l']),
                    ('o', ['m', 'n', 'p']),
                    ('u', ['q', 'r', 's']),
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
                    ('J', ['G', 'I', 'Y']),
                    ('K', ['C', 'H', 'X']),
                    ('P', ['B', 'D', 'Q']),
                    ('Q', ['O', 'G', 'P']),
                    ('V', ['F', 'U', 'W']),
                    ('W', ['V', 'M', 'N']),
                    ('X', ['Z', 'S', 'K']),
                    ('Y', ['V', 'I', 'J']),
                    ('Z', ['S', 'X', 'N']),
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
                    ('c', ['g', 'k', 's']),
                    ('f', ['v', 'p', 's']),
                    ('g', ['j', 'c', 'q']),
                    ('h', ['m', 'n', 'k']),
                    ('j', ['g', 'i', 'y']),
                    ('k', ['c', 'h', 'x']),
                    ('l', ['r', 'i', 'j']),
                    ('r', ['l', 'n', 'w']),
                    ('s', ['c', 'z', 'x']),
                    ('t', ['d', 'p', 'f']),
                    ('x', ['z', 's', 'k']),
                    ('y', ['v', 'i', 'j']),
                    ('z', ['s', 'x', 'n']),
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
                # Full independent-vowel set per easysinhalatyping.com/sinhala/letters,
                # including the vocalic r/rr/l/ll (rare/archaic in modern Sinhala,
                # kept for completeness at the user's request).
                'name': 'ස්වර (Vowels)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': [
                    'අ', 'ආ', 'ඇ', 'ඈ', 'ඉ', 'ඊ', 'උ', 'ඌ',
                    'ඍ', 'ඎ', 'ඏ', 'ඐ', 'එ', 'ඒ', 'ඓ', 'ඔ', 'ඕ', 'ඖ',
                ],
                'phonics_mcq': [
                    ('අ', ['ආ', 'ඉ', 'උ']),
                    ('ආ', ['අ', 'ඊ', 'ඌ']),
                    ('ඇ', ['ආ', 'ඈ', 'අ']),
                    ('ඈ', ['ඇ', 'ආ', 'ඊ']),
                    ('ඉ', ['ඊ', 'අ', 'එ']),
                    ('ඊ', ['ඉ', 'උ', 'ඒ']),
                    ('උ', ['ඌ', 'අ', 'ඉ']),
                    ('ඌ', ['උ', 'ආ', 'ඒ']),
                    ('ඍ', ['ඎ', 'ඉ', 'උ']),
                    ('ඎ', ['ඍ', 'ඊ', 'ඌ']),
                    ('ඏ', ['ඐ', 'උ', 'අ']),
                    ('ඐ', ['ඏ', 'ඌ', 'ආ']),
                    ('එ', ['ඒ', 'ඔ', 'අ']),
                    ('ඒ', ['එ', 'ඕ', 'ඉ']),
                    ('ඓ', ['එ', 'ඒ', 'ඔ']),
                    ('ඔ', ['ඕ', 'එ', 'උ']),
                    ('ඕ', ['ඔ', 'ඒ', 'ඌ']),
                    ('ඖ', ['ඔ', 'ඕ', 'ඌ']),
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
                    ('ඟ', ['ග', 'ද', 'බ']),
                    ('ඤ', ['ය', 'ම', 'ව']),
                    ('ඦ', ['ජ', 'ච', 'ස']),
                    ('ණ', ['න', 'ම', 'ල']),
                    ('ඳ', ['ද', 'බ', 'ග']),
                    ('ඬ', ['ට', 'ද', 'ණ']),
                ],
            },
            {
                # Remaining consonants to reach the full 41-letter set per
                # easysinhalatyping.com/sinhala/letters — mostly aspirated/
                # retroflex letters used in Sanskrit-derived vocabulary,
                # taught after the core intermediate set.
                'name': 'ව්‍යංජන (Consonants)',
                'order': 2,
                'level': 'advanced',
                'letter_writing': [
                    'ඛ', 'ඝ', 'ඞ', 'ඡ', 'ඣ', 'ඥ', 'ඨ', 'ඩ', 'ඪ', 'ථ', 'ධ', 'ඵ', 'භ', 'ඹ',
                ],
                'phonics_mcq': [
                    ('ඛ', ['ක', 'ඝ', 'ග']),
                    ('ඝ', ['ග', 'ඛ', 'ඟ']),
                    ('ඞ', ['ණ', 'ඟ', 'න']),
                    ('ඡ', ['ච', 'ජ', 'ඣ']),
                    ('ඣ', ['ජ', 'ඡ', 'ඦ']),
                    ('ඥ', ['ඤ', 'ජ', 'ග']),
                    ('ඨ', ['ට', 'ඩ', 'ථ']),
                    ('ඩ', ['ට', 'ඨ', 'ද']),
                    ('ඪ', ['ඩ', 'ඨ', 'ධ']),
                    ('ථ', ['ත', 'ට', 'ධ']),
                    ('ධ', ['ද', 'ථ', 'ඩ']),
                    ('ඵ', ['ප', 'බ', 'භ']),
                    ('භ', ['බ', 'ඵ', 'ම']),
                    ('ඹ', ['ම', 'බ', 'භ']),
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
                # Kuril (short) vowels -- 5 of the 12 uyir ezhuthukkal.
                'name': 'குறில் எழுத்துகள் (Short Vowels)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': ['அ', 'இ', 'உ', 'எ', 'ஒ'],
                'phonics_mcq': [
                    ('அ', ['ஆ', 'இ', 'உ']),
                    ('இ', ['ஈ', 'அ', 'எ']),
                    ('உ', ['ஊ', 'அ', 'இ']),
                    ('எ', ['ஏ', 'ஒ', 'அ']),
                    ('ஒ', ['ஓ', 'எ', 'உ']),
                ],
            },
            {
                # Nedil (long) vowels -- 5 of the 12 uyir ezhuthukkal.
                # 'beginner' (not gated behind Short Vowels): the unlock
                # mechanism only tracks progression *within* one topic
                # (beginner -> intermediate of the same topic name), so a
                # differently-named topic sitting at 'intermediate' has no
                # sibling 'beginner' level of its own to ever unlock it --
                # it would stay permanently locked. There's no pedagogical
                # need to gate the vowel/consonant sub-categories behind
                # each other anyway (the original ungated "Vowels" topic
                # didn't), so every category here is 'beginner'.
                'name': 'நெடில் எழுத்துகள் (Long Vowels)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': ['ஆ', 'ஈ', 'ஊ', 'ஏ', 'ஓ'],
                'phonics_mcq': [
                    ('ஆ', ['அ', 'ஈ', 'ஊ']),
                    ('ஈ', ['இ', 'உ', 'ஏ']),
                    ('ஊ', ['உ', 'ஆ', 'ஏ']),
                    ('ஏ', ['எ', 'ஓ', 'இ']),
                    ('ஓ', ['ஒ', 'ஏ', 'ஊ']),
                ],
            },
            {
                # The 2 diphthongs, completing the 12 uyir ezhuthukkal.
                # 'beginner' -- see the Long Vowels comment above.
                'name': 'ஐகார ஔகார எழுத்துகள் (Diphthongs)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': ['ஐ', 'ஔ'],
                'phonics_mcq': [
                    ('ஐ', ['ஔ', 'ஏ', 'ஈ']),
                    ('ஔ', ['ஐ', 'ஓ', 'ஆ']),
                ],
            },
            {
                # Vallinam -- hard/chest consonants, 6 of the 18 mei ezhuthukkal.
                'name': 'வல்லினம் (Hard Consonants)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['க', 'ச', 'ட', 'த', 'ப', 'ற'],
                'phonics_mcq': [
                    ('க', ['ச', 'ட', 'த']),
                    ('ச', ['க', 'ட', 'த']),
                    ('ட', ['த', 'க', 'ச']),
                    ('த', ['ட', 'ச', 'ப']),
                    ('ப', ['ம', 'த', 'க']),
                    ('ற', ['ர', 'ல', 'ன']),
                ],
            },
            {
                # Mellinam -- soft/nasal consonants, 6 of the 18 mei ezhuthukkal.
                'name': 'மெல்லினம் (Soft Consonants)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['ங', 'ஞ', 'ண', 'ந', 'ம', 'ன'],
                'phonics_mcq': [
                    ('ங', ['ஞ', 'ண', 'ந']),
                    ('ஞ', ['ங', 'ண', 'ந']),
                    ('ண', ['ந', 'ங', 'ஞ']),
                    ('ந', ['ண', 'ம', 'ஞ']),
                    ('ம', ['ந', 'ப', 'ண']),
                    ('ன', ['ந', 'ண', 'ற']),
                ],
            },
            {
                # Idaiyinam -- medium consonants, the last 6 of the 18 mei
                # ezhuthukkal. 'beginner' -- see the Long Vowels comment
                # above.
                'name': 'இடையினம் (Medium Consonants)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['ய', 'ர', 'ல', 'வ', 'ழ', 'ள'],
                'phonics_mcq': [
                    ('ய', ['ர', 'ல', 'வ']),
                    ('ர', ['ல', 'ற', 'ய']),
                    ('ல', ['ள', 'ழ', 'ர']),
                    ('வ', ['ய', 'ர', 'ம']),
                    ('ழ', ['ள', 'ல', 'ண']),
                    ('ள', ['ழ', 'ல', 'ண']),
                ],
            },
            {
                # Aytham -- the 1 special character, standing outside the
                # vowel/consonant split.
                'name': 'ஆய்த எழுத்து (Special Character)',
                'order': 3,
                'level': 'beginner',
                'letter_writing': ['ஃ'],
                'phonics_mcq': [
                    ('ஃ', ['க', 'ச', 'ட']),
                ],
            },
        ],
    },

    'fr': {
        'name': 'French',
        'script_type': 'latin',
        'topics': [
            {
                # Same 26-letter Latin alphabet as English -- reuses the
                # already hand-authored A-Z / a-z stroke data (identical
                # letterforms), no new stroke authoring needed here.
                'name': 'Alphabet',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                'phonics_mcq': [
                    ('A', ['B', 'C', 'D']), ('E', ['A', 'F', 'G']), ('I', ['J', 'K', 'L']),
                    ('O', ['M', 'N', 'P']), ('U', ['Q', 'R', 'S']),
                    ('B', ['D', 'P', 'Q']), ('C', ['G', 'K', 'S']), ('D', ['B', 'P', 'T']),
                    ('F', ['V', 'P', 'S']), ('G', ['J', 'C', 'Q']), ('H', ['M', 'N', 'K']),
                    ('J', ['G', 'I', 'Y']), ('K', ['C', 'H', 'X']), ('L', ['R', 'I', 'J']),
                    ('M', ['N', 'H', 'W']), ('N', ['M', 'H', 'R']), ('P', ['B', 'D', 'Q']),
                    ('Q', ['O', 'G', 'P']), ('R', ['L', 'N', 'W']), ('S', ['C', 'Z', 'X']),
                    ('T', ['D', 'P', 'F']), ('V', ['F', 'U', 'W']), ('W', ['V', 'M', 'N']),
                    ('X', ['Z', 'S', 'K']), ('Y', ['V', 'I', 'J']), ('Z', ['S', 'X', 'N']),
                ],
            },
            {
                'name': 'Alphabet',
                'order': 1,
                'level': 'intermediate',
                'letter_writing': list('abcdefghijklmnopqrstuvwxyz'),
                'phonics_mcq': [
                    ('a', ['b', 'c', 'd']), ('e', ['a', 'f', 'g']), ('i', ['j', 'k', 'l']),
                    ('o', ['m', 'n', 'p']), ('u', ['q', 'r', 's']),
                    ('b', ['d', 'p', 'q']), ('c', ['g', 'k', 's']), ('d', ['b', 'p', 't']),
                    ('f', ['v', 'p', 's']), ('g', ['j', 'c', 'q']), ('h', ['m', 'n', 'k']),
                    ('j', ['g', 'i', 'y']), ('k', ['c', 'h', 'x']), ('l', ['r', 'i', 'j']),
                    ('m', ['n', 'h', 'w']), ('n', ['m', 'h', 'r']), ('p', ['b', 'd', 'q']),
                    ('q', ['o', 'g', 'p']), ('r', ['l', 'n', 'w']), ('s', ['c', 'z', 'x']),
                    ('t', ['d', 'p', 'f']), ('v', ['f', 'u', 'w']), ('w', ['v', 'm', 'n']),
                    ('x', ['z', 's', 'k']), ('y', ['v', 'i', 'j']), ('z', ['s', 'x', 'n']),
                ],
            },
            {
                # Accented letters -- 'beginner' (not gated behind
                # Alphabet): different topic name, so it has no sibling
                # 'beginner' level of its own to be unlocked by -- see the
                # Tamil category topics above for the same lesson.
                'name': 'Accents',
                'order': 2,
                'level': 'beginner',
                'letter_writing': ['à', 'â', 'ç', 'é', 'è', 'ê', 'ë', 'î', 'ï', 'ô', 'ù', 'û', 'ü'],
                'phonics_mcq': [
                    ('à', ['â', 'a', 'e']),
                    ('â', ['à', 'a', 'e']),
                    ('ç', ['c', 's', 'e']),
                    ('é', ['è', 'ê', 'e']),
                    ('è', ['é', 'ê', 'e']),
                    ('ê', ['é', 'è', 'e']),
                    ('ë', ['é', 'è', 'e']),
                    ('î', ['ï', 'i', 'ê']),
                    ('ï', ['î', 'i', 'ë']),
                    ('ô', ['o', 'â', 'ê']),
                    ('ù', ['û', 'u', 'ü']),
                    ('û', ['ù', 'u', 'ü']),
                    ('ü', ['ù', 'û', 'u']),
                ],
            },
        ],
    },

    'zh': {
        'name': 'Mandarin',
        'script_type': 'cjk',
        'topics': [
            {
                # Numbers 1-10 -- conventionally the first characters taught,
                # and the simplest strokewise (一/二/三 are 1-3 strokes).
                'name': '数字 (Numbers)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('一二三四五六七八九十'),
                'phonics_mcq': [
                    ('一', ['二', '三', '十']), ('二', ['一', '三', '八']),
                    ('三', ['二', '四', '一']), ('四', ['五', '六', '十']),
                    ('五', ['四', '六', '八']), ('六', ['五', '八', '九']),
                    ('七', ['十', '九', '八']), ('八', ['六', '九', '七']),
                    ('九', ['七', '八', '十']), ('十', ['一', '七', '四']),
                ],
            },
            {
                # Kangxi radicals — 1 stroke (6 of the 214).
                'name': '部首 · 一画 (Radicals — 1 stroke)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': list('一丨丶丿乙亅'),
                'phonics_mcq': [
                    ('一', ['丨', '丶', '丿']),
                    ('丨', ['丶', '丿', '乙']),
                    ('丶', ['丿', '乙', '亅']),
                    ('丿', ['乙', '亅', '一']),
                    ('乙', ['亅', '一', '丨']),
                    ('亅', ['一', '丨', '丶']),
                ],
            },
            {
                # Kangxi radicals — 2 strokes (23 of the 214).
                'name': '部首 · 二画 (Radicals — 2 strokes)',
                'order': 3,
                'level': 'beginner',
                'letter_writing': list('二亠人儿入八冂冖冫几凵刀力勹匕匚匸十卜卩厂厶又'),
                'phonics_mcq': [
                    ('二', ['亠', '人', '儿']),
                    ('亠', ['人', '儿', '入']),
                    ('人', ['儿', '入', '八']),
                    ('儿', ['入', '八', '冂']),
                    ('入', ['八', '冂', '冖']),
                    ('八', ['冂', '冖', '冫']),
                    ('冂', ['冖', '冫', '几']),
                    ('冖', ['冫', '几', '凵']),
                    ('冫', ['几', '凵', '刀']),
                    ('几', ['凵', '刀', '力']),
                    ('凵', ['刀', '力', '勹']),
                    ('刀', ['力', '勹', '匕']),
                    ('力', ['勹', '匕', '匚']),
                    ('勹', ['匕', '匚', '匸']),
                    ('匕', ['匚', '匸', '十']),
                    ('匚', ['匸', '十', '卜']),
                    ('匸', ['十', '卜', '卩']),
                    ('十', ['卜', '卩', '厂']),
                    ('卜', ['卩', '厂', '厶']),
                    ('卩', ['厂', '厶', '又']),
                    ('厂', ['厶', '又', '二']),
                    ('厶', ['又', '二', '亠']),
                    ('又', ['二', '亠', '人']),
                ],
            },
            {
                # Kangxi radicals — 3 strokes (31 of the 214).
                'name': '部首 · 三画 (Radicals — 3 strokes)',
                'order': 4,
                'level': 'beginner',
                'letter_writing': list('口囗土士夂夊夕大女子宀寸小尢尸屮山巛工己巾干幺广廴廾弋弓彐彡彳'),
                'phonics_mcq': [
                    ('口', ['囗', '土', '士']),
                    ('囗', ['土', '士', '夂']),
                    ('土', ['士', '夂', '夊']),
                    ('士', ['夂', '夊', '夕']),
                    ('夂', ['夊', '夕', '大']),
                    ('夊', ['夕', '大', '女']),
                    ('夕', ['大', '女', '子']),
                    ('大', ['女', '子', '宀']),
                    ('女', ['子', '宀', '寸']),
                    ('子', ['宀', '寸', '小']),
                    ('宀', ['寸', '小', '尢']),
                    ('寸', ['小', '尢', '尸']),
                    ('小', ['尢', '尸', '屮']),
                    ('尢', ['尸', '屮', '山']),
                    ('尸', ['屮', '山', '巛']),
                    ('屮', ['山', '巛', '工']),
                    ('山', ['巛', '工', '己']),
                    ('巛', ['工', '己', '巾']),
                    ('工', ['己', '巾', '干']),
                    ('己', ['巾', '干', '幺']),
                    ('巾', ['干', '幺', '广']),
                    ('干', ['幺', '广', '廴']),
                    ('幺', ['广', '廴', '廾']),
                    ('广', ['廴', '廾', '弋']),
                    ('廴', ['廾', '弋', '弓']),
                    ('廾', ['弋', '弓', '彐']),
                    ('弋', ['弓', '彐', '彡']),
                    ('弓', ['彐', '彡', '彳']),
                    ('彐', ['彡', '彳', '口']),
                    ('彡', ['彳', '口', '囗']),
                    ('彳', ['口', '囗', '土']),
                ],
            },
            {
                # Kangxi radicals — 4 strokes (34 of the 214).
                'name': '部首 · 四画 (Radicals — 4 strokes)',
                'order': 5,
                'level': 'beginner',
                'letter_writing': list('心戈户手支攴文斗斤方无日曰月木欠止歹殳毋比毛氏气水火爪父爻爿片牙牛犬'),
                'phonics_mcq': [
                    ('心', ['戈', '户', '手']),
                    ('戈', ['户', '手', '支']),
                    ('户', ['手', '支', '攴']),
                    ('手', ['支', '攴', '文']),
                    ('支', ['攴', '文', '斗']),
                    ('攴', ['文', '斗', '斤']),
                    ('文', ['斗', '斤', '方']),
                    ('斗', ['斤', '方', '无']),
                    ('斤', ['方', '无', '日']),
                    ('方', ['无', '日', '曰']),
                    ('无', ['日', '曰', '月']),
                    ('日', ['曰', '月', '木']),
                    ('曰', ['月', '木', '欠']),
                    ('月', ['木', '欠', '止']),
                    ('木', ['欠', '止', '歹']),
                    ('欠', ['止', '歹', '殳']),
                    ('止', ['歹', '殳', '毋']),
                    ('歹', ['殳', '毋', '比']),
                    ('殳', ['毋', '比', '毛']),
                    ('毋', ['比', '毛', '氏']),
                    ('比', ['毛', '氏', '气']),
                    ('毛', ['氏', '气', '水']),
                    ('氏', ['气', '水', '火']),
                    ('气', ['水', '火', '爪']),
                    ('水', ['火', '爪', '父']),
                    ('火', ['爪', '父', '爻']),
                    ('爪', ['父', '爻', '爿']),
                    ('父', ['爻', '爿', '片']),
                    ('爻', ['爿', '片', '牙']),
                    ('爿', ['片', '牙', '牛']),
                    ('片', ['牙', '牛', '犬']),
                    ('牙', ['牛', '犬', '心']),
                    ('牛', ['犬', '心', '戈']),
                    ('犬', ['心', '戈', '户']),
                ],
            },
            {
                # Kangxi radicals — 5 strokes (23 of the 214).
                'name': '部首 · 五画 (Radicals — 5 strokes)',
                'order': 6,
                'level': 'beginner',
                'letter_writing': list('玄玉瓜瓦甘生用田疋疒癶白皮皿目矛矢石示禸禾穴立'),
                'phonics_mcq': [
                    ('玄', ['玉', '瓜', '瓦']),
                    ('玉', ['瓜', '瓦', '甘']),
                    ('瓜', ['瓦', '甘', '生']),
                    ('瓦', ['甘', '生', '用']),
                    ('甘', ['生', '用', '田']),
                    ('生', ['用', '田', '疋']),
                    ('用', ['田', '疋', '疒']),
                    ('田', ['疋', '疒', '癶']),
                    ('疋', ['疒', '癶', '白']),
                    ('疒', ['癶', '白', '皮']),
                    ('癶', ['白', '皮', '皿']),
                    ('白', ['皮', '皿', '目']),
                    ('皮', ['皿', '目', '矛']),
                    ('皿', ['目', '矛', '矢']),
                    ('目', ['矛', '矢', '石']),
                    ('矛', ['矢', '石', '示']),
                    ('矢', ['石', '示', '禸']),
                    ('石', ['示', '禸', '禾']),
                    ('示', ['禸', '禾', '穴']),
                    ('禸', ['禾', '穴', '立']),
                    ('禾', ['穴', '立', '玄']),
                    ('穴', ['立', '玄', '玉']),
                    ('立', ['玄', '玉', '瓜']),
                ],
            },
            {
                # Kangxi radicals — 6 strokes (29 of the 214).
                'name': '部首 · 六画 (Radicals — 6 strokes)',
                'order': 7,
                'level': 'beginner',
                'letter_writing': list('竹米糸缶网羊羽老而耒耳聿肉臣自至臼舌舛舟艮色艸虍虫血行衣襾'),
                'phonics_mcq': [
                    ('竹', ['米', '糸', '缶']),
                    ('米', ['糸', '缶', '网']),
                    ('糸', ['缶', '网', '羊']),
                    ('缶', ['网', '羊', '羽']),
                    ('网', ['羊', '羽', '老']),
                    ('羊', ['羽', '老', '而']),
                    ('羽', ['老', '而', '耒']),
                    ('老', ['而', '耒', '耳']),
                    ('而', ['耒', '耳', '聿']),
                    ('耒', ['耳', '聿', '肉']),
                    ('耳', ['聿', '肉', '臣']),
                    ('聿', ['肉', '臣', '自']),
                    ('肉', ['臣', '自', '至']),
                    ('臣', ['自', '至', '臼']),
                    ('自', ['至', '臼', '舌']),
                    ('至', ['臼', '舌', '舛']),
                    ('臼', ['舌', '舛', '舟']),
                    ('舌', ['舛', '舟', '艮']),
                    ('舛', ['舟', '艮', '色']),
                    ('舟', ['艮', '色', '艸']),
                    ('艮', ['色', '艸', '虍']),
                    ('色', ['艸', '虍', '虫']),
                    ('艸', ['虍', '虫', '血']),
                    ('虍', ['虫', '血', '行']),
                    ('虫', ['血', '行', '衣']),
                    ('血', ['行', '衣', '襾']),
                    ('行', ['衣', '襾', '竹']),
                    ('衣', ['襾', '竹', '米']),
                    ('襾', ['竹', '米', '糸']),
                ],
            },
            {
                # Kangxi radicals — 7 strokes (20 of the 214).
                'name': '部首 · 七画 (Radicals — 7 strokes)',
                'order': 8,
                'level': 'beginner',
                'letter_writing': list('见角言谷豆豕豸贝赤走足身车辛辰辵邑酉釆里'),
                'phonics_mcq': [
                    ('见', ['角', '言', '谷']),
                    ('角', ['言', '谷', '豆']),
                    ('言', ['谷', '豆', '豕']),
                    ('谷', ['豆', '豕', '豸']),
                    ('豆', ['豕', '豸', '贝']),
                    ('豕', ['豸', '贝', '赤']),
                    ('豸', ['贝', '赤', '走']),
                    ('贝', ['赤', '走', '足']),
                    ('赤', ['走', '足', '身']),
                    ('走', ['足', '身', '车']),
                    ('足', ['身', '车', '辛']),
                    ('身', ['车', '辛', '辰']),
                    ('车', ['辛', '辰', '辵']),
                    ('辛', ['辰', '辵', '邑']),
                    ('辰', ['辵', '邑', '酉']),
                    ('辵', ['邑', '酉', '釆']),
                    ('邑', ['酉', '釆', '里']),
                    ('酉', ['釆', '里', '见']),
                    ('釆', ['里', '见', '角']),
                    ('里', ['见', '角', '言']),
                ],
            },
            {
                # Kangxi radicals — 8 strokes (9 of the 214).
                'name': '部首 · 八画 (Radicals — 8 strokes)',
                'order': 9,
                'level': 'beginner',
                'letter_writing': list('金长门阜隶隹雨青非'),
                'phonics_mcq': [
                    ('金', ['长', '门', '阜']),
                    ('长', ['门', '阜', '隶']),
                    ('门', ['阜', '隶', '隹']),
                    ('阜', ['隶', '隹', '雨']),
                    ('隶', ['隹', '雨', '青']),
                    ('隹', ['雨', '青', '非']),
                    ('雨', ['青', '非', '金']),
                    ('青', ['非', '金', '长']),
                    ('非', ['金', '长', '门']),
                ],
            },
            {
                # Kangxi radicals — 9 strokes (11 of the 214).
                'name': '部首 · 九画 (Radicals — 9 strokes)',
                'order': 10,
                'level': 'beginner',
                'letter_writing': list('面革韦韭音页风飞食首香'),
                'phonics_mcq': [
                    ('面', ['革', '韦', '韭']),
                    ('革', ['韦', '韭', '音']),
                    ('韦', ['韭', '音', '页']),
                    ('韭', ['音', '页', '风']),
                    ('音', ['页', '风', '飞']),
                    ('页', ['风', '飞', '食']),
                    ('风', ['飞', '食', '首']),
                    ('飞', ['食', '首', '香']),
                    ('食', ['首', '香', '面']),
                    ('首', ['香', '面', '革']),
                    ('香', ['面', '革', '韦']),
                ],
            },
            {
                # Kangxi radicals — 10 strokes (8 of the 214).
                'name': '部首 · 十画 (Radicals — 10 strokes)',
                'order': 11,
                'level': 'beginner',
                'letter_writing': list('马骨高髟鬥鬯鬲鬼'),
                'phonics_mcq': [
                    ('马', ['骨', '高', '髟']),
                    ('骨', ['高', '髟', '鬥']),
                    ('高', ['髟', '鬥', '鬯']),
                    ('髟', ['鬥', '鬯', '鬲']),
                    ('鬥', ['鬯', '鬲', '鬼']),
                    ('鬯', ['鬲', '鬼', '马']),
                    ('鬲', ['鬼', '马', '骨']),
                    ('鬼', ['马', '骨', '高']),
                ],
            },
            {
                # Kangxi radicals — 11 strokes (6 of the 214).
                'name': '部首 · 十一画 (Radicals — 11 strokes)',
                'order': 12,
                'level': 'beginner',
                'letter_writing': list('鱼鸟卤鹿麦麻'),
                'phonics_mcq': [
                    ('鱼', ['鸟', '卤', '鹿']),
                    ('鸟', ['卤', '鹿', '麦']),
                    ('卤', ['鹿', '麦', '麻']),
                    ('鹿', ['麦', '麻', '鱼']),
                    ('麦', ['麻', '鱼', '鸟']),
                    ('麻', ['鱼', '鸟', '卤']),
                ],
            },
            {
                # Kangxi radicals — 12 strokes (4 of the 214).
                'name': '部首 · 十二画 (Radicals — 12 strokes)',
                'order': 13,
                'level': 'beginner',
                'letter_writing': list('黄黍黑黹'),
                'phonics_mcq': [
                    ('黄', ['黍', '黑', '黹']),
                    ('黍', ['黑', '黹', '黄']),
                    ('黑', ['黹', '黄', '黍']),
                    ('黹', ['黄', '黍', '黑']),
                ],
            },
            {
                # Kangxi radicals — 13 strokes (4 of the 214).
                'name': '部首 · 十三画 (Radicals — 13 strokes)',
                'order': 14,
                'level': 'beginner',
                'letter_writing': list('黾鼎鼓鼠'),
                'phonics_mcq': [
                    ('黾', ['鼎', '鼓', '鼠']),
                    ('鼎', ['鼓', '鼠', '黾']),
                    ('鼓', ['鼠', '黾', '鼎']),
                    ('鼠', ['黾', '鼎', '鼓']),
                ],
            },
            {
                # Kangxi radicals — 14 strokes (2 of the 214).
                'name': '部首 · 十四画 (Radicals — 14 strokes)',
                'order': 15,
                'level': 'beginner',
                'letter_writing': list('鼻齐'),
                'phonics_mcq': [
                    ('鼻', ['齐']),
                    ('齐', ['鼻']),
                ],
            },
            {
                # Kangxi radicals — 15 strokes (1 of the 214, no same-group
                # peer to build an MCQ distractor from).
                'name': '部首 · 十五画 (Radicals — 15 strokes)',
                'order': 16,
                'level': 'beginner',
                'letter_writing': list('齿'),
                'phonics_mcq': [],
            },
            {
                # Kangxi radicals — 16 strokes (2 of the 214).
                'name': '部首 · 十六画 (Radicals — 16 strokes)',
                'order': 17,
                'level': 'beginner',
                'letter_writing': list('龙龟'),
                'phonics_mcq': [
                    ('龙', ['龟']),
                    ('龟', ['龙']),
                ],
            },
            {
                # Kangxi radicals — 17 strokes (1 of the 214, no same-group
                # peer to build an MCQ distractor from).
                'name': '部首 · 十七画 (Radicals — 17 strokes)',
                'order': 18,
                'level': 'beginner',
                'letter_writing': list('龠'),
                'phonics_mcq': [],
            },
            {
                # A handful of very common compound-ish words built from
                # the radicals above (好 = 女+子, etc.), plus 中 (not itself
                # one of the 214 official radicals, but too fundamental a
                # character to drop) -- 'beginner' and a separate topic from
                # the radical groups above rather than an 'intermediate'
                # level of any of them: the unlock mechanism only tracks
                # progress *within* one topic, so a differently-named topic
                # sitting at 'intermediate' has no sibling 'beginner' level
                # of its own to ever unlock it (see the Tamil/French category
                # topics above for the same lesson learned the hard way).
                'name': '常用字 (Common Words)',
                'order': 19,
                'level': 'beginner',
                'letter_writing': list('中我你他好是不上下天地'),
                'phonics_mcq': [
                    ('中', ['口', '日', '田']), ('我', ['你', '他', '是']),
                    ('你', ['我', '他', '好']), ('他', ['我', '你', '好']),
                    ('好', ['女', '你', '是']), ('是', ['不', '好', '他']),
                    ('不', ['是', '下', '上']), ('上', ['下', '不', '天']),
                    ('下', ['上', '不', '天']), ('天', ['大', '上', '地']),
                    ('地', ['天', '下', '上']),
                ],
            },
        ],
    },

    'ja': {
        'name': 'Japanese',
        'script_type': 'kana',
        'topics': [
            {
                # The 46 basic (seion) hiragana in gojuon order -- the
                # core phonetic syllabary, no dakuten/handakuten yet.
                'name': 'ひらがな (Hiragana)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん'),
                'phonics_mcq': [
                    ('あ', ['い', 'う', 'え']),
                    ('い', ['う', 'え', 'お']),
                    ('う', ['え', 'お', 'か']),
                    ('え', ['お', 'か', 'き']),
                    ('お', ['か', 'き', 'く']),
                    ('か', ['き', 'く', 'け']),
                    ('き', ['く', 'け', 'こ']),
                    ('く', ['け', 'こ', 'さ']),
                    ('け', ['こ', 'さ', 'し']),
                    ('こ', ['さ', 'し', 'す']),
                    ('さ', ['し', 'す', 'せ']),
                    ('し', ['す', 'せ', 'そ']),
                    ('す', ['せ', 'そ', 'た']),
                    ('せ', ['そ', 'た', 'ち']),
                    ('そ', ['た', 'ち', 'つ']),
                    ('た', ['ち', 'つ', 'て']),
                    ('ち', ['つ', 'て', 'と']),
                    ('つ', ['て', 'と', 'な']),
                    ('て', ['と', 'な', 'に']),
                    ('と', ['な', 'に', 'ぬ']),
                    ('な', ['に', 'ぬ', 'ね']),
                    ('に', ['ぬ', 'ね', 'の']),
                    ('ぬ', ['ね', 'の', 'は']),
                    ('ね', ['の', 'は', 'ひ']),
                    ('の', ['は', 'ひ', 'ふ']),
                    ('は', ['ひ', 'ふ', 'へ']),
                    ('ひ', ['ふ', 'へ', 'ほ']),
                    ('ふ', ['へ', 'ほ', 'ま']),
                    ('へ', ['ほ', 'ま', 'み']),
                    ('ほ', ['ま', 'み', 'む']),
                    ('ま', ['み', 'む', 'め']),
                    ('み', ['む', 'め', 'も']),
                    ('む', ['め', 'も', 'や']),
                    ('め', ['も', 'や', 'ゆ']),
                    ('も', ['や', 'ゆ', 'よ']),
                    ('や', ['ゆ', 'よ', 'ら']),
                    ('ゆ', ['よ', 'ら', 'り']),
                    ('よ', ['ら', 'り', 'る']),
                    ('ら', ['り', 'る', 'れ']),
                    ('り', ['る', 'れ', 'ろ']),
                    ('る', ['れ', 'ろ', 'わ']),
                    ('れ', ['ろ', 'わ', 'を']),
                    ('ろ', ['わ', 'を', 'ん']),
                    ('わ', ['を', 'ん', 'あ']),
                    ('を', ['ん', 'あ', 'い']),
                    ('ん', ['あ', 'い', 'う']),
                ],
            },
            {
                # Dakuten (゛-- が/ざ/だ/ば rows) and handakuten (゜-- ぱ row)
                # hiragana -- same topic NAME as above, 'intermediate' level,
                # so completing the beginner set unlocks this rather than
                # leaving it permanently locked (see the Tamil/Mandarin
                # category-topic lesson: the unlock mechanism only tracks
                # progress *within* one topic name across its own levels).
                # 'order' matches the beginner entry above, not the next
                # sequential number: LanguageTopic is keyed on (language,
                # name) via get_or_create, so 'order' only ever takes effect
                # from whichever of a topic's level-entries is seeded FIRST
                # — a later entry's differing 'order' is silently ignored.
                # Keeping it identical here (mirrors the existing French
                # 'Alphabet' beginner/intermediate pair) avoids implying it
                # does something it doesn't.
                'name': 'ひらがな (Hiragana)',
                'order': 1,
                'level': 'intermediate',
                'letter_writing': list('がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ'),
                'phonics_mcq': [
                    ('が', ['ぎ', 'ぐ', 'げ']),
                    ('ぎ', ['ぐ', 'げ', 'ご']),
                    ('ぐ', ['げ', 'ご', 'ざ']),
                    ('げ', ['ご', 'ざ', 'じ']),
                    ('ご', ['ざ', 'じ', 'ず']),
                    ('ざ', ['じ', 'ず', 'ぜ']),
                    ('じ', ['ず', 'ぜ', 'ぞ']),
                    ('ず', ['ぜ', 'ぞ', 'だ']),
                    ('ぜ', ['ぞ', 'だ', 'ぢ']),
                    ('ぞ', ['だ', 'ぢ', 'づ']),
                    ('だ', ['ぢ', 'づ', 'で']),
                    ('ぢ', ['づ', 'で', 'ど']),
                    ('づ', ['で', 'ど', 'ば']),
                    ('で', ['ど', 'ば', 'び']),
                    ('ど', ['ば', 'び', 'ぶ']),
                    ('ば', ['び', 'ぶ', 'べ']),
                    ('び', ['ぶ', 'べ', 'ぼ']),
                    ('ぶ', ['べ', 'ぼ', 'ぱ']),
                    ('べ', ['ぼ', 'ぱ', 'ぴ']),
                    ('ぼ', ['ぱ', 'ぴ', 'ぷ']),
                    ('ぱ', ['ぴ', 'ぷ', 'ぺ']),
                    ('ぴ', ['ぷ', 'ぺ', 'ぽ']),
                    ('ぷ', ['ぺ', 'ぽ', 'が']),
                    ('ぺ', ['ぽ', 'が', 'ぎ']),
                    ('ぽ', ['が', 'ぎ', 'ぐ']),
                ],
            },
            {
                # The 46 basic (seion) katakana in gojuon order -- used for
                # loanwords, onomatopoeia and emphasis.
                'name': 'カタカナ (Katakana)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': list('アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン'),
                'phonics_mcq': [
                    ('ア', ['イ', 'ウ', 'エ']),
                    ('イ', ['ウ', 'エ', 'オ']),
                    ('ウ', ['エ', 'オ', 'カ']),
                    ('エ', ['オ', 'カ', 'キ']),
                    ('オ', ['カ', 'キ', 'ク']),
                    ('カ', ['キ', 'ク', 'ケ']),
                    ('キ', ['ク', 'ケ', 'コ']),
                    ('ク', ['ケ', 'コ', 'サ']),
                    ('ケ', ['コ', 'サ', 'シ']),
                    ('コ', ['サ', 'シ', 'ス']),
                    ('サ', ['シ', 'ス', 'セ']),
                    ('シ', ['ス', 'セ', 'ソ']),
                    ('ス', ['セ', 'ソ', 'タ']),
                    ('セ', ['ソ', 'タ', 'チ']),
                    ('ソ', ['タ', 'チ', 'ツ']),
                    ('タ', ['チ', 'ツ', 'テ']),
                    ('チ', ['ツ', 'テ', 'ト']),
                    ('ツ', ['テ', 'ト', 'ナ']),
                    ('テ', ['ト', 'ナ', 'ニ']),
                    ('ト', ['ナ', 'ニ', 'ヌ']),
                    ('ナ', ['ニ', 'ヌ', 'ネ']),
                    ('ニ', ['ヌ', 'ネ', 'ノ']),
                    ('ヌ', ['ネ', 'ノ', 'ハ']),
                    ('ネ', ['ノ', 'ハ', 'ヒ']),
                    ('ノ', ['ハ', 'ヒ', 'フ']),
                    ('ハ', ['ヒ', 'フ', 'ヘ']),
                    ('ヒ', ['フ', 'ヘ', 'ホ']),
                    ('フ', ['ヘ', 'ホ', 'マ']),
                    ('ヘ', ['ホ', 'マ', 'ミ']),
                    ('ホ', ['マ', 'ミ', 'ム']),
                    ('マ', ['ミ', 'ム', 'メ']),
                    ('ミ', ['ム', 'メ', 'モ']),
                    ('ム', ['メ', 'モ', 'ヤ']),
                    ('メ', ['モ', 'ヤ', 'ユ']),
                    ('モ', ['ヤ', 'ユ', 'ヨ']),
                    ('ヤ', ['ユ', 'ヨ', 'ラ']),
                    ('ユ', ['ヨ', 'ラ', 'リ']),
                    ('ヨ', ['ラ', 'リ', 'ル']),
                    ('ラ', ['リ', 'ル', 'レ']),
                    ('リ', ['ル', 'レ', 'ロ']),
                    ('ル', ['レ', 'ロ', 'ワ']),
                    ('レ', ['ロ', 'ワ', 'ヲ']),
                    ('ロ', ['ワ', 'ヲ', 'ン']),
                    ('ワ', ['ヲ', 'ン', 'ア']),
                    ('ヲ', ['ン', 'ア', 'イ']),
                    ('ン', ['ア', 'イ', 'ウ']),
                ],
            },
            {
                # Dakuten/handakuten katakana -- 'intermediate' level of the
                # same 'カタカナ (Katakana)' topic, same unlock reasoning as
                # hiragana above. 'order' matches the beginner entry above
                # for the same reason as ひらがな's intermediate entry.
                'name': 'カタカナ (Katakana)',
                'order': 2,
                'level': 'intermediate',
                'letter_writing': list('ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ'),
                'phonics_mcq': [
                    ('ガ', ['ギ', 'グ', 'ゲ']),
                    ('ギ', ['グ', 'ゲ', 'ゴ']),
                    ('グ', ['ゲ', 'ゴ', 'ザ']),
                    ('ゲ', ['ゴ', 'ザ', 'ジ']),
                    ('ゴ', ['ザ', 'ジ', 'ズ']),
                    ('ザ', ['ジ', 'ズ', 'ゼ']),
                    ('ジ', ['ズ', 'ゼ', 'ゾ']),
                    ('ズ', ['ゼ', 'ゾ', 'ダ']),
                    ('ゼ', ['ゾ', 'ダ', 'ヂ']),
                    ('ゾ', ['ダ', 'ヂ', 'ヅ']),
                    ('ダ', ['ヂ', 'ヅ', 'デ']),
                    ('ヂ', ['ヅ', 'デ', 'ド']),
                    ('ヅ', ['デ', 'ド', 'バ']),
                    ('デ', ['ド', 'バ', 'ビ']),
                    ('ド', ['バ', 'ビ', 'ブ']),
                    ('バ', ['ビ', 'ブ', 'ベ']),
                    ('ビ', ['ブ', 'ベ', 'ボ']),
                    ('ブ', ['ベ', 'ボ', 'パ']),
                    ('ベ', ['ボ', 'パ', 'ピ']),
                    ('ボ', ['パ', 'ピ', 'プ']),
                    ('パ', ['ピ', 'プ', 'ペ']),
                    ('ピ', ['プ', 'ペ', 'ポ']),
                    ('プ', ['ペ', 'ポ', 'ガ']),
                    ('ペ', ['ポ', 'ガ', 'ギ']),
                    ('ポ', ['ガ', 'ギ', 'グ']),
                ],
            },
        ],
    },

    'ko': {
        'name': 'Korean',
        'script_type': 'hangul',
        'topics': [
            {
                # The 14 basic consonants (jaeum) -- ordered per the
                # standard Hangul chart / dictionary order.
                'name': '자음 (Consonants)',
                'order': 1,
                'level': 'beginner',
                'letter_writing': list('ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ'),
                'phonics_mcq': [
                    ('ㄱ', ['ㄴ', 'ㄷ', 'ㄹ']),
                    ('ㄴ', ['ㄷ', 'ㄹ', 'ㅁ']),
                    ('ㄷ', ['ㄹ', 'ㅁ', 'ㅂ']),
                    ('ㄹ', ['ㅁ', 'ㅂ', 'ㅅ']),
                    ('ㅁ', ['ㅂ', 'ㅅ', 'ㅇ']),
                    ('ㅂ', ['ㅅ', 'ㅇ', 'ㅈ']),
                    ('ㅅ', ['ㅇ', 'ㅈ', 'ㅊ']),
                    ('ㅇ', ['ㅈ', 'ㅊ', 'ㅋ']),
                    ('ㅈ', ['ㅊ', 'ㅋ', 'ㅌ']),
                    ('ㅊ', ['ㅋ', 'ㅌ', 'ㅍ']),
                    ('ㅋ', ['ㅌ', 'ㅍ', 'ㅎ']),
                    ('ㅌ', ['ㅍ', 'ㅎ', 'ㄱ']),
                    ('ㅍ', ['ㅎ', 'ㄱ', 'ㄴ']),
                    ('ㅎ', ['ㄱ', 'ㄴ', 'ㄷ']),
                ],
            },
            {
                # The 5 doubled (tensed) consonants (쌍자음) -- each is
                # literally its base consonant written twice, so this is
                # 'intermediate' of the SAME '자음 (Consonants)' topic
                # rather than a separate topic, letting mastery of the
                # beginner set unlock it (the unlock mechanism only
                # tracks progress within one topic's own levels -- see the
                # Tamil/Mandarin/Japanese category-topic lesson above).
                # 'order' matches the beginner entry above, not the next
                # sequential number -- see the identical note on Japanese's
                # ひらがな intermediate entry: LanguageTopic is keyed on
                # (language, name), so only the first-seeded level-entry's
                # 'order' ever takes effect.
                'name': '자음 (Consonants)',
                'order': 1,
                'level': 'intermediate',
                'letter_writing': list('ㄲㄸㅃㅆㅉ'),
                'phonics_mcq': [
                    ('ㄲ', ['ㄸ', 'ㅃ', 'ㅆ']),
                    ('ㄸ', ['ㅃ', 'ㅆ', 'ㅉ']),
                    ('ㅃ', ['ㅆ', 'ㅉ', 'ㄲ']),
                    ('ㅆ', ['ㅉ', 'ㄲ', 'ㄸ']),
                    ('ㅉ', ['ㄲ', 'ㄸ', 'ㅃ']),
                ],
            },
            {
                # The 10 basic vowels (moeum).
                'name': '모음 (Vowels)',
                'order': 2,
                'level': 'beginner',
                'letter_writing': list('ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ'),
                'phonics_mcq': [
                    ('ㅏ', ['ㅑ', 'ㅓ', 'ㅕ']),
                    ('ㅑ', ['ㅓ', 'ㅕ', 'ㅗ']),
                    ('ㅓ', ['ㅕ', 'ㅗ', 'ㅛ']),
                    ('ㅕ', ['ㅗ', 'ㅛ', 'ㅜ']),
                    ('ㅗ', ['ㅛ', 'ㅜ', 'ㅠ']),
                    ('ㅛ', ['ㅜ', 'ㅠ', 'ㅡ']),
                    ('ㅜ', ['ㅠ', 'ㅡ', 'ㅣ']),
                    ('ㅠ', ['ㅡ', 'ㅣ', 'ㅏ']),
                    ('ㅡ', ['ㅣ', 'ㅏ', 'ㅑ']),
                    ('ㅣ', ['ㅏ', 'ㅑ', 'ㅓ']),
                ],
            },
            {
                # The 11 compound vowels (이중모음) -- each is two (or
                # three) of the basic vowels above written together (e.g.
                # 와 = ㅗ+ㅏ) -- 'intermediate' of the same '모음 (Vowels)'
                # topic, same unlock reasoning as consonants above. 'order'
                # matches the beginner entry above for the same reason as
                # 자음's intermediate entry.
                'name': '모음 (Vowels)',
                'order': 2,
                'level': 'intermediate',
                'letter_writing': list('ㅐㅒㅔㅖㅘㅙㅚㅝㅞㅟㅢ'),
                'phonics_mcq': [
                    ('ㅐ', ['ㅒ', 'ㅔ', 'ㅖ']),
                    ('ㅒ', ['ㅔ', 'ㅖ', 'ㅘ']),
                    ('ㅔ', ['ㅖ', 'ㅘ', 'ㅙ']),
                    ('ㅖ', ['ㅘ', 'ㅙ', 'ㅚ']),
                    ('ㅘ', ['ㅙ', 'ㅚ', 'ㅝ']),
                    ('ㅙ', ['ㅚ', 'ㅝ', 'ㅞ']),
                    ('ㅚ', ['ㅝ', 'ㅞ', 'ㅟ']),
                    ('ㅝ', ['ㅞ', 'ㅟ', 'ㅢ']),
                    ('ㅞ', ['ㅟ', 'ㅢ', 'ㅐ']),
                    ('ㅟ', ['ㅢ', 'ㅐ', 'ㅒ']),
                    ('ㅢ', ['ㅐ', 'ㅒ', 'ㅔ']),
                ],
            },
            {
                # The 11 syllable-final consonant clusters (겹받침) --
                # each a combination of two of the 19 consonants above,
                # used only in coda/batchim position (e.g. 넋 ends in ㄳ).
                # 'beginner' as its own single-level topic (not a level of
                # 자음 above) since it isn't a natural 'harder version' of
                # the basic consonants -- it's a distinct usage pattern
                # (finals only) students meet once they read full
                # syllable blocks, not a progression step within the
                # consonant set itself.
                'name': '겹받침 (Final Consonant Clusters)',
                'order': 3,
                'level': 'beginner',
                'letter_writing': list('ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ'),
                'phonics_mcq': [
                    ('ㄳ', ['ㄵ', 'ㄶ', 'ㄺ']),
                    ('ㄵ', ['ㄶ', 'ㄺ', 'ㄻ']),
                    ('ㄶ', ['ㄺ', 'ㄻ', 'ㄼ']),
                    ('ㄺ', ['ㄻ', 'ㄼ', 'ㄽ']),
                    ('ㄻ', ['ㄼ', 'ㄽ', 'ㄾ']),
                    ('ㄼ', ['ㄽ', 'ㄾ', 'ㄿ']),
                    ('ㄽ', ['ㄾ', 'ㄿ', 'ㅀ']),
                    ('ㄾ', ['ㄿ', 'ㅀ', 'ㅄ']),
                    ('ㄿ', ['ㅀ', 'ㅄ', 'ㄳ']),
                    ('ㅀ', ['ㅄ', 'ㄳ', 'ㄵ']),
                    ('ㅄ', ['ㄳ', 'ㄵ', 'ㄶ']),
                ],
            },
        ],
    },
}


def expected_exercise_count(code):
    """How many LanguageExercise rows seeding ``code`` should produce.

    Both seeders key exercises on (topic_level, exercise_type, prompt) via
    get_or_create, so a prompt repeated inside one topic entry collapses to a
    single row — the count has to de-duplicate the same way or it lies.

    Used by ``manage.py check_language_seed`` to catch the quieter half of this
    bug: a language whose row exists but whose content silently came up short.
    That is not hypothetical. Before migration 0011 switched the prompt columns
    to utf8mb4_bin, MySQL's accent- and case-insensitive default collation made
    get_or_create treat 'e' == 'é' == 'è' and 'A' == 'a', so French lost 3 of 4
    'e' variants and Sinhala lost every lowercase vowel — on the server only,
    with SQLite tests green throughout.
    """
    total = 0
    for topic in SEED[code]['topics']:
        total += len(set(topic.get('letter_writing', [])))
        total += len({prompt for prompt, _wrong in topic.get('phonics_mcq', [])})
        total += len({word for word, _wrong in topic.get('spelling_mcq', [])})
        total += len({word for word, _clue in topic.get('spelling_type', [])})
        total += len({sentence for sentence, *_rest in topic.get('grammar_fill_blank', [])})
        total += len({sentence for sentence, _order in topic.get('sentence_order', [])})
        if topic.get('crossword'):
            total += 1
    return total
