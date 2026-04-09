"""
Migration 0016 — Space + Statistics strand additions:
  Space:
    - 3D Shapes          (Year 7, 10 questions)
  Statistics:
    - Mean and Average   (Year 7, 10 questions)
    - Probability        (Year 7, 10 questions)
    - Data Interpretation (Year 7, 10 questions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
SHAPES_3D_QUESTIONS = [
    {
        "text": "How many faces does a rectangular prism (cuboid) have?",
        "difficulty": 1,
        "answers": [
            ("6", True), ("4", False), ("8", False), ("12", False),
        ],
    },
    {
        "text": "How many edges does a cube have?",
        "difficulty": 1,
        "answers": [
            ("12", True), ("6", False), ("8", False), ("24", False),
        ],
    },
    {
        "text": "How many vertices does a triangular pyramid (tetrahedron) have?",
        "difficulty": 1,
        "answers": [
            ("4", True), ("3", False), ("6", False), ("8", False),
        ],
    },
    {
        "text": "What is the name of a 3D shape with a circular base and one apex (vertex)?",
        "difficulty": 1,
        "answers": [
            ("Cone", True), ("Cylinder", False), ("Pyramid", False), ("Sphere", False),
        ],
    },
    {
        "text": "How many faces does a square pyramid have?",
        "difficulty": 1,
        "answers": [
            ("5", True), ("4", False), ("6", False), ("8", False),
        ],
    },
    {
        "text": "A shape has 5 faces, 9 edges, and 6 vertices. What 3D shape is it?",
        "difficulty": 2,
        "answers": [
            ("Triangular prism", True),
            ("Square pyramid", False),
            ("Rectangular prism", False),
            ("Pentagonal face", False),
        ],
    },
    {
        "text": "Which 3D shape has no flat faces?",
        "difficulty": 1,
        "answers": [
            ("Sphere", True), ("Cone", False), ("Cylinder", False), ("Pyramid", False),
        ],
    },
    {
        "text": "A cube has edge length 4 cm. What is its total surface area?",
        "difficulty": 2,
        "answers": [
            ("96 cm²", True), ("64 cm²", False), ("48 cm²", False), ("144 cm²", False),
        ],
    },
    {
        "text": "A triangular prism has two triangular faces and three rectangular faces. How many edges does it have?",
        "difficulty": 2,
        "answers": [
            ("9", True), ("6", False), ("12", False), ("15", False),
        ],
    },
    {
        "text": "A rectangular prism has length 5 cm, width 4 cm, and height 3 cm. What is its total surface area?",
        "difficulty": 3,
        "answers": [
            ("94 cm²", True), ("60 cm²", False), ("47 cm²", False), ("120 cm²", False),
        ],
    },
]

MEAN_AVERAGE_QUESTIONS = [
    {
        "text": "Find the mean of: 4, 7, 9, 2, 8",
        "difficulty": 1,
        "answers": [
            ("6", True), ("7", False), ("5", False), ("4", False),
        ],
    },
    {
        "text": "Find the median of: 3, 7, 1, 9, 5",
        "difficulty": 1,
        "answers": [
            ("5", True), ("7", False), ("6", False), ("4", False),
        ],
    },
    {
        "text": "Find the mode of: 2, 5, 3, 5, 7, 2, 5, 1",
        "difficulty": 1,
        "answers": [
            ("5", True), ("2", False), ("3", False), ("4", False),
        ],
    },
    {
        "text": "Find the range of: 12, 7, 19, 3, 15",
        "difficulty": 1,
        "answers": [
            ("16", True), ("12", False), ("11", False), ("19", False),
        ],
    },
    {
        "text": "The mean of 5 numbers is 8. What is their sum?",
        "difficulty": 1,
        "answers": [
            ("40", True), ("8", False), ("1.6", False), ("13", False),
        ],
    },
    {
        "text": "The mean of 4 numbers is 9. Three of them are 6, 11, and 8. What is the fourth number?",
        "difficulty": 2,
        "answers": [
            ("11", True), ("9", False), ("7", False), ("25", False),
        ],
    },
    {
        "text": "Find the median of: 14, 22, 17, 8, 31, 26",
        "difficulty": 2,
        "answers": [
            ("19.5", True), ("17", False), ("22", False), ("18", False),
        ],
    },
    {
        "text": "Six test scores are: 72, 85, 91, 68, 79, 85. What is the mean?",
        "difficulty": 2,
        "answers": [
            ("80", True), ("85", False), ("79", False), ("78", False),
        ],
    },
    {
        "text": "A cricket player's scores over 6 innings are: 34, 67, 12, 89, 45, 23. What is the mean score?",
        "difficulty": 2,
        "answers": [
            ("45", True), ("67", False), ("44", False), ("50", False),
        ],
    },
    {
        "text": "A dataset has mean 50 and 8 values. If a new value of 66 is added, what is the new mean?",
        "difficulty": 3,
        "answers": [
            ("52", True), ("58", False), ("50", False), ("55", False),
        ],
    },
]

PROBABILITY_QUESTIONS = [
    {
        "text": "A fair coin is flipped. What is the probability of getting heads?",
        "difficulty": 1,
        "answers": [
            ("1/2", True), ("1", False), ("0", False), ("2", False),
        ],
    },
    {
        "text": "A standard die is rolled. What is the probability of rolling a 4?",
        "difficulty": 1,
        "answers": [
            ("1/6", True), ("1/4", False), ("4/6", False), ("1/3", False),
        ],
    },
    {
        "text": "What is the probability of an impossible event?",
        "difficulty": 1,
        "answers": [
            ("0", True), ("1", False), ("0.5", False), ("−1", False),
        ],
    },
    {
        "text": "A bag has 3 red, 4 blue, and 5 green marbles. What is the probability of picking a red marble?",
        "difficulty": 1,
        "answers": [
            ("1/4", True), ("3/5", False), ("4/12", False), ("5/12", False),
        ],
    },
    {
        "text": "A letter is chosen randomly from the word MATHEMATICS. What is the probability it is an M?",
        "difficulty": 2,
        "answers": [
            ("2/11", True), ("1/11", False), ("3/11", False), ("2/9", False),
        ],
    },
    {
        "text": "A spinner has 8 equal sections numbered 1–8. What is the probability of landing on a prime number?",
        "difficulty": 2,
        "answers": [
            ("1/2", True), ("3/8", False), ("5/8", False), ("1/4", False),
        ],
    },
    {
        "text": "A box contains 12 chocolates: 5 dark and 7 milk. What is the probability of NOT choosing a dark chocolate?",
        "difficulty": 2,
        "answers": [
            ("7/12", True), ("5/12", False), ("1/2", False), ("7/5", False),
        ],
    },
    {
        "text": "Two coins are flipped at the same time. What is the probability of getting two tails?",
        "difficulty": 2,
        "answers": [
            ("1/4", True), ("1/2", False), ("1/3", False), ("3/4", False),
        ],
    },
    {
        "text": "A class has 15 girls and 10 boys. A student is selected at random. What is the probability of choosing a girl?",
        "difficulty": 2,
        "answers": [
            ("3/5", True), ("1/3", False), ("2/3", False), ("15/10", False),
        ],
    },
    {
        "text": "A bag has 6 red and 4 blue balls. One is drawn and not replaced, then another is drawn. What is the probability both are red?",
        "difficulty": 3,
        "answers": [
            ("1/3", True), ("6/10", False), ("3/10", False), ("36/100", False),
        ],
    },
]

DATA_INTERPRETATION_QUESTIONS = [
    {
        "text": "A bar graph shows daily sales: Mon=20, Tue=35, Wed=25, Thu=40, Fri=30. What is the mean daily sales?",
        "difficulty": 1,
        "answers": [
            ("30", True), ("35", False), ("25", False), ("150", False),
        ],
    },
    {
        "text": "A pie chart shows: 25% football, 30% basketball, 20% tennis, 25% other. In a group of 200 students, how many prefer basketball?",
        "difficulty": 1,
        "answers": [
            ("60", True), ("50", False), ("40", False), ("30", False),
        ],
    },
    {
        "text": "A frequency table shows: Score 1–2: 4 students, Score 3–4: 7 students, Score 5–6: 5 students, Score 7–8: 4 students. How many students are there in total?",
        "difficulty": 1,
        "answers": [
            ("20", True), ("16", False), ("7", False), ("18", False),
        ],
    },
    {
        "text": "A bar graph shows monthly rainfall: Jan=40mm, Feb=35mm, Mar=55mm, Apr=30mm. What is the total rainfall over these four months?",
        "difficulty": 1,
        "answers": [
            ("160 mm", True), ("150 mm", False), ("140 mm", False), ("170 mm", False),
        ],
    },
    {
        "text": "A stem-and-leaf plot has: stem 1 — leaves 2, 5, 8; stem 2 — leaves 0, 3; stem 3 — leaf 1. How many data values are there in total?",
        "difficulty": 2,
        "answers": [
            ("6", True), ("8", False), ("5", False), ("3", False),
        ],
    },
    {
        "text": "A pie chart represents 360°. A slice represents 72°. What percentage of the total does this slice represent?",
        "difficulty": 2,
        "answers": [
            ("20%", True), ("72%", False), ("25%", False), ("10%", False),
        ],
    },
    {
        "text": "Class A scores (sorted): 45, 52, 67, 73, 81. Class B scores (sorted): 48, 56, 63, 70, 82. Which class has the higher median?",
        "difficulty": 2,
        "answers": [
            ("Class A (median 67)", True),
            ("Class B (median 63)", False),
            ("They are equal", False),
            ("Cannot be determined", False),
        ],
    },
    {
        "text": "A tally shows: value 1 → 4 tallies, value 2 → 3 tallies, value 3 → 5 tallies, value 4 → 2 tallies. What is the mode?",
        "difficulty": 2,
        "answers": [
            ("3", True), ("1", False), ("4", False), ("2", False),
        ],
    },
    {
        "text": "A dataset is: 12, 15, 11, 18, 14, 15, 13, 12, 15, 10. What is the mode?",
        "difficulty": 2,
        "answers": [
            ("15", True), ("12", False), ("13", False), ("14", False),
        ],
    },
    {
        "text": "A line graph shows temperatures: Mon=18°C, Tue=22°C, Wed=20°C, Thu=25°C, Fri=17°C. What is the range of temperatures shown?",
        "difficulty": 3,
        "answers": [
            ("8°C", True), ("25°C", False), ("7°C", False), ("17°C", False),
        ],
    },
]


def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('maths', 'Question')
    Answer   = apps.get_model('maths', 'Answer')

    maths  = Subject.objects.get(slug='mathematics')
    year7  = Level.objects.filter(level_number=7).first()

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

    # --- Space strand ---
    try:
        space_strand = Topic.objects.get(subject=maths, slug='space', parent=None)
    except Topic.DoesNotExist:
        space_strand = None

    if space_strand and year7:
        shapes_3d, _ = Topic.objects.get_or_create(
            subject=maths, slug='3d-shapes',
            defaults={'name': '3D Shapes', 'order': 1, 'is_active': True, 'parent': space_strand},
        )
        shapes_3d.levels.add(year7)
        add_questions(shapes_3d, SHAPES_3D_QUESTIONS, year7)

    # --- Statistics strand ---
    try:
        stats_strand = Topic.objects.get(subject=maths, slug='statistics', parent=None)
    except Topic.DoesNotExist:
        stats_strand = None

    if stats_strand and year7:
        stat_subtopics = [
            ('Mean and Average',      'mean-and-average',      1, MEAN_AVERAGE_QUESTIONS),
            ('Probability',           'probability',           2, PROBABILITY_QUESTIONS),
            ('Data Interpretation',   'data-interpretation',   3, DATA_INTERPRETATION_QUESTIONS),
        ]
        for name, slug, order, q_list in stat_subtopics:
            subtopic, _ = Topic.objects.get_or_create(
                subject=maths, slug=slug,
                defaults={'name': name, 'order': order, 'is_active': True, 'parent': stats_strand},
            )
            subtopic.levels.add(year7)
            add_questions(subtopic, q_list, year7)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    maths   = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return
    for slug in ('3d-shapes', 'mean-and-average', 'probability', 'data-interpretation'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0015_seed_geometry_subtopics'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
