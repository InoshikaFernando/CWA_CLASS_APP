"""
Migration: Year 7 Computation with Positive Integers
Sourced from G7- Computation with integers-Topic Exam.pdf (Tests A, B, C, D)

New subtopics under Number (Year 7):
  - Number Systems    (Roman, Egyptian, Babylonian numerals)
  - Addition and Subtraction  (mental strategies, algorithms, word problems)
  - Estimation and Rounding   (rounding, leading digit approximation)

Extended to Year 7 (existing subtopics):
  - Place Values      (large numbers, expanded form, index notation)
  - Multiplication    (mental strategies, short/long algorithm)
  - Division          (short division, remainders, word problems)
"""
from django.db import migrations


NUMBER_SYSTEMS_QUESTIONS = [
    {
        'text': 'What does the Roman numeral "X" represent?',
        'difficulty': 1, 'points': 1,
        'explanation': 'In Roman numerals, X = 10. The basic symbols are I=1, V=5, X=10, L=50, C=100, D=500, M=1000.',
        'answers': [
            ('5', False),
            ('10', True),
            ('50', False),
            ('100', False),
        ],
    },
    {
        'text': 'What does the Roman numeral "L" represent?',
        'difficulty': 1, 'points': 1,
        'explanation': 'In Roman numerals, L = 50.',
        'answers': [
            ('5', False),
            ('10', False),
            ('50', True),
            ('100', False),
        ],
    },
    {
        'text': 'Which number system is used in everyday life today?',
        'difficulty': 1, 'points': 1,
        'explanation': 'The Hindu-Arabic number system (base 10) is the decimal system used worldwide today.',
        'answers': [
            ('Egyptian', False),
            ('Roman', False),
            ('Babylonian', False),
            ('Hindu-Arabic', True),
        ],
    },
    {
        'text': 'What is the value of the Roman numeral XLII?',
        'difficulty': 2, 'points': 2,
        'explanation': 'XL = 40 (10 before 50) and II = 2, so XLII = 40 + 2 = 42.',
        'answers': [
            ('32', False),
            ('42', True),
            ('52', False),
            ('62', False),
        ],
    },
    {
        'text': 'What is the Roman numeral for 49?',
        'difficulty': 2, 'points': 2,
        'explanation': '49 = 40 + 9 = XL + IX = XLIX. In Roman numerals, subtraction is used: XL means 10 before 50, IX means 1 before 10.',
        'answers': [
            ('IL', False),
            ('XXXXIX', False),
            ('XLIX', True),
            ('XLXI', False),
        ],
    },
    {
        'text': 'What is the value of LXXXIV?',
        'difficulty': 2, 'points': 2,
        'explanation': 'L=50, XXX=30, IV=4. So LXXXIV = 50 + 30 + 4 = 84.',
        'answers': [
            ('74', False),
            ('84', True),
            ('94', False),
            ('104', False),
        ],
    },
    {
        'text': 'What is the Roman numeral for 274?',
        'difficulty': 2, 'points': 2,
        'explanation': '274 = 200 + 70 + 4 = CC + LXX + IV = CCLXXIV.',
        'answers': [
            ('CCLXXIV', True),
            ('CCLXXIII', False),
            ('CCLXXV', False),
            ('CCXLIV', False),
        ],
    },
    {
        'text': 'Which ancient number system used a base of 60?',
        'difficulty': 2, 'points': 2,
        'explanation': 'The Babylonian number system used base 60 (sexagesimal). We still see this in time (60 seconds, 60 minutes) and angles (360°).',
        'answers': [
            ('Egyptian', False),
            ('Roman', False),
            ('Babylonian', True),
            ('Hindu-Arabic', False),
        ],
    },
    {
        'text': 'What is MCMXCIX in Hindu-Arabic numerals?',
        'difficulty': 3, 'points': 3,
        'explanation': 'M=1000, CM=900 (100 before 1000), XC=90 (10 before 100), IX=9 (1 before 10). So 1000+900+90+9 = 1999.',
        'answers': [
            ('1989', False),
            ('1999', True),
            ('2001', False),
            ('1901', False),
        ],
    },
    {
        'text': 'What is the Roman numeral for 94?',
        'difficulty': 3, 'points': 3,
        'explanation': '94 = 90 + 4 = XC + IV = XCIV. XC means 10 before 100 (= 90), IV means 1 before 5 (= 4).',
        'answers': [
            ('XCIV', True),
            ('LXXXXIV', False),
            ('XCIIII', False),
            ('XCVI', False),
        ],
    },
]


