"""
Migration 0017 — Year 7 additional questions from G7.pdf (Cambridge textbook):
  - Number Systems   : +10 questions (Roman numerals, system properties)
  - Place Values     : +10 questions (expanded form, index notation, comparison symbols)
  - Addition and Subtraction : +10 questions (mental strategies)
All appended to existing subtopics — no new subtopics created.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
NUMBER_SYSTEMS_QUESTIONS = [
    {
        "text": "What decimal number does the Roman numeral XIV represent?",
        "difficulty": 1,
        "answers": [
            ("14", True), ("16", False), ("9", False), ("15", False),
        ],
    },
    {
        "text": "Write the number 9 in Roman numerals.",
        "difficulty": 1,
        "answers": [
            ("IX", True), ("VIIII", False), ("IIX", False), ("XI", False),
        ],
    },
    {
        "text": "Which Roman numeral letter represents 50?",
        "difficulty": 1,
        "answers": [
            ("L", True), ("X", False), ("C", False), ("D", False),
        ],
    },
    {
        "text": "What decimal number does the Roman numeral XLVII represent?",
        "difficulty": 2,
        "answers": [
            ("47", True), ("42", False), ("57", False), ("37", False),
        ],
    },
    {
        "text": "Write the number 24 in Roman numerals.",
        "difficulty": 2,
        "answers": [
            ("XXIV", True), ("XXVI", False), ("IIIXX", False), ("XXIIII", False),
        ],
    },
    {
        "text": "What decimal number does CLVI represent?",
        "difficulty": 2,
        "answers": [
            ("156", True), ("155", False), ("146", False), ("166", False),
        ],
    },
    {
        "text": "In the Roman system, only one numeral can reduce another. Which of these is correct for 8?",
        "difficulty": 2,
        "answers": [
            ("VIII", True), ("IIX", False), ("IIIX", False), ("VVV", False),
        ],
    },
    {
        "text": "Which ancient number system is based on the number 60 and used wedge-shaped cuneiform symbols?",
        "difficulty": 2,
        "answers": [
            ("Babylonian", True), ("Egyptian", False), ("Roman", False), ("Hindu–Arabic", False),
        ],
    },
    {
        "text": "Which ancient number system used hieroglyphics and had no symbol for zero?",
        "difficulty": 2,
        "answers": [
            ("Egyptian", True), ("Babylonian", False), ("Roman", False), ("Greek", False),
        ],
    },
    {
        "text": "What decimal number does the Roman numeral MCMXCIX represent?",
        "difficulty": 3,
        "answers": [
            ("1999", True), ("1899", False), ("1991", False), ("2001", False),
        ],
    },
]

# ---------------------------------------------------------------------------
PLACE_VALUES_QUESTIONS = [
    {
        "text": "What is the place value of the digit 4 in the number 437?",
        "difficulty": 1,
        "answers": [
            ("400", True), ("40", False), ("4000", False), ("4", False),
        ],
    },
    {
        "text": "What is the place value of the digit 7 in the number 1712?",
        "difficulty": 1,
        "answers": [
            ("700", True), ("70", False), ("7000", False), ("7", False),
        ],
    },
    {
        "text": "Write 517 in expanded form.",
        "difficulty": 1,
        "answers": [
            ("5 × 100 + 1 × 10 + 7 × 1", True),
            ("5 × 1000 + 1 × 100 + 7 × 10", False),
            ("517 × 1", False),
            ("5 × 10 + 1 × 7", False),
        ],
    },
    {
        "text": "Write 2003 in expanded form.",
        "difficulty": 1,
        "answers": [
            ("2 × 1000 + 3 × 1", True),
            ("2 × 1000 + 0 × 100 + 0 × 10 + 3 × 1 only when written in full", False),
            ("2 × 100 + 3 × 10", False),
            ("20 × 100 + 3", False),
        ],
    },
    {
        "text": "What is the place value of the digit 6 in the number 45 620?",
        "difficulty": 2,
        "answers": [
            ("600", True), ("60", False), ("6000", False), ("6", False),
        ],
    },
    {
        "text": "Which shows 3254 correctly in expanded form using index notation?",
        "difficulty": 2,
        "answers": [
            ("3 × 10³ + 2 × 10² + 5 × 10¹ + 4 × 10⁰", True),
            ("3 × 10⁴ + 2 × 10³ + 5 × 10² + 4 × 10¹", False),
            ("3 × 10² + 2 × 10¹ + 5 × 10⁰ + 4", False),
            ("32 × 10² + 54", False),
        ],
    },
    {
        "text": "What number is represented by 4 × 1000 + 5 × 100 + 2 × 10 + 8 × 1?",
        "difficulty": 2,
        "answers": [
            ("4528", True), ("4258", False), ("5428", False), ("4582", False),
        ],
    },
    {
        "text": "What is the value of 3 × 10³ + 7 × 10² + 0 × 10¹ + 5 × 10⁰?",
        "difficulty": 2,
        "answers": [
            ("3705", True), ("3750", False), ("3075", False), ("370", False),
        ],
    },
    {
        "text": "Which symbol means 'is approximately equal to'?",
        "difficulty": 2,
        "answers": [
            ("≈", True), ("=", False), ("≠", False), ("≤", False),
        ],
    },
    {
        "text": "Which symbol means 'is greater than or equal to'?",
        "difficulty": 2,
        "answers": [
            ("≥", True), ("≤", False), (">", False), ("≠", False),
        ],
    },
]

# ---------------------------------------------------------------------------
ADDITION_SUBTRACTION_QUESTIONS = [
    {
        "text": "Use the partitioning strategy to find: 138 + 441",
        "difficulty": 1,
        "answers": [
            ("579", True), ("580", False), ("569", False), ("599", False),
        ],
    },
    {
        "text": "Use the compensating strategy to find: 46 + 9",
        "difficulty": 1,
        "answers": [
            ("55", True), ("56", False), ("54", False), ("45", False),
        ],
    },
    {
        "text": "Use the compensating strategy to find: 156 − 48",
        "difficulty": 1,
        "answers": [
            ("108", True), ("110", False), ("104", False), ("112", False),
        ],
    },
    {
        "text": "Use the doubling strategy to find: 75 + 78",
        "difficulty": 2,
        "answers": [
            ("153", True), ("150", False), ("155", False), ("148", False),
        ],
    },
    {
        "text": "Use the halving strategy to find: 124 − 61",
        "difficulty": 2,
        "answers": [
            ("63", True), ("62", False), ("64", False), ("65", False),
        ],
    },
    {
        "text": "Calculate mentally: 98 + 22 − 31 + 29",
        "difficulty": 2,
        "answers": [
            ("118", True), ("120", False), ("116", False), ("119", False),
        ],
    },
    {
        "text": "Gary worked 7, 5, 13, 11, and 2 hours on Monday through Friday. What is his total for the week?",
        "difficulty": 2,
        "answers": [
            ("38", True), ("36", False), ("40", False), ("34", False),
        ],
    },
    {
        "text": "Phil hit 126 runs and Mario hit 19 runs. How many more runs did Phil hit than Mario?",
        "difficulty": 2,
        "answers": [
            ("107", True), ("105", False), ("145", False), ("117", False),
        ],
    },
    {
        "text": "Use the compensating strategy to find: 31 + 136",
        "difficulty": 2,
        "answers": [
            ("167", True), ("166", False), ("168", False), ("170", False),
        ],
    },
    {
        "text": "The sum of two numbers is 87 and their difference is 29. What are the two numbers?",
        "difficulty": 3,
        "answers": [
            ("58 and 29", True), ("60 and 27", False), ("50 and 37", False), ("56 and 31", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('maths', 'Question')
    Answer   = apps.get_model('maths', 'Answer')

    maths  = Subject.objects.get(slug='mathematics')
    year7  = Level.objects.filter(level_number=7).first()

    if not year7:
        return

    def add_questions(subtopic, q_list):
        for q_data in q_list:
            q, created = Question.objects.get_or_create(
                topic=subtopic,
                level=year7,
                question_text=q_data['text'],
                defaults={
                    'difficulty':    q_data['difficulty'],
                    'question_type': 'multiple_choice',
                },
            )
            if created:
                for display_order, (ans_text, is_correct) in enumerate(q_data['answers'], start=1):
                    Answer.objects.create(
                        question=q,
                        text=ans_text,
                        is_correct=is_correct,
                        display_order=display_order,
                    )

    subtopics_data = [
        ('number-systems',        NUMBER_SYSTEMS_QUESTIONS),
        ('place-values',          PLACE_VALUES_QUESTIONS),
        ('addition-and-subtraction', ADDITION_SUBTRACTION_QUESTIONS),
    ]

    for slug, q_list in subtopics_data:
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year7)
        add_questions(subtopic, q_list)


def reverse_data(apps, schema_editor):
    # Questions are appended to existing subtopics — reversing would require
    # identifying and deleting only these specific question texts.
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('maths', 'Question')

    maths  = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in NUMBER_SYSTEMS_QUESTIONS]
        + [q['text'] for q in PLACE_VALUES_QUESTIONS]
        + [q['text'] for q in ADDITION_SUBTRACTION_QUESTIONS]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0016_seed_space_statistics_subtopics'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
