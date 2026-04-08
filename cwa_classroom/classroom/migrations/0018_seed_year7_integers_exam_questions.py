"""
Migration 0018 — Year 7 questions from G7 Exam Integers.pdf:
  - Indices and Powers     : +10 questions (base/exponent, zero law, powers of 10)
  - BODMAS                 : +10 questions (nested bracket calculations)
  - Addition and Subtraction: +3 questions (decimal word problems)
  - Ratios                 : +1 question  (ratio of losses)
  - Mean and Average       : +1 question  (average temperature change)
All assigned to Year 7.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
INDICES_POWERS_QUESTIONS = [
    {
        "text": "In the expression 5³, what is the base?",
        "difficulty": 1,
        "answers": [
            ("5", True), ("3", False), ("15", False), ("125", False),
        ],
    },
    {
        "text": "In the expression 5³, what is the exponent?",
        "difficulty": 1,
        "answers": [
            ("3", True), ("5", False), ("15", False), ("125", False),
        ],
    },
    {
        "text": "Write 3 × 3 × 3 × 3 × 3 × 3 × 3 as a single power.",
        "difficulty": 1,
        "answers": [
            ("3⁷", True), ("7³", False), ("3⁶", False), ("7⁶", False),
        ],
    },
    {
        "text": "Evaluate 4³ (write as repeated multiplication, then in standard form).",
        "difficulty": 1,
        "answers": [
            ("64", True), ("12", False), ("16", False), ("43", False),
        ],
    },
    {
        "text": "Evaluate (−2)⁵.",
        "difficulty": 2,
        "answers": [
            ("−32", True), ("32", False), ("−10", False), ("10", False),
        ],
    },
    {
        "text": "What is the value of (−3)⁴?",
        "difficulty": 2,
        "answers": [
            ("81", True), ("−81", False), ("12", False), ("−12", False),
        ],
    },
    {
        "text": "What is the value of −3⁴? (Note: the negative sign is NOT inside the brackets.)",
        "difficulty": 2,
        "answers": [
            ("−81", True), ("81", False), ("−12", False), ("12", False),
        ],
    },
    {
        "text": "Write 10 000 as a power of 10.",
        "difficulty": 1,
        "answers": [
            ("10⁴", True), ("10⁵", False), ("4¹⁰", False), ("10³", False),
        ],
    },
    {
        "text": "Write 1 000 000 as a power of 10.",
        "difficulty": 2,
        "answers": [
            ("10⁶", True), ("10⁵", False), ("10⁷", False), ("6¹⁰", False),
        ],
    },
    {
        "text": "What is the value of (−4)⁰?",
        "difficulty": 2,
        "answers": [
            ("1", True), ("0", False), ("−4", False), ("4", False),
        ],
    },
]

# ---------------------------------------------------------------------------
BODMAS_QUESTIONS = [
    {
        "text": "Calculate: (108 + 292) − 119",
        "difficulty": 1,
        "answers": [
            ("281", True), ("175", False), ("391", False), ("519", False),
        ],
    },
    {
        "text": "Calculate: 509 − (219 + 111)",
        "difficulty": 1,
        "answers": [
            ("179", True), ("839", False), ("401", False), ("399", False),
        ],
    },
    {
        "text": "Calculate: 15 × (3 + 1 × 1)",
        "difficulty": 1,
        "answers": [
            ("60", True), ("75", False), ("45", False), ("90", False),
        ],
    },
    {
        "text": "Calculate: (15 − 13) × 16 + (20 − 18) ÷ 2",
        "difficulty": 2,
        "answers": [
            ("33", True), ("34", False), ("32", False), ("35", False),
        ],
    },
    {
        "text": "Calculate: (62 − 2 × 2) × 19",
        "difficulty": 2,
        "answers": [
            ("1102", True), ("1140", False), ("1064", False), ("988", False),
        ],
    },
    {
        "text": "Calculate: (23 × 3 + 4) × 50",
        "difficulty": 2,
        "answers": [
            ("3650", True), ("3700", False), ("3450", False), ("2950", False),
        ],
    },
    {
        "text": "Calculate: 7 × [(4 − 2) × 2 + 1]",
        "difficulty": 2,
        "answers": [
            ("35", True), ("21", False), ("49", False), ("28", False),
        ],
    },
    {
        "text": "Calculate: [3 × (2 + 2 × 3) + 1] ÷ 5",
        "difficulty": 3,
        "answers": [
            ("5", True), ("7", False), ("4", False), ("6", False),
        ],
    },
    {
        "text": "Calculate: 4 × [2 + (3 × 5 − 7) × 2]",
        "difficulty": 3,
        "answers": [
            ("72", True), ("56", False), ("80", False), ("64", False),
        ],
    },
    {
        "text": "Calculate: (23 + 30) × 2 + (17 − 1) × 48",
        "difficulty": 3,
        "answers": [
            ("874", True), ("876", False), ("770", False), ("926", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Word problems from the Rational Numbers exam section
ADDITION_SUBTRACTION_WORD_PROBLEMS = [
    {
        "text": "A share price increased by $0.05 one day, decreased by $0.02 the next day, and decreased again by $0.01 the following day. What was the total change in price?",
        "difficulty": 2,
        "answers": [
            ("$0.02 increase", True),
            ("$0.02 decrease", False),
            ("$0.08 increase", False),
            ("no change", False),
        ],
    },
    {
        "text": "Over five days, a city's temperature changed by +4.2°, +1.7°, −11.7°, −2.3°, and +5.2°C. What was the total change from start to end?",
        "difficulty": 2,
        "answers": [
            ("−2.9°C", True), ("+13.1°C", False), ("+11.1°C", False), ("−14.0°C", False),
        ],
    },
    {
        "text": "Over a five-day period, a city's temperature changed by +4.2°, +1.7°, −11.7°, −2.3°, and +5.2°C. What was the average daily change?",
        "difficulty": 3,
        "answers": [
            ("−0.58°C", True), ("+0.58°C", False), ("−2.9°C", False), ("−1.16°C", False),
        ],
    },
]

RATIOS_WORD_PROBLEM = [
    {
        "text": "One share lost $0.25 and another share lost $0.03. What is the ratio of the first loss to the second?",
        "difficulty": 2,
        "answers": [
            ("25 : 3", True), ("3 : 25", False), ("1 : 8", False), ("5 : 1", False),
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

    slug_to_questions = {
        'indices-and-powers':      INDICES_POWERS_QUESTIONS,
        'bodmas':                  BODMAS_QUESTIONS,
        'addition-and-subtraction': ADDITION_SUBTRACTION_WORD_PROBLEMS,
        'ratios':                  RATIOS_WORD_PROBLEM,
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
        [q['text'] for q in INDICES_POWERS_QUESTIONS]
        + [q['text'] for q in BODMAS_QUESTIONS]
        + [q['text'] for q in ADDITION_SUBTRACTION_WORD_PROBLEMS]
        + [q['text'] for q in RATIOS_WORD_PROBLEM]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0017_seed_year7_g7_textbook_questions'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
