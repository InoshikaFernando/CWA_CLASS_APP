"""
Migration 0024 — G7 Naplan.pdf (NAPLAN 2025 Mathematics Paper 1):
  Division              (Y7): +1 question  (Q2  — meal cost per person)
  Fractions             (Y7): +4 questions (Q7 reverse %, Q9 reverse fraction, Q17 mixed %, Q19c cards)
  Addition & Subtraction(Y7): +1 question  (Q10 — train passengers)
  Logic & Problem Solving(Y7):+3 questions (Q8a, Q8b repeating sequence; Q19b card sum)
  Perimeter             (Y7): +1 question  (Q13 — isosceles triangle perimeter)
  Linear Equations      (Y7): +5 questions (Q14a,b,c custom operator; Q16 parcels; Q18 rectangles)
  Angles                (Y7): +1 question  (Q15 — isosceles + right-angle triangle angles)

Questions that rely on diagrams (number line, flowchart, ruler, line graph,
grid, box-circle puzzle) were skipped.
All assigned to Year 7.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
DIVISION_Y7 = [
    {
        "text": "A meal for 6 people cost $104.10. Each person paid the same amount. How much did each person pay?",
        "difficulty": 1,
        "answers": [
            ("$17.35", True), ("$17.40", False), ("$16.35", False), ("$17.10", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FRACTIONS_Y7 = [
    {
        "text": "12.5% of Year 7 students play the violin. There are 11 students who play the violin. How many students are there in Year 7 in total?",
        "difficulty": 2,
        "answers": [
            ("88", True), ("110", False), ("96", False), ("132", False),
        ],
    },
    {
        "text": "In a sale, the price of a jumper was reduced by 1/5. The sale price was $48. What was the original price?",
        "difficulty": 2,
        "answers": [
            ("$60", True), ("$57.60", False), ("$40", False), ("$58", False),
        ],
    },
    {
        "text": "On an aeroplane with 400 passengers, 9/20 are men and 30% are women. How many passengers are children?",
        "difficulty": 2,
        "answers": [
            ("100", True), ("80", False), ("120", False), ("60", False),
        ],
    },
    {
        "text": "Nicola has 7 cards labelled C C C D D D D, where C and D are different whole numbers each less than 10. The total of all 7 cards is 36. Which pair (C, D) is a valid solution?",
        "difficulty": 3,
        "answers": [
            ("C = 8, D = 3", True), ("C = 6, D = 5", False), ("C = 9, D = 1", False), ("C = 7, D = 4", False),
        ],
    },
]

# ---------------------------------------------------------------------------
ADDITION_SUBTRACTION_Y7 = [
    {
        "text": "A train stopped at Stockport. 42 people got off and 60 people got on. There were 322 people on the train when it left Stockport. How many people were on the train before it stopped?",
        "difficulty": 1,
        "answers": [
            ("304", True), ("280", False), ("340", False), ("424", False),
        ],
    },
]

# ---------------------------------------------------------------------------
LOGIC_Y7 = [
    {
        "text": "A sequence repeats in the pattern: 2, 4, 6, 8, 2, 4, 6, 8, … What is the 16th number in the sequence?",
        "difficulty": 1,
        "answers": [
            ("8", True), ("2", False), ("4", False), ("6", False),
        ],
    },
    {
        "text": "A sequence repeats in the pattern: 2, 4, 6, 8, 2, 4, 6, 8, … What is the 105th number in the sequence?",
        "difficulty": 2,
        "answers": [
            ("2", True), ("4", False), ("6", False), ("8", False),
        ],
    },
    {
        "text": "Samara has 7 cards labelled A A B B B B B, where A and B are different whole numbers each less than 10. The total of all 7 cards is 45. What are the values of A and B?",
        "difficulty": 2,
        "answers": [
            ("A = 5, B = 7", True), ("A = 7, B = 5", False), ("A = 3, B = 8", False), ("A = 6, B = 6", False),
        ],
    },
]

# ---------------------------------------------------------------------------
PERIMETER_Y7 = [
    {
        "text": "Triangle PQR has a perimeter of 28 cm. Sides PQ and PR are each three times the length of QR. What is the length of QR?",
        "difficulty": 2,
        "answers": [
            ("4 cm", True), ("7 cm", False), ("3.5 cm", False), ("5 cm", False),
        ],
    },
]

# ---------------------------------------------------------------------------
LINEAR_EQUATIONS_Y7 = [
    {
        "text": "A special operation is defined as: a ⊗ b = a² + 3b. Calculate 4 ⊗ 5.",
        "difficulty": 1,
        "answers": [
            ("31", True), ("25", False), ("47", False), ("28", False),
        ],
    },
    {
        "text": "A special operation is defined as: a ⊗ b = a² + 3b. If 6 ⊗ x = 48, find x.",
        "difficulty": 2,
        "answers": [
            ("4", True), ("2", False), ("6", False), ("12", False),
        ],
    },
    {
        "text": "A special operation is defined as: a ⊗ b = a² + 3b. If n ⊗ 5 = 79, find n (where n is a positive whole number).",
        "difficulty": 2,
        "answers": [
            ("8", True), ("6", False), ("7", False), ("9", False),
        ],
    },
    {
        "text": "Three parcels have a total mass of 900 g. Parcels A and B together weigh the same as parcel C. Parcel A weighs 350 g. How much does parcel B weigh?",
        "difficulty": 2,
        "answers": [
            ("100 g", True), ("200 g", False), ("150 g", False), ("250 g", False),
        ],
    },
    {
        "text": "Two rows of a diagram share the same total width. The top row consists of a strip of width w, a gap of 65 cm, another strip of width w, and a gap of 45 cm. The bottom row consists of a gap of 30 cm, a strip of width w, a gap of 50 cm, and three strips each of width w. All strips have the same width w. Find w.",
        "difficulty": 3,
        "answers": [
            ("15 cm", True), ("10 cm", False), ("20 cm", False), ("12.5 cm", False),
        ],
    },
]

# ---------------------------------------------------------------------------
ANGLES_Y7 = [
    {
        "text": "In triangle ABC, angle B = 90° and angle ACB = 22°. Point Q lies on AB between A and B. Triangle APQ is isosceles with AP = AQ, where P is a point on AC. What is the size of angle AQP?",
        "difficulty": 3,
        "answers": [
            ("56°", True), ("68°", False), ("44°", False), ("34°", False),
        ],
    },
]


# ---------------------------------------------------------------------------
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
        'division':                   DIVISION_Y7,
        'fractions':                  FRACTIONS_Y7,
        'addition-and-subtraction':   ADDITION_SUBTRACTION_Y7,
        'logic-and-problem-solving':  LOGIC_Y7,
        'perimeter':                  PERIMETER_Y7,
        'linear-equations':           LINEAR_EQUATIONS_Y7,
        'angles':                     ANGLES_Y7,
    }

    for slug, q_list in slug_to_questions.items():
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            continue
        subtopic.levels.add(year7)
        add_questions(subtopic, q_list)


def reverse_data(apps, schema_editor):
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in DIVISION_Y7]
        + [q['text'] for q in FRACTIONS_Y7]
        + [q['text'] for q in ADDITION_SUBTRACTION_Y7]
        + [q['text'] for q in LOGIC_Y7]
        + [q['text'] for q in PERIMETER_Y7]
        + [q['text'] for q in LINEAR_EQUATIONS_Y7]
        + [q['text'] for q in ANGLES_Y7]
    )
    Question.objects.filter(
        topic__subject=maths,
        question_text__in=all_texts,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0023_seed_year7_g7_2_workbook'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