PLACE_VALUES_QUESTIONS = [
    {
        'text': 'In the number 796 032, what is the place value of the digit 7?',
        'difficulty': 1, 'points': 1,
        'explanation': '796 032 has 6 digits. From right: 2=ones, 3=tens, 0=hundreds, 6=thousands, 9=ten thousands, 7=hundred thousands. So 7 = 700 000.',
        'answers': [
            ('7 thousand', False),
            ('70 thousand', False),
            ('700 thousand', True),
            ('7 million', False),
        ],
    },
    {
        'text': 'Write "two million, four hundred thousand and sixty-three" as a numeral.',
        'difficulty': 1, 'points': 1,
        'explanation': 'Two million = 2 000 000, four hundred thousand = 400 000, sixty-three = 63. Total: 2 400 063.',
        'answers': [
            ('2 040 063', False),
            ('2 400 063', True),
            ('24 000 063', False),
            ('2 004 063', False),
        ],
    },
    {
        'text': 'How many thousands are in one million?',
        'difficulty': 1, 'points': 1,
        'explanation': '1 000 000 ÷ 1 000 = 1 000. There are one thousand thousands in one million.',
        'answers': [
            ('10', False),
            ('100', False),
            ('1000', True),
            ('10 000', False),
        ],
    },
    {
        'text': 'What is the expanded form of 58 407?',
        'difficulty': 2, 'points': 2,
        'explanation': '58 407 = 50 000 + 8000 + 400 + 0 + 7. Each digit is multiplied by its place value.',
        'answers': [
            ('5000 + 800 + 40 + 7', False),
            ('50 000 + 8000 + 400 + 7', True),
            ('58 000 + 407', False),
            ('5 + 8 + 4 + 0 + 7', False),
        ],
    },
    {
        'text': 'What is the place value of the digit 3 in 2 345 678?',
        'difficulty': 2, 'points': 2,
        'explanation': '2 345 678: 2=millions, 3=hundred thousands, 4=ten thousands, 5=thousands, 6=hundreds, 7=tens, 8=ones. The 3 is in the hundred thousands position = 300 000.',
        'answers': [
            ('3 000', False),
            ('30 000', False),
            ('300 000', True),
            ('3 000 000', False),
        ],
    },
    {
        'text': 'Which shows 304 007 in expanded form using index notation?',
        'difficulty': 2, 'points': 2,
        'explanation': '304 007 = 3 × 100 000 + 4 × 1000 + 7 = 3 × 10⁵ + 4 × 10³ + 7.',
        'answers': [
            ('3 × 10⁵ + 4 × 10³ + 7', True),
            ('3 × 10⁶ + 4 × 10³ + 7', False),
            ('3 × 10⁴ + 4 × 10³ + 7', False),
            ('30 × 10⁴ + 4 × 10³ + 7', False),
        ],
    },
    {
        'text': 'Which value of x makes this statement true: 3 < x ≤ 5?',
        'difficulty': 2, 'points': 2,
        'explanation': '3 < x means x is greater than 3 (not equal). x ≤ 5 means x is at most 5. So x can be 4 or 5. From the options, x = 4 works.',
        'answers': [
            ('x = 3', False),
            ('x = 4', True),
            ('x = 6', False),
            ('x = 2', False),
        ],
    },
    {
        'text': 'A number has: 3 in millions, 0 in hundred thousands, 5 in ten thousands, 2 in thousands, 0 in hundreds, 6 in tens, 4 in ones. What is the number?',
        'difficulty': 3, 'points': 3,
        'explanation': '3 000 000 + 0 + 50 000 + 2 000 + 0 + 60 + 4 = 3 052 064.',
        'answers': [
            ('3 502 064', False),
            ('3 052 064', True),
            ('3 052 640', False),
            ('3 520 064', False),
        ],
    },
    {
        'text': 'What number does 5 × 10⁶ + 3 × 10⁴ + 7 × 10² + 2 represent?',
        'difficulty': 3, 'points': 3,
        'explanation': '5 × 10⁶ = 5 000 000, 3 × 10⁴ = 30 000, 7 × 10² = 700, 2 = 2. Total: 5 030 702.',
        'answers': [
            ('5 300 720', False),
            ('5 030 702', True),
            ('53 000 702', False),
            ('5 030 720', False),
        ],
    },
    {
        'text': 'Which correctly orders these numbers from smallest to largest: 2 345 678; 2 354 678; 2 435 678; 2 345 768?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Compare digit by digit from left. All start with 2 3__, so look at the next digit: 45, 54, 43 → 43 < 45 < 54, and within 2 345, compare 678 vs 768 → 678 < 768. Order: 2 345 678 < 2 345 768 < 2 354 678 < 2 435 678.',
        'answers': [
            ('2 345 678 < 2 345 768 < 2 354 678 < 2 435 678', True),
            ('2 435 678 < 2 354 678 < 2 345 768 < 2 345 678', False),
            ('2 345 678 < 2 354 678 < 2 345 768 < 2 435 678', False),
            ('2 345 768 < 2 345 678 < 2 354 678 < 2 435 678', False),
        ],
    },
]


