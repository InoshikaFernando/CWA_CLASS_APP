"""
Migration 0023 — G7-2.pdf (Maths Hub Melbourne workbook):
  Prime Numbers                  (Y7): +8 questions (definitions, factors, factor chains)
  Square and Triangular Numbers  (Y7): +10 questions (triangular sequences, handshakes,
                                        identifying square/triangular numbers)
  Operation Order                (Y7): +6 questions (commutative/associative properties)
All assigned to Year 7.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
PRIME_NUMBERS_Y7 = [
    {
        "text": "What is special about the number 2 as a prime number?",
        "difficulty": 1,
        "answers": [
            ("It is the only even prime number", True),
            ("It is the smallest composite number", False),
            ("It has three factors: 1, 2, and 4", False),
            ("It is neither prime nor composite", False),
        ],
    },
    {
        "text": "Which of the following correctly describes a prime number?",
        "difficulty": 1,
        "answers": [
            ("A number with exactly two factors: 1 and itself", True),
            ("A number that is always odd", False),
            ("A number divisible by 1, itself, and at least one other factor", False),
            ("A number with more than two factors", False),
        ],
    },
    {
        "text": "Which of the following correctly describes a composite number?",
        "difficulty": 1,
        "answers": [
            ("A number with more than two factors", True),
            ("A number that is always even", False),
            ("A number divisible only by 1 and itself", False),
            ("A number that cannot be divided", False),
        ],
    },
    {
        "text": "How many factors does 25 have?",
        "difficulty": 1,
        "answers": [
            ("3 (factors: 1, 5, 25)", True),
            ("2 (factors: 1 and 25)", False),
            ("5 (factors: 1, 5, 10, 20, 25)", False),
            ("4 (factors: 1, 5, 25, 50)", False),
        ],
    },
    {
        "text": "How many factors does 42 have?",
        "difficulty": 2,
        "answers": [
            ("8 (factors: 1, 2, 3, 6, 7, 14, 21, 42)", True),
            ("4", False),
            ("6", False),
            ("10", False),
        ],
    },
    {
        "text": "Which of these numbers is prime?",
        "difficulty": 2,
        "answers": [
            ("97", True), ("51", False), ("57", False), ("91", False),
        ],
    },
    {
        "text": "10 is a factor of 2550. Since 2 × 5 = 10, which of these must also be a factor of 2550?",
        "difficulty": 2,
        "answers": [
            ("5", True), ("3", False), ("7", False), ("11", False),
        ],
    },
    {
        "text": "15 is a factor of 37,500. Since 3 × 5 = 15, which of these must also be a factor of 37,500?",
        "difficulty": 2,
        "answers": [
            ("3", True), ("7", False), ("11", False), ("13", False),
        ],
    },
]

# ---------------------------------------------------------------------------
SQUARE_TRIANGULAR_Y7 = [
    {
        "text": "Cans are stacked in a triangular pattern (1 level = 1 can, 2 levels = 3 cans, 3 levels = 6 cans, 4 levels = 10 cans). How many cans are needed for 5 levels?",
        "difficulty": 1,
        "answers": [
            ("15", True), ("12", False), ("18", False), ("20", False),
        ],
    },
    {
        "text": "Using the same triangular stacking pattern (1, 3, 6, 10, …), how many cans are needed for 8 levels?",
        "difficulty": 2,
        "answers": [
            ("36", True), ("28", False), ("32", False), ("40", False),
        ],
    },
    {
        "text": "Using the triangular stacking pattern, Bassima has exactly 55 cans. How many complete levels can she make with no cans left over?",
        "difficulty": 2,
        "answers": [
            ("10", True), ("8", False), ("9", False), ("11", False),
        ],
    },
    {
        "text": "At a party, each new guest shakes hands with everyone already there. Starting with 1 guest (1 handshake), then 2 guests (3 handshakes total). How many handshakes in total when there are 4 people?",
        "difficulty": 1,
        "answers": [
            ("6", True), ("4", False), ("8", False), ("10", False),
        ],
    },
    {
        "text": "Using the same handshake pattern, how many handshakes in total when there are 5 people in the room?",
        "difficulty": 2,
        "answers": [
            ("10", True), ("8", False), ("12", False), ("15", False),
        ],
    },
    {
        "text": "Which of these is a triangular number?",
        "difficulty": 1,
        "answers": [
            ("6", True), ("7", False), ("9", False), ("8", False),
        ],
    },
    {
        "text": "Which of these is a triangular number?",
        "difficulty": 1,
        "answers": [
            ("28", True), ("25", False), ("24", False), ("30", False),
        ],
    },
    {
        "text": "The triangular numbers are: 1, 3, 6, 10, 15, 21, 28 … Which of these is NOT a triangular number?",
        "difficulty": 2,
        "answers": [
            ("14", True), ("6", False), ("15", False), ("21", False),
        ],
    },
    {
        "text": "What is the 7th triangular number? (Triangular numbers start: 1, 3, 6, 10, 15, 21, …)",
        "difficulty": 2,
        "answers": [
            ("28", True), ("21", False), ("36", False), ("27", False),
        ],
    },
    {
        "text": "Which of these is a square number?",
        "difficulty": 1,
        "answers": [
            ("9", True), ("15", False), ("34", False), ("11", False),
        ],
    },
]

# ---------------------------------------------------------------------------
OPERATION_ORDER_Y7 = [
    {
        "text": "Which of the following is TRUE?",
        "difficulty": 1,
        "answers": [
            ("4 + 9 = 9 + 4", True),
            ("12 − 5 = 5 − 12", False),
            ("49 ÷ 7 = 7 ÷ 49", False),
            ("(18 + 6) ÷ 3 = 18 + (6 ÷ 3)", False),
        ],
    },
    {
        "text": "Which of the following is FALSE?",
        "difficulty": 2,
        "answers": [
            ("(5 × 4) − 2 = 5 × (4 − 2)", True),
            ("13 × 6 = 6 × 13", False),
            ("(15 × 2) ÷ 3 = (15 ÷ 3) × 2", False),
            ("4 + 9 = 9 + 4", False),
        ],
    },
    {
        "text": "Evaluate (4 × 3) + 5 and 4 × (3 + 5). Which statement is correct?",
        "difficulty": 2,
        "answers": [
            ("They are NOT equal: (4×3)+5 = 17 but 4×(3+5) = 32", True),
            ("They are equal; both equal 17", False),
            ("They are equal; both equal 32", False),
            ("They are NOT equal: (4×3)+5 = 12 but 4×(3+5) = 24", False),
        ],
    },
    {
        "text": "Evaluate (18 + 6) ÷ 3 and 18 + (6 ÷ 3). Which statement is correct?",
        "difficulty": 2,
        "answers": [
            ("They are NOT equal: (18+6)÷3 = 8 but 18+(6÷3) = 20", True),
            ("They are equal; both equal 8", False),
            ("They are equal; both equal 20", False),
            ("They are NOT equal: (18+6)÷3 = 24 but 18+(6÷3) = 3", False),
        ],
    },
    {
        "text": "Evaluate (12 ÷ 6) − 2 and 12 ÷ (6 − 2). Which statement is correct?",
        "difficulty": 2,
        "answers": [
            ("They are NOT equal: (12÷6)−2 = 0 but 12÷(6−2) = 3", True),
            ("They are equal; both equal 0", False),
            ("They are equal; both equal 3", False),
            ("They are NOT equal: (12÷6)−2 = 2 but 12÷(6−2) = 4", False),
        ],
    },
    {
        "text": "Evaluate (15 × 2) ÷ 3 and (15 ÷ 3) × 2. Which statement is correct?",
        "difficulty": 2,
        "answers": [
            ("They are equal; both equal 10", True),
            ("They are NOT equal: (15×2)÷3 = 30 but (15÷3)×2 = 5", False),
            ("They are NOT equal: (15×2)÷3 = 10 but (15÷3)×2 = 5", False),
            ("They are NOT equal: (15×2)÷3 = 10 but (15÷3)×2 = 15", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('maths', 'Question')
    Answer   = apps.get_model('maths', 'Answer')

    maths = Subject.objects.get(slug='mathematics')
    year7 = Level.objects.filter(level_number=7).first()

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

    slug_to_questions = {
        'prime-numbers':                  PRIME_NUMBERS_Y7,
        'square-and-triangular-numbers':  SQUARE_TRIANGULAR_Y7,
        'operation-order':                OPERATION_ORDER_Y7,
    }

    for slug, q_list in slug_to_questions.items():
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year7)
        add_questions(subtopic, q_list)


def reverse_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('maths', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in PRIME_NUMBERS_Y7]
        + [q['text'] for q in SQUARE_TRIANGULAR_Y7]
        + [q['text'] for q in OPERATION_ORDER_Y7]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0022_seed_acer_maths_set01'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
