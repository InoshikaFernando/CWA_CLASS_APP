"""
Migration: Add Year 4 Finance questions (Australian Money & Budgeting)
sourced from G4Money worksheet.

Covers:
  - Reading and writing money amounts with decimals
  - Counting coins to make $1
  - Identifying mistakes in written amounts
  - Equivalent amounts
  - Totalling notes and coins
  - Budgeting: calculating totals, leftover money, savings goals
"""
from django.db import migrations


QUESTIONS = [
    # ── Section 1: Reading & Writing Money ─────────────────────────────────
    {
        'text': 'How do you write "twenty dollars" with a decimal point?',
        'difficulty': 1, 'points': 1,
        'explanation': '$20 written with a decimal is $20.00 — showing dollars and zero cents.',
        'answers': [
            ('$20', False),
            ('$20.00', True),
            ('$0.20', False),
            ('$200.00', False),
        ],
    },
    {
        'text': 'How do you write "fifty cents" using a dollar sign and decimal point?',
        'difficulty': 1, 'points': 1,
        'explanation': '50 cents is 50 out of 100 cents in a dollar, so it is written as $0.50.',
        'answers': [
            ('$50.00', False),
            ('$5.00', False),
            ('$0.50', True),
            ('$0.05', False),
        ],
    },
    {
        'text': 'Which amount is the same as $2 and 50c?',
        'difficulty': 1, 'points': 1,
        'explanation': '$2 and 50c means 2 dollars and 50 cents, written as $2.50.',
        'answers': [
            ('$2.05', False),
            ('$25.00', False),
            ('$2.50', True),
            ('$250.00', False),
        ],
    },
    {
        'text': 'What is $10 and 10c written with a decimal point?',
        'difficulty': 1, 'points': 1,
        'explanation': '$10 and 10c = 10 dollars and 10 cents = $10.10.',
        'answers': [
            ('$10.01', False),
            ('$10.10', True),
            ('$1.10', False),
            ('$1010.00', False),
        ],
    },
    # ── Section 2: Counting Coins ───────────────────────────────────────────
    {
        'text': 'How many 50c coins do you need to make $1?',
        'difficulty': 1, 'points': 1,
        'explanation': '50c + 50c = 100c = $1, so you need 2 coins.',
        'answers': [
            ('5', False),
            ('4', False),
            ('2', True),
            ('10', False),
        ],
    },
    {
        'text': 'How many 20c coins do you need to make $1?',
        'difficulty': 1, 'points': 1,
        'explanation': '20c × 5 = 100c = $1, so you need 5 coins.',
        'answers': [
            ('4', False),
            ('5', True),
            ('10', False),
            ('20', False),
        ],
    },
    {
        'text': 'How many 10c coins do you need to make $1?',
        'difficulty': 1, 'points': 1,
        'explanation': '10c × 10 = 100c = $1, so you need 10 coins.',
        'answers': [
            ('5', False),
            ('20', False),
            ('10', True),
            ('100', False),
        ],
    },
    {
        'text': 'How many 5c coins do you need to make $1?',
        'difficulty': 1, 'points': 1,
        'explanation': '5c × 20 = 100c = $1, so you need 20 coins.',
        'answers': [
            ('5', False),
            ('10', False),
            ('20', True),
            ('50', False),
        ],
    },
    # ── Section 3: Spotting Mistakes ────────────────────────────────────────
    {
        'text': 'David has a $2 coin, a $1 coin, and two 20c coins. He wrote the total as "3.40$". What should David have written?',
        'difficulty': 1, 'points': 1,
        'explanation': '$2 + $1 + 20c + 20c = $3.40. The dollar sign goes at the front: $3.40.',
        'answers': [
            ('$3.40', True),
            ('$34.00', False),
            ('3.40c', False),
            ('$3.4', False),
        ],
    },
    {
        'text': 'Chelsea has a $5 note and a 20c coin. She wrote the total as "$5.20c". What should she have written?',
        'difficulty': 1, 'points': 1,
        'explanation': '$5 + 20c = $5.20. There is no "c" after a dollar amount — write $5.20.',
        'answers': [
            ('$5.20', True),
            ('$520', False),
            ('$52.00', False),
            ('5.20c', False),
        ],
    },
    {
        'text': 'Viv has a $10 note and a 5c coin. She wrote the total as $10.50. What should she have written?',
        'difficulty': 2, 'points': 1,
        'explanation': '$10 + 5c = $10.05. The 5c coin is 5 cents, not 50 cents.',
        'answers': [
            ('$10.50', False),
            ('$10.05', True),
            ('$1.05', False),
            ('$105.00', False),
        ],
    },
    {
        'text': 'Li has a 50c coin and a 10c coin. She wrote the total as $0.6. What should she have written?',
        'difficulty': 2, 'points': 1,
        'explanation': '50c + 10c = 60c = $0.60. Money amounts always show two decimal places.',
        'answers': [
            ('$0.06', False),
            ('$6.00', False),
            ('$0.60', True),
            ('$60.00', False),
        ],
    },
    # ── Section 4: Equivalent Amounts ───────────────────────────────────────
    {
        'text': 'Which of the following equals $1?',
        'difficulty': 2, 'points': 1,
        'explanation': '$0.50 + $0.50 = $1.00.',
        'answers': [
            ('$0.50 + $0.25', False),
            ('$0.50 + $0.50', True),
            ('$0.50 + $0.10', False),
            ('$0.20 + $0.20', False),
        ],
    },
    {
        'text': 'Which of the following does NOT equal $1?',
        'difficulty': 2, 'points': 1,
        'explanation': 'Ten 20c coins = $2.00 — twice as much as $1. All others equal $1.',
        'answers': [
            ('Five 20c coins', False),
            ('Two 50c coins', False),
            ('Ten 10c coins', False),
            ('Ten 20c coins', True),
        ],
    },
    # ── Section 5: Totalling Notes and Coins ────────────────────────────────
    {
        'text': 'You have a $10 note, three $1 coins, one 20c coin and one 10c coin. What is the total?',
        'difficulty': 2, 'points': 1,
        'explanation': '$10 + $3 + $0.20 + $0.10 = $13.30.',
        'answers': [
            ('$13.20', False),
            ('$13.30', True),
            ('$14.30', False),
            ('$13.03', False),
        ],
    },
    {
        'text': 'You have a $20 note, a $10 note, a $2 coin and a $1 coin. What is the total?',
        'difficulty': 2, 'points': 1,
        'explanation': '$20 + $10 + $2 + $1 = $33.00.',
        'answers': [
            ('$34.00', False),
            ('$32.00', False),
            ('$33.00', True),
            ('$23.00', False),
        ],
    },
    {
        'text': 'Which set of money does NOT equal $5.80?',
        'difficulty': 2, 'points': 1,
        'explanation': 'Three $2 coins + 50c + 20c + 5c + 5c = $6 + 80c = $6.80, not $5.80.',
        'answers': [
            ('$5 note + four 20c coins', False),
            ('Three $2 coins + 50c + 20c + 5c + 5c', True),
            ('$5 note + 50c + 20c + 5c + 5c', False),
            ('Two $2 coins + $1 coin + four 20c coins', False),
        ],
    },
    {
        'text': 'Which set of money does NOT equal $9.10?',
        'difficulty': 2, 'points': 1,
        'explanation': '$5 + $1 + $1 + 50c + 50c + 10c = $7 + $1.10 = $8.10, not $9.10.',
        'answers': [
            ('Three $2 coins + three $1 coins + 10c', False),
            ('$5 + $2 + $1 + $1 + 10c', False),
            ('Four $2 coins + $1 + 5c + 5c', False),
            ('$5 + $1 + $1 + 50c + 50c + 10c', True),
        ],
    },
    # ── Section 6: Budgeting — Calculating Totals ───────────────────────────
    {
        'text': 'Justine buys 2 cakes at $12 each for her party. What is the total cost of the cakes?',
        'difficulty': 2, 'points': 1,
        'explanation': '2 × $12 = $24.',
        'answers': [
            ('$12', False),
            ('$14', False),
            ('$24', True),
            ('$22', False),
        ],
    },
    {
        'text': 'Justine buys 5 bags of chips at $3 each. What is the total cost?',
        'difficulty': 2, 'points': 1,
        'explanation': '5 × $3 = $15.',
        'answers': [
            ('$8', False),
            ('$15', True),
            ('$35', False),
            ('$53', False),
        ],
    },
    {
        'text': 'Justine buys 30 sandwiches at $2 each. What is the total cost?',
        'difficulty': 2, 'points': 1,
        'explanation': '30 × $2 = $60.',
        'answers': [
            ('$30', False),
            ('$32', False),
            ('$60', True),
            ('$23', False),
        ],
    },
    {
        'text': 'Justine buys 4 bags of mixed lollies at $6 each. What is the total cost?',
        'difficulty': 2, 'points': 1,
        'explanation': '4 × $6 = $24.',
        'answers': [
            ('$64', False),
            ('$46', False),
            ('$10', False),
            ('$24', True),
        ],
    },
    {
        'text': 'A family goes to the movies. They buy 3 adult tickets at $21 each and 2 child tickets at $16 each. What is the total cost?',
        'difficulty': 2, 'points': 1,
        'explanation': '3 × $21 = $63. 2 × $16 = $32. Total = $63 + $32 = $95.',
        'answers': [
            ('$85', False),
            ('$95', True),
            ('$63', False),
            ('$105', False),
        ],
    },
    {
        'text': 'Shane buys 3 sets of pens at $3 each and 2 sets of pencils at $8 each. What is the total cost?',
        'difficulty': 2, 'points': 1,
        'explanation': '3 × $3 = $9. 2 × $8 = $16. Total = $9 + $16 = $25.',
        'answers': [
            ('$11', False),
            ('$22', False),
            ('$25', True),
            ('$30', False),
        ],
    },
    # ── Section 7: Leftover Money & Savings Goals ────────────────────────────
    {
        'text': "Maddie's monthly costs are: rent $600, phone $40, internet $30, transport $150, gas/electricity $50, food $570. What is her total monthly cost?",
        'difficulty': 3, 'points': 2,
        'explanation': '$600 + $40 + $30 + $150 + $50 + $570 = $1,440.',
        'answers': [
            ('$1,400', False),
            ('$1,440', True),
            ('$1,340', False),
            ('$1,240', False),
        ],
    },
    {
        'text': 'Maddie earns $4,300 per month. Her total monthly costs are $1,440. How much does she have left over?',
        'difficulty': 3, 'points': 2,
        'explanation': '$4,300 − $1,440 = $2,860.',
        'answers': [
            ('$2,760', False),
            ('$2,860', True),
            ('$3,860', False),
            ('$2,960', False),
        ],
    },
    {
        'text': "Melissa earns $975 per week. Her weekly expenses total $425. How much does she have left over each week?",
        'difficulty': 3, 'points': 2,
        'explanation': '$975 − $425 = $550.',
        'answers': [
            ('$450', False),
            ('$500', False),
            ('$550', True),
            ('$650', False),
        ],
    },
    {
        'text': 'Melissa saves $550 per week. She wants to buy a saxophone that costs $1,100. How many weeks does she need to save?',
        'difficulty': 3, 'points': 2,
        'explanation': '$1,100 ÷ $550 = 2 weeks.',
        'answers': [
            ('1 week', False),
            ('2 weeks', True),
            ('3 weeks', False),
            ('4 weeks', False),
        ],
    },
    {
        'text': 'Tammy earns $110 per week. Her weekly expenses are: transport $25, phone $7, movies $16, food $40, stationery $10, magazine $6. How much does she have left over?',
        'difficulty': 3, 'points': 2,
        'explanation': '$25 + $7 + $16 + $40 + $10 + $6 = $104 total expenses. $110 − $104 = $6.',
        'answers': [
            ('$4', False),
            ('$6', True),
            ('$8', False),
            ('$16', False),
        ],
    },
    {
        'text': 'Tammy saves $6 per week. She wants to buy a magazine subscription for $50. How many weeks does she need to save?',
        'difficulty': 3, 'points': 2,
        'explanation': '$50 ÷ $6 = 8.33... She needs 9 full weeks to have enough (8 weeks = $48, not enough).',
        'answers': [
            ('7 weeks', False),
            ('8 weeks', False),
            ('9 weeks', True),
            ('10 weeks', False),
        ],
    },
    {
        'text': 'Jackson wants to buy: 3 t-shirts at $14 each, jeans for $45, 7 underpants at $3 each, 2 bow ties at $12 each, 2 hoodies at $28 each. What is the total cost?',
        'difficulty': 3, 'points': 2,
        'explanation': '3×$14=$42, $45, 7×$3=$21, 2×$12=$24, 2×$28=$56. Total = $42+$45+$21+$24+$56 = $188.',
        'answers': [
            ('$168', False),
            ('$178', False),
            ('$188', True),
            ('$198', False),
        ],
    },
    {
        'text': 'Jackson has $150. The new clothes he wants cost $188. Which statement is correct?',
        'difficulty': 3, 'points': 2,
        'explanation': '$188 − $150 = $38. He is $38 short.',
        'answers': [
            ('He has enough money and $38 left over', False),
            ('He is $38 short', True),
            ('He is $28 short', False),
            ('He has exactly enough money', False),
        ],
    },
]


