"""
Migration: Add Year 7 Number subtopics and questions
Subtopics: Prime Numbers, Square and Triangular Numbers, Square Roots, Operation Order

Sourced from G7Numbers.pdf worksheet.

Covers:
  - Prime Numbers: definition, identification, prime factorization
  - Square and Triangular Numbers: patterns, sequences, calculations
  - Square Roots: √ notation, perfect squares, applications
  - Operation Order: BODMAS rules and multi-step calculations
"""
from django.db import migrations


PRIME_NUMBERS_QUESTIONS = [
    {
        'text': 'What is a prime number?',
        'difficulty': 1, 'points': 1,
        'explanation': 'A prime number has exactly two factors: 1 and itself. Examples: 2, 3, 5, 7, 11.',
        'answers': [
            ('A number divisible only by 1 and itself', True),
            ('A number with exactly 3 factors', False),
            ('A number that can be divided by 2', False),
            ('A number ending in 1, 3, 7 or 9', False),
        ],
    },
    {
        'text': 'Which of the following is a prime number?',
        'difficulty': 1, 'points': 1,
        'explanation': '11 is prime because its only factors are 1 and 11. The others (9=3×3, 15=3×5, 21=3×7) are composite.',
        'answers': [
            ('9', False),
            ('15', False),
            ('11', True),
            ('21', False),
        ],
    },
    {
        'text': 'Is 1 a prime number?',
        'difficulty': 1, 'points': 1,
        'explanation': '1 is NOT prime. A prime must have exactly two factors. 1 has only one factor (itself), so it is neither prime nor composite.',
        'answers': [
            ('Yes, because it is only divisible by 1', False),
            ('No, because it has only one factor', True),
            ('Yes, because it is an odd number', False),
            ('No, because all primes must be greater than 10', False),
        ],
    },
    {
        'text': 'What is the only even prime number?',
        'difficulty': 2, 'points': 2,
        'explanation': '2 is the only even prime. All other even numbers are divisible by 2, giving them at least 3 factors.',
        'answers': [
            ('2', True),
            ('4', False),
            ('6', False),
            ('There are no even prime numbers', False),
        ],
    },
    {
        'text': 'How many prime numbers are there between 1 and 20?',
        'difficulty': 2, 'points': 2,
        'explanation': 'The primes between 1 and 20 are: 2, 3, 5, 7, 11, 13, 17, 19 — that is 8 prime numbers.',
        'answers': [
            ('6', False),
            ('7', False),
            ('8', True),
            ('9', False),
        ],
    },
    {
        'text': 'Which of these numbers is NOT prime?',
        'difficulty': 2, 'points': 2,
        'explanation': '21 = 3 × 7, so it has more than two factors and is composite. 7, 11 and 13 are all prime.',
        'answers': [
            ('7', False),
            ('11', False),
            ('13', False),
            ('21', True),
        ],
    },
    {
        'text': 'What is the prime factorization of 12?',
        'difficulty': 2, 'points': 2,
        'explanation': '12 = 2 × 2 × 3 = 2² × 3. Breaking 12 into its smallest prime building blocks gives 2² × 3.',
        'answers': [
            ('2 × 6', False),
            ('3 × 4', False),
            ('2² × 3', True),
            ('12 × 1', False),
        ],
    },
    {
        'text': 'What are the prime factors of 30?',
        'difficulty': 2, 'points': 2,
        'explanation': '30 = 2 × 3 × 5. All three are prime numbers, so the prime factors of 30 are 2, 3 and 5.',
        'answers': [
            ('2, 3, 5', True),
            ('5, 6', False),
            ('2, 15', False),
            ('3, 10', False),
        ],
    },
    {
        'text': 'Which of the following numbers is composite?',
        'difficulty': 3, 'points': 3,
        'explanation': '51 = 3 × 17, so it is composite. 29, 31 and 37 are all prime numbers.',
        'answers': [
            ('29', False),
            ('31', False),
            ('37', False),
            ('51', True),
        ],
    },
    {
        'text': 'What is the prime factorization of 36?',
        'difficulty': 3, 'points': 3,
        'explanation': '36 = 4 × 9 = 2² × 3². The prime factorization uses only prime numbers as factors.',
        'answers': [
            ('2 × 18', False),
            ('4 × 9', False),
            ('2² × 3²', True),
            ('6²', False),
        ],
    },
]


