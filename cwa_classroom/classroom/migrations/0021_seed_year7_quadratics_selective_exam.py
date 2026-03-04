"""
Migration 0021 — Selective Entrance Exam Quadratic.pdf:
  Expanding and Factorising Quadratics (Y7): +10 new factorising x²+bx+c questions
  Expanding and Factorising Quadratics (Y7): +10 solving-by-factoring questions
  Factorising Harder Quadratics (Y7)        : +5 new ax²+bx+c questions
  Quadratic Formula (Y7)                    : +5 new questions (rational roots)
All assigned to Year 7.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# New factorising questions — x² + bx + c form (simple quadratics)
# ---------------------------------------------------------------------------
FACTORISE_SIMPLE_NEW = [
    {
        "text": "Factorise x² − 6x + 5",
        "difficulty": 1,
        "answers": [
            ("(x − 5)(x − 1)", True), ("(x + 5)(x + 1)", False),
            ("(x − 5)(x + 1)", False), ("(x − 3)(x − 2)", False),
        ],
    },
    {
        "text": "Factorise x² − 6x − 7",
        "difficulty": 1,
        "answers": [
            ("(x − 7)(x + 1)", True), ("(x + 7)(x − 1)", False),
            ("(x − 7)(x − 1)", False), ("(x − 3)(x − 4)", False),
        ],
    },
    {
        "text": "Factorise x² + 4x − 5",
        "difficulty": 1,
        "answers": [
            ("(x + 5)(x − 1)", True), ("(x − 5)(x + 1)", False),
            ("(x + 5)(x + 1)", False), ("(x + 4)(x − 5)", False),
        ],
    },
    {
        "text": "Factorise x² − 4x − 5",
        "difficulty": 1,
        "answers": [
            ("(x − 5)(x + 1)", True), ("(x + 5)(x − 1)", False),
            ("(x − 5)(x − 1)", False), ("(x − 4)(x + 5)", False),
        ],
    },
    {
        "text": "Factorise x² − 2x − 63",
        "difficulty": 2,
        "answers": [
            ("(x − 9)(x + 7)", True), ("(x + 9)(x − 7)", False),
            ("(x − 7)(x + 9)", False), ("(x − 63)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise x² − 64",
        "difficulty": 2,
        "answers": [
            ("(x + 8)(x − 8)", True), ("(x − 8)²", False),
            ("(x + 8)²", False), ("(x − 4)(x + 16)", False),
        ],
    },
    {
        "text": "Factorise x² + 10x − 96",
        "difficulty": 2,
        "answers": [
            ("(x + 16)(x − 6)", True), ("(x − 16)(x + 6)", False),
            ("(x + 8)(x − 12)", False), ("(x + 12)(x − 8)", False),
        ],
    },
    {
        "text": "Factorise x² + 4x − 45",
        "difficulty": 2,
        "answers": [
            ("(x + 9)(x − 5)", True), ("(x − 9)(x + 5)", False),
            ("(x + 15)(x − 3)", False), ("(x + 45)(x − 1)", False),
        ],
    },
    {
        "text": "Factorise x² + 9x − 36",
        "difficulty": 2,
        "answers": [
            ("(x + 12)(x − 3)", True), ("(x − 12)(x + 3)", False),
            ("(x + 9)(x − 4)", False), ("(x + 6)(x − 6)", False),
        ],
    },
    {
        "text": "Factorise x² + 11x − 80",
        "difficulty": 3,
        "answers": [
            ("(x + 16)(x − 5)", True), ("(x − 16)(x + 5)", False),
            ("(x + 20)(x − 4)", False), ("(x + 11)(x − 80)", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Solving quadratics by factoring — rearrange then solve
# ---------------------------------------------------------------------------
SOLVING_BY_FACTORING_NEW = [
    {
        "text": "Solve (x + 8)(x + 6) = 0",
        "difficulty": 1,
        "answers": [
            ("x = −8 or x = −6", True), ("x = 8 or x = 6", False),
            ("x = −8 or x = 6", False), ("x = 8 or x = −6", False),
        ],
    },
    {
        "text": "Solve x(x − 5) = 0",
        "difficulty": 1,
        "answers": [
            ("x = 0 or x = 5", True), ("x = 5", False),
            ("x = 0 or x = −5", False), ("x = 0", False),
        ],
    },
    {
        "text": "Solve (2x + 5)(x − 3) = 0",
        "difficulty": 2,
        "answers": [
            ("x = −5/2 or x = 3", True), ("x = 5/2 or x = −3", False),
            ("x = −5 or x = 3", False), ("x = 5/2 or x = 3", False),
        ],
    },
    {
        "text": "Solve x² + 7x − 18 = 0",
        "difficulty": 2,
        "answers": [
            ("x = −9 or x = 2", True), ("x = 9 or x = −2", False),
            ("x = −18 or x = 1", False), ("x = 7 or x = −18", False),
        ],
    },
    {
        "text": "Solve x² − 49 = 0",
        "difficulty": 1,
        "answers": [
            ("x = 7 or x = −7", True), ("x = 49", False),
            ("x = 7", False), ("x = −49 or x = 1", False),
        ],
    },
    {
        "text": "Solve x² + 10x + 25 = 0",
        "difficulty": 2,
        "answers": [
            ("x = −5", True), ("x = 5 or x = −5", False),
            ("x = −5 or x = −5 (two distinct roots)", False), ("x = 5", False),
        ],
    },
    {
        "text": "Solve x² − x = 42 (rearrange first)",
        "difficulty": 2,
        "answers": [
            ("x = 7 or x = −6", True), ("x = 6 or x = −7", False),
            ("x = 7 or x = 6", False), ("x = −7 or x = −6", False),
        ],
    },
    {
        "text": "Solve x² − 2x = 63 (rearrange first)",
        "difficulty": 2,
        "answers": [
            ("x = 9 or x = −7", True), ("x = −9 or x = 7", False),
            ("x = 9 or x = 7", False), ("x = 63 or x = −2", False),
        ],
    },
    {
        "text": "Solve y(y − 5) = 14",
        "difficulty": 2,
        "answers": [
            ("y = 7 or y = −2", True), ("y = −7 or y = 2", False),
            ("y = 14 or y = 5", False), ("y = 7 or y = 2", False),
        ],
    },
    {
        "text": "Solve 7m² = 8m (rearrange first)",
        "difficulty": 3,
        "answers": [
            ("m = 0 or m = 8/7", True), ("m = 8/7", False),
            ("m = 0 or m = 7/8", False), ("m = 1 or m = 8/7", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Factorising Harder Quadratics — new questions (ax² + bx + c)
# ---------------------------------------------------------------------------
HARDER_QUADRATICS_NEW = [
    {
        "text": "Factorise 7x² − 15x + 2",
        "difficulty": 2,
        "answers": [
            ("(7x − 1)(x − 2)", True), ("(7x − 2)(x − 1)", False),
            ("(7x + 1)(x + 2)", False), ("(7x − 1)(x + 2)", False),
        ],
    },
    {
        "text": "Factorise 8x² − 6x + 1",
        "difficulty": 2,
        "answers": [
            ("(4x − 1)(2x − 1)", True), ("(8x − 1)(x − 1)", False),
            ("(4x + 1)(2x − 1)", False), ("(4x − 1)(2x + 1)", False),
        ],
    },
    {
        "text": "Factorise 9x² + 3x − 2",
        "difficulty": 2,
        "answers": [
            ("(3x − 1)(3x + 2)", True), ("(9x − 1)(x + 2)", False),
            ("(3x + 1)(3x − 2)", False), ("(9x + 1)(x − 2)", False),
        ],
    },
    {
        "text": "Factorise 2x² − 5x − 3",
        "difficulty": 2,
        "answers": [
            ("(2x + 1)(x − 3)", True), ("(2x − 1)(x + 3)", False),
            ("(2x − 3)(x + 1)", False), ("(2x + 3)(x − 1)", False),
        ],
    },
    {
        "text": "Factorise 3x² + 7x + 2",
        "difficulty": 2,
        "answers": [
            ("(3x + 1)(x + 2)", True), ("(3x + 2)(x + 1)", False),
            ("(3x − 1)(x − 2)", False), ("(x + 2)(3x − 1)", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Quadratic Formula — new questions with rational solutions
# ---------------------------------------------------------------------------
QUADRATIC_FORMULA_NEW = [
    {
        "text": "Solve x² + 10x + 9 = 0 using the quadratic formula.",
        "difficulty": 1,
        "answers": [
            ("x = −1 or x = −9", True), ("x = 1 or x = 9", False),
            ("x = −1 or x = 9", False), ("x = −2 or x = −9", False),
        ],
    },
    {
        "text": "Solve 2x² + 4x − 6 = 0 using the quadratic formula.",
        "difficulty": 2,
        "answers": [
            ("x = 1 or x = −3", True), ("x = −1 or x = 3", False),
            ("x = 1 or x = 3", False), ("x = −1 or x = −3", False),
        ],
    },
    {
        "text": "Solve 2x² + 3x + 1 = 0 using the quadratic formula.",
        "difficulty": 2,
        "answers": [
            ("x = −1/2 or x = −1", True), ("x = 1/2 or x = 1", False),
            ("x = −3/4 or x = −1", False), ("x = −1/2 or x = 1", False),
        ],
    },
    {
        "text": "Solve 5x² + 31x + 6 = 0 using the quadratic formula. (Hint: discriminant = 841)",
        "difficulty": 3,
        "answers": [
            ("x = −1/5 or x = −6", True), ("x = 1/5 or x = 6", False),
            ("x = −1/5 or x = 6", False), ("x = −6/5 or x = −1", False),
        ],
    },
    {
        "text": "Solve x² − 7x − 60 = 0 using the quadratic formula. (Hint: discriminant = 289)",
        "difficulty": 3,
        "answers": [
            ("x = 12 or x = −5", True), ("x = −12 or x = 5", False),
            ("x = 7 or x = −60", False), ("x = 12 or x = 5", False),
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
        'expanding-and-factorising-quadratics': FACTORISE_SIMPLE_NEW + SOLVING_BY_FACTORING_NEW,
        'factorising-harder-quadratics':        HARDER_QUADRATICS_NEW,
        'quadratic-formula':                    QUADRATIC_FORMULA_NEW,
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
        [q['text'] for q in FACTORISE_SIMPLE_NEW]
        + [q['text'] for q in SOLVING_BY_FACTORING_NEW]
        + [q['text'] for q in HARDER_QUADRATICS_NEW]
        + [q['text'] for q in QUADRATIC_FORMULA_NEW]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0020_seed_year7_square_roots_g7week5'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
