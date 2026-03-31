"""
Migration 0014 — Algebra strand additions:
  - Linear Equations        (Year 8, 10 questions)
  - Simultaneous Equations  (Year 8, 10 questions)
  - Indices and Powers      (Year 7 × 5 + Year 8 × 5 = 10 questions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
LINEAR_EQUATIONS_QUESTIONS = [
    {
        "text": "Solve: 3x + 5 = 20",
        "difficulty": 1,
        "answers": [
            ("x = 5", True), ("x = 8", False), ("x = 3", False), ("x = 25", False),
        ],
    },
    {
        "text": "Solve: 2x − 7 = 11",
        "difficulty": 1,
        "answers": [
            ("x = 9", True), ("x = 2", False), ("x = 18", False), ("x = 4", False),
        ],
    },
    {
        "text": "Solve: x/4 + 3 = 7",
        "difficulty": 1,
        "answers": [
            ("x = 16", True), ("x = 1", False), ("x = 10", False), ("x = 40", False),
        ],
    },
    {
        "text": "Solve: 4(x − 2) = 20",
        "difficulty": 2,
        "answers": [
            ("x = 7", True), ("x = 5", False), ("x = 18", False), ("x = 3", False),
        ],
    },
    {
        "text": "Solve: 2x + 5 = x + 9",
        "difficulty": 2,
        "answers": [
            ("x = 4", True), ("x = 2", False), ("x = 14", False), ("x = 7", False),
        ],
    },
    {
        "text": "Solve: 3(2x + 1) = 27",
        "difficulty": 2,
        "answers": [
            ("x = 4", True), ("x = 4.5", False), ("x = 9", False), ("x = 13", False),
        ],
    },
    {
        "text": "A number increased by 12 equals three times the number. What is the number?",
        "difficulty": 2,
        "answers": [
            ("6", True), ("12", False), ("3", False), ("4", False),
        ],
    },
    {
        "text": "Solve: (x + 3)/2 = (x − 1)/3",
        "difficulty": 3,
        "answers": [
            ("x = −11", True), ("x = 5", False), ("x = 3", False), ("x = 1", False),
        ],
    },
    {
        "text": "A rectangle has perimeter 46 cm. Its length is 5 cm more than its width. What is the width?",
        "difficulty": 3,
        "answers": [
            ("9 cm", True), ("14 cm", False), ("7 cm", False), ("18 cm", False),
        ],
    },
    {
        "text": "If 5 times a number minus 8 equals 3 times the number plus 10, what is the number?",
        "difficulty": 3,
        "answers": [
            ("9", True), ("1", False), ("18", False), ("6", False),
        ],
    },
]

SIMULTANEOUS_EQUATIONS_QUESTIONS = [
    {
        "text": "Solve: x + y = 10 and x − y = 4. What is x?",
        "difficulty": 1,
        "answers": [
            ("x = 7", True), ("x = 3", False), ("x = 6", False), ("x = 5", False),
        ],
    },
    {
        "text": "Solve: x + y = 10 and x − y = 4. What is y?",
        "difficulty": 1,
        "answers": [
            ("y = 3", True), ("y = 7", False), ("y = 6", False), ("y = 4", False),
        ],
    },
    {
        "text": "Solve: 2x + y = 11 and x + y = 7. What is x?",
        "difficulty": 2,
        "answers": [
            ("x = 4", True), ("x = 3", False), ("x = 9", False), ("x = 6", False),
        ],
    },
    {
        "text": "If 2a + 3b = 13 and a + b = 5, find b.",
        "difficulty": 2,
        "answers": [
            ("b = 3", True), ("b = 2", False), ("b = 4", False), ("b = 8", False),
        ],
    },
    {
        "text": "A DVD costs $d and a CD costs $c. Given 5d + 2c = $179 and d + 2c = $67, find the cost of a DVD.",
        "difficulty": 2,
        "answers": [
            ("$28", True), ("$35", False), ("$22", False), ("$39", False),
        ],
    },
    {
        "text": "Solve: 3x + 2y = 16 and x + y = 6. Find x.",
        "difficulty": 2,
        "answers": [
            ("x = 4", True), ("x = 6", False), ("x = 2", False), ("x = 3", False),
        ],
    },
    {
        "text": "Two adult and one child ticket costs $35. One adult and two child tickets costs $28. Find the adult ticket price.",
        "difficulty": 2,
        "answers": [
            ("$14", True), ("$21", False), ("$7", False), ("$18", False),
        ],
    },
    {
        "text": "Solve: y = 2x + 1 and y = x + 5. Find x.",
        "difficulty": 2,
        "answers": [
            ("x = 4", True), ("x = 3", False), ("x = 6", False), ("x = 2", False),
        ],
    },
    {
        "text": "The sum of two numbers is 20 and their difference is 6. What is the larger number?",
        "difficulty": 3,
        "answers": [
            ("13", True), ("7", False), ("14", False), ("10", False),
        ],
    },
    {
        "text": "Solve: 2x + 3y = 12 and 4x − 3y = 6. Find y.",
        "difficulty": 3,
        "answers": [
            ("y = 2", True), ("y = 4", False), ("y = 3", False), ("y = 1", False),
        ],
    },
]

# Indices: first 5 = Year 7 (basic), last 5 = Year 8 (advanced)
INDICES_Y7_QUESTIONS = [
    {
        "text": "What is 3⁴?",
        "difficulty": 1,
        "answers": [
            ("81", True), ("12", False), ("64", False), ("27", False),
        ],
    },
    {
        "text": "What is 2⁵?",
        "difficulty": 1,
        "answers": [
            ("32", True), ("10", False), ("25", False), ("64", False),
        ],
    },
    {
        "text": "What is the value of any number raised to the power of 0 (e.g. 7⁰)?",
        "difficulty": 1,
        "answers": [
            ("1", True), ("0", False), ("7", False), ("Undefined", False),
        ],
    },
    {
        "text": "Simplify: 5² × 5³",
        "difficulty": 2,
        "answers": [
            ("5⁵", True), ("5⁶", False), ("25⁵", False), ("10⁵", False),
        ],
    },
    {
        "text": "Simplify: 4⁶ ÷ 4²",
        "difficulty": 2,
        "answers": [
            ("4⁴", True), ("4³", False), ("4⁸", False), ("1⁴", False),
        ],
    },
]

INDICES_Y8_QUESTIONS = [
    {
        "text": "Simplify: (3²)³",
        "difficulty": 2,
        "answers": [
            ("3⁶", True), ("3⁵", False), ("9⁶", False), ("6³", False),
        ],
    },
    {
        "text": "Evaluate: 2³ × 3²",
        "difficulty": 2,
        "answers": [
            ("72", True), ("216", False), ("36", False), ("18", False),
        ],
    },
    {
        "text": "A square has area 144 cm². What is its side length?",
        "difficulty": 2,
        "answers": [
            ("12 cm", True), ("11 cm", False), ("13 cm", False), ("72 cm", False),
        ],
    },
    {
        "text": "Solve: 104 − x³ = 96",
        "difficulty": 3,
        "answers": [
            ("x = 2", True), ("x = 8", False), ("x = 4", False), ("x = 3", False),
        ],
    },
    {
        "text": "Evaluate: 2⁴ + 3² − 5¹",
        "difficulty": 3,
        "answers": [
            ("20", True), ("12", False), ("14", False), ("8", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('quiz', 'Question')
    Answer   = apps.get_model('quiz', 'Answer')

    maths  = Subject.objects.get(slug='mathematics')
    year7  = Level.objects.filter(level_number=7).first()
    year8  = Level.objects.filter(level_number=8).first()

    try:
        algebra_strand = Topic.objects.get(subject=maths, slug='algebra', parent=None)
    except Topic.DoesNotExist:
        return

    def add_questions(subtopic, q_list, level):
        for q_data in q_list:
            q, created = Question.objects.get_or_create(
                topic=subtopic,
                level=level,
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

    # --- Linear Equations (Year 8) ---
    linear, _ = Topic.objects.get_or_create(
        subject=maths, slug='linear-equations',
        defaults={'name': 'Linear Equations', 'order': 3, 'is_active': True, 'parent': algebra_strand},
    )
    if year8:
        linear.levels.add(year8)
        add_questions(linear, LINEAR_EQUATIONS_QUESTIONS, year8)

    # --- Simultaneous Equations (Year 8) ---
    simultaneous, _ = Topic.objects.get_or_create(
        subject=maths, slug='simultaneous-equations',
        defaults={'name': 'Simultaneous Equations', 'order': 4, 'is_active': True, 'parent': algebra_strand},
    )
    if year8:
        simultaneous.levels.add(year8)
        add_questions(simultaneous, SIMULTANEOUS_EQUATIONS_QUESTIONS, year8)

    # --- Indices and Powers (Year 7 + Year 8) ---
    indices, _ = Topic.objects.get_or_create(
        subject=maths, slug='indices-and-powers',
        defaults={'name': 'Indices and Powers', 'order': 5, 'is_active': True, 'parent': algebra_strand},
    )
    if year7:
        indices.levels.add(year7)
        add_questions(indices, INDICES_Y7_QUESTIONS, year7)
    if year8:
        indices.levels.add(year8)
        add_questions(indices, INDICES_Y8_QUESTIONS, year8)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    maths   = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return
    for slug in ('linear-equations', 'simultaneous-equations', 'indices-and-powers'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0013_seed_measurement_subtopics'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
