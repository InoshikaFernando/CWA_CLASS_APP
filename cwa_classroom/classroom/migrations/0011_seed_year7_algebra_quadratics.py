"""
Migration 0011 — Year 7 Algebra update:
  1. Move 'Factors' subtopic from Algebra strand → Number strand
  2. Create 'Expanding and Factorising Quadratics' under Algebra for Year 7
     (questions sourced from Selective Quadratics Exam worksheet, pages 1-15)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# Questions for Expanding and Factorising Quadratics
# ---------------------------------------------------------------------------

EXPANDING_QUESTIONS = [
    {
        "text": "Expand (x + 3)(x + 5)",
        "difficulty": 1,
        "answers": [
            ("x² + 8x + 15", True),
            ("x² + 15x + 8", False),
            ("x² + 8x + 8",  False),
            ("x² + 15",      False),
        ],
    },
    {
        "text": "Expand (x + 2)(x + 7)",
        "difficulty": 1,
        "answers": [
            ("x² + 9x + 14", True),
            ("x² + 7x + 14", False),
            ("x² + 14x + 9", False),
            ("x² + 9x + 9",  False),
        ],
    },
    {
        "text": "Expand (x + 4)(x + 6)",
        "difficulty": 1,
        "answers": [
            ("x² + 10x + 24", True),
            ("x² + 24x + 10", False),
            ("x² + 10x + 10", False),
            ("x² + 24",       False),
        ],
    },
    {
        "text": "Expand (x − 3)(x + 5)",
        "difficulty": 2,
        "answers": [
            ("x² + 2x − 15", True),
            ("x² − 2x − 15", False),
            ("x² + 2x + 15", False),
            ("x² − 15",      False),
        ],
    },
    {
        "text": "Expand (x − 4)(x − 2)",
        "difficulty": 2,
        "answers": [
            ("x² − 6x + 8",  True),
            ("x² + 6x + 8",  False),
            ("x² − 6x − 8",  False),
            ("x² − 8x + 6",  False),
        ],
    },
    {
        "text": "Expand (x + 1)(x − 9)",
        "difficulty": 2,
        "answers": [
            ("x² − 8x − 9",  True),
            ("x² + 8x − 9",  False),
            ("x² − 8x + 9",  False),
            ("x² − 9",       False),
        ],
    },
    {
        "text": "Expand (x + 5)(x + 5)",
        "difficulty": 2,
        "answers": [
            ("x² + 10x + 25", True),
            ("x² + 25",       False),
            ("x² + 5x + 25",  False),
            ("x² + 10x + 10", False),
        ],
    },
    {
        "text": "Expand (x − 6)(x + 6)",
        "difficulty": 2,
        "answers": [
            ("x² − 36",      True),
            ("x² + 36",      False),
            ("x² − 12x − 36", False),
            ("x² + 12x − 36", False),
        ],
    },
    {
        "text": "Expand (x + 3)(x − 7)",
        "difficulty": 2,
        "answers": [
            ("x² − 4x − 21", True),
            ("x² + 4x − 21", False),
            ("x² − 4x + 21", False),
            ("x² − 21",      False),
        ],
    },
    {
        "text": "Which expansion is correct for (x − 5)(x − 3)?",
        "difficulty": 3,
        "answers": [
            ("x² − 8x + 15", True),
            ("x² + 8x + 15", False),
            ("x² − 8x − 15", False),
            ("x² − 15x + 8", False),
        ],
    },
]

FACTORISING_QUESTIONS = [
    {
        "text": "Factorise x² + 7x + 12",
        "difficulty": 1,
        "answers": [
            ("(x + 3)(x + 4)", True),
            ("(x + 2)(x + 6)", False),
            ("(x + 1)(x + 12)", False),
            ("(x + 4)(x + 4)", False),
        ],
    },
    {
        "text": "Factorise x² + 9x + 20",
        "difficulty": 1,
        "answers": [
            ("(x + 4)(x + 5)", True),
            ("(x + 2)(x + 10)", False),
            ("(x + 1)(x + 20)", False),
            ("(x + 3)(x + 7)",  False),
        ],
    },
    {
        "text": "Factorise x² + 6x + 8",
        "difficulty": 1,
        "answers": [
            ("(x + 2)(x + 4)", True),
            ("(x + 1)(x + 8)", False),
            ("(x + 3)(x + 3)", False),
            ("(x + 2)(x + 6)", False),
        ],
    },
    {
        "text": "Factorise x² − 5x + 6",
        "difficulty": 2,
        "answers": [
            ("(x − 2)(x − 3)", True),
            ("(x + 2)(x − 3)", False),
            ("(x − 6)(x + 1)", False),
            ("(x − 1)(x + 6)", False),
        ],
    },
    {
        "text": "Factorise x² + x − 12",
        "difficulty": 2,
        "answers": [
            ("(x + 4)(x − 3)", True),
            ("(x − 4)(x + 3)", False),
            ("(x + 6)(x − 2)", False),
            ("(x − 6)(x + 2)", False),
        ],
    },
    {
        "text": "Factorise x² − 2x − 15",
        "difficulty": 2,
        "answers": [
            ("(x − 5)(x + 3)", True),
            ("(x + 5)(x − 3)", False),
            ("(x − 15)(x + 1)", False),
            ("(x + 15)(x − 1)", False),
        ],
    },
    {
        "text": "Factorise x² − 9",
        "difficulty": 2,
        "answers": [
            ("(x − 3)(x + 3)", True),
            ("(x − 9)(x + 1)", False),
            ("(x − 3)²",       False),
            ("(x + 3)²",       False),
        ],
    },
    {
        "text": "Factorise x² − 8x + 16",
        "difficulty": 2,
        "answers": [
            ("(x − 4)²",       True),
            ("(x − 4)(x + 4)", False),
            ("(x − 2)(x − 8)", False),
            ("(x + 4)²",       False),
        ],
    },
    {
        "text": "Factorise x² + 3x − 18",
        "difficulty": 3,
        "answers": [
            ("(x + 6)(x − 3)", True),
            ("(x − 6)(x + 3)", False),
            ("(x + 9)(x − 2)", False),
            ("(x − 9)(x + 2)", False),
        ],
    },
    {
        "text": "Which factorisation of x² − 7x + 10 is correct?",
        "difficulty": 3,
        "answers": [
            ("(x − 2)(x − 5)", True),
            ("(x + 2)(x + 5)", False),
            ("(x − 10)(x + 1)", False),
            ("(x − 1)(x + 10)", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    Level   = apps.get_model('classroom', 'Level')
    Question = apps.get_model('maths', 'Question')
    Answer   = apps.get_model('maths', 'Answer')

    maths = Subject.objects.get(slug='mathematics')
    year7 = Level.objects.filter(level_number=7).first()

    # ------------------------------------------------------------------
    # 1. Move Factors from Algebra → Number strand
    # ------------------------------------------------------------------
    try:
        algebra_strand = Topic.objects.get(subject=maths, slug='algebra', parent=None)
        number_strand  = Topic.objects.get(subject=maths, slug='number',  parent=None)
        factors = Topic.objects.get(subject=maths, slug='factors', parent=algebra_strand)
        factors.parent = number_strand
        factors.save(update_fields=['parent'])
    except Topic.DoesNotExist:
        pass  # already moved or doesn't exist yet

    # ------------------------------------------------------------------
    # 2. Create 'Expanding and Factorising Quadratics' under Algebra, Y7
    # ------------------------------------------------------------------
    try:
        algebra_strand = Topic.objects.get(subject=maths, slug='algebra', parent=None)
    except Topic.DoesNotExist:
        return  # nothing to do

    quadratics, _ = Topic.objects.get_or_create(
        subject=maths,
        slug='expanding-and-factorising-quadratics',
        defaults={
            'name':      'Expanding and Factorising Quadratics',
            'order':     10,
            'is_active': True,
            'parent':    algebra_strand,
        },
    )
    if year7:
        quadratics.levels.add(year7)

    # Helper to add questions idempotently
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

    if year7:
        add_questions(quadratics, EXPANDING_QUESTIONS)
        add_questions(quadratics, FACTORISING_QUESTIONS)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    # Move Factors back to Algebra
    try:
        algebra_strand = Topic.objects.get(subject=maths, slug='algebra', parent=None)
        factors = Topic.objects.get(subject=maths, slug='factors')
        factors.parent = algebra_strand
        factors.save(update_fields=['parent'])
    except Topic.DoesNotExist:
        pass

    # Remove the quadratics subtopic (cascades to questions/answers)
    Topic.objects.filter(subject=maths, slug='expanding-and-factorising-quadratics').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0010_seed_year7_computation_integers'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