ADDITION_SUBTRACTION_QUESTIONS = [
    {
        'text': 'What is 153 + 234?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Using partitioning: 100+200=300, 50+30=80, 3+4=7. Total: 300+80+7=387.',
        'answers': [
            ('377', False),
            ('387', True),
            ('397', False),
            ('383', False),
        ],
    },
    {
        'text': 'What is 709 + 1998?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Compensating: 709 + 2000 − 2 = 2709 − 2 = 2707.',
        'answers': [
            ('2607', False),
            ('2707', True),
            ('2807', False),
            ('2797', False),
        ],
    },
    {
        'text': 'Which mental strategy is shown in: 68 + 19 → 68 + 20 − 1 = 87?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Compensating means rounding one number to make it easier to add, then adjusting. Here 19 is rounded to 20 (add 1 too many), then subtract 1.',
        'answers': [
            ('Partitioning', False),
            ('Compensating', True),
            ('Doubling', False),
            ('Leading digit', False),
        ],
    },
    {
        'text': 'What is 3016 − 1743?',
        'difficulty': 2, 'points': 2,
        'explanation': '3016 − 1743: 3016 − 1000 = 2016, − 700 = 1316, − 43 = 1273.',
        'answers': [
            ('1263', False),
            ('1273', True),
            ('1283', False),
            ('1373', False),
        ],
    },
    {
        'text': 'What is 5000 − 2367?',
        'difficulty': 2, 'points': 2,
        'explanation': '5000 − 2367 = 2633. (Count up from 2367: +33=2400, +600=3000, +2000=5000 → total added = 2633.)',
        'answers': [
            ('2533', False),
            ('2633', True),
            ('2733', False),
            ('2543', False),
        ],
    },
    {
        'text': 'A car odometer reads 23 846 km. After a 1273 km trip, what does it read?',
        'difficulty': 2, 'points': 2,
        'explanation': '23 846 + 1273 = 25 119. (23 846 + 1000 = 24 846, + 200 = 25 046, + 73 = 25 119.)',
        'answers': [
            ('24 119 km', False),
            ('25 019 km', False),
            ('25 119 km', True),
            ('24 029 km', False),
        ],
    },
    {
        'text': 'Using leading digit approximation, what is the best estimate of 2873 + 4156?',
        'difficulty': 2, 'points': 2,
        'explanation': '2873 → 3000 (leading digit rounds up), 4156 → 4000 (leading digit rounds down). Estimate: 3000 + 4000 = 7000.',
        'answers': [
            ('6000', False),
            ('7000', True),
            ('8000', False),
            ('6900', False),
        ],
    },
    {
        'text': 'What is 4009 + 3678 + 2007?',
        'difficulty': 3, 'points': 3,
        'explanation': '4009 + 3678 = 7687. Then 7687 + 2007 = 9694.',
        'answers': [
            ('9584', False),
            ('9684', False),
            ('9694', True),
            ('9794', False),
        ],
    },
    {
        'text': 'A school has 1248 students. 576 are boys. How many are girls?',
        'difficulty': 3, 'points': 3,
        'explanation': '1248 − 576 = 672. (1248 − 500 = 748, − 76 = 672.)',
        'answers': [
            ('662', False),
            ('672', True),
            ('682', False),
            ('762', False),
        ],
    },
    {
        'text': 'An odometer reads 18 763 km before a trip and 19 425 km at the end. How far was the trip?',
        'difficulty': 3, 'points': 3,
        'explanation': '19 425 − 18 763 = 662 km. (Count up: 18 763 + 37 = 18 800, + 200 = 19 000, + 425 = 19 425 → total = 37+200+425 = 662.)',
        'answers': [
            ('552 km', False),
            ('652 km', False),
            ('662 km', True),
            ('772 km', False),
        ],
    },
]


