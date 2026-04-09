"""
Migration 0026 — ACER TT8 Set02 (Year 8 MCQ, 44 questions from 50 total):
  Skipped: Q1, Q16, Q25, Q29, Q46, Q50 (require geometric/visual diagrams)

  Simultaneous Equations (Y8): +1  (line intersection)
  Linear Equations       (Y8): +6  (rearrange, flag perimeter, midpoint, gradient, quadrant, equation setup)
  Expanding/Factorising  (Y8): +3  (simplify, no-real-solution, algebraic fraction)
  Indices and Powers     (Y8): +2  (multiply indices, equivalent expressions)
  Angles                 (Y8): +3  (isosceles split, rotation, bearing)
  Area                   (Y8): +4  (flag area, rhombus, enclosed by line, hexagon)
  Circles                (Y8): +1  (pizza arc → circumference)
  Pythagoras' Theorem    (Y8): +1  (circle-in-square diagonal)
  Data Interpretation    (Y8): +4  (stem-and-leaf, pie chart × 2, breakfast table)
  Probability            (Y8): +1  (independent events)
  Percentages            (Y8): +2  (salary increase, fraction to percent)
  Factors                (Y8): +1  (hidden number)
  Ratios                 (Y8): +4  (weight conversion, packets, butter cost, charity)
  Date and Time          (Y8): +1  (recipe countdown)
  Unit Conversion        (Y8): +1  (water bottle mL)
  Rates                  (Y8): +1  (odometer)
  Fractions              (Y8): +2  (fraction method, fraction of hour)
  Finance                (Y8): +1  (simple interest)
  Integers               (Y8): +1  (temperature drop)
  BODMAS                 (Y8): +1  (missing operator)
  Number Systems         (Y8): +1  (scientific notation)
  Logic and Prob Solving (Y8): +1  (work rate problem)
  Composite Areas        (Y8): +1  (max surface area of glued blocks)
All assigned to Year 8.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
SIMULTANEOUS_EQNS = [
    {
        "text": "What is the intersection point of the line y = 5x − 6 and the line 2x = y − 9?",
        "difficulty": 2,
        "answers": [
            ("(5, 19)", True), ("(3, 15)", False), ("(6, 24)", False), ("(2, 13)", False),
        ],
    },
]

# ---------------------------------------------------------------------------
LINEAR_EQNS = [
    {
        "text": "Using the following formula, rearrange the quantities to make x the subject: y = n/(m + x) − a",
        "difficulty": 2,
        "answers": [
            ("x = n/(y + a) − m", True), ("x = n/(m + y) + a", False),
            ("x = a/(m + y) − n", False), ("x = n/(y − m) + a", False),
        ],
    },
    {
        "text": "A flag's length needs to be three times its width (w). What is the expression for the perimeter of the flag?",
        "difficulty": 1,
        "answers": [
            ("8w", True), ("6w", False), ("4w", False), ("2(w + l)", False),
        ],
    },
    {
        "text": "The mid-point between (1, −3) and (7, 9) is:",
        "difficulty": 1,
        "answers": [
            ("(4, 3)", True), ("(3.5, 4.5)", False), ("(2, 4)", False), ("(2, 2)", False),
        ],
    },
    {
        "text": "The perpendicular gradient to the line y = 7 − 6x is:",
        "difficulty": 2,
        "answers": [
            ("1/6", True), ("6", False), ("−6", False), ("−1/6", False),
        ],
    },
    {
        "text": "The point (−2, 7) is placed in which quadrant on the Cartesian plane?",
        "difficulty": 1,
        "answers": [
            ("Quadrant II", True), ("Quadrant I", False), ("Quadrant III", False), ("Quadrant IV", False),
        ],
    },
    {
        "text": "The sum of two numbers that have been individually squared is equal to 100, and the difference between the first and second number is 2. Which gives the correct pair of expressions?",
        "difficulty": 2,
        "answers": [
            ("x − y = 2,  x² + y² = 100", True),
            ("x − y = 2,  (x + y)² = 100", False),
            ("x + y = 2,  x² + y² = 100", False),
            ("(x − y)² = 3,  x + y = 15", False),
        ],
    },
]

# ---------------------------------------------------------------------------
EXPANDING_FACTORISING = [
    {
        "text": "2x² − (−5 + 3x²) is equivalent to?",
        "difficulty": 2,
        "answers": [
            ("5 − x²", True), ("5(1 + x²)", False), ("x² − 5", False), ("x² + 5", False),
        ],
    },
    {
        "text": "Which of the following equations would not give you a real solution?",
        "difficulty": 2,
        "answers": [
            ("2x² + 13 = 5", True), ("x² − 4 = 5", False),
            ("x² + 2 = 18", False), ("−(45 − 3x²) = 63", False),
        ],
    },
    {
        "text": "Simplify: (x² − 16)/(4x + 16) ÷ (x − 4)/2",
        "difficulty": 3,
        "answers": [
            ("1/2", True), ("(x − 4)/2", False), ("x/2", False), ("(x + 4)/2", False),
        ],
    },
]

# ---------------------------------------------------------------------------
INDICES_POWERS = [
    {
        "text": "Simplify 5a²b¹⁰ × 3a⁷b².",
        "difficulty": 2,
        "answers": [
            ("15a⁹b¹²", True), ("15a⁵b⁸", False), ("8a⁹b⁸", False), ("8a⁹b¹²", False),
        ],
    },
    {
        "text": "Which of the following is NOT the same as 8^(2/7)?",
        "difficulty": 3,
        "answers": [
            ("8^(1/7)", True), ("(8^(1/7))²", False), ("(8²)^(1/7)", False), ("(⁷√8)²", False),
        ],
    },
]

# ---------------------------------------------------------------------------
ANGLES = [
    {
        "text": "An isosceles right-angle triangle is divided into two pieces along its axis of symmetry. The angles of the two small triangles are:",
        "difficulty": 2,
        "answers": [
            ("45°, 45°, 90°", True), ("60°, 60°, 60°", False),
            ("50°, 60°, 70°", False), ("30°, 60°, 90°", False),
        ],
    },
    {
        "text": "When facing due south, you spin 1170° clockwise then 630° anticlockwise. What direction are you now facing?",
        "difficulty": 3,
        "answers": [
            ("North", True), ("South", False), ("East", False), ("West", False),
        ],
    },
    {
        "text": "Thomas' bearing from Chloe's position is 120°T. What is Chloe's bearing from Thomas' position?",
        "difficulty": 2,
        "answers": [
            ("300°T", True), ("340°T", False), ("160°T", False), ("275°T", False),
        ],
    },
]

# ---------------------------------------------------------------------------
AREA = [
    {
        "text": "A flag's length is three times its width. If the perimeter is 32 cm, what is the area of the flag?",
        "difficulty": 2,
        "answers": [
            ("48 cm²", True), ("50 cm²", False), ("42 cm²", False), ("40 cm²", False),
        ],
    },
    {
        "text": "The diagonal lines of a rhombus are 15 cm and 8 cm. What is its area?",
        "difficulty": 2,
        "answers": [
            ("60 cm²", True), ("130 cm²", False), ("120 cm²", False), ("90 cm²", False),
        ],
    },
    {
        "text": "What is the area enclosed by the line 8 − 2x = y and the x-axis and y-axis?",
        "difficulty": 2,
        "answers": [
            ("16 units²", True), ("8 units²", False), ("20 units²", False), ("24 units²", False),
        ],
    },
    {
        "text": "Amanda wants to build a regular hexagon flower garden using 6 planks each 6 m long. The axis of symmetry from midpoint to midpoint is 10.4 m long. What is the area of the flower bed?",
        "difficulty": 3,
        "answers": [
            ("93.6 m²", True), ("110 m²", False), ("83.4 m²", False), ("96.7 m²", False),
        ],
    },
]

# ---------------------------------------------------------------------------
CIRCLES = [
    {
        "text": "The angle at the point of a pizza slice at the centre is 30°. The crust (arc) of that slice is 13 cm long. What is the circumference of the whole pizza?",
        "difficulty": 2,
        "answers": [
            ("156 cm", True), ("130 cm", False), ("181 cm", False), ("195 cm", False),
        ],
    },
]

# ---------------------------------------------------------------------------
PYTHAGORAS = [
    {
        "text": "A circle with a radius of 5 cm is placed inside a square so that it touches all four sides. What is the length of the diagonal of the square?",
        "difficulty": 2,
        "answers": [
            ("10√2", True), ("2√10", False), ("5√3", False), ("12√7", False),
        ],
    },
]

# ---------------------------------------------------------------------------
DATA_INTERP = [
    {
        "text": "Students' test results shown as a stem-and-leaf plot: Stem 6: 0 5 7 8 | Stem 7: 3 4 5 5 8 9 9 | Stem 8: 0 1 2 2 3 3 5 6 8 | Stem 9: 3 4 5. What is the median of this data?",
        "difficulty": 2,
        "answers": [
            ("80", True), ("75", False), ("79", False), ("82", False),
        ],
    },
    {
        "text": "A survey of devices owned by class 6W shows: Computer 48%, Home Phone 12%, Mobile Phone 24%, with Laptops and Tablets making up the rest equally. What percentage of students own a laptop?",
        "difficulty": 2,
        "answers": [
            ("8%", True), ("5%", False), ("11%", False), ("15%", False),
        ],
    },
    {
        "text": "A survey of devices owned by class 6W shows: Computer 48%, Home Phone 12%, Mobile Phone 24%, Laptops 8%, Tablets 8%. If there are 75 devices altogether, how many are mobile phones?",
        "difficulty": 2,
        "answers": [
            ("18", True), ("36", False), ("9", False), ("6", False),
        ],
    },
    {
        "text": "A teacher recorded breakfast habits: Boys ate 15, boys did not eat 3; Girls ate 6, girls did not eat 7. What is the best estimate in percentage of boys who ate breakfast out of all students in the class?",
        "difficulty": 2,
        "answers": [
            ("48%", True), ("15%", False), ("51%", False), ("23%", False),
        ],
    },
]

# ---------------------------------------------------------------------------
PROBABILITY = [
    {
        "text": "Ailsa gets wet because of rain 1 in every 5 days. She also forgets her phone 3 days out of every 8. What is the probability that Ailsa will not get wet and will remember her phone?",
        "difficulty": 2,
        "answers": [
            ("50%", True), ("25%", False), ("40%", False), ("30%", False),
        ],
    },
]

# ---------------------------------------------------------------------------
PERCENTAGES = [
    {
        "text": "Last year Jess earned $82,000. This year she earns $91,840. By what percentage did Jess's salary increase?",
        "difficulty": 2,
        "answers": [
            ("12%", True), ("5%", False), ("10%", False), ("2.5%", False),
        ],
    },
    {
        "text": "The equivalent of 7/20 is:",
        "difficulty": 1,
        "answers": [
            ("35%", True), ("3½%", False), ("7%", False), ("24%", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FACTORS = [
    {
        "text": "A hidden number is less than 50 and has factors of 4, 7 and 14. What is the number?",
        "difficulty": 2,
        "answers": [
            ("28", True), ("14", False), ("21", False), ("42", False),
        ],
    },
]

# ---------------------------------------------------------------------------
RATIOS = [
    {
        "text": "On a newly found planet, 1 kilogram on Earth is equivalent to 1.25 kilograms on the new planet. What would a person who weighs 56 kg on Earth weigh on the new planet?",
        "difficulty": 1,
        "answers": [
            ("70 kg", True), ("64 kg", False), ("83 kg", False), ("86 kg", False),
        ],
    },
    {
        "text": "Archie has flour, sugar and salt in 1 kg packets: 500 packets total. In each group there are 4 packets of flour, 5 packets of sugar and 1 packet of salt. How many packets of flour, sugar and salt does he have respectively?",
        "difficulty": 2,
        "answers": [
            ("200 : 250 : 50", True), ("166 : 168 : 166", False),
            ("150 : 300 : 50", False), ("250 : 200 : 50", False),
        ],
    },
    {
        "text": "You need 250 g of butter to make a cake serving 10 people. One bar of 500 g butter costs $3.10. How much will butter cost for a cake serving 50 people?",
        "difficulty": 2,
        "answers": [
            ("$7.75", True), ("$6.55", False), ("$9.45", False), ("$8.65", False),
        ],
    },
    {
        "text": "At a charity event, 300 people participated. In each group there were 3 males and 2 females. How many female participants were at the charity event?",
        "difficulty": 2,
        "answers": [
            ("120", True), ("140", False), ("90", False), ("190", False),
        ],
    },
]

# ---------------------------------------------------------------------------
DATE_TIME = [
    {
        "text": "A recipe told Tom to leave the stove on low for 5.5 minutes. His stopwatch reads that 200 seconds have passed. How much longer does Tom need to wait?",
        "difficulty": 2,
        "answers": [
            ("2 minutes and 10 seconds", True), ("2 minutes and 25 seconds", False),
            ("1 minute and 50 seconds", False), ("1 minute and 35 seconds", False),
        ],
    },
]

# ---------------------------------------------------------------------------
UNIT_CONV = [
    {
        "text": "A full bottle can hold 3 L of water. You pour water into 4 containers of 505 mL, 320 mL, 1.2 L, and 830 mL. How much water is left in the bottle?",
        "difficulty": 2,
        "answers": [
            ("145 mL", True), ("160 mL", False), ("1.1 L", False), ("130 mL", False),
        ],
    },
]

# ---------------------------------------------------------------------------
RATES = [
    {
        "text": "Kara has travelled 12,761.3 km since she bought her car. Today she travelled for 1.5 hours at 100 km/h then 40 minutes at 60 km/h. What would her odometer read now?",
        "difficulty": 2,
        "answers": [
            ("12,951.3 km", True), ("12,921.3 km", False),
            ("13,951.3 km", False), ("12,651.3 km", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FRACTIONS = [
    {
        "text": "When finding 3/7 of 238, the correct method would be:",
        "difficulty": 1,
        "answers": [
            ("Divide 238 by 7 then multiply by 3", True),
            ("Divide 238 by 3 then multiply by 7", False),
            ("Multiply 238 by 3 then multiply by 7", False),
            ("Multiply 238 by 7 then divide by 3", False),
        ],
    },
    {
        "text": "Two-fifths of an hour is equivalent to how many minutes?",
        "difficulty": 1,
        "answers": [
            ("24 minutes", True), ("12 minutes", False), ("30 minutes", False), ("52 minutes", False),
        ],
    },
]

# ---------------------------------------------------------------------------
FINANCE = [
    {
        "text": "Madison invests $12,000 for 8 months at a simple interest rate of 6% per year. What is her total amount after 8 months?",
        "difficulty": 2,
        "answers": [
            ("$12,480", True), ("$12,840", False), ("$14,280", False), ("$14,820", False),
        ],
    },
]

# ---------------------------------------------------------------------------
INTEGERS = [
    {
        "text": "During winter, at 6:00 pm it was 4°C. Overnight the temperature dropped by 12 degrees. What was the temperature at night?",
        "difficulty": 1,
        "answers": [
            ("−8°C", True), ("−12°C", False), ("−16°C", False), ("−4°C", False),
        ],
    },
]

# ---------------------------------------------------------------------------
BODMAS = [
    {
        "text": "The missing symbol in 5(2 − 3) + (8 □ 4) = 27 is:",
        "difficulty": 2,
        "answers": [
            ("×", True), ("+", False), ("−", False), ("÷", False),
        ],
    },
]

# ---------------------------------------------------------------------------
NUMBER_SYSTEMS = [
    {
        "text": "The expression (0.03)² is equal to:",
        "difficulty": 2,
        "answers": [
            ("9 × 10⁻⁴", True), ("0.09", False), ("9.0", False), ("0.009", False),
        ],
    },
]

# ---------------------------------------------------------------------------
LOGIC = [
    {
        "text": "Alex can build a wall in 8 days, Ben in 6 days. Together with Carter, all three complete the wall in 2 days. How many days does Carter need to build the wall alone?",
        "difficulty": 3,
        "answers": [
            ("4⁴⁄₅", True), ("5⅕", False), ("6⅔", False), ("3³⁄₅", False),
        ],
    },
]

# ---------------------------------------------------------------------------
COMPOSITE_AREAS = [
    {
        "text": "When gluing three identical blocks face-to-face to maximise total surface area, where each block's dimensions are 12 × 5 × 2 cm, what is the greatest possible surface area?",
        "difficulty": 3,
        "answers": [
            ("524 cm²", True), ("632 cm²", False), ("548 cm²", False), ("564 cm²", False),
        ],
    },
]


# ---------------------------------------------------------------------------
def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('maths', 'Question')
    Answer   = apps.get_model('maths', 'Answer')

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
        'simultaneous-equations':               SIMULTANEOUS_EQNS,
        'linear-equations':                     LINEAR_EQNS,
        'expanding-and-factorising-quadratics': EXPANDING_FACTORISING,
        'indices-and-powers':                   INDICES_POWERS,
        'angles':                               ANGLES,
        'area':                                 AREA,
        'circles':                              CIRCLES,
        'pythagoras-theorem':                   PYTHAGORAS,
        'data-interpretation':                  DATA_INTERP,
        'probability':                          PROBABILITY,
        'percentages':                          PERCENTAGES,
        'factors':                              FACTORS,
        'ratios':                               RATIOS,
        'date-and-time':                        DATE_TIME,
        'unit-conversion':                      UNIT_CONV,
        'rates':                                RATES,
        'fractions':                            FRACTIONS,
        'finance':                              FINANCE,
        'integers':                             INTEGERS,
        'bodmas':                               BODMAS,
        'number-systems':                       NUMBER_SYSTEMS,
        'logic-and-problem-solving':            LOGIC,
        'composite-areas':                      COMPOSITE_AREAS,
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
    Question = apps.get_model('maths', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in SIMULTANEOUS_EQNS]
        + [q['text'] for q in LINEAR_EQNS]
        + [q['text'] for q in EXPANDING_FACTORISING]
        + [q['text'] for q in INDICES_POWERS]
        + [q['text'] for q in ANGLES]
        + [q['text'] for q in AREA]
        + [q['text'] for q in CIRCLES]
        + [q['text'] for q in PYTHAGORAS]
        + [q['text'] for q in DATA_INTERP]
        + [q['text'] for q in PROBABILITY]
        + [q['text'] for q in PERCENTAGES]
        + [q['text'] for q in FACTORS]
        + [q['text'] for q in RATIOS]
        + [q['text'] for q in DATE_TIME]
        + [q['text'] for q in UNIT_CONV]
        + [q['text'] for q in RATES]
        + [q['text'] for q in FRACTIONS]
        + [q['text'] for q in FINANCE]
        + [q['text'] for q in INTEGERS]
        + [q['text'] for q in BODMAS]
        + [q['text'] for q in NUMBER_SYSTEMS]
        + [q['text'] for q in LOGIC]
        + [q['text'] for q in COMPOSITE_AREAS]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0025_seed_year8_integers'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
