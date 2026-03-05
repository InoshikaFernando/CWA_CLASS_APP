"""
Migration 0030 — Create missing subtopics + seed their Year 8 questions.

The subtopics 'percentages', 'hcf-and-lcm', and 'cube-numbers' did not exist
when migrations 0025–0029 ran, so questions targeting them were silently skipped.
This migration creates those three subtopics under the Number strand, then
re-inserts all question data that was previously dropped.

Topics created:
  Percentages  (slug: percentages)   → Year 7 + Year 8
  HCF and LCM (slug: hcf-and-lcm)   → Year 8
  Cube Numbers (slug: cube-numbers)  → Year 8

Questions seeded for Year 8:
  percentages:  20 questions (from ACER Set02, ACER Set03, AMC, G Percentages worksheet)
  hcf-and-lcm: 10 questions (from G8 Week 1)
  cube-numbers: 14 questions (from G8 Week 1)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# Re-include question data that was skipped in earlier migrations
# ---------------------------------------------------------------------------

# From migration 0026 (ACER Set02)
PERCENTAGES_ACER02 = [
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

# From migration 0027 (ACER Set03 + AMC)
PERCENTAGES_ACER03 = [
    {
        "text": (
            "There were 840 people in a marathon. 45% are female and 100 of the female participants "
            "were not wearing red. 35% of all participants are in red. How many males were wearing red?"
        ),
        "difficulty": 3,
        "answers": [
            ("16", True), ("75", False), ("24", False), ("37", False),
        ],
    },
    {
        "text": "What is 60% of the circumference, if 45% of the circumference is 60 cm?",
        "difficulty": 2,
        "answers": [
            ("80 cm", True), ("48 cm", False), ("66 cm", False), ("72 cm", False),
        ],
    },
    {
        "text": "What is 19% of $20?",
        "difficulty": 1,
        "answers": [
            ("$3.80", True), ("$20.19", False), ("$1.90", False), ("$0.19", False),
        ],
    },
]

# From migration 0028 (G Percenrages.pdf worksheet)
PERCENTAGES_WS = [
    {
        "text": (
            "Isaac's comic book collection is 125% the size of Angela's collection. "
            "Isaac has 75 comic books. How many comic books does Angela have?"
        ),
        "difficulty": 2,
        "answers": [
            ("60", True), ("94", False), ("50", False), ("75", False),
        ],
    },
    {
        "text": (
            "A fast food meal provides 390% of the recommended daily fat allowance. "
            "The recommended daily allowance is 20 grams. "
            "How many grams of fat are in the meal?"
        ),
        "difficulty": 1,
        "answers": [
            ("78 g", True), ("390 g", False), ("19.5 g", False), ("410 g", False),
        ],
    },
    {
        "text": (
            "A girl usually grows to be 125% of her height at age 9. "
            "If a girl is 132 cm tall at age 9, what will her adult height likely be?"
        ),
        "difficulty": 1,
        "answers": [
            ("165 cm", True), ("157 cm", False), ("176 cm", False), ("99 cm", False),
        ],
    },
    {
        "text": (
            "Last year, 800 students were enrolled at Claire's school. "
            "This is 250% of the enrolment 15 years ago. "
            "What was the enrolment 15 years ago?"
        ),
        "difficulty": 2,
        "answers": [
            ("320", True), ("2000", False), ("550", False), ("400", False),
        ],
    },
    {
        "text": (
            "A fast food meal contains 70 grams of fat. "
            "What percentage of the recommended daily allowance of 20 grams is this?"
        ),
        "difficulty": 2,
        "answers": [
            ("350%", True), ("29%", False), ("70%", False), ("50%", False),
        ],
    },
    {
        "text": (
            "You can taste sweetness if 0.5% of a sugar-and-water mixture is sugar. "
            "What is the least amount of sugar needed in a 250-gram mixture "
            "for it to taste sweet?"
        ),
        "difficulty": 2,
        "answers": [
            ("1.25 g", True), ("12.5 g", False), ("125 g", False), ("0.5 g", False),
        ],
    },
    {
        "text": (
            "About 0.9% of Canada's population is Sikh. "
            "If Canada's population is about 34 million, "
            "approximately how many people are Sikh?"
        ),
        "difficulty": 2,
        "answers": [
            ("306 000", True), ("3 060 000", False), ("30 600", False), ("340 000", False),
        ],
    },
    {
        "text": (
            "The recommended body mass for muscle should be about 310% of the mass for fat. "
            "Blake's fat mass is 10.4 kg. What should his muscle mass be?"
        ),
        "difficulty": 2,
        "answers": [
            ("32.24 kg", True), ("322.4 kg", False), ("13.5 kg", False), ("3.35 kg", False),
        ],
    },
    {
        "text": (
            "Jeff's parents paid $400 for new flooring after receiving a 20% discount. "
            "What was the original (regular) price of the flooring?"
        ),
        "difficulty": 3,
        "answers": [
            ("$500", True), ("$480", False), ("$320", False), ("$420", False),
        ],
    },
    {
        "text": (
            "Isaac is saving for a mountain bike. The bike costs $349, "
            "which is 212% of the amount currently in his savings account. "
            "Approximately how much has Isaac saved?"
        ),
        "difficulty": 3,
        "answers": [
            ("$164.62", True), ("$739.88", False), ("$137.00", False), ("$212.00", False),
        ],
    },
    {
        "text": (
            "Nick buys a book with a regular price of $69.98. "
            "It is on sale for 30% off, and he pays 5% GST on the sale price. "
            "How much does Nick pay in total?"
        ),
        "difficulty": 3,
        "answers": [
            ("$51.44", True), ("$48.99", False), ("$52.48", False), ("$45.49", False),
        ],
    },
    {
        "text": (
            "Holly finds a guitar on sale for 25% off the regular price of $329.99. "
            "She pays 5% GST and 7% PST on the discounted price. "
            "How much does she pay in total?"
        ),
        "difficulty": 3,
        "answers": [
            ("$277.19", True), ("$247.49", False), ("$259.87", False), ("$287.09", False),
        ],
    },
    {
        "text": (
            "A sugar-and-water mixture of 250 grams contains 8 grams of sugar. "
            "What percentage of the mixture is sugar?"
        ),
        "difficulty": 1,
        "answers": [
            ("3.2%", True), ("31.25%", False), ("8%", False), ("0.032%", False),
        ],
    },
    {
        "text": (
            "In Kyle's class, 15 students play in the local soccer league. "
            "They make up 6% of the total league. "
            "How many students are in the league altogether?"
        ),
        "difficulty": 3,
        "answers": [
            ("250", True), ("90", False), ("21", False), ("150", False),
        ],
    },
    {
        "text": (
            "Barry scored 17 out of 20 on a science test and 39 out of 50 on a maths test. "
            "On which test did he perform better, and what were the two percentages?"
        ),
        "difficulty": 2,
        "answers": [
            ("Science was better: 85% vs 78%", True),
            ("Maths was better: 85% vs 78%", False),
            ("Maths was better: 39% vs 17%", False),
            ("They were equal: both 80%", False),
        ],
    },
]

# All percentage questions combined
ALL_PERCENTAGES_Y8 = PERCENTAGES_ACER02 + PERCENTAGES_ACER03 + PERCENTAGES_WS

# From migration 0029 (G8 Week 1)
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

# From migration 0029 (G8 Week 1)
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
def seed_data(apps, schema_editor):
    from django.utils.text import slugify

    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('quiz', 'Question')
    Answer   = apps.get_model('quiz', 'Answer')

    maths  = Subject.objects.get(slug='mathematics')
    year7  = Level.objects.filter(level_number=7).first()
    year8  = Level.objects.filter(level_number=8).first()
    if not year8:
        return

    # Get the Number strand
    try:
        number_strand = Topic.objects.get(subject=maths, slug='number')
    except Topic.DoesNotExist:
        return

    # Create the three missing subtopics
    new_subtopics = [
        ('Percentages',  'percentages',  19, [year7, year8]),
        ('HCF and LCM', 'hcf-and-lcm',  20, [year8]),
        ('Cube Numbers', 'cube-numbers', 21, [year8]),
    ]
    for name, slug, order, levels in new_subtopics:
        topic, _ = Topic.objects.get_or_create(
            subject=maths,
            slug=slug,
            defaults={
                'name':      name,
                'order':     order,
                'is_active': True,
                'parent':    number_strand,
            },
        )
        for lv in levels:
            if lv:
                topic.levels.add(lv)

    def add_questions(slug, q_list, level):
        try:
            subtopic = Topic.objects.get(subject=maths, slug=slug)
        except Topic.DoesNotExist:
            return
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

    add_questions('percentages', ALL_PERCENTAGES_Y8, year8)
    add_questions('hcf-and-lcm',  HCF_LCM,          year8)
    add_questions('cube-numbers', CUBE_NUMBERS,      year8)


def reverse_data(apps, schema_editor):
    Subject  = apps.get_model('classroom', 'Subject')
    Topic    = apps.get_model('classroom', 'Topic')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = (
        [q['text'] for q in ALL_PERCENTAGES_Y8]
        + [q['text'] for q in HCF_LCM]
        + [q['text'] for q in CUBE_NUMBERS]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()

    for slug in ('percentages', 'hcf-and-lcm', 'cube-numbers'):
        Topic.objects.filter(subject=maths, slug=slug).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0029_seed_year8_g8_week1'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