MULTIPLICATION_QUESTIONS = [
    {
        'text': 'What is 54 × 1000?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Multiplying by 1000 shifts all digits 3 places to the left (or adds 3 zeros). 54 × 1000 = 54 000.',
        'answers': [
            ('540', False),
            ('5400', False),
            ('54 000', True),
            ('540 000', False),
        ],
    },
    {
        'text': 'Which mental strategy is shown in: 3 × 32 = 6 × 16?',
        'difficulty': 1, 'points': 1,
        'explanation': 'Doubling and halving: double the 3 to get 6, halve the 32 to get 16. The product stays the same.',
        'answers': [
            ('Distributive law', False),
            ('Doubling and halving', True),
            ('Commutative law', False),
            ('Associative law', False),
        ],
    },
    {
        'text': 'Which law states that a × b = b × a?',
        'difficulty': 1, 'points': 1,
        'explanation': 'The commutative law of multiplication states that the order of factors does not change the product: a × b = b × a.',
        'answers': [
            ('Associative law', False),
            ('Distributive law', False),
            ('Commutative law', True),
            ('Identity law', False),
        ],
    },
    {
        'text': 'What is 63 × 8?',
        'difficulty': 2, 'points': 2,
        'explanation': 'Using the distributive law: 63 × 8 = 60 × 8 + 3 × 8 = 480 + 24 = 504.',
        'answers': [
            ('484', False),
            ('494', False),
            ('504', True),
            ('514', False),
        ],
    },
    {
        'text': 'Use the distributive law: 7 × 38 = 7 × 30 + 7 × 8 = ?',
        'difficulty': 2, 'points': 2,
        'explanation': '7 × 30 = 210 and 7 × 8 = 56. So 7 × 38 = 210 + 56 = 266.',
        'answers': [
            ('256', False),
            ('266', True),
            ('276', False),
            ('286', False),
        ],
    },
    {
        'text': 'What is 307 × 6?',
        'difficulty': 2, 'points': 2,
        'explanation': '307 × 6 = 300 × 6 + 7 × 6 = 1800 + 42 = 1842.',
        'answers': [
            ('1832', False),
            ('1842', True),
            ('1852', False),
            ('1932', False),
        ],
    },
    {
        'text': 'What is 192 × 37?',
        'difficulty': 2, 'points': 2,
        'explanation': '192 × 37 = 192 × 30 + 192 × 7 = 5760 + 1344 = 7104.',
        'answers': [
            ('6904', False),
            ('7004', False),
            ('7104', True),
            ('7204', False),
        ],
    },
    {
        'text': 'What is 5037 × 4?',
        'difficulty': 3, 'points': 3,
        'explanation': '5037 × 4 = 5000 × 4 + 37 × 4 = 20 000 + 148 = 20 148.',
        'answers': [
            ('20 028', False),
            ('20 128', False),
            ('20 148', True),
            ('21 048', False),
        ],
    },
    {
        'text': '8 classes each have 29 students. How many students are there in total?',
        'difficulty': 3, 'points': 3,
        'explanation': '8 × 29 = 8 × 30 − 8 × 1 = 240 − 8 = 232.',
        'answers': [
            ('222', False),
            ('232', True),
            ('242', False),
            ('252', False),
        ],
    },
    {
        'text': 'What is 248 × 53?',
        'difficulty': 3, 'points': 3,
        'explanation': '248 × 53 = 248 × 50 + 248 × 3 = 12 400 + 744 = 13 144.',
        'answers': [
            ('13 044', False),
            ('13 094', False),
            ('13 144', True),
            ('13 194', False),
        ],
    },
]


