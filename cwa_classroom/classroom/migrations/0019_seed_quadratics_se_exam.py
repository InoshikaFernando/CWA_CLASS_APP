"""
Migration 0019 — SE Quadratics + Exam PDF content:
  Expanding and Factorising Quadratics (Y7): +20 new expand/factorise questions
  Expanding and Factorising Quadratics (Y7): +10 solving-by-factorising questions
  Factorising Harder Quadratics           : new subtopic, Year 7, 10 questions
  Quadratic Formula                       : new subtopic, Year 7, 10 questions
  Completing the Square                   : new subtopic, Year 8, 10 questions
  Probability / Ratios / Finance          : +5 questions from Year 8 exam section
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# Expanding and Factorising Quadratics — new Year 7 questions (pages 1-4)
# ---------------------------------------------------------------------------
QUADRATICS_Y7_NEW = [
    # --- Factorising ---
    {
        "text": "Factorise x² + 10x + 21",
        "difficulty": 1,
        "answers": [
            ("(x + 7)(x + 3)", True), ("(x + 5)(x + 6)", False),
            ("(x + 3)(x + 3)", False), ("(x + 21)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise x² + 14x + 24",
        "difficulty": 2,
        "answers": [
            ("(x + 12)(x + 2)", True), ("(x + 8)(x + 6)", False),
            ("(x + 6)(x + 4)", False), ("(x + 12)(x + 12)", False),
        ],
    },
    {
        "text": "Factorise x² − 11x + 18",
        "difficulty": 2,
        "answers": [
            ("(x − 9)(x − 2)", True), ("(x − 6)(x − 3)", False),
            ("(x − 9)(x + 2)", False), ("(x + 9)(x + 2)", False),
        ],
    },
    {
        "text": "Factorise x² + 3x − 10",
        "difficulty": 2,
        "answers": [
            ("(x + 5)(x − 2)", True), ("(x − 5)(x + 2)", False),
            ("(x + 10)(x − 1)", False), ("(x + 2)(x + 5)", False),
        ],
    },
    {
        "text": "Factorise x² + 11x + 18",
        "difficulty": 2,
        "answers": [
            ("(x + 9)(x + 2)", True), ("(x + 6)(x + 3)", False),
            ("(x + 11)(x + 1)", False), ("(x + 9)(x − 2)", False),
        ],
    },
    {
        "text": "Factorise x² − 4x − 21",
        "difficulty": 2,
        "answers": [
            ("(x − 7)(x + 3)", True), ("(x + 7)(x − 3)", False),
            ("(x − 21)(x + 1)", False), ("(x − 4)(x + 21)", False),
        ],
    },
    {
        "text": "Factorise x² − 8x − 9",
        "difficulty": 2,
        "answers": [
            ("(x − 9)(x + 1)", True), ("(x + 9)(x − 1)", False),
            ("(x − 3)(x + 3)", False), ("(x − 9)(x − 1)", False),
        ],
    },
    {
        "text": "Factorise x² − 6x + 9",
        "difficulty": 2,
        "answers": [
            ("(x − 3)²", True), ("(x + 3)²", False),
            ("(x − 3)(x + 3)", False), ("(x − 9)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise x² + x − 20",
        "difficulty": 2,
        "answers": [
            ("(x + 5)(x − 4)", True), ("(x − 5)(x + 4)", False),
            ("(x + 20)(x − 1)", False), ("(x − 20)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise x² − x − 6",
        "difficulty": 2,
        "answers": [
            ("(x − 3)(x + 2)", True), ("(x + 3)(x − 2)", False),
            ("(x − 6)(x + 1)", False), ("(x + 6)(x − 1)", False),
        ],
    },
    # --- Expanding ---
    {
        "text": "Expand (x − 3)(x + 6)",
        "difficulty": 1,
        "answers": [
            ("x² + 3x − 18", True), ("x² − 3x − 18", False),
            ("x² + 3x + 18", False), ("x² − 9x − 18", False),
        ],
    },
    {
        "text": "Expand (x + 4)(x − 5)",
        "difficulty": 1,
        "answers": [
            ("x² − x − 20", True), ("x² + x − 20", False),
            ("x² − x + 20", False), ("x² + 9x − 20", False),
        ],
    },
    {
        "text": "Expand (x − 3)(x − 2)",
        "difficulty": 1,
        "answers": [
            ("x² − 5x + 6", True), ("x² + 5x + 6", False),
            ("x² − 5x − 6", False), ("x² − x + 6", False),
        ],
    },
    {
        "text": "Expand (x + 3)(x + 7)",
        "difficulty": 1,
        "answers": [
            ("x² + 10x + 21", True), ("x² + 21x + 10", False),
            ("x² + 10x + 10", False), ("x² + 4x + 21", False),
        ],
    },
    {
        "text": "Expand (x − 5)(x + 1)",
        "difficulty": 2,
        "answers": [
            ("x² − 4x − 5", True), ("x² + 4x − 5", False),
            ("x² − 4x + 5", False), ("x² − 5x − 5", False),
        ],
    },
    {
        "text": "Expand (x + 9)(x − 4)",
        "difficulty": 2,
        "answers": [
            ("x² + 5x − 36", True), ("x² − 5x − 36", False),
            ("x² + 5x + 36", False), ("x² + 13x − 36", False),
        ],
    },
    {
        "text": "Expand (x + 4)(x + 7)",
        "difficulty": 2,
        "answers": [
            ("x² + 11x + 28", True), ("x² + 28x + 11", False),
            ("x² + 3x + 28", False), ("x² + 11x − 28", False),
        ],
    },
    {
        "text": "Expand (x − 4)(x − 3)",
        "difficulty": 2,
        "answers": [
            ("x² − 7x + 12", True), ("x² + 7x + 12", False),
            ("x² − 7x − 12", False), ("x² − x + 12", False),
        ],
    },
    {
        "text": "Expand (x − 1)(x − 6)",
        "difficulty": 2,
        "answers": [
            ("x² − 7x + 6", True), ("x² + 7x + 6", False),
            ("x² − 7x − 6", False), ("x² − 5x + 6", False),
        ],
    },
    {
        "text": "Expand (x − 10)(x − 2)",
        "difficulty": 3,
        "answers": [
            ("x² − 12x + 20", True), ("x² + 12x + 20", False),
            ("x² − 12x − 20", False), ("x² − 8x + 20", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Solving Quadratics by Factorising — Year 8 extension (pages 9-10)
# ---------------------------------------------------------------------------
SOLVING_QUADRATICS_Y8 = [
    {
        "text": "Solve x² − 8x − 20 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 10 or x = −2", True), ("x = −10 or x = 2", False),
            ("x = 8 or x = −20", False), ("x = 4 or x = −5", False),
        ],
    },
    {
        "text": "Solve x² − x − 20 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 5 or x = −4", True), ("x = −5 or x = 4", False),
            ("x = 20 or x = −1", False), ("x = 4 or x = −5", False),
        ],
    },
    {
        "text": "Solve x² − x − 6 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 3 or x = −2", True), ("x = −3 or x = 2", False),
            ("x = 6 or x = −1", False), ("x = −3 or x = −2", False),
        ],
    },
    {
        "text": "Solve x² − 5x + 6 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 3 or x = 2", True), ("x = −3 or x = −2", False),
            ("x = 6 or x = −1", False), ("x = 5 or x = 1", False),
        ],
    },
    {
        "text": "Solve x² − 5x + 4 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 4 or x = 1", True), ("x = −4 or x = −1", False),
            ("x = 5 or x = −4", False), ("x = 2 or x = 2", False),
        ],
    },
    {
        "text": "Solve x² − 4x + 4 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 2 (repeated root)", True), ("x = 4 or x = 1", False),
            ("x = 2 or x = −2", False), ("x = −2 (repeated root)", False),
        ],
    },
    {
        "text": "Solve x² − 4x − 21 = 0",
        "difficulty": 2,
        "answers": [
            ("x = 7 or x = −3", True), ("x = −7 or x = 3", False),
            ("x = 21 or x = −1", False), ("x = 7 or x = 3", False),
        ],
    },
    {
        "text": "Solve x² − 3x − 40 = 0",
        "difficulty": 3,
        "answers": [
            ("x = 8 or x = −5", True), ("x = −8 or x = 5", False),
            ("x = 40 or x = −1", False), ("x = 10 or x = −4", False),
        ],
    },
    {
        "text": "Solve x² + 13x + 42 = 0",
        "difficulty": 3,
        "answers": [
            ("x = −6 or x = −7", True), ("x = 6 or x = 7", False),
            ("x = −42 or x = −1", False), ("x = −6 or x = 7", False),
        ],
    },
    {
        "text": "Solve x² + 2x − 15 = 0",
        "difficulty": 3,
        "answers": [
            ("x = 3 or x = −5", True), ("x = −3 or x = 5", False),
            ("x = 15 or x = −1", False), ("x = −3 or x = −5", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Factorising Harder Quadratics (ax² + bx + c) — new subtopic, Year 8
# ---------------------------------------------------------------------------
HARDER_QUADRATICS_QUESTIONS = [
    {
        "text": "Factorise 2x² + 7x + 6",
        "difficulty": 2,
        "answers": [
            ("(2x + 3)(x + 2)", True), ("(2x + 6)(x + 1)", False),
            ("(x + 3)(2x + 2)", False), ("(2x + 2)(x + 3)", False),
        ],
    },
    {
        "text": "Factorise 3x² + 19x + 6",
        "difficulty": 2,
        "answers": [
            ("(3x + 1)(x + 6)", True), ("(3x + 6)(x + 1)", False),
            ("(x + 3)(3x + 2)", False), ("(3x + 3)(x + 2)", False),
        ],
    },
    {
        "text": "Factorise 8x² + 6x − 9",
        "difficulty": 2,
        "answers": [
            ("(4x − 3)(2x + 3)", True), ("(4x + 3)(2x − 3)", False),
            ("(8x − 3)(x + 3)", False), ("(4x − 9)(2x + 1)", False),
        ],
    },
    {
        "text": "Factorise 5x² + 12x − 9",
        "difficulty": 2,
        "answers": [
            ("(5x − 3)(x + 3)", True), ("(5x + 3)(x − 3)", False),
            ("(x + 3)(5x − 3)", False), ("(5x − 9)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise 9x² − 9x − 10",
        "difficulty": 3,
        "answers": [
            ("(3x + 2)(3x − 5)", True), ("(9x + 2)(x − 5)", False),
            ("(3x − 2)(3x + 5)", False), ("(3x + 5)(3x − 2)", False),
        ],
    },
    {
        "text": "Factorise 6x² + x − 5",
        "difficulty": 3,
        "answers": [
            ("(6x − 5)(x + 1)", True), ("(6x + 5)(x − 1)", False),
            ("(2x − 1)(3x + 5)", False), ("(3x − 5)(2x + 1)", False),
        ],
    },
    {
        "text": "Factorise 8x² − 18x + 7",
        "difficulty": 3,
        "answers": [
            ("(2x − 1)(4x − 7)", True), ("(2x + 1)(4x + 7)", False),
            ("(8x − 1)(x − 7)", False), ("(2x − 7)(4x − 1)", False),
        ],
    },
    {
        "text": "Factorise 4x² − 12x + 5",
        "difficulty": 3,
        "answers": [
            ("(2x − 1)(2x − 5)", True), ("(4x − 1)(x − 5)", False),
            ("(2x + 1)(2x + 5)", False), ("(2x − 5)(2x + 1)", False),
        ],
    },
    {
        "text": "Factorise 6x² + 17x + 5",
        "difficulty": 3,
        "answers": [
            ("(3x + 1)(2x + 5)", True), ("(6x + 1)(x + 5)", False),
            ("(3x + 5)(2x + 1)", False), ("(6x + 5)(x + 1)", False),
        ],
    },
    {
        "text": "Factorise 12x² + 7x − 10",
        "difficulty": 3,
        "answers": [
            ("(4x + 5)(3x − 2)", True), ("(4x − 5)(3x + 2)", False),
            ("(12x − 5)(x + 2)", False), ("(6x + 5)(2x − 2)", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Quadratic Formula — new subtopic, Year 8 (pages 11-12)
# ---------------------------------------------------------------------------
QUADRATIC_FORMULA_QUESTIONS = [
    {
        "text": "For x² + 5x + 1 = 0, what is the value of the discriminant (b² − 4ac)?",
        "difficulty": 1,
        "answers": [
            ("21", True), ("27", False), ("23", False), ("17", False),
        ],
    },
    {
        "text": "Solve x² + 5x + 1 = 0 using the quadratic formula. What are the solutions (to 3 s.f.)?",
        "difficulty": 2,
        "answers": [
            ("x = −0.209 or x = −4.79", True),
            ("x = 0.209 or x = 4.79", False),
            ("x = −1 or x = −5", False),
            ("x = −0.5 or x = −4.5", False),
        ],
    },
    {
        "text": "For 2x² + 5x + 1 = 0, what is the value of the discriminant?",
        "difficulty": 1,
        "answers": [
            ("17", True), ("25", False), ("9", False), ("33", False),
        ],
    },
    {
        "text": "For 2x² − 7x + 3 = 0, what is the value of the discriminant (b² − 4ac)?",
        "difficulty": 2,
        "answers": [
            ("25", True), ("37", False), ("17", False), ("49", False),
        ],
    },
    {
        "text": "Solve 2x² − 7x + 3 = 0 using the quadratic formula.",
        "difficulty": 2,
        "answers": [
            ("x = 3 or x = 0.5", True), ("x = 7 or x = −3", False),
            ("x = 3.5 or x = 0.5", False), ("x = 3 or x = −0.5", False),
        ],
    },
    {
        "text": "For x² − 7x + 3 = 0, what is the discriminant?",
        "difficulty": 2,
        "answers": [
            ("37", True), ("25", False), ("61", False), ("45", False),
        ],
    },
    {
        "text": "Solve 3x² + 5x + 2 = 0 using the quadratic formula.",
        "difficulty": 3,
        "answers": [
            ("x = −2/3 or x = −1", True), ("x = 2/3 or x = 1", False),
            ("x = −5/6 or x = −1", False), ("x = 2/3 or x = −1", False),
        ],
    },
    {
        "text": "For 5x² + x − 2 = 0, the discriminant is 41. What are the solutions (to 3 s.f.)?",
        "difficulty": 3,
        "answers": [
            ("x ≈ 0.540 or x ≈ −0.740", True),
            ("x ≈ 0.740 or x ≈ −0.540", False),
            ("x ≈ 1.540 or x ≈ −0.540", False),
            ("x ≈ 0.540 or x ≈ 0.740", False),
        ],
    },
    {
        "text": "In the quadratic formula x = (−b ± √(b²−4ac)) / 2a, what does the discriminant b²−4ac tell you?",
        "difficulty": 2,
        "answers": [
            ("How many real solutions the equation has", True),
            ("The sum of the two roots", False),
            ("The product of the two roots", False),
            ("The value of x directly", False),
        ],
    },
    {
        "text": "If the discriminant b² − 4ac = 0, how many solutions does the quadratic equation have?",
        "difficulty": 2,
        "answers": [
            ("Exactly one (a repeated root)", True),
            ("Two distinct solutions", False),
            ("No real solutions", False),
            ("Cannot be determined", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Completing the Square — new subtopic, Year 9 (pages 7-8)
# ---------------------------------------------------------------------------
COMPLETING_SQUARE_QUESTIONS = [
    {
        "text": "Complete the square for x² + 8x.",
        "difficulty": 1,
        "answers": [
            ("(x + 4)² − 16", True), ("(x + 4)² + 16", False),
            ("(x + 8)² − 64", False), ("(x + 4)²", False),
        ],
    },
    {
        "text": "Complete the square for x² − 6x.",
        "difficulty": 1,
        "answers": [
            ("(x − 3)² − 9", True), ("(x − 3)² + 9", False),
            ("(x − 6)² − 36", False), ("(x + 3)² − 9", False),
        ],
    },
    {
        "text": "Complete the square for x² + 10x.",
        "difficulty": 1,
        "answers": [
            ("(x + 5)² − 25", True), ("(x + 5)² + 25", False),
            ("(x + 10)² − 100", False), ("(x + 5)² − 10", False),
        ],
    },
    {
        "text": "Write 2x² + 16x in completed square form.",
        "difficulty": 2,
        "answers": [
            ("2(x + 4)² − 32", True), ("(x + 4)² − 32", False),
            ("2(x + 4)² + 32", False), ("2(x + 8)² − 32", False),
        ],
    },
    {
        "text": "Write 3x² − 18x in completed square form.",
        "difficulty": 2,
        "answers": [
            ("3(x − 3)² − 27", True), ("3(x − 3)² + 27", False),
            ("(x − 3)² − 27", False), ("3(x + 3)² − 27", False),
        ],
    },
    {
        "text": "Write 2x² + 12x + 1 in completed square form.",
        "difficulty": 2,
        "answers": [
            ("2(x + 3)² − 17", True), ("2(x + 3)² + 17", False),
            ("2(x + 3)² − 18", False), ("(x + 3)² − 17", False),
        ],
    },
    {
        "text": "Write 3x² + 6x − 5 in completed square form.",
        "difficulty": 2,
        "answers": [
            ("3(x + 1)² − 8", True), ("3(x + 1)² + 8", False),
            ("3(x + 1)² − 3", False), ("3(x + 2)² − 8", False),
        ],
    },
    {
        "text": "Write 4x² + 16x − 1 in completed square form.",
        "difficulty": 3,
        "answers": [
            ("4(x + 2)² − 17", True), ("4(x + 2)² + 17", False),
            ("4(x + 2)² − 15", False), ("(x + 2)² − 17", False),
        ],
    },
    {
        "text": "Write 2x² − 20x − 7 in completed square form.",
        "difficulty": 3,
        "answers": [
            ("2(x − 5)² − 57", True), ("2(x − 5)² + 57", False),
            ("2(x − 5)² − 50", False), ("2(x − 10)² − 7", False),
        ],
    },
    {
        "text": "Write 5x² − 30x + 11 in completed square form.",
        "difficulty": 3,
        "answers": [
            ("5(x − 3)² − 34", True), ("5(x − 3)² + 34", False),
            ("5(x − 3)² − 45", False), ("(x − 3)² − 34", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Year 8 exam — questions mappable to existing subtopics
# ---------------------------------------------------------------------------
PROBABILITY_NEW = [
    {
        "text": "From the word ALPHABET, a letter is chosen at random. What is the probability of drawing the letter A?",
        "difficulty": 2,
        "answers": [
            ("1/4", True), ("1/8", False), ("1/7", False), ("2/7", False),
        ],
    },
]

RATIOS_NEW = [
    {
        "text": "There are 600 people at a conference. The ratio of men to women is 3:2. How many men are there?",
        "difficulty": 2,
        "answers": [
            ("360", True), ("240", False), ("300", False), ("200", False),
        ],
    },
    {
        "text": "A triangle has sides in the ratio 4:8:16 and a perimeter of 112 cm. What is the length of the longest side?",
        "difficulty": 3,
        "answers": [
            ("64 cm", True), ("32 cm", False), ("16 cm", False), ("28 cm", False),
        ],
    },
]

FINANCE_NEW = [
    {
        "text": "A dress has a marked price of $1 200. It is reduced by 40%. What is the new selling price?",
        "difficulty": 2,
        "answers": [
            ("$720", True), ("$480", False), ("$840", False), ("$960", False),
        ],
    },
]

VOLUME_NEW = [
    {
        "text": "A rectangular jerry can (12 cm × 40 cm × 60 cm) is five-eighths full of petrol. Petrol costs $1.20 per litre. What is the cost of the petrol in the jerry can? (1 cm³ = 1 mL)",
        "difficulty": 3,
        "answers": [
            ("$21.60", True), ("$28.80", False), ("$34.56", False), ("$3.46", False),
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
    year8 = Level.objects.filter(level_number=8).first()
    year9 = Level.objects.filter(level_number=9).first()

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

    try:
        algebra_strand = Topic.objects.get(subject=maths, slug='algebra', parent=None)
    except Topic.DoesNotExist:
        return

    # ------------------------------------------------------------------
    # 1. Expanding and Factorising Quadratics — extend to Y7 + Y8
    # ------------------------------------------------------------------
    try:
        quadratics = Topic.objects.get(subject=maths, slug='expanding-and-factorising-quadratics')
    except Topic.DoesNotExist:
        quadratics = None

    if quadratics and year7:
        quadratics.levels.add(year7)
        add_questions(quadratics, QUADRATICS_Y7_NEW, year7)

    if quadratics and year7:
        add_questions(quadratics, SOLVING_QUADRATICS_Y8, year7)

    # ------------------------------------------------------------------
    # 2. Factorising Harder Quadratics — new subtopic, Year 7
    # ------------------------------------------------------------------
    harder, _ = Topic.objects.get_or_create(
        subject=maths, slug='factorising-harder-quadratics',
        defaults={
            'name': 'Factorising Harder Quadratics', 'order': 7,
            'is_active': True, 'parent': algebra_strand,
        },
    )
    if year7:
        harder.levels.add(year7)
        add_questions(harder, HARDER_QUADRATICS_QUESTIONS, year7)

    # ------------------------------------------------------------------
    # 3. Quadratic Formula — new subtopic, Year 7
    # ------------------------------------------------------------------
    qf, _ = Topic.objects.get_or_create(
        subject=maths, slug='quadratic-formula',
        defaults={
            'name': 'Quadratic Formula', 'order': 8,
            'is_active': True, 'parent': algebra_strand,
        },
    )
    if year7:
        qf.levels.add(year7)
        add_questions(qf, QUADRATIC_FORMULA_QUESTIONS, year7)

    # ------------------------------------------------------------------
    # 4. Completing the Square — new subtopic, Year 8
    # ------------------------------------------------------------------
    cts, _ = Topic.objects.get_or_create(
        subject=maths, slug='completing-the-square',
        defaults={
            'name': 'Completing the Square', 'order': 9,
            'is_active': True, 'parent': algebra_strand,
        },
    )
    if year8:
        cts.levels.add(year8)
        add_questions(cts, COMPLETING_SQUARE_QUESTIONS, year8)

    # ------------------------------------------------------------------
    # 5. Year 8 exam questions → existing subtopics
    # ------------------------------------------------------------------
    slug_map = {
        'probability': (PROBABILITY_NEW, year7),
        'ratios':      (RATIOS_NEW,      year7),
        'finance':     (FINANCE_NEW,     year7),
        'volume':      (VOLUME_NEW,      year8),
    }
    for slug, (q_list, level) in slug_map.items():
        if not level:
            continue
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(level)
        add_questions(subtopic, q_list, level)


def reverse_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    for slug in ('factorising-harder-quadratics', 'quadratic-formula', 'completing-the-square'):
        Topic.objects.filter(subject=maths, slug=slug).delete()

    all_texts = (
        [q['text'] for q in QUADRATICS_Y7_NEW]
        + [q['text'] for q in SOLVING_QUADRATICS_Y8]
        + [q['text'] for q in PROBABILITY_NEW]
        + [q['text'] for q in RATIOS_NEW]
        + [q['text'] for q in FINANCE_NEW]
        + [q['text'] for q in VOLUME_NEW]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0018_seed_year7_integers_exam_questions'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
