"""
Migration 0029 — G8 Week 1 Questions.pdf (Year 8):
  Cube Numbers         (Y8): +14 questions
  HCF and LCM         (Y8): +10 questions
  Integers             (Y8): +8  questions (negative number arithmetic)
  Mean and Average     (Y8): +2  questions (range/mean with negatives)
  BODMAS               (Y8): +13 questions (extended order-of-operations)
All assigned to Year 8.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
CUBE_NUMBERS = [
    {
        "text": "From the list of numbers   3  6  8  14  16  28  41  64,\nwhich TWO are cube numbers?",
        "difficulty": 1,
        "answers": [
            ("8 and 64", True), ("16 and 64", False), ("8 and 27", False), ("3 and 64", False),
        ],
    },
    {
        "text": "Write down the cube root of 27.",
        "difficulty": 1,
        "answers": [
            ("3", True), ("9", False), ("13", False), ("27", False),
        ],
    },
    {
        "text": "What is the value of 5³?",
        "difficulty": 1,
        "answers": [
            ("125", True), ("15", False), ("25", False), ("243", False),
        ],
    },
    {
        "text": "What is the value of 6 cubed?",
        "difficulty": 1,
        "answers": [
            ("216", True), ("18", False), ("36", False), ("12", False),
        ],
    },
    {
        "text": "What is the value of 8³?",
        "difficulty": 1,
        "answers": [
            ("512", True), ("24", False), ("64", False), ("256", False),
        ],
    },
    {
        "text": "From the list   20  64  1  343  300  726  150  81,\nwhich values are cube numbers?",
        "difficulty": 2,
        "answers": [
            ("1, 64 and 343", True), ("1, 64 and 81", False),
            ("64, 343 and 726", False), ("1, 27 and 64", False),
        ],
    },
    {
        "text": "What is the value of ∛64?",
        "difficulty": 1,
        "answers": [
            ("4", True), ("8", False), ("32", False), ("16", False),
        ],
    },
    {
        "text": "What is the value of ∛1000?",
        "difficulty": 2,
        "answers": [
            ("10", True), ("100", False), ("31", False), ("333", False),
        ],
    },
    {
        "text": "Calculate 7.1³",
        "difficulty": 2,
        "answers": [
            ("357.911", True), ("50.41", False), ("21.3", False), ("360", False),
        ],
    },
    {
        "text": "Calculate ∛614.125",
        "difficulty": 3,
        "answers": [
            ("8.5", True), ("7.8", False), ("9.0", False), ("24.78", False),
        ],
    },
    {
        "text": "Write down a cube number that is greater than 100 and less than 200.",
        "difficulty": 1,
        "answers": [
            ("125", True), ("144", False), ("128", False), ("150", False),
        ],
    },
    {
        "text": "Arrange   2²   ∛27   1³   √25   in order starting with the smallest.",
        "difficulty": 2,
        "answers": [
            ("1³,  ∛27,  2²,  √25", True),
            ("∛27,  1³,  2²,  √25", False),
            ("1³,  2²,  ∛27,  √25", False),
            ("1³,  ∛27,  √25,  2²", False),
        ],
    },
    {
        "text": "729 is both a square number and a cube number.\nFind TWO other numbers (less than 100) that are both square and cube numbers.",
        "difficulty": 3,
        "answers": [
            ("1 and 64", True), ("4 and 64", False), ("1 and 125", False), ("64 and 144", False),
        ],
    },
    {
        "text": "Don says: 'The difference between two consecutive cube numbers is always odd.'\nIs Don correct?\n(Hint: consider (n+1)³ − n³)",
        "difficulty": 3,
        "answers": [
            ("Yes — (n+1)³ − n³ = 3n² + 3n + 1, which is always odd", True),
            ("No — e.g. 3³ − 2³ = 19 which is even", False),
            ("No — the differences are sometimes even", False),
            ("Yes — but only for even values of n", False),
        ],
    },
]

# ---------------------------------------------------------------------------
HCF_LCM = [
    {
        "text": "From the box of numbers   12  28  100  40  64  35  6  18  38,\nchoose TWO numbers that have a common factor of 10.",
        "difficulty": 1,
        "answers": [
            ("40 and 100", True), ("12 and 18", False), ("28 and 38", False), ("64 and 100", False),
        ],
    },
    {
        "text": "From the box of numbers   12  28  100  40  64  35  6  18  38,\nchoose TWO numbers that have a common multiple of 24.",
        "difficulty": 1,
        "answers": [
            ("6 and 12", True), ("12 and 18", False), ("6 and 18", False), ("12 and 28", False),
        ],
    },
    {
        "text": "From the box of numbers   12  28  100  40  64  35  6  18  38,\nchoose TWO numbers that have a common factor of 7.",
        "difficulty": 1,
        "answers": [
            ("28 and 35", True), ("35 and 64", False), ("28 and 64", False), ("12 and 28", False),
        ],
    },
    {
        "text": "A red light flashes every 6 seconds.\nA yellow light flashes every 4 seconds.\nThey both flash at the same time.\nAfter how many seconds will they next both flash at the same time?",
        "difficulty": 1,
        "answers": [
            ("12 seconds", True), ("24 seconds", False), ("10 seconds", False), ("6 seconds", False),
        ],
    },
    {
        "text": "Tilly the dog barks every 9 seconds.\nBilly the dog barks every 12 seconds.\nThey both bark at the same time.\nAfter how many seconds will they next bark at the same time?",
        "difficulty": 2,
        "answers": [
            ("36 seconds", True), ("108 seconds", False), ("21 seconds", False), ("3 seconds", False),
        ],
    },
    {
        "text": "A blue light flashes every 8 minutes.\nA pink light flashes every 54 minutes.\nBoth lights flash together at 2:00 pm.\nWhen is the next time both lights will flash together?",
        "difficulty": 3,
        "answers": [
            ("5:36 pm", True), ("3:00 pm", False), ("6:02 pm", False), ("4:08 pm", False),
        ],
    },
    {
        "text": "There are 18 bread rolls in a packet and 15 hot dogs in a packet.\nMary buys exactly the same number of bread rolls as hot dogs.\nWhat is the smallest number of packets of bread rolls she must buy?",
        "difficulty": 2,
        "answers": [
            ("5 packets", True), ("6 packets", False), ("3 packets", False), ("15 packets", False),
        ],
    },
    {
        "text": "Trains leave Bristol to Cardiff every 15 minutes and to London every 21 minutes.\nBoth trains leave together at 11:00 am.\nAt what time will they next leave Bristol at the same time?",
        "difficulty": 3,
        "answers": [
            ("12:45 pm", True), ("11:36 am", False), ("1:00 pm", False), ("12:15 pm", False),
        ],
    },
    {
        "text": "The HCF of two numbers is 6 and their LCM is 60.\nBoth numbers are between 10 and 50.\nWhat are the two numbers?",
        "difficulty": 3,
        "answers": [
            ("12 and 30", True), ("6 and 60", False), ("6 and 10", False), ("12 and 60", False),
        ],
    },
    {
        "text": "A red light flashes every 3 seconds, a yellow every 8 seconds, a green every 11 seconds.\nThey all flash at the same time.\nAfter how many seconds will they all next flash together?",
        "difficulty": 3,
        "answers": [
            ("264 seconds", True), ("22 seconds", False), ("88 seconds", False), ("33 seconds", False),
        ],
    },
]

# ---------------------------------------------------------------------------
NEGATIVES = [
    {
        "text": "The temperature in Leek is −8°C.\nThe temperature in Randalstown is 10°C colder than Leek.\nWhat is the temperature in Randalstown?",
        "difficulty": 1,
        "answers": [
            ("−18°C", True), ("−2°C", False), ("2°C", False), ("18°C", False),
        ],
    },
    {
        "text": "Boston's minimum temperature is −2°C and maximum is 13°C.\nWhat is the difference between Boston's minimum and maximum temperature?",
        "difficulty": 1,
        "answers": [
            ("15°C", True), ("11°C", False), ("−15°C", False), ("26°C", False),
        ],
    },
    {
        "text": "Anchorage's minimum temperature is −12°C and maximum is −5°C.\nWhat is the difference between these two temperatures?",
        "difficulty": 2,
        "answers": [
            ("7°C", True), ("−7°C", False), ("17°C", False), ("−17°C", False),
        ],
    },
    {
        "text": "Georgetown's elevation is −2 metres. Dublin's elevation is 8 metres.\nWork out the difference in their elevations.",
        "difficulty": 2,
        "answers": [
            ("10 m", True), ("6 m", False), ("−10 m", False), ("16 m", False),
        ],
    },
    {
        "text": "Work out the difference between −3°C and 4°C.",
        "difficulty": 1,
        "answers": [
            ("7°C", True), ("1°C", False), ("−7°C", False), ("−1°C", False),
        ],
    },
    {
        "text": "At 5 am the temperature is −6°C.\nBy 2 pm it rose by 9°C.\nFrom 2 pm to 11 pm it fell by 15°C.\nWhat is the temperature at 11 pm?",
        "difficulty": 2,
        "answers": [
            ("−12°C", True), ("−3°C", False), ("0°C", False), ("−18°C", False),
        ],
    },
    {
        "text": "Frome Rovers started the season on −10 points.\nEach win = 3 pts, each draw = 1 pt, each loss = 0 pts.\nThey won 11, drew 6, and lost 3 matches.\nHow many points did they finish with?",
        "difficulty": 3,
        "answers": [
            ("29", True), ("39", False), ("19", False), ("−1", False),
        ],
    },
    {
        "text": "Fiona throws 8 balls. Each hit = +5 pts, each miss = −3 pts.\nShe hits 5 and misses 3.\nHow many points does Fiona score?",
        "difficulty": 2,
        "answers": [
            ("16", True), ("25", False), ("22", False), ("−9", False),
        ],
    },
]

# ---------------------------------------------------------------------------
NEGATIVES_MEAN = [
    {
        "text": "A weather station records these midnight temperatures (°C) over 5 days:\nMon: −4,  Tue: 1,  Wed: −6,  Thu: 1,  Fri: −2\nWhat is the range of the temperatures?",
        "difficulty": 2,
        "answers": [
            ("7°C", True), ("5°C", False), ("−5°C", False), ("12°C", False),
        ],
    },
    {
        "text": "A weather station records these midnight temperatures (°C) over 5 days:\nMon: −4,  Tue: 1,  Wed: −6,  Thu: 1,  Fri: −2\nWhat is the mean temperature?",
        "difficulty": 2,
        "answers": [
            ("−2°C", True), ("0°C", False), ("−10°C", False), ("2°C", False),
        ],
    },
]

# ---------------------------------------------------------------------------
BODMAS_EXTRA = [
    {
        "text": "Calculate: 16 − 5 × 2",
        "difficulty": 1,
        "answers": [
            ("6", True), ("22", False), ("11", False), ("10", False),
        ],
    },
    {
        "text": "Calculate: 10 − 3²",
        "difficulty": 1,
        "answers": [
            ("1", True), ("49", False), ("−49", False), ("7", False),
        ],
    },
    {
        "text": "Calculate: 8 ÷ 2 + 12 ÷ 4",
        "difficulty": 1,
        "answers": [
            ("7", True), ("5", False), ("4", False), ("2.5", False),
        ],
    },
    {
        "text": "Calculate: 8 + 3(5 − 1)",
        "difficulty": 2,
        "answers": [
            ("20", True), ("44", False), ("35", False), ("12", False),
        ],
    },
    {
        "text": "Calculate: 9 × 2 + 20 ÷ 2",
        "difficulty": 2,
        "answers": [
            ("28", True), ("19", False), ("145", False), ("14", False),
        ],
    },
    {
        "text": "Where should brackets be placed to make this true?\n6 × 7 + 3 − 8 = 52",
        "difficulty": 2,
        "answers": [
            ("6 × (7 + 3) − 8", True),
            ("(6 × 7 + 3) − 8", False),
            ("6 × (7 + 3 − 8)", False),
            ("6 × 7 + (3 − 8)", False),
        ],
    },
    {
        "text": "Where should brackets be placed to make this true?\n4 + 3 × 7 − 1 = 42",
        "difficulty": 2,
        "answers": [
            ("(4 + 3) × (7 − 1)", True),
            ("4 + 3 × (7 − 1)", False),
            ("(4 + 3) × 7 − 1", False),
            ("4 + (3 × 7 − 1)", False),
        ],
    },
    {
        "text": "Work out: 6 × 4 − 7 × 3",
        "difficulty": 2,
        "answers": [
            ("3", True), ("−3", False), ("42", False), ("51", False),
        ],
    },
    {
        "text": "Work out: 2³ + 3²",
        "difficulty": 2,
        "answers": [
            ("17", True), ("25", False), ("13", False), ("11", False),
        ],
    },
    {
        "text": "Work out: 2² × 3³",
        "difficulty": 2,
        "answers": [
            ("108", True), ("216", False), ("72", False), ("36", False),
        ],
    },
    {
        "text": "Work out: (2 + 5)²",
        "difficulty": 1,
        "answers": [
            ("49", True), ("29", False), ("14", False), ("32", False),
        ],
    },
    {
        "text": "Work out: (9 + 4) × (100 ÷ 25)",
        "difficulty": 2,
        "answers": [
            ("52", True), ("36", False), ("40", False), ("56", False),
        ],
    },
    {
        "text": "Work out: (11 + 7 − 2) ÷ 2²",
        "difficulty": 3,
        "answers": [
            ("4", True), ("10", False), ("16", False), ("6.25", False),
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
        'cube-numbers':  CUBE_NUMBERS,
        'hcf-and-lcm':   HCF_LCM,
        'integers':      NEGATIVES,
        'mean-and-average': NEGATIVES_MEAN,
        'bodmas':        BODMAS_EXTRA,
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
        [q['text'] for q in CUBE_NUMBERS]
        + [q['text'] for q in HCF_LCM]
        + [q['text'] for q in NEGATIVES]
        + [q['text'] for q in NEGATIVES_MEAN]
        + [q['text'] for q in BODMAS_EXTRA]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0028_seed_year8_percentages_bodmas'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