SQUARE_TRIANGULAR_QUESTIONS = [
    {
        'text': 'What is 5²?',
        'difficulty': 1, 'points': 1,
        'explanation': '5² means 5 × 5 = 25.',
        'answers': [
            ('10', False),
            ('15', False),
            ('25', True),
            ('50', False),
        ],
    },
    {
        'text': 'Which of these is a triangular number?',
        'difficulty': 1, 'points': 1,
        'explanation': '10 is a triangular number because 1 + 2 + 3 + 4 = 10. Triangular numbers are sums of consecutive counting numbers starting from 1.',
        'answers': [
            ('4', False),
            ('8', False),
            ('10', True),
            ('12', False),
        ],
    },
    {
        'text': 'Which sequence shows the first five square numbers?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Square numbers are 1², 2², 3², 4², 5² = 1, 4, 9, 16, 25.',
        'answers': [
            ('1, 2, 3, 4, 5', False),
            ('1, 3, 6, 10, 15', False),
            ('1, 4, 9, 16, 25', True),
            ('2, 4, 6, 8, 10', False),
        ],
    },
    {
        'text': 'What is 9²?',
        'difficulty': 2, 'points': 2,
        'explanation': '9² means 9 × 9 = 81.',
        'answers': [
            ('27', False),
            ('81', True),
            ('90', False),
            ('99', False),
        ],
    },
    {
        'text': 'What is the 5th triangular number?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Triangular numbers: 1, 3, 6, 10, 15. The 5th is 1+2+3+4+5 = 15.',
        'answers': [
            ('10', False),
            ('12', False),
            ('15', True),
            ('20', False),
        ],
    },
    {
        'text': 'What is the next triangular number after 21?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Triangular numbers: 1, 3, 6, 10, 15, 21, 28 … Each step adds the next whole number. After 21 (the 6th), add 7: 21 + 7 = 28.',
        'answers': [
            ('24', False),
            ('25', False),
            ('28', True),
            ('30', False),
        ],
    },
    {
        'text': 'Which of these is both a square number AND a triangular number?',
        'difficulty': 2, 'points': 2,
        'explanation': '36 = 6² (square number) and 36 = 1+2+3+4+5+6+7+8 (8th triangular number). 36 is both!',
        'answers': [
            ('9', False),
            ('16', False),
            ('25', False),
            ('36', True),
        ],
    },
    {
        'text': 'What is 1 + 2 + 3 + 4 + 5 + 6?',
        'difficulty': 2, 'points': 2,
        'explanation': '1 + 2 + 3 + 4 + 5 + 6 = 21, which is the 6th triangular number.',
        'answers': [
            ('18', False),
            ('20', False),
            ('21', True),
            ('24', False),
        ],
    },
    {
        'text': 'What is 12²?',
        'difficulty': 3, 'points': 3,
        'explanation': '12² means 12 × 12 = 144.',
        'answers': [
            ('122', False),
            ('124', False),
            ('144', True),
            ('148', False),
        ],
    },
    {
        'text': 'The 9th triangular number is 45. What is the 10th triangular number?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Each triangular number is formed by adding the next counting number. 10th triangular number = 45 + 10 = 55.',
        'answers': [
            ('50', False),
            ('54', False),
            ('55', True),
            ('60', False),
        ],
    },
]


