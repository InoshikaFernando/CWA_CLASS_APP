"""
Migration 0022 — ACER Maths Test Set 01 (Math_ACER_Maths_TT8_set01.pdf):
  Expanding and Factorising Quadratics (Y7): +3 questions (grouping, expanding, diff of squares)
  Fractions            (Y7): +1 question
  Division             (Y7): +1 question
  Unit Conversion      (Y7): +1 question
  Ratios               (Y7): +1 question (similar triangles)
  Data Interpretation  (Y7): +3 questions (Venn diagram)
  Finance              (Y7): +5 questions
  Indices and Powers   (Y7): +2 questions
  Logic and Problem Solving (Y7): +2 questions
  Probability          (Y7): +1 question
  Area                 (Y7): +1 question (surface area of rectangular prism)
  Square Roots         (Y7): +1 question
  Linear Equations     (Y8): +5 questions
  Simultaneous Equations (Y8): +1 question
  Volume               (Y8): +1 question
  Rates                (Y8): +1 question (density formula)
  Indices and Powers   (Y8): +2 questions (surds, algebraic fractions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# Year 7
# ---------------------------------------------------------------------------

EXPAND_FACTORISE_Y7 = [
    {
        "text": "Factorise 2x + 10 + dx + 5d",
        "difficulty": 2,
        "answers": [
            ("(x + 5)(2 + d)", True), ("(x + 2)(5 + d)", False),
            ("(x + d)(2 + 5)", False), ("(x + 10)(d + 5)", False),
        ],
    },
    {
        "text": "Expand and simplify 3x(x + 1) + x(x − 4)",
        "difficulty": 2,
        "answers": [
            ("4x² − x", True), ("−x² + 4x", False),
            ("6x² − 4x", False), ("4x² + x", False),
        ],
    },
    {
        "text": "Simplify (2w + 4)(2w − 4)",
        "difficulty": 1,
        "answers": [
            ("4w² − 16", True), ("4w² + 8w − 16", False),
            ("4w² − 8w − 16", False), ("4w² + 16", False),
        ],
    },
]

FRACTIONS_Y7 = [
    {
        "text": "If x = 2/3, y = 3/4 and z = 1/6, calculate x ÷ z − y.",
        "difficulty": 2,
        "answers": [
            ("13/4", True), ("8/7", False), ("23/36", False), ("7/18", False),
        ],
    },
]

DIVISION_Y7 = [
    {
        "text": "Given that 280 ÷ 1.4 = 200, what is 28 ÷ 0.14?",
        "difficulty": 1,
        "answers": [
            ("200", True), ("20", False), ("2", False), ("0.2", False),
        ],
    },
]

UNIT_CONVERSION_Y7 = [
    {
        "text": "A kitten is 25 inches tall. How tall is the kitten in centimetres? (1 inch = 2.54 cm)",
        "difficulty": 1,
        "answers": [
            ("63.5 cm", True), ("37.5 cm", False), ("50.0 cm", False), ("50.5 cm", False),
        ],
    },
]

RATIOS_Y7 = [
    {
        "text": "Two similar triangles have sides in proportion. The first triangle has sides 3, 4 and 5. The second similar triangle has corresponding sides 8, Z and 10. What is the value of Z?",
        "difficulty": 2,
        "answers": [
            ("6", True), ("7", False), ("4", False), ("2", False),
        ],
    },
]

DATA_INTERPRETATION_Y7 = [
    {
        "text": "In a class survey about sports: 13 students play tennis only, 8 play both tennis and badminton, 17 play badminton only, and 2 play neither sport. How many students were surveyed in total?",
        "difficulty": 1,
        "answers": [
            ("40", True), ("48", False), ("46", False), ("37", False),
        ],
    },
    {
        "text": "In a class survey about sports: 13 students play tennis only, 8 play both tennis and badminton, 17 play badminton only, and 2 play neither sport. How many students played tennis only?",
        "difficulty": 1,
        "answers": [
            ("13", True), ("21", False), ("17", False), ("8", False),
        ],
    },
    {
        "text": "In a class survey about sports: 13 students play tennis only, 8 play both tennis and badminton, 17 play badminton only, and 2 play neither sport. How many students played neither tennis nor badminton?",
        "difficulty": 1,
        "answers": [
            ("2", True), ("8", False), ("4", False), ("12", False),
        ],
    },
]

FINANCE_Y7 = [
    {
        "text": "At a conference, 240 audience members were researchers, which was 60% of the total audience. What was the total number of people at the conference?",
        "difficulty": 2,
        "answers": [
            ("400", True), ("384", False), ("300", False), ("336", False),
        ],
    },
    {
        "text": "At a medical conference with 400 people in total, 240 were researchers and the rest were doctors. How many doctors attended?",
        "difficulty": 1,
        "answers": [
            ("160", True), ("144", False), ("60", False), ("240", False),
        ],
    },
    {
        "text": "Tim was paid $313 after working 20 hours. What is his hourly pay rate?",
        "difficulty": 1,
        "answers": [
            ("$15.65", True), ("$15.35", False), ("$15.55", False), ("$15.85", False),
        ],
    },
    {
        "text": "A refrigerator is priced at $2,400. A 15% discount is applied. What is the discounted price?",
        "difficulty": 2,
        "answers": [
            ("$2,040", True), ("$360", False), ("$1,800", False), ("$2,280", False),
        ],
    },
    {
        "text": "A smartphone was worth $1,200 last year. Its value has decreased by 25%. What is the new value of the phone?",
        "difficulty": 2,
        "answers": [
            ("$900", True), ("$300", False), ("$600", False), ("$800", False),
        ],
    },
]

INDICES_POWERS_Y7 = [
    {
        "text": "Evaluate −(−4)³",
        "difficulty": 2,
        "answers": [
            ("64", True), ("−64", False), ("12", False), ("−12", False),
        ],
    },
    {
        "text": "Simplify (2x⁰) × (3x³)⁰",
        "difficulty": 2,
        "answers": [
            ("2", True), ("6x³", False), ("2x³", False), ("6", False),
        ],
    },
]

LOGIC_Y7 = [
    {
        "text": "A number table has columns I–IV and rows A–E. Row A is: 3, 5, 7, 9. Each new row starts 10 more than the first value of the previous row, and each column increases by 2. What is the value in column IV, row E?",
        "difficulty": 2,
        "answers": [
            ("49", True), ("41", False), ("51", False), ("59", False),
        ],
    },
    {
        "text": "A number table has columns I–IV and rows starting from A. Row A is: 3, 5, 7, 9. Each new row starts 10 more than the previous, and values increase by 2 across columns. In which column and row does the number 77 appear?",
        "difficulty": 3,
        "answers": [
            ("Column III, Row H", True), ("Column III, Row G", False),
            ("Column VII, Row G", False), ("Column VII, Row H", False),
        ],
    },
]

PROBABILITY_Y7 = [
    {
        "text": "Two six-sided dice are thrown together. What is the probability that the total score is 7?",
        "difficulty": 2,
        "answers": [
            ("1/6", True), ("1/12", False), ("1/9", False), ("1/18", False),
        ],
    },
]

AREA_Y7 = [
    {
        "text": "A rectangular prism has dimensions 2 cm × 5 cm × 7 cm. What is its total surface area?",
        "difficulty": 2,
        "answers": [
            ("118 cm²", True), ("70 cm²", False), ("59 cm²", False), ("90 cm²", False),
        ],
    },
]

SQUARE_ROOTS_Y7 = [
    {
        "text": "Simplify 2√40",
        "difficulty": 2,
        "answers": [
            ("4√10", True), ("2√10", False), ("4√20", False), ("20", False),
        ],
    },
]

# ---------------------------------------------------------------------------
# Year 8
# ---------------------------------------------------------------------------

LINEAR_EQUATIONS_Y8 = [
    {
        "text": "A number z is squared and then subtracted from three times its cube. The result is 33. Which equation represents this?",
        "difficulty": 2,
        "answers": [
            ("3z³ − z² = 33", True), ("z² − 3z³ = 33", False),
            ("3z² − z³ = 33", False), ("3(z³ − z²) = 33", False),
        ],
    },
    {
        "text": "A straight line passes through the points (0, 10), (1, 3) and (2, −4). What is the gradient of the line?",
        "difficulty": 1,
        "answers": [
            ("−7", True), ("7", False), ("−2", False), ("2", False),
        ],
    },
    {
        "text": "A straight line has gradient −7 and passes through the point (0, 10). What is the equation of the line?",
        "difficulty": 2,
        "answers": [
            ("y = −7x + 10", True), ("y = 7x + 10", False),
            ("y = −2x + 4", False), ("y = 2x − 4", False),
        ],
    },
    {
        "text": "If A = B(C − 4) ÷ 2D, rearrange to make C the subject.",
        "difficulty": 3,
        "answers": [
            ("C = 2AD/B + 4", True), ("C = (AB + 4)/2D", False),
            ("C = 2AD/(B + 4)", False), ("C = AB/(2D) + 4", False),
        ],
    },
    {
        "text": "A linear graph has x-intercept (2, 0) and y-intercept (0, −5). What is the gradient of the line?",
        "difficulty": 2,
        "answers": [
            ("2.5", True), ("−2.5", False), ("10", False), ("−10", False),
        ],
    },
]

SIMULTANEOUS_Y8 = [
    {
        "text": "Find the intersection point of y = 3 − 2x and y = x².",
        "difficulty": 3,
        "answers": [
            ("(1, 1)", True), ("(2, 3)", False), ("(3, −1)", False), ("(−1, 3)", False),
        ],
    },
]

VOLUME_Y8 = [
    {
        "text": "A rectangular prism has dimensions 2 cm × 5 cm × 7 cm. What is its volume?",
        "difficulty": 1,
        "answers": [
            ("70 cm³", True), ("118 cm³", False), ("59 cm³", False), ("90 cm³", False),
        ],
    },
]

RATES_Y8 = [
    {
        "text": "A rectangular prism has a volume of 70 cm³ and a density of 1.4 g/cm³. What is its mass? (Density = Mass ÷ Volume)",
        "difficulty": 2,
        "answers": [
            ("98 g", True), ("165.2 g", False), ("82.6 g", False), ("126 g", False),
        ],
    },
]

INDICES_POWERS_Y8 = [
    {
        "text": "Simplify (4√3 − √5)²",
        "difficulty": 3,
        "answers": [
            ("53 − 8√15", True), ("53 − 4√15", False),
            ("16 − 4√15", False), ("12 − 4√5", False),
        ],
    },
    {
        "text": "Simplify: (3y²)/(4x) × (6x³)/(xy³)",
        "difficulty": 3,
        "answers": [
            ("9x/(2y)", True), ("9xy²/2", False),
            ("9x²/y", False), ("9y²/(2x)", False),
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

    y7_slug_map = {
        'expanding-and-factorising-quadratics': EXPAND_FACTORISE_Y7,
        'fractions':                             FRACTIONS_Y7,
        'division':                              DIVISION_Y7,
        'unit-conversion':                       UNIT_CONVERSION_Y7,
        'ratios':                                RATIOS_Y7,
        'data-interpretation':                   DATA_INTERPRETATION_Y7,
        'finance':                               FINANCE_Y7,
        'indices-and-powers':                    INDICES_POWERS_Y7,
        'logic-and-problem-solving':             LOGIC_Y7,
        'probability':                           PROBABILITY_Y7,
        'area':                                  AREA_Y7,
        'square-roots':                          SQUARE_ROOTS_Y7,
    }

    for slug, q_list in y7_slug_map.items():
        if not year7:
            continue
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year7)
        add_questions(subtopic, q_list, year7)

    y8_slug_map = {
        'linear-equations':       LINEAR_EQUATIONS_Y8,
        'simultaneous-equations': SIMULTANEOUS_Y8,
        'volume':                 VOLUME_Y8,
        'rates':                  RATES_Y8,
        'indices-and-powers':     INDICES_POWERS_Y8,
    }

    for slug, q_list in y8_slug_map.items():
        if not year8:
            continue
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year8)
        add_questions(subtopic, q_list, year8)


def reverse_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in EXPAND_FACTORISE_Y7]
        + [q['text'] for q in FRACTIONS_Y7]
        + [q['text'] for q in DIVISION_Y7]
        + [q['text'] for q in UNIT_CONVERSION_Y7]
        + [q['text'] for q in RATIOS_Y7]
        + [q['text'] for q in DATA_INTERPRETATION_Y7]
        + [q['text'] for q in FINANCE_Y7]
        + [q['text'] for q in INDICES_POWERS_Y7]
        + [q['text'] for q in LOGIC_Y7]
        + [q['text'] for q in PROBABILITY_Y7]
        + [q['text'] for q in AREA_Y7]
        + [q['text'] for q in SQUARE_ROOTS_Y7]
        + [q['text'] for q in LINEAR_EQUATIONS_Y8]
        + [q['text'] for q in SIMULTANEOUS_Y8]
        + [q['text'] for q in VOLUME_Y8]
        + [q['text'] for q in RATES_Y8]
        + [q['text'] for q in INDICES_POWERS_Y8]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0021_seed_year7_quadratics_selective_exam'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