def seed_questions(apps, schema_editor):
    from django.utils.text import slugify

    Subject = apps.get_model('classroom', 'Subject')
    Topic = apps.get_model('classroom', 'Topic')
    Level = apps.get_model('classroom', 'Level')
    Question = apps.get_model('quiz', 'Question')
    Answer = apps.get_model('quiz', 'Answer')

    maths = Subject.objects.filter(name='Mathematics').first()
    if not maths:
        return

    year4 = Level.objects.filter(level_number=4).first()
    if not year4:
        return

    # Ensure Finance subtopic exists and is linked to Year 4
    number_strand = Topic.objects.filter(subject=maths, slug='number', parent=None).first()
    finance, _ = Topic.objects.get_or_create(
        subject=maths,
        slug='finance',
        defaults={'name': 'Finance', 'order': 5, 'is_active': True, 'parent': number_strand},
    )
    if number_strand and finance.parent_id != number_strand.id:
        finance.parent = number_strand
        finance.save()
    finance.levels.add(year4)

    created = 0
    for q_data in QUESTIONS:
        if Question.objects.filter(topic=finance, level=year4, question_text=q_data['text']).exists():
            continue
        question = Question.objects.create(
            topic=finance,
            level=year4,
            question_text=q_data['text'],
            question_type='multiple_choice',
            difficulty=q_data['difficulty'],
            points=q_data['points'],
            explanation=q_data.get('explanation', ''),
        )
        for order, (answer_text, is_correct) in enumerate(q_data['answers']):
            Answer.objects.create(
                question=question,
                text=answer_text,
                is_correct=is_correct,
                display_order=order,
            )
        created += 1

    print(f'  Year 4 Finance: {created} questions created')


def reverse_questions(apps, schema_editor):
    Question = apps.get_model('quiz', 'Question')
    Topic = apps.get_model('classroom', 'Topic')
    Level = apps.get_model('classroom', 'Level')

    year4 = Level.objects.filter(level_number=4).first()
    finance = Topic.objects.filter(slug='finance').first()
    if year4 and finance:
        Question.objects.filter(topic=finance, level=year4).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0007_seed_topic_level_links'),
    ]

    operations = [
        migrations.RunPython(seed_questions, reverse_questions),
    ]