DIVISION_QUESTIONS = [
    {
        'text': 'What is the quotient when 56 is divided by 7?',
        'difficulty': 1, 'points': 1,
        'explanation': '56 ÷ 7 = 8 because 7 × 8 = 56.',
        'answers': [
            ('6', False),
            ('7', False),
            ('8', True),
            ('9', False),
        ],
    },
    {
        'text': 'What is the remainder when 17 is divided by 5?',
        'difficulty': 1, 'points': 1,
        'explanation': '17 ÷ 5 = 3 remainder 2 (5 × 3 = 15, 17 − 15 = 2).',
        'answers': [
            ('1', False),
            ('2', True),
            ('3', False),
            ('4', False),
        ],
    },
    {
        'text': 'What is 78 ÷ 5?',
        'difficulty': 1, 'points': 1,
        'explanation': '78 ÷ 5: 5 × 15 = 75, remainder = 78 − 75 = 3. Answer: 15 remainder 3.',
        'answers': [
            ('15 remainder 2', False),
            ('15 remainder 3', True),
            ('16 remainder 0', False),
            ('14 remainder 8', False),
        ],
    },
    {
        'text': 'What is the remainder when 5092 is divided by 8?',
        'difficulty': 2, 'points': 2,
        'explanation': '8 × 636 = 5088. Remainder = 5092 − 5088 = 4.',
        'answers': [
            ('2', False),
            ('3', False),
            ('4', True),
            ('5', False),
        ],
    },
    {
        'text': 'Use short division to find 1493 ÷ 6.',
        'difficulty': 2, 'points': 2,
        'explanation': '6 × 248 = 1488. Remainder = 1493 − 1488 = 5. Answer: 248 remainder 5.',
        'answers': [
            ('247 remainder 5', False),
            ('248 remainder 5', True),
            ('248 remainder 3', False),
            ('249 remainder 2', False),
        ],
    },
    {
        'text': 'A bus holds 48 passengers. How many buses are needed to transport 300 students?',
        'difficulty': 2, 'points': 2,
        'explanation': '300 ÷ 48 = 6.25, so 6 buses are not enough. You need 7 buses to transport all 300 students.',
        'answers': [
            ('5', False),
            ('6', False),
            ('7', True),
            ('8', False),
        ],
    },
    {
        'text': 'What is 9946 ÷ 7?',
        'difficulty': 2, 'points': 2,
        'explanation': '7 × 1420 = 9940. Remainder = 9946 − 9940 = 6. Answer: 1420 remainder 6.',
        'answers': [
            ('1419 remainder 3', False),
            ('1420 remainder 6', True),
            ('1421 remainder 0', False),
            ('1422 remainder 5', False),
        ],
    },
    {
        'text': 'What is the quotient of (6 + 25) ÷ 4?',
        'difficulty': 3, 'points': 3,
        'explanation': 'Brackets first: 6 + 25 = 31. Then 31 ÷ 4 = 7 remainder 3. The quotient (whole number part) is 7.',
        'answers': [
            ('5', False),
            ('6', False),
            ('7', True),
            ('8', False),
        ],
    },
    {
        'text': '1248 chocolates are packed in boxes of 6. How many full boxes are made?',
        'difficulty': 3, 'points': 3,
        'explanation': '1248 ÷ 6 = 208 exactly (6 × 208 = 1248). So 208 full boxes with 0 left over.',
        'answers': [
            ('206', False),
            ('207', False),
            ('208', True),
            ('209', False),
        ],
    },
    {
        'text': 'A nurse earns $62 400 per year. How much does she earn per week? (52 weeks per year)',
        'difficulty': 3, 'points': 3,
        'explanation': '$62 400 ÷ 52 = $1200. (52 × 1200 = 52 × 1000 + 52 × 200 = 52 000 + 10 400 = 62 400 ✓)',
        'answers': [
            ('$1100', False),
            ('$1200', True),
            ('$1300', False),
            ('$1400', False),
        ],
    },
]


