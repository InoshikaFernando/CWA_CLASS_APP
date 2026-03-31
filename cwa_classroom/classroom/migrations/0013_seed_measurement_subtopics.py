"""
Migration 0013 — Measurement strand additions:
  - Area            (Year 7, 10 questions)
  - Perimeter       (Year 7, 10 questions)
  - Volume          (Year 8, 10 questions)
  - Rates           (Year 7 × 5 + Year 8 × 5 = 10 questions)
  - Unit Conversion (Year 7, 10 questions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
AREA_QUESTIONS = [
    {
        "text": "What is the area of a rectangle with length 8 cm and width 5 cm?",
        "difficulty": 1,
        "answers": [
            ("40 cm²", True), ("26 cm²", False), ("13 cm²", False), ("80 cm²", False),
        ],
    },
    {
        "text": "What is the area of a triangle with base 10 cm and height 6 cm?",
        "difficulty": 1,
        "answers": [
            ("30 cm²", True), ("60 cm²", False), ("15 cm²", False), ("48 cm²", False),
        ],
    },
    {
        "text": "A square has side length 7 m. What is its area?",
        "difficulty": 1,
        "answers": [
            ("49 m²", True), ("28 m²", False), ("14 m²", False), ("56 m²", False),
        ],
    },
    {
        "text": "What is the area of a parallelogram with base 9 cm and height 4 cm?",
        "difficulty": 1,
        "answers": [
            ("36 cm²", True), ("26 cm²", False), ("18 cm²", False), ("72 cm²", False),
        ],
    },
    {
        "text": "A room is 5.5 m long and 4 m wide. What is its area?",
        "difficulty": 2,
        "answers": [
            ("22 m²", True), ("19 m²", False), ("38 m²", False), ("9.5 m²", False),
        ],
    },
    {
        "text": "A triangle has base 12 cm and area 42 cm². What is its height?",
        "difficulty": 2,
        "answers": [
            ("7 cm", True), ("3.5 cm", False), ("14 cm", False), ("5 cm", False),
        ],
    },
    {
        "text": "What is the area of a trapezium with parallel sides 6 cm and 10 cm, and height 4 cm?",
        "difficulty": 2,
        "answers": [
            ("32 cm²", True), ("24 cm²", False), ("40 cm²", False), ("64 cm²", False),
        ],
    },
    {
        "text": "A circular garden has radius 7 m. What is its approximate area? (Use π ≈ 22/7)",
        "difficulty": 2,
        "answers": [
            ("154 m²", True), ("44 m²", False), ("308 m²", False), ("77 m²", False),
        ],
    },
    {
        "text": "A rectangle has area 60 cm² and length 12 cm. What is its width?",
        "difficulty": 2,
        "answers": [
            ("5 cm", True), ("6 cm", False), ("4 cm", False), ("48 cm", False),
        ],
    },
    {
        "text": "A rectangle is 6 cm × 8 cm, a square has side 7 cm, and a triangle has base 12 cm and height 9 cm. Which has the greatest area?",
        "difficulty": 3,
        "answers": [
            ("The triangle (54 cm²)", True),
            ("The square (49 cm²)", False),
            ("The rectangle (48 cm²)", False),
            ("They are all equal", False),
        ],
    },
]

PERIMETER_QUESTIONS = [
    {
        "text": "What is the perimeter of a rectangle with length 9 cm and width 4 cm?",
        "difficulty": 1,
        "answers": [
            ("26 cm", True), ("36 cm", False), ("13 cm", False), ("52 cm", False),
        ],
    },
    {
        "text": "A square has perimeter 36 cm. What is its side length?",
        "difficulty": 1,
        "answers": [
            ("9 cm", True), ("6 cm", False), ("4 cm", False), ("18 cm", False),
        ],
    },
    {
        "text": "What is the perimeter of a triangle with sides 5 cm, 7 cm, and 9 cm?",
        "difficulty": 1,
        "answers": [
            ("21 cm", True), ("11 cm", False), ("315 cm", False), ("42 cm", False),
        ],
    },
    {
        "text": "A rectangle has perimeter 30 cm and width 6 cm. What is its length?",
        "difficulty": 1,
        "answers": [
            ("9 cm", True), ("24 cm", False), ("18 cm", False), ("12 cm", False),
        ],
    },
    {
        "text": "What is the circumference of a circle with diameter 14 cm? (Use π ≈ 22/7)",
        "difficulty": 2,
        "answers": [
            ("44 cm", True), ("22 cm", False), ("154 cm", False), ("88 cm", False),
        ],
    },
    {
        "text": "A regular hexagon has side length 5 cm. What is its perimeter?",
        "difficulty": 2,
        "answers": [
            ("30 cm", True), ("25 cm", False), ("36 cm", False), ("15 cm", False),
        ],
    },
    {
        "text": "A rectangular garden (13 m × 8 m) has a 1 m wide path around the outside. What is the perimeter of the outer edge of the path?",
        "difficulty": 2,
        "answers": [
            ("50 m", True), ("44 m", False), ("46 m", False), ("52 m", False),
        ],
    },
    {
        "text": "An equilateral triangle has perimeter 33 cm. What is its side length?",
        "difficulty": 2,
        "answers": [
            ("11 cm", True), ("9 cm", False), ("3 cm", False), ("99 cm", False),
        ],
    },
    {
        "text": "A regular pentagon has perimeter 40 cm. What is the length of each side?",
        "difficulty": 2,
        "answers": [
            ("8 cm", True), ("5 cm", False), ("10 cm", False), ("4 cm", False),
        ],
    },
    {
        "text": "A wire of length 60 cm is bent into a rectangle where the length is twice the width. What are the dimensions?",
        "difficulty": 3,
        "answers": [
            ("Length 20 cm, width 10 cm", True),
            ("Length 30 cm, width 15 cm", False),
            ("Length 15 cm, width 15 cm", False),
            ("Length 20 cm, width 20 cm", False),
        ],
    },
]

# Rates: first 5 = Year 7, last 5 = Year 8
RATES_Y7_QUESTIONS = [
    {
        "text": "A car travels 180 km in 3 hours. What is its average speed?",
        "difficulty": 1,
        "answers": [
            ("60 km/h", True), ("540 km/h", False), ("45 km/h", False), ("90 km/h", False),
        ],
    },
    {
        "text": "Water flows into a tank at 15 litres per minute. How many litres enter in 8 minutes?",
        "difficulty": 1,
        "answers": [
            ("120 L", True), ("23 L", False), ("7.5 L", False), ("1.875 L", False),
        ],
    },
    {
        "text": "A factory produces 240 items in 6 hours. What is the production rate per hour?",
        "difficulty": 1,
        "answers": [
            ("40 items/h", True), ("1440 items/h", False), ("30 items/h", False), ("48 items/h", False),
        ],
    },
    {
        "text": "A tap drips at 5 mL per minute. How many litres does it waste in 24 hours?",
        "difficulty": 2,
        "answers": [
            ("7.2 L", True), ("120 L", False), ("0.12 L", False), ("720 L", False),
        ],
    },
    {
        "text": "A car uses 8 L of petrol per 100 km. How much petrol is needed for a 450 km journey?",
        "difficulty": 2,
        "answers": [
            ("36 L", True), ("56.25 L", False), ("4.5 L", False), ("3600 L", False),
        ],
    },
]

RATES_Y8_QUESTIONS = [
    {
        "text": "A cyclist travels at 18 km/h. How far does she travel in 45 minutes?",
        "difficulty": 2,
        "answers": [
            ("13.5 km", True), ("810 km", False), ("0.4 km", False), ("27 km", False),
        ],
    },
    {
        "text": "A pool holds 60 000 L. A pump fills it at 150 L per minute. How long does it take to fill the pool?",
        "difficulty": 2,
        "answers": [
            ("6 hours 40 minutes", True), ("6 hours", False), ("7 hours", False), ("400 hours", False),
        ],
    },
    {
        "text": "Train A travels at 90 km/h. Train B travels at 110 km/h in the same direction, starting 1 hour after Train A. How long after Train B departs until it catches Train A?",
        "difficulty": 3,
        "answers": [
            ("4.5 hours", True), ("5 hours", False), ("9 hours", False), ("4 hours", False),
        ],
    },
    {
        "text": "Pipe A fills a tank in 4 hours. Pipe B drains it in 6 hours. If both are open at the same time, how long does it take to fill the tank?",
        "difficulty": 3,
        "answers": [
            ("12 hours", True), ("10 hours", False), ("8 hours", False), ("5 hours", False),
        ],
    },
    {
        "text": "Two taps fill a bath. Tap A fills it in 10 minutes, Tap B in 15 minutes. How long do they take working together?",
        "difficulty": 3,
        "answers": [
            ("6 minutes", True), ("5 minutes", False), ("7.5 minutes", False), ("12.5 minutes", False),
        ],
    },
]

VOLUME_QUESTIONS = [
    {
        "text": "What is the volume of a rectangular prism with length 5 cm, width 4 cm, and height 3 cm?",
        "difficulty": 1,
        "answers": [
            ("60 cm³", True), ("47 cm³", False), ("35 cm³", False), ("120 cm³", False),
        ],
    },
    {
        "text": "A cube has side length 4 cm. What is its volume?",
        "difficulty": 1,
        "answers": [
            ("64 cm³", True), ("48 cm³", False), ("16 cm³", False), ("12 cm³", False),
        ],
    },
    {
        "text": "A rectangular box has volume 240 cm³. Its length is 8 cm and width is 6 cm. What is its height?",
        "difficulty": 1,
        "answers": [
            ("5 cm", True), ("4 cm", False), ("3 cm", False), ("10 cm", False),
        ],
    },
    {
        "text": "A swimming pool is 25 m long, 10 m wide, and 2 m deep. What is its volume?",
        "difficulty": 2,
        "answers": [
            ("500 m³", True), ("250 m³", False), ("70 m³", False), ("1000 m³", False),
        ],
    },
    {
        "text": "What is the volume of a triangular prism with triangle base 6 cm, triangle height 4 cm, and prism length 10 cm?",
        "difficulty": 2,
        "answers": [
            ("120 cm³", True), ("240 cm³", False), ("60 cm³", False), ("80 cm³", False),
        ],
    },
    {
        "text": "What is the approximate volume of a cylinder with radius 3 cm and height 5 cm? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("141.3 cm³", True), ("94.2 cm³", False), ("47.1 cm³", False), ("188.4 cm³", False),
        ],
    },
    {
        "text": "A cylindrical tin has diameter 10 cm and height 15 cm. What is its approximate volume? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("1177.5 cm³", True), ("471 cm³", False), ("2355 cm³", False), ("942 cm³", False),
        ],
    },
    {
        "text": "Cube A has side 5 cm. Rectangular prism B has dimensions 4 cm × 6 cm × 5 cm. Which has the greater volume?",
        "difficulty": 2,
        "answers": [
            ("Cube A (125 cm³)", True),
            ("Prism B (120 cm³)", False),
            ("They are equal", False),
            ("Cannot be determined", False),
        ],
    },
    {
        "text": "A rectangular prism has volume 360 cm³. If all its dimensions are doubled, what is the new volume?",
        "difficulty": 3,
        "answers": [
            ("2880 cm³", True), ("720 cm³", False), ("1440 cm³", False), ("180 cm³", False),
        ],
    },
    {
        "text": "A square pyramid has base side 6 cm and height 8 cm. What is its volume? (V = ⅓ × base area × height)",
        "difficulty": 3,
        "answers": [
            ("96 cm³", True), ("288 cm³", False), ("48 cm³", False), ("144 cm³", False),
        ],
    },
]

UNIT_CONVERSION_QUESTIONS = [
    {
        "text": "Convert 3.5 km to metres.",
        "difficulty": 1,
        "answers": [
            ("3500 m", True), ("350 m", False), ("35 000 m", False), ("0.35 m", False),
        ],
    },
    {
        "text": "Convert 250 cm to metres.",
        "difficulty": 1,
        "answers": [
            ("2.5 m", True), ("25 m", False), ("0.25 m", False), ("2500 m", False),
        ],
    },
    {
        "text": "Convert 4.2 kg to grams.",
        "difficulty": 1,
        "answers": [
            ("4200 g", True), ("420 g", False), ("42 g", False), ("42 000 g", False),
        ],
    },
    {
        "text": "Convert 1800 seconds to minutes.",
        "difficulty": 1,
        "answers": [
            ("30 min", True), ("18 min", False), ("3 min", False), ("300 min", False),
        ],
    },
    {
        "text": "Convert 2.75 hours to minutes.",
        "difficulty": 2,
        "answers": [
            ("165 min", True), ("275 min", False), ("27.5 min", False), ("2750 min", False),
        ],
    },
    {
        "text": "Convert 5000 mL to litres.",
        "difficulty": 1,
        "answers": [
            ("5 L", True), ("50 L", False), ("0.5 L", False), ("500 L", False),
        ],
    },
    {
        "text": "A race is 1.6 km long. How many metres is this?",
        "difficulty": 1,
        "answers": [
            ("1600 m", True), ("160 m", False), ("16 000 m", False), ("0.16 m", False),
        ],
    },
    {
        "text": "Convert 3 hours 20 minutes to minutes.",
        "difficulty": 2,
        "answers": [
            ("200 min", True), ("320 min", False), ("23 min", False), ("180 min", False),
        ],
    },
    {
        "text": "Given that 1 mile ≈ 1.6 km, convert 5 miles to metres.",
        "difficulty": 2,
        "answers": [
            ("8000 m", True), ("8 m", False), ("800 m", False), ("80 000 m", False),
        ],
    },
    {
        "text": "A recipe needs 750 mL of milk. The bottle holds 1.5 L. What fraction of the bottle is used?",
        "difficulty": 2,
        "answers": [
            ("1/2", True), ("3/4", False), ("1/4", False), ("2/3", False),
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
        measurement_strand = Topic.objects.get(subject=maths, slug='measurement', parent=None)
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

    # --- Area (Year 7) ---
    area, _ = Topic.objects.get_or_create(
        subject=maths, slug='area',
        defaults={'name': 'Area', 'order': 3, 'is_active': True, 'parent': measurement_strand},
    )
    if year7:
        area.levels.add(year7)
        add_questions(area, AREA_QUESTIONS, year7)

    # --- Perimeter (Year 7) ---
    perimeter, _ = Topic.objects.get_or_create(
        subject=maths, slug='perimeter',
        defaults={'name': 'Perimeter', 'order': 4, 'is_active': True, 'parent': measurement_strand},
    )
    if year7:
        perimeter.levels.add(year7)
        add_questions(perimeter, PERIMETER_QUESTIONS, year7)

    # --- Volume (Year 8) ---
    volume, _ = Topic.objects.get_or_create(
        subject=maths, slug='volume',
        defaults={'name': 'Volume', 'order': 5, 'is_active': True, 'parent': measurement_strand},
    )
    if year8:
        volume.levels.add(year8)
        add_questions(volume, VOLUME_QUESTIONS, year8)

    # --- Rates (Year 7 + Year 8) ---
    rates, _ = Topic.objects.get_or_create(
        subject=maths, slug='rates',
        defaults={'name': 'Rates', 'order': 6, 'is_active': True, 'parent': measurement_strand},
    )
    if year7:
        rates.levels.add(year7)
        add_questions(rates, RATES_Y7_QUESTIONS, year7)
    if year8:
        rates.levels.add(year8)
        add_questions(rates, RATES_Y8_QUESTIONS, year8)

    # --- Unit Conversion (Year 7) ---
    unit_conv, _ = Topic.objects.get_or_create(
        subject=maths, slug='unit-conversion',
        defaults={'name': 'Unit Conversion', 'order': 7, 'is_active': True, 'parent': measurement_strand},
    )
    if year7:
        unit_conv.levels.add(year7)
        add_questions(unit_conv, UNIT_CONVERSION_QUESTIONS, year7)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    maths   = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return
    for slug in ('area', 'perimeter', 'volume', 'rates', 'unit-conversion'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0012_seed_year7_number_ratios_logic'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
