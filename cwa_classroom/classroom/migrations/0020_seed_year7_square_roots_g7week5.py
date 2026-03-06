"""
Migration 0020 — Year 7 questions from G7 Week 5.pdf (Square Roots and Exponents):
  - Square and Triangular Numbers : +10 questions (perfect squares, prime factorisation test)
  - Square Roots                  : +10 questions (exact & estimated square roots, word problems)
All assigned to Year 7.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
PERFECT_SQUARES_QUESTIONS = [
    {
        "text": "Which of the following is NOT a perfect square?",
        "difficulty": 1,
        "answers": [
            ("120", True), ("64", False), ("100", False), ("900", False),
        ],
    },
    {
        "text": "What is 6²?",
        "difficulty": 1,
        "answers": [
            ("36", True), ("12", False), ("66", False), ("46", False),
        ],
    },
    {
        "text": "What is 11²?",
        "difficulty": 1,
        "answers": [
            ("121", True), ("22", False), ("111", False), ("112", False),
        ],
    },
    {
        "text": "1225 = 35 × 35. What is √1225?",
        "difficulty": 1,
        "answers": [
            ("35", True), ("25", False), ("45", False), ("55", False),
        ],
    },
    {
        "text": "484 = 2 × 2 × 11 × 11. What is √484?",
        "difficulty": 2,
        "answers": [
            ("22", True), ("44", False), ("11", False), ("4", False),
        ],
    },
    {
        "text": "289 has exactly three factors: 1, 17, and 289. Why does this confirm 289 is a perfect square?",
        "difficulty": 2,
        "answers": [
            ("Because 17 × 17 = 289, giving a whole-number square root", True),
            ("Because it has an odd number of factors", False),
            ("Because 289 is divisible by 3", False),
            ("Because all numbers with three factors are perfect squares", False),
        ],
    },
    {
        "text": "When you square an odd number, the result is always…",
        "difficulty": 2,
        "answers": [
            ("Odd", True), ("Even", False), ("Prime", False), ("A multiple of 4", False),
        ],
    },
    {
        "text": "Are 0 and 1 both square numbers?",
        "difficulty": 2,
        "answers": [
            ("Yes — 0 = 0² and 1 = 1²", True),
            ("No — neither is a square number", False),
            ("Only 1 is a square number", False),
            ("Only 0 is a square number", False),
        ],
    },
    {
        "text": "The prime factorisation of a number is 3 × 3 × 5 × 5 × 7 × 7. Is this number a perfect square?",
        "difficulty": 2,
        "answers": [
            ("Yes — every prime factor appears an even number of times", True),
            ("No — it has too many prime factors", False),
            ("No — it is only a perfect square if it has two prime factors", False),
            ("Cannot be determined without calculating", False),
        ],
    },
    {
        "text": "3969 = 3 × 3 × 3 × 3 × 7 × 7. Which statement is correct?",
        "difficulty": 3,
        "answers": [
            ("3969 is a perfect square because all prime factors appear an even number of times", True),
            ("3969 is not a perfect square because it has more than two distinct prime factors", False),
            ("3969 is a perfect square only if 3 appears twice in the factorisation", False),
            ("3969 cannot be a perfect square since it is odd", False),
        ],
    },
]

# ---------------------------------------------------------------------------
SQUARE_ROOTS_QUESTIONS = [
    {
        "text": "What is √4?",
        "difficulty": 1,
        "answers": [
            ("2", True), ("4", False), ("8", False), ("16", False),
        ],
    },
    {
        "text": "What is √81?",
        "difficulty": 1,
        "answers": [
            ("9", True), ("8", False), ("7", False), ("11", False),
        ],
    },
    {
        "text": "√(31 × 31) equals…",
        "difficulty": 1,
        "answers": [
            ("31", True), ("31²", False), ("961", False), ("62", False),
        ],
    },
    {
        "text": "What is √400?",
        "difficulty": 1,
        "answers": [
            ("20", True), ("40", False), ("200", False), ("4", False),
        ],
    },
    {
        "text": "32² = 1024. What is √1024?",
        "difficulty": 1,
        "answers": [
            ("32", True), ("64", False), ("16", False), ("31", False),
        ],
    },
    {
        "text": "A square gymnastics mat has an area of 169 m². What is the side length?",
        "difficulty": 2,
        "answers": [
            ("13 m", True), ("14 m", False), ("12 m", False), ("84.5 m", False),
        ],
    },
    {
        "text": "The square root of a perfect square is 11. What is the perfect square?",
        "difficulty": 2,
        "answers": [
            ("121", True), ("22", False), ("111", False), ("110", False),
        ],
    },
    {
        "text": "A square weightlifting platform has an area of 16 m². What is its perimeter?",
        "difficulty": 2,
        "answers": [
            ("16 m", True), ("4 m", False), ("64 m", False), ("8 m", False),
        ],
    },
    {
        "text": "Between which two consecutive whole numbers does √50 lie?",
        "difficulty": 2,
        "answers": [
            ("7 and 8", True), ("6 and 7", False), ("5 and 6", False), ("8 and 9", False),
        ],
    },
    {
        "text": "A square field has an area of 3000 m². Which best estimates the side length?",
        "difficulty": 2,
        "answers": [
            ("Between 50 m and 60 m", True),
            ("Between 40 m and 50 m", False),
            ("Between 60 m and 70 m", False),
            ("Exactly 55 m", False),
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
        'square-and-triangular-numbers': PERFECT_SQUARES_QUESTIONS,
        'square-roots':                  SQUARE_ROOTS_QUESTIONS,
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
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in PERFECT_SQUARES_QUESTIONS]
        + [q['text'] for q in SQUARE_ROOTS_QUESTIONS]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0019_seed_quadratics_se_exam'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