SQUARE_ROOTS_QUESTIONS = [
    {
        'text': 'What is √49?',
        'difficulty': 1, 'points': 1,
        'explanation': '√49 = 7 because 7 × 7 = 49.',
        'answers': [
            ('5', False),
            ('6', False),
            ('7', True),
            ('8', False),
        ],
    },
    {
        'text': 'What is √25?',
        'difficulty': 1, 'points': 1,
        'explanation': '√25 = 5 because 5 × 5 = 25.',
        'answers': [
            ('3', False),
            ('4', False),
            ('5', True),
            ('6', False),
        ],
    },
    {
        'text': 'What is √64?',
        'difficulty': 1, 'points': 1,
        'explanation': '√64 = 8 because 8 × 8 = 64.',
        'answers': [
            ('6', False),
            ('7', False),
            ('8', True),
            ('9', False),
        ],
    },
    {
        'text': 'What is √100?',
        'difficulty': 2, 'points': 2,
        'explanation': '√100 = 10 because 10 × 10 = 100.',
        'answers': [
            ('5', False),
            ('10', True),
            ('20', False),
            ('50', False),
        ],
    },
    {
        'text': 'If √n = 9, what is n?',
        'difficulty': 2, 'points': 2,
        'explanation': 'If √n = 9, then n = 9² = 81.',
        'answers': [
            ('18', False),
            ('27', False),
            ('81', True),
            ('90', False),
        ],
    },
    {
        'text': 'What is √144?',
        'difficulty': 2, 'points': 2,
        'explanation': '√144 = 12 because 12 × 12 = 144.',
        'answers': [
            ('11', False),
            ('12', True),
            ('13', False),
            ('14', False),
        ],
    },
    {
        'text': 'Which of these is NOT a perfect square?',
        'difficulty': 2, 'points': 2,
        'explanation': '50 is not a perfect square because no whole number multiplied by itself equals 50. (7² = 49, 8² = 64)',
        'answers': [
            ('16', False),
            ('36', False),
            ('50', True),
            ('81', False),
        ],
    },
    {
        'text': 'What is √36 + √64?',
        'difficulty': 2, 'points': 2,
        'explanation': '√36 = 6 and √64 = 8, so √36 + √64 = 6 + 8 = 14.',
        'answers': [
            ('10', False),
            ('12', False),
            ('14', True),
            ('16', False),
        ],
    },
    {
        'text': 'A square has an area of 169 cm². What is the length of one side?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Side length = √169 = 13 cm, because 13 × 13 = 169.',
        'answers': [
            ('11 cm', False),
            ('12 cm', False),
            ('13 cm', True),
            ('14 cm', False),
        ],
    },
    {
        'text': 'What is √(16 + 9)?',
        'difficulty': 3, 'points': 3,
        'explanation': 'First add inside the square root: 16 + 9 = 25. Then √25 = 5. Note: you cannot split √ over addition — √16 + √9 = 4 + 3 = 7, which is wrong.',
        'answers': [
            ('7', False),
            ('5', True),
            ('25', False),
            ('12', False),
        ],
    },
]


