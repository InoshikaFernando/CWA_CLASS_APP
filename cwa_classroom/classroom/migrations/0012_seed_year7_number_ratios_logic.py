"""
Migration 0012 — Year 7 Number strand additions:
  - Ratios                  (Year 7, 10 questions)
  - Logic and Problem Solving (Year 7, 10 questions)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
RATIOS_QUESTIONS = [
    {
        "text": "Simplify the ratio 12:8.",
        "difficulty": 1,
        "answers": [
            ("3:2", True), ("2:3", False), ("4:6", False), ("6:4", False),
        ],
    },
    {
        "text": "Simplify the ratio 15:25.",
        "difficulty": 1,
        "answers": [
            ("3:5", True), ("5:3", False), ("6:10", False), ("3:4", False),
        ],
    },
    {
        "text": "Which ratio is equivalent to 2:3?",
        "difficulty": 1,
        "answers": [
            ("4:6", True), ("3:4", False), ("6:8", False), ("5:6", False),
        ],
    },
    {
        "text": "The ratio of boys to girls in a class is 3:2. There are 30 boys. How many girls are there?",
        "difficulty": 1,
        "answers": [
            ("20", True), ("15", False), ("45", False), ("12", False),
        ],
    },
    {
        "text": "$80 is divided in the ratio 3:5. What is the larger share?",
        "difficulty": 2,
        "answers": [
            ("$50", True), ("$30", False), ("$40", False), ("$60", False),
        ],
    },
    {
        "text": "A recipe uses flour and sugar in the ratio 2:3. If 6 cups of flour are used, how many cups of sugar are needed?",
        "difficulty": 2,
        "answers": [
            ("9", True), ("6", False), ("4", False), ("12", False),
        ],
    },
    {
        "text": "There are 40 marbles in a bag. The ratio of red to blue is 3:5. How many red marbles are there?",
        "difficulty": 2,
        "answers": [
            ("15", True), ("25", False), ("8", False), ("20", False),
        ],
    },
    {
        "text": "Simplify the ratio 1.5:3.",
        "difficulty": 2,
        "answers": [
            ("1:2", True), ("3:6", False), ("2:3", False), ("1:3", False),
        ],
    },
    {
        "text": "Tom and Jerry share $56 in the ratio 3:5. How much does Tom receive?",
        "difficulty": 2,
        "answers": [
            ("$21", True), ("$35", False), ("$24", False), ("$28", False),
        ],
    },
    {
        "text": "The ratio of cats to dogs in a shelter is 4:7. There are 28 dogs. How many animals are there in total?",
        "difficulty": 3,
        "answers": [
            ("44", True), ("16", False), ("112", False), ("32", False),
        ],
    },
]

LOGIC_QUESTIONS = [
    {
        "text": "A number is doubled and then 5 is added. The result is 21. What is the number?",
        "difficulty": 1,
        "answers": [
            ("8", True), ("13", False), ("16", False), ("10", False),
        ],
    },
    {
        "text": "In a class, 12 students play sport, 8 play music, and 5 do both. How many students play at least one activity?",
        "difficulty": 1,
        "answers": [
            ("15", True), ("20", False), ("10", False), ("25", False),
        ],
    },
    {
        "text": "A shop sells pens at 3 for $5. How much do 12 pens cost?",
        "difficulty": 1,
        "answers": [
            ("$20", True), ("$15", False), ("$36", False), ("$60", False),
        ],
    },
    {
        "text": "Five people in a room each shake hands once with every other person. How many handshakes are there in total?",
        "difficulty": 2,
        "answers": [
            ("10", True), ("20", False), ("25", False), ("5", False),
        ],
    },
    {
        "text": "Four consecutive whole numbers add up to 54. What is the smallest number?",
        "difficulty": 2,
        "answers": [
            ("12", True), ("13", False), ("11", False), ("14", False),
        ],
    },
    {
        "text": "A snail is at the bottom of a 10 m well. Each day it climbs 3 m, and each night it slips back 2 m. How many days does it take to reach the top?",
        "difficulty": 2,
        "answers": [
            ("8", True), ("10", False), ("7", False), ("9", False),
        ],
    },
    {
        "text": "What is the sum of the first 20 positive whole numbers?",
        "difficulty": 2,
        "answers": [
            ("210", True), ("200", False), ("190", False), ("220", False),
        ],
    },
    {
        "text": "In a tournament, every team plays every other team exactly once. With 6 teams, how many games are played in total?",
        "difficulty": 2,
        "answers": [
            ("15", True), ("12", False), ("30", False), ("6", False),
        ],
    },
    {
        "text": "Emma is twice Sam's age. In 6 years, Emma will be 1.5 times Sam's age. How old is Sam now?",
        "difficulty": 3,
        "answers": [
            ("6", True), ("12", False), ("8", False), ("3", False),
        ],
    },
    {
        "text": "A train travels 120 km in 1.5 hours. At the same speed, how far does it travel in 2.5 hours?",
        "difficulty": 3,
        "answers": [
            ("200 km", True), ("180 km", False), ("160 km", False), ("240 km", False),
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

    try:
        number_strand = Topic.objects.get(subject=maths, slug='number', parent=None)
    except Topic.DoesNotExist:
        return

    subtopics_data = [
        ('Ratios',                   'ratios',                    17, RATIOS_QUESTIONS),
        ('Logic and Problem Solving', 'logic-and-problem-solving', 18, LOGIC_QUESTIONS),
    ]

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

    for name, slug, order, q_list in subtopics_data:
        subtopic, _ = Topic.objects.get_or_create(
            subject=maths,
            slug=slug,
            defaults={
                'name':      name,
                'order':     order,
                'is_active': True,
                'parent':    number_strand,
            },
        )
        if year7:
            subtopic.levels.add(year7)
            add_questions(subtopic, q_list, year7)


def reverse_data(apps, schema_editor):
    Topic   = apps.get_model('classroom', 'Topic')
    Subject = apps.get_model('classroom', 'Subject')
    maths   = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return
    for slug in ('ratios', 'logic-and-problem-solving'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0011_seed_year7_algebra_quadratics'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
