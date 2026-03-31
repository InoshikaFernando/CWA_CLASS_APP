"""
Migration 0015 — Geometry strand additions:
  - Pythagoras' Theorem  (Year 8, 10 questions)
  - Circles              (Year 8, 10 questions)
  - Composite Areas      (Year 8, 10 questions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
PYTHAGORAS_QUESTIONS = [
    {
        "text": "A right-angled triangle has legs 3 cm and 4 cm. What is the length of the hypotenuse?",
        "difficulty": 1,
        "answers": [
            ("5 cm", True), ("7 cm", False), ("12 cm", False), ("25 cm", False),
        ],
    },
    {
        "text": "A right-angled triangle has legs 5 cm and 12 cm. What is the length of the hypotenuse?",
        "difficulty": 1,
        "answers": [
            ("13 cm", True), ("17 cm", False), ("169 cm", False), ("7 cm", False),
        ],
    },
    {
        "text": "A right-angled triangle has hypotenuse 10 cm and one leg 6 cm. What is the length of the other leg?",
        "difficulty": 1,
        "answers": [
            ("8 cm", True), ("4 cm", False), ("11.7 cm", False), ("16 cm", False),
        ],
    },
    {
        "text": "A ladder 5 m long leans against a wall. Its base is 3 m from the wall. How high up the wall does it reach?",
        "difficulty": 2,
        "answers": [
            ("4 m", True), ("5.8 m", False), ("2 m", False), ("8 m", False),
        ],
    },
    {
        "text": "A rectangle has length 15 cm and width 8 cm. What is the length of its diagonal?",
        "difficulty": 2,
        "answers": [
            ("17 cm", True), ("23 cm", False), ("12.7 cm", False), ("289 cm", False),
        ],
    },
    {
        "text": "Is a triangle with sides 6 cm, 8 cm, and 11 cm a right-angled triangle?",
        "difficulty": 2,
        "answers": [
            ("No — 6² + 8² = 100, but 11² = 121", True),
            ("Yes — it satisfies Pythagoras' theorem", False),
            ("Cannot be determined without angles", False),
            ("Yes — because 6 + 8 > 11", False),
        ],
    },
    {
        "text": "What is the length of the diagonal of a square with side 7 cm? (Leave in surd form)",
        "difficulty": 2,
        "answers": [
            ("7√2 cm", True), ("14 cm", False), ("√7 cm", False), ("49 cm", False),
        ],
    },
    {
        "text": "A right-angled triangle has hypotenuse 25 cm and one leg 7 cm. What is the other leg?",
        "difficulty": 2,
        "answers": [
            ("24 cm", True), ("18 cm", False), ("26 cm", False), ("32 cm", False),
        ],
    },
    {
        "text": "Two ships leave a port. One sails 9 km east and the other 12 km north. How far apart are they?",
        "difficulty": 3,
        "answers": [
            ("15 km", True), ("21 km", False), ("225 km", False), ("3 km", False),
        ],
    },
    {
        "text": "A right-angled triangle has one leg twice the length of the other. If the shorter leg is 5 cm, what is the hypotenuse? (Round to 1 decimal place)",
        "difficulty": 3,
        "answers": [
            ("11.2 cm", True), ("10 cm", False), ("15 cm", False), ("7.1 cm", False),
        ],
    },
]

CIRCLES_QUESTIONS = [
    {
        "text": "What is the circumference of a circle with radius 7 cm? (Use π ≈ 22/7)",
        "difficulty": 1,
        "answers": [
            ("44 cm", True), ("154 cm", False), ("22 cm", False), ("49 cm", False),
        ],
    },
    {
        "text": "What is the area of a circle with radius 5 cm? (Use π ≈ 3.14)",
        "difficulty": 1,
        "answers": [
            ("78.5 cm²", True), ("31.4 cm²", False), ("15.7 cm²", False), ("157 cm²", False),
        ],
    },
    {
        "text": "A circle has diameter 20 cm. What is its radius?",
        "difficulty": 1,
        "answers": [
            ("10 cm", True), ("40 cm", False), ("5 cm", False), ("20 cm", False),
        ],
    },
    {
        "text": "What is the area of a circle with diameter 14 cm? (Use π ≈ 22/7)",
        "difficulty": 1,
        "answers": [
            ("154 cm²", True), ("616 cm²", False), ("44 cm²", False), ("77 cm²", False),
        ],
    },
    {
        "text": "A circle has circumference 62.8 cm. What is its radius? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("10 cm", True), ("5 cm", False), ("20 cm", False), ("31.4 cm", False),
        ],
    },
    {
        "text": "The area of a circle is 1386 cm². What is its diameter? (Use π ≈ 22/7)",
        "difficulty": 2,
        "answers": [
            ("42 cm", True), ("21 cm", False), ("84 cm", False), ("441 cm", False),
        ],
    },
    {
        "text": "A semicircle has diameter 10 cm. What is its perimeter (straight edge + curved edge)? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("25.7 cm", True), ("15.7 cm", False), ("31.4 cm", False), ("51.4 cm", False),
        ],
    },
    {
        "text": "What is the length of an arc that subtends a 90° angle at the centre of a circle with radius 8 cm? (Use π ≈ 3.14)",
        "difficulty": 3,
        "answers": [
            ("12.56 cm", True), ("25.12 cm", False), ("50.24 cm", False), ("6.28 cm", False),
        ],
    },
    {
        "text": "What is the area of a sector with radius 6 cm and central angle 60°? (Use π ≈ 3.14)",
        "difficulty": 3,
        "answers": [
            ("18.84 cm²", True), ("113.04 cm²", False), ("56.52 cm²", False), ("37.68 cm²", False),
        ],
    },
    {
        "text": "A circular pizza has radius 12 cm. It is cut into 8 equal slices. What is the arc length of one slice? (Use π ≈ 3.14)",
        "difficulty": 3,
        "answers": [
            ("9.42 cm", True), ("18.84 cm", False), ("75.36 cm", False), ("4.71 cm", False),
        ],
    },
]

COMPOSITE_AREAS_QUESTIONS = [
    {
        "text": "A shape has a rectangle (6 cm × 4 cm) with a triangle on top (base 6 cm, height 3 cm). What is the total area?",
        "difficulty": 1,
        "answers": [
            ("33 cm²", True), ("27 cm²", False), ("39 cm²", False), ("24 cm²", False),
        ],
    },
    {
        "text": "Two rectangles do not overlap. One is 8 cm × 5 cm and the other is 4 cm × 3 cm. What is the total area?",
        "difficulty": 1,
        "answers": [
            ("52 cm²", True), ("76 cm²", False), ("24 cm²", False), ("44 cm²", False),
        ],
    },
    {
        "text": "A shape is formed by removing a triangle (base 4 cm, height 3 cm) from a rectangle (8 cm × 5 cm). What is the remaining area?",
        "difficulty": 2,
        "answers": [
            ("34 cm²", True), ("28 cm²", False), ("46 cm²", False), ("32 cm²", False),
        ],
    },
    {
        "text": "A square has a circular hole cut from its centre. The square has side 10 cm and the circle has radius 3 cm. What is the remaining area? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("71.74 cm²", True), ("94 cm²", False), ("78.26 cm²", False), ("100 cm²", False),
        ],
    },
    {
        "text": "A semicircle sits on top of a rectangle. The rectangle is 8 cm wide and 5 cm tall. The semicircle has diameter 8 cm. What is the total area? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("65.12 cm²", True), ("40 cm²", False), ("90.24 cm²", False), ("71.04 cm²", False),
        ],
    },
    {
        "text": "A rectangular pool (12 m × 8 m) has a circular fountain (radius 2 m) in the centre. What is the pool area excluding the fountain? (Use π ≈ 3.14)",
        "difficulty": 2,
        "answers": [
            ("83.44 m²", True), ("96 m²", False), ("108.56 m²", False), ("79.44 m²", False),
        ],
    },
    {
        "text": "An L-shaped room is formed by a 10 m × 8 m rectangle with a 4 m × 3 m section removed from one corner. What is the area of the L-shape?",
        "difficulty": 2,
        "answers": [
            ("68 m²", True), ("80 m²", False), ("72 m²", False), ("56 m²", False),
        ],
    },
    {
        "text": "A running track has two straight sections (100 m × 60 m rectangle) with a semicircle on each short end. What is the total area enclosed? (Use π ≈ 3.14)",
        "difficulty": 3,
        "answers": [
            ("8826 m²", True), ("6000 m²", False), ("11424 m²", False), ("9424 m²", False),
        ],
    },
    {
        "text": "A shape is formed by a rectangle (10 cm × 6 cm) with a semicircle removed from one short end (diameter 6 cm). What is the remaining area? (Use π ≈ 3.14)",
        "difficulty": 3,
        "answers": [
            ("45.87 cm²", True), ("60 cm²", False), ("74.13 cm²", False), ("31.74 cm²", False),
        ],
    },
    {
        "text": "Two identical circles each with radius 4 cm have a combined area of 100.48 cm² (π ≈ 3.14). If their overlapping region has area 10 cm², what is the total area covered?",
        "difficulty": 3,
        "answers": [
            ("90.48 cm²", True), ("100.48 cm²", False), ("80.48 cm²", False), ("110.48 cm²", False),
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
    year8  = Level.objects.filter(level_number=8).first()

    try:
        geometry_strand = Topic.objects.get(subject=maths, slug='geometry', parent=None)
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

    subtopics_data = [
        ("Pythagoras' Theorem", 'pythagoras-theorem',  3, PYTHAGORAS_QUESTIONS),
        ('Circles',             'circles',             4, CIRCLES_QUESTIONS),
        ('Composite Areas',     'composite-areas',     5, COMPOSITE_AREAS_QUESTIONS),
    ]

    for name, slug, order, q_list in subtopics_data:
        subtopic, _ = Topic.objects.get_or_create(
            subject=maths, slug=slug,
            defaults={'name': name, 'order': order, 'is_active': True, 'parent': geometry_strand},
        )
        if year8:
            subtopic.levels.add(year8)
            add_questions(subtopic, q_list, year8)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    maths   = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return
    for slug in ('pythagoras-theorem', 'circles', 'composite-areas'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0014_seed_algebra_subtopics'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