OPERATION_ORDER_QUESTIONS = [
    {
        'text': 'In BODMAS, what does the letter "B" stand for?',
        'difficulty': 1, 'points': 1,
        'explanation': 'BODMAS stands for Brackets, Orders, Division, Multiplication, Addition, Subtraction — in that order of priority.',
        'answers': [
            ('Before', False),
            ('Brackets', True),
            ('Basic', False),
            ('Binary', False),
        ],
    },
    {
        'text': 'In 5 + 3 × 2, which operation do you perform first?',
        'difficulty': 1, 'points': 1,
        'explanation': 'According to BODMAS, multiplication comes before addition. So 3 × 2 = 6 is done first.',
        'answers': [
            ('Addition (5 + 3)', False),
            ('Multiplication (3 × 2)', True),
            ('Work from left to right', False),
            ('Subtraction', False),
        ],
    },
    {
        'text': 'What is 5 + 3 × 2?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Using BODMAS: multiply first — 3 × 2 = 6. Then add: 5 + 6 = 11.',
        'answers': [
            ('16', False),
            ('11', True),
            ('13', False),
            ('10', False),
        ],
    },
    {
        'text': 'What is (5 + 3) × 2?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Brackets first: (5 + 3) = 8. Then multiply: 8 × 2 = 16.',
        'answers': [
            ('11', False),
            ('13', False),
            ('16', True),
            ('18', False),
        ],
    },
    {
        'text': 'What is 20 ÷ 4 + 3?',
        'difficulty': 2, 'points': 2,
        'explanation': 'BODMAS: division before addition. 20 ÷ 4 = 5, then 5 + 3 = 8.',
        'answers': [
            ('2', False),
            ('8', True),
            ('10', False),
            ('4', False),
        ],
    },
    {
        'text': 'What is 3² + 4?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Orders (powers) come before addition in BODMAS. 3² = 9, then 9 + 4 = 13.',
        'answers': [
            ('10', False),
            ('13', True),
            ('49', False),
            ('19', False),
        ],
    },
    {
        'text': 'What is 24 ÷ (6 − 2)?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Brackets first: (6 − 2) = 4. Then divide: 24 ÷ 4 = 6.',
        'answers': [
            ('2', False),
            ('4', False),
            ('6', True),
            ('8', False),
        ],
    },
    {
        'text': 'What is 5 × 3 − 2 × 4?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Do both multiplications first: 5 × 3 = 15 and 2 × 4 = 8. Then subtract: 15 − 8 = 7.',
        'answers': [
            ('28', False),
            ('7', True),
            ('4', False),
            ('30', False),
        ],
    },
    {
        'text': 'What is (3 + 2)² − 4 × 3?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Brackets: (3 + 2) = 5. Orders: 5² = 25. Multiplication: 4 × 3 = 12. Subtraction: 25 − 12 = 13.',
        'answers': [
            ('1', False),
            ('13', True),
            ('21', False),
            ('37', False),
        ],
    },
    {
        'text': 'What is 36 ÷ 6 + 2² × 3 − 1?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Orders: 2² = 4. Division: 36 ÷ 6 = 6. Multiplication: 4 × 3 = 12. Left to right: 6 + 12 − 1 = 17.',
        'answers': [
            ('13', False),
            ('17', True),
            ('23', False),
            ('11', False),
        ],
    },
]


def seed_year7_number_questions(apps, schema_editor):
    Topic = apps.get_model('classroom', 'Topic')
    Level = apps.get_model('classroom', 'Level')
    Subject = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('maths', 'Question')
    Answer = apps.get_model('maths', 'Answer')

    maths = Subject.objects.filter(name='Mathematics').first()
    if not maths:
        return

    number_strand = Topic.objects.filter(
        subject=maths, slug='number', parent__isnull=True
    ).first()
    if not number_strand:
        return

    year7 = Level.objects.filter(level_number=7).first()
    if not year7:
        return

    subtopics_data = [
        ('Prime Numbers',                 'prime-numbers',                 10, PRIME_NUMBERS_QUESTIONS),
        ('Square and Triangular Numbers', 'square-and-triangular-numbers', 11, SQUARE_TRIANGULAR_QUESTIONS),
        ('Square Roots',                  'square-roots',                  12, SQUARE_ROOTS_QUESTIONS),
        ('Operation Order',               'operation-order',               13, OPERATION_ORDER_QUESTIONS),
    ]

    for name, slug, order, questions in subtopics_data:
        subtopic, _ = Topic.objects.get_or_create(
            subject=maths,
            slug=slug,
            defaults={
                'name': name,
                'order': order,
                'is_active': True,
                'parent': number_strand,
            },
        )
        if subtopic.parent_id != number_strand.id:
            subtopic.parent = number_strand
            subtopic.save(update_fields=['parent'])

        subtopic.levels.add(year7)

        for q_data in questions:
            if Question.objects.filter(
                topic=subtopic, level=year7, question_text=q_data['text']
            ).exists():
                continue
            question = Question.objects.create(
                topic=subtopic,
                level=year7,
                question_text=q_data['text'],
                question_type='multiple_choice',
                difficulty=q_data['difficulty'],
                points=q_data['points'],
                explanation=q_data.get('explanation', ''),
            )
            for display_order, (answer_text, is_correct) in enumerate(q_data['answers']):
                Answer.objects.create(
                    question=question,
                    text=answer_text,
                    is_correct=is_correct,
                    display_order=display_order,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0008_seed_year4_finance_questions'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_year7_number_questions, migrations.RunPython.noop),
    ]
