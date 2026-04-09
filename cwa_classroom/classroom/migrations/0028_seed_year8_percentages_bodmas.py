"""
Migration 0028 — G Percenrages.pdf + BODMAS.pdf worksheets (Year 8):
  Percentages (Y8): +15 questions (reverse %, percent of amount, discount+tax, comparing)
  BODMAS     (Y8): +10 questions (precedence, indices, brackets, negative integers)
All assigned to Year 8.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
BODMAS_WS = [
    {
        "text": "Evaluate: 6 + 7 × 8",
        "difficulty": 1,
        "answers": [
            ("62", True), ("104", False), ("56", False), ("48", False),
        ],
    },
    {
        "text": "Evaluate: 2 × (5 + 7) − 6 + 2",
        "difficulty": 1,
        "answers": [
            ("20", True), ("28", False), ("18", False), ("14", False),
        ],
    },
    {
        "text": "Evaluate: 7 × 1 + 4 + (0 − 2) × 3",
        "difficulty": 2,
        "answers": [
            ("5", True), ("17", False), ("27", False), ("9", False),
        ],
    },
    {
        "text": "Evaluate: 6² + 14 ÷ 2 − 8",
        "difficulty": 2,
        "answers": [
            ("35", True), ("11", False), ("5", False), ("43", False),
        ],
    },
    {
        "text": "Evaluate: 9 ÷ 3 + 7 × 4 ÷ 2",
        "difficulty": 2,
        "answers": [
            ("17", True), ("20", False), ("15", False), ("31", False),
        ],
    },
    {
        "text": "Evaluate: 12 ÷ 6 + 5² × 3",
        "difficulty": 2,
        "answers": [
            ("77", True), ("81", False), ("32", False), ("17", False),
        ],
    },
    {
        "text": "Evaluate: 42 ÷ 6 + 5",
        "difficulty": 1,
        "answers": [
            ("12", True), ("14", False), ("47", False), ("4", False),
        ],
    },
    {
        "text": "Evaluate: 4 × (−12 + 6) ÷ 3",
        "difficulty": 3,
        "answers": [
            ("−8", True), ("8", False), ("−6", False), ("−46", False),
        ],
    },
    {
        "text": "Evaluate: 6 × 8 − (4² + 2) + 72 ÷ 8",
        "difficulty": 3,
        "answers": [
            ("39", True), ("43", False), ("21", False), ("30", False),
        ],
    },
    {
        "text": "Evaluate: 5 × 5 − 0 + 6 − (7 × 6)",
        "difficulty": 2,
        "answers": [
            ("−11", True), ("31", False), ("144", False), ("11", False),
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
        'percentages': PERCENTAGES_WS,
        'bodmas':      BODMAS_WS,
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
        [q['text'] for q in PERCENTAGES_WS]
        + [q['text'] for q in BODMAS_WS]
    )
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0027_seed_year8_selective_entrance_acer_amc'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
