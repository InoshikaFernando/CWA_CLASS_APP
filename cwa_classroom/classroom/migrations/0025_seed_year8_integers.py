"""
Migration 0025 — Grade 8 Math Test — Integers (from G8 Exam Integers.pdf):
  Integers      (Y8): +12 questions (classification, operations, ordering, real-life)
  Fractions     (Y8): +2  questions (rational number arithmetic)
  BODMAS        (Y8): +2  questions (order of operations with integers)
  Finance       (Y8): +1  question  (money word problem)
All assigned to Year 8.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
INTEGERS_Y8 = [
    {
        "text": "Which of the following is an integer?",
        "difficulty": 1,
        "answers": [
            ("−9", True), ("−2/5", False), ("2.9", False), ("√2", False),
        ],
    },
    {
        "text": "Which of the following expressions has the least value?",
        "difficulty": 1,
        "answers": [
            ("3 × (−2)", True), ("−3 + (−2)", False), ("−3 + 2", False), ("3 × 2", False),
        ],
    },
    {
        "text": "The temperature at 7:00 am was −4°C and rose 17°C during the morning. What was the temperature at noon?",
        "difficulty": 1,
        "answers": [
            ("13°C", True), ("−13°C", False), ("21°C", False), ("12°C", False),
        ],
    },
    {
        "text": "Which set of numbers is arranged correctly from greatest to least?",
        "difficulty": 2,
        "answers": [
            ("5/2, 1.2, −0.3, −1/2", True),
            ("−1/2, −0.3, 1.2, 5/2", False),
            ("1.2, 5/2, −1/2, −0.3", False),
            ("−0.3, −1/2, 1.2, 5/2", False),
        ],
    },
    {
        "text": "An elevator started on the 5th floor. It went up 3 floors, down 6, up 9, up 3, down 2, then down 3. On which floor did it stop?",
        "difficulty": 2,
        "answers": [
            ("9th floor", True), ("5th floor", False), ("8th floor", False), ("Basement", False),
        ],
    },
    {
        "text": "How many integers are strictly greater than −12 and strictly less than −7?",
        "difficulty": 1,
        "answers": [
            ("4", True), ("5", False), ("19", False), ("None", False),
        ],
    },
    {
        "text": "Which statement is FALSE?",
        "difficulty": 1,
        "answers": [
            ("−4 > −3", True), ("−1 > −8", False), ("0 < 1", False), ("−5 < 3", False),
        ],
    },
    {
        "text": "Which set of integers is arranged from least to greatest?",
        "difficulty": 1,
        "answers": [
            ("−7, −5, −1, 0, +3, +4", True),
            ("−3, +3, −2, +2, −1, +1", False),
            ("+4, +2, +1, −4, −7", False),
            ("0, +4, −5, +6, −7", False),
        ],
    },
    {
        "text": "What is −252 ÷ (+14)?",
        "difficulty": 1,
        "answers": [
            ("−18", True), ("+18", False), ("−238", False), ("+238", False),
        ],
    },
    {
        "text": "On a number line, which integer is halfway between −7 and +1?",
        "difficulty": 2,
        "answers": [
            ("−3", True), ("−5", False), ("+5", False), ("0", False),
        ],
    },
    {
        "text": "What is the product of −4 and −25?",
        "difficulty": 1,
        "answers": [
            ("+100", True), ("−100", False), ("+29", False), ("−29", False),
        ],
    },
    {
        "text": "Each term in a number sequence is 8 less than the term before it. The third term is 21. What is the fifteenth term?",
        "difficulty": 3,
        "answers": [
            ("−75", True), ("−67", False), ("−83", False), ("−120", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FRACTIONS_Y8 = [
    {
        "text": "Which of the following lists the numbers in order from greatest to least? (−1/2, −0.3, 1.2, 5/2)",
        "difficulty": 2,
        "answers": [
            ("5/2, 1.2, −0.3, −1/2", True),
            ("−1/2, −0.3, 1.2, 5/2", False),
            ("5/2, 1.2, −1/2, −0.3", False),
            ("−0.3, −1/2, 1.2, 5/2", False),
        ],
    },
    {
        "text": "What is 15/4 − 3/2 in simplest form?",
        "difficulty": 2,
        "answers": [
            ("9/4", True), ("−9/4", False), ("17/4", False), ("−17/4", False),
        ],
    },
]

# ---------------------------------------------------------------------------
BODMAS_Y8 = [
    {
        "text": "Evaluate: (−1/2 × −4) + [−12 ÷ (+3)]",
        "difficulty": 2,
        "answers": [
            ("−2", True), ("+4", False), ("+2", False), ("0", False),
        ],
    },
    {
        "text": "Evaluate: 15 + 3 × 2 − 6 ÷ 3",
        "difficulty": 2,
        "answers": [
            ("19", True), ("5", False), ("10", False), ("34", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FINANCE_Y8 = [
    {
        "text": "Alan has $50. Brendan repays him the $12.50 he borrowed. Then Alan buys a CD for $21.18. How much does Alan have left?",
        "difficulty": 2,
        "answers": [
            ("$41.32", True), ("$16.32", False), ("$58.68", False), ("$83.68", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Also: (−5.6) ÷ (−0.16)
DIVISION_Y8 = [
    {
        "text": "What is (−5.6) ÷ (−0.16)?",
        "difficulty": 2,
        "answers": [
            ("+35", True), ("−35", False), ("−3.5", False), ("+3.5", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('quiz', 'Question')
    Answer   = apps.get_model('quiz', 'Answer')

    maths = Subject.objects.get(slug='mathematics')
    year8 = Level.objects.filter(level_number=8).first()
    if not year8:
        return

    def add_questions(subtopic, q_list):
        for q_data in q_list:
            q, created = Question.objects.get_or_create(
                topic=subtopic,
                level=year8,
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
        'integers': INTEGERS_Y8,
        'fractions': FRACTIONS_Y8,
        'bodmas':   BODMAS_Y8,
        'finance':  FINANCE_Y8,
        'division': DIVISION_Y8,
    }

    for slug, q_list in slug_to_questions.items():
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year8)
        add_questions(subtopic, q_list)


def reverse_data(apps, schema_editor):
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in INTEGERS_Y8]
        + [q['text'] for q in FRACTIONS_Y8]
        + [q['text'] for q in BODMAS_Y8]
        + [q['text'] for q in FINANCE_Y8]
        + [q['text'] for q in DIVISION_Y8]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0024_seed_year7_naplan'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