ESTIMATION_ROUNDING_QUESTIONS = [
    {
        'text': 'Round 738 to the nearest 10.',
        'difficulty': 1, 'points': 1,
        'explanation': 'The ones digit is 8 (≥ 5), so round up. 738 → 740.',
        'answers': [
            ('730', False),
            ('740', True),
            ('700', False),
            ('800', False),
        ],
    },
    {
        'text': 'Round 5642 to the nearest 1000.',
        'difficulty': 1, 'points': 1,
        'explanation': 'The hundreds digit is 6 (≥ 5), so round up. 5642 → 6000.',
        'answers': [
            ('5000', False),
            ('5600', False),
            ('5700', False),
            ('6000', True),
        ],
    },
    {
        'text': 'What is the leading digit of 7394?',
        'difficulty': 1, 'points': 1,
        'explanation': 'The leading digit is the first (most significant) non-zero digit. In 7394, the leading digit is 7.',
        'answers': [
            ('3', False),
            ('4', False),
            ('7', True),
            ('9', False),
        ],
    },
    {
        'text': 'Round 29 356 to the nearest 10.',
        'difficulty': 2, 'points': 2,
        'explanation': 'The ones digit is 6 (≥ 5), so round up the tens digit. 29 356 → 29 360.',
        'answers': [
            ('29 350', False),
            ('29 360', True),
            ('29 300', False),
            ('29 400', False),
        ],
    },
    {
        'text': 'Round 3784 to the nearest 100.',
        'difficulty': 2, 'points': 2,
        'explanation': 'The tens digit is 8 (≥ 5), so round up the hundreds digit. 3784 → 3800.',
        'answers': [
            ('3700', False),
            ('3800', True),
            ('3900', False),
            ('4000', False),
        ],
    },
    {
        'text': 'Estimate 28 × 43 by rounding each number to the nearest 10.',
        'difficulty': 2, 'points': 2,
        'explanation': '28 rounds to 30, 43 rounds to 40. Estimate: 30 × 40 = 1200.',
        'answers': [
            ('800', False),
            ('900', False),
            ('1200', True),
            ('1500', False),
        ],
    },
    {
        'text': 'Using leading digit approximation, what is the best estimate of 739 + 456?',
        'difficulty': 2, 'points': 2,
        'explanation': '739 rounded to 1 significant figure = 700. 456 rounded to 1 significant figure = 500. Estimate: 700 + 500 = 1200.',
        'answers': [
            ('1000', False),
            ('1100', False),
            ('1200', True),
            ('1300', False),
        ],
    },
    {
        'text': 'A stadium holds 47 832 spectators. Rounded to the nearest 1000, approximately how many does it hold?',
        'difficulty': 3, 'points': 3,
        'explanation': 'The hundreds digit is 8 (≥ 5), so round up. 47 832 → 48 000.',
        'answers': [
            ('47 000', False),
            ('48 000', True),
            ('50 000', False),
            ('47 500', False),
        ],
    },
    {
        'text': 'Estimate 583 × 61 using leading digit approximation.',
        'difficulty': 3, 'points': 3,
        'explanation': '583 rounded to 1 significant figure = 600. 61 rounded to 1 significant figure = 60. Estimate: 600 × 60 = 36 000.',
        'answers': [
            ('3 000', False),
            ('30 000', False),
            ('36 000', True),
            ('60 000', False),
        ],
    },
    {
        'text': 'A shop sells 386 items at $29 each. Using leading digit approximation, estimate the total cost.',
        'difficulty': 3, 'points': 3,
        'explanation': '386 → 400 (1 sig fig), 29 → 30 (1 sig fig). Estimate: 400 × 30 = $12 000.',
        'answers': [
            ('$8 000', False),
            ('$9 000', False),
            ('$12 000', True),
            ('$15 000', False),
        ],
    },
]


def seed_year7_computation_integers(apps, schema_editor):
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

    # (name, slug, order, questions)
    # order 10-13 already used by Prime Numbers etc (migration 0009)
    subtopics_data = [
        ('Number Systems',         'number-systems',           14, NUMBER_SYSTEMS_QUESTIONS),
        ('Place Values',           'place-values',              1, PLACE_VALUES_QUESTIONS),     # existing
        ('Addition and Subtraction', 'addition-and-subtraction', 15, ADDITION_SUBTRACTION_QUESTIONS),
        ('Multiplication',         'multiplication',             3, MULTIPLICATION_QUESTIONS),  # existing
        ('Division',               'division',                   4, DIVISION_QUESTIONS),        # existing
        ('Estimation and Rounding', 'estimation-and-rounding',  16, ESTIMATION_ROUNDING_QUESTIONS),
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
        ('classroom', '0009_seed_year7_number_questions'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_year7_computation_integers, migrations.RunPython.noop),
    ]
