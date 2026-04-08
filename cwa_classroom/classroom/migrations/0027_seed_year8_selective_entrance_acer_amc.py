"""
Migration 0027 — ACER Set03 + AMC 2019 Senior (Year 8 MCQ):

  Source 1: Selective Entrance .pdf (ACER Set03, 50 MCQ)
    Included: 36 questions that require no visual diagram
    Skipped:  Q6 (angle diagram), Q10 (shape diagram), Q11–12 (bar chart),
              Q24 (garbled algebraic indices encoding), Q25 (trig diagram),
              Q26 (shape image), Q35 (nets image), Q46–48 (land layout diagram),
              Q50 (angle diagram)

  Source 2: Selective Entrance 1.pdf (AMC 2019 Senior, Q1–Q16 only)
    Included: 12 questions accessible without diagrams
    Skipped:  Q2 (shaded triangle diagram), Q4 (crossing-lines diagram),
              Q12 (right-triangle altitude diagram), Q15 (nonagram diagram)

  Topic breakdown (Year 8):
    probability                          : +2  (dice, late-to-school)
    number-systems                       : +2  (scientific notation ×2)
    percentages                          : +2  (marathon red, circumference %)
    expanding-and-factorising-quadratics : +1  (factorise x²−2x−15)
    pythagoras-theorem                   : +2  (2D triangle, 3D diagonal)
    logic-and-problem-solving            : +8  (work rate, distance, direction, best value,
                                                milkshake ratio, cardinal direction,
                                                water bucket, sequences, divisibility)
    finance                              : +2  (lollies split, simple interest)
    measurement                          : +7  (surface area pyramid, time quarter-year,
                                                time January, time flight, volume ratio,
                                                estimation petrol, minutes January)
    area                                 : +2  (trapezium area, rectangle dimensions)
    fractions                            : +2  (0.375 as fraction, 3/7 of 238)
    angles                               : +1  (polygon interior angle sum)
    linear-equations                     : +4  (substitute point, linear table,
                                                gradient, rearrange equation)
    simultaneous-equations               : +1  (people on ride)
    ratios                               : +3  (best value, paper-plane ratio, milkshake)
    integers                             : +1  (which statement is true)
    algebra (indices)                    : +2  (AMC: function evaluation, AMC: indices)
    data-interpretation                  : +1  (mean of data set)
    estimation                           : +1  (316 ÷ 0.631)
"""
from django.db import migrations

# ---------------------------------------------------------------------------
# ACER Set03 questions
# ---------------------------------------------------------------------------

PROBABILITY = [
    {
        "text": (
            "I rolled two dice together, but one rolled under the table. "
            "The one I can see is showing a 6. What is the probability that both are 6?"
        ),
        "difficulty": 2,
        "topic": "probability",
        "answers": [
            ("1/6",  True),
            ("1/12", False),
            ("1/36", False),
            ("1/18", False),
        ],
        "source": "ACER Set03 Q1",
    },
    {
        "text": (
            "I am late 2 days a week going to school and forget my books 3 days out of 4. "
            "What is the chance that I am on time AND have my books that day?"
        ),
        "difficulty": 2,
        "topic": "probability",
        "answers": [
            ("15%", True),
            ("20%", False),
            ("30%", False),
            ("10%", False),
        ],
        "source": "ACER Set03 Q8",
    },
]

NUMBER_SYSTEMS = [
    {
        "text": (
            "If a = 3.2 × 10⁴ and b = 7.3 × 10³, find the value of a + b."
        ),
        "difficulty": 2,
        "topic": "number-systems",
        "answers": [
            ("3.93 × 10⁴", True),
            ("7.62 × 10³", False),
            ("10.5 × 10⁴", False),
            ("9.5 × 10³",  False),
        ],
        "source": "ACER Set03 Q2",
    },
    {
        "text": "Which is the correct scientific notation of 0.00387?",
        "difficulty": 1,
        "topic": "number-systems",
        "answers": [
            ("3.87 × 10⁻³", True),
            ("3.87 × 10³",  False),
            ("0.387 × 10⁻²", False),
            ("387 × 10⁻⁵",  False),
        ],
        "source": "ACER Set03 Q21",
    },
]

PERCENTAGES = [
    {
        "text": (
            "There were 840 people in a marathon. 45% are female and 100 of the female "
            "participants were not wearing red. 35% of all participants are in red. "
            "How many males were wearing red?"
        ),
        "difficulty": 3,
        "topic": "percentages",
        "answers": [
            ("16",  True),
            ("75",  False),
            ("24",  False),
            ("37",  False),
        ],
        "source": "ACER Set03 Q3",
    },
    {
        "text": (
            "What is 60% of the circumference, if 45% of the circumference is 60 cm?"
        ),
        "difficulty": 2,
        "topic": "percentages",
        "answers": [
            ("80 cm", True),
            ("48 cm", False),
            ("66 cm", False),
            ("72 cm", False),
        ],
        "source": "ACER Set03 Q7",
    },
]

EXPANDING_FACTORISING = [
    {
        "text": "Factorise x² − 2x − 15.",
        "difficulty": 2,
        "topic": "expanding-and-factorising-quadratics",
        "answers": [
            ("(x − 5)(x + 3)", True),
            ("(x + 5)(x + 3)", False),
            ("(x − 5)(x − 3)", False),
            ("(x + 5)(x − 3)", False),
        ],
        "source": "ACER Set03 Q4",
    },
]

PYTHAGORAS = [
    {
        "text": (
            "The hypotenuse of a right-angled triangle is 10 cm and one of the other sides "
            "is 4 cm. What is the length of the third side?"
        ),
        "difficulty": 2,
        "topic": "pythagoras-theorem",
        "answers": [
            ("2√21", True),
            ("3√6",  False),
            ("3√21", False),
            ("2√6",  False),
        ],
        "source": "ACER Set03 Q5",
    },
    {
        "text": (
            "What is the longest diagonal length of a rectangular prism with "
            "dimensions 3 × 4 × 12 metres?"
        ),
        "difficulty": 2,
        "topic": "pythagoras-theorem",
        "answers": [
            ("13 m", True),
            ("11 m", False),
            ("12 m", False),
            ("15 m", False),
        ],
        "source": "ACER Set03 Q43",
    },
]

SIMULTANEOUS_EQNS = [
    {
        "text": (
            "One hundred and thirty-three people went on a ride. "
            "An adult ticket costs $8 and a child ticket costs $3. "
            "At the end of the day the ride made $624. How many children went on the ride?"
        ),
        "difficulty": 2,
        "topic": "simultaneous-equations",
        "answers": [
            ("88",  True),
            ("57",  False),
            ("92",  False),
            ("103", False),
        ],
        "source": "ACER Set03 Q9",
    },
]

LOGIC = [
    {
        "text": (
            "Matthew and Nicholas finished a task together in 16 days. "
            "Nicholas and Oliver completed the same task in 24 days. "
            "All three working together finished it in 12 days. "
            "How long would Matthew and Oliver take working together?"
        ),
        "difficulty": 3,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("16 days", True),
            ("12 days", False),
            ("18 days", False),
            ("20 days", False),
        ],
        "source": "ACER Set03 Q13",
    },
    {
        "text": (
            "The distance from City A to City B is 195 km. "
            "Car 1 travels from City A at 60 km/h for 1 hour and 38 minutes before stopping. "
            "Car 2 travels from City B at 90 km/h for 50 minutes before stopping. "
            "What is the distance between the two cars?"
        ),
        "difficulty": 3,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("22 km", True),
            ("60 km", False),
            ("15 km", False),
            ("40 km", False),
        ],
        "source": "ACER Set03 Q31",
    },
    {
        "text": (
            "To make a milkshake I need 2 bananas for every 250 mL of milk. "
            "If I want to use up 2 L of milk, how many bananas do I need?"
        ),
        "difficulty": 1,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("16 bananas", True),
            ("8 bananas",  False),
            ("12 bananas", False),
            ("32 bananas", False),
        ],
        "source": "ACER Set03 Q32",
    },
    {
        "text": (
            "A man walked 2.5 km south, then turned right and walked 5 km, "
            "then turned right and walked 2 km. After a rest he walked a further 3 km north. "
            "What direction is the starting point from where he is now standing?"
        ),
        "difficulty": 3,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("South-East",  True),
            ("North-East",  False),
            ("North-West",  False),
            ("South-West",  False),
        ],
        "source": "ACER Set03 Q33",
    },
    {
        "text": (
            "A bucket started with 2.5 L. 800 mL was poured out, then 1 L was poured back in. "
            "While carrying it, half the water spilt out. "
            "How much water needs to be added to fill it to 3 L?"
        ),
        "difficulty": 2,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("1650 mL", True),
            ("1400 mL", False),
            ("1435 mL", False),
            ("1750 mL", False),
        ],
        "source": "ACER Set03 Q34",
    },
    {
        "text": (
            "Petrol costs 119.3 cents per litre. A full tank holds 52.3 L. "
            "What is the best estimate for the cost of a full tank?"
        ),
        "difficulty": 1,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("$65", True),
            ("$55", False),
            ("$75", False),
            ("$50", False),
        ],
        "source": "ACER Set03 Q37",
    },
    {
        "text": (
            "A rectangular festival hall has an area of 45 m² and a perimeter of 28 m. "
            "What are its dimensions?"
        ),
        "difficulty": 2,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("5 × 9 m",  True),
            ("5 × 6 m",  False),
            ("9 × 7 m",  False),
            ("3 × 15 m", False),
        ],
        "source": "ACER Set03 Q39",
    },
    {
        "text": "The value of 316 ÷ 0.631 is approximately:",
        "difficulty": 1,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("500",  True),
            ("5",    False),
            ("50",   False),
            ("5000", False),
        ],
        "source": "ACER Set03 Q40",
    },
]

FINANCE = [
    {
        "text": (
            "Mia bought 18 lolly bags for $3.10 each. "
            "She divided all the bags equally among her three friends. "
            "How much does each friend need to pay her back?"
        ),
        "difficulty": 1,
        "topic": "finance",
        "answers": [
            ("$18.60", True),
            ("$16.10", False),
            ("$18.30", False),
            ("$19.20", False),
        ],
        "source": "ACER Set03 Q14",
    },
    {
        "text": (
            "Sophia borrowed $11,000 from the bank at a rate of 6% per year. "
            "She borrowed it 6 years ago. What is the simple interest she needs to pay off?"
        ),
        "difficulty": 2,
        "topic": "finance",
        "answers": [
            ("$3,960", True),
            ("$5,230", False),
            ("$4,310", False),
            ("$2,450", False),
        ],
        "source": "ACER Set03 Q15",
    },
]

MEASUREMENT = [
    {
        "text": (
            "What is the surface area of a square-based pyramid if the base length "
            "is 18 cm and the height is 12 cm?"
        ),
        "difficulty": 2,
        "topic": "measurement",
        "answers": [
            ("864 cm²", True),
            ("648 cm²", False),
            ("788 cm²", False),
            ("838 cm²", False),
        ],
        "source": "ACER Set03 Q16",
    },
    {
        "text": "In a quarter of a year, how many weeks is it?",
        "difficulty": 1,
        "topic": "measurement",
        "answers": [
            ("13 weeks", True),
            ("12 weeks", False),
            ("24 weeks", False),
            ("6 weeks",  False),
        ],
        "source": "ACER Set03 Q17",
    },
    {
        "text": "How many minutes are there in January?",
        "difficulty": 1,
        "topic": "measurement",
        "answers": [
            ("44,640 minutes", True),
            ("62,431 minutes", False),
            ("76,145 minutes", False),
            ("39,540 minutes", False),
        ],
        "source": "ACER Set03 Q36",
    },
    {
        "text": (
            "On Wednesday at 9:15 am I left on a plane for a 21-hour and 25-minute flight. "
            "What time would I arrive at my destination?"
        ),
        "difficulty": 2,
        "topic": "measurement",
        "answers": [
            ("Thursday 6:40 am",   True),
            ("Wednesday 11:40 pm", False),
            ("Wednesday 11:55 pm", False),
            ("Thursday 4:20 am",   False),
        ],
        "source": "ACER Set03 Q28",
    },
    {
        "text": (
            "A rectangular prism container with dimensions 3 × 8 × 10 cm holds 1.5 kg of liquid. "
            "How much of the same liquid can a container with dimensions 2 × 5 × 6 cm hold?"
        ),
        "difficulty": 2,
        "topic": "measurement",
        "answers": [
            ("375 g",  True),
            ("1 kg",   False),
            ("125 g",  False),
            ("540 g",  False),
        ],
        "source": "ACER Set03 Q38",
    },
]

AREA = [
    {
        "text": (
            "A trapezium has a height of 16 cm and two parallel sides of 14 cm and 26 cm. "
            "What is the area of the trapezium?"
        ),
        "difficulty": 2,
        "topic": "area",
        "answers": [
            ("320 cm²", True),
            ("240 cm²", False),
            ("280 cm²", False),
            ("360 cm²", False),
        ],
        "source": "ACER Set03 Q20",
    },
]

FRACTIONS = [
    {
        "text": "What is 0.375 as a fraction in its simplest form?",
        "difficulty": 1,
        "topic": "fractions",
        "answers": [
            ("3/8",    True),
            ("375/100", False),
            ("75/100", False),
            ("3/5",    False),
        ],
        "source": "ACER Set03 Q22",
    },
    {
        "text": "What is 3/7 of 238?",
        "difficulty": 1,
        "topic": "fractions",
        "answers": [
            ("102", True),
            ("68",  False),
            ("136", False),
            ("90",  False),
        ],
        "source": "ACER Set03 Q30",
    },
]

ANGLES = [
    {
        "text": (
            "The sum of the interior angles of which polygon is always equal to 540°?"
        ),
        "difficulty": 1,
        "topic": "angles",
        "answers": [
            ("Pentagon",      True),
            ("Quadrilateral", False),
            ("Hexagon",       False),
            ("Heptagon",      False),
        ],
        "source": "ACER Set03 Q23",
    },
]

LINEAR_EQNS = [
    {
        "text": (
            "The point (3, k) lies on the graph of 10 = 2y − 8x. What does k equal?"
        ),
        "difficulty": 2,
        "topic": "linear-equations",
        "answers": [
            ("17", True),
            ("11", False),
            ("13", False),
            ("19", False),
        ],
        "source": "ACER Set03 Q27",
    },
    {
        "text": (
            "A table of values is given where x = 1 maps to y = 4, and x = 3 maps to y = 10. "
            "Which equation best fits the pattern?"
        ),
        "difficulty": 2,
        "topic": "linear-equations",
        "answers": [
            ("y = 3x + 1", True),
            ("y = x + 2",  False),
            ("y = 4x − 4", False),
            ("y = 5x − 6", False),
        ],
        "source": "ACER Set03 Q41",
    },
    {
        "text": "What is the gradient of the line passing through (−1, 6) and (3, −2)?",
        "difficulty": 2,
        "topic": "linear-equations",
        "answers": [
            ("−2", True),
            ("2",  False),
            ("5",  False),
            ("−5", False),
        ],
        "source": "ACER Set03 Q42",
    },
    {
        "text": (
            "To find the variable x in the equation y = (2x + m) / a, "
            "what must the first step be?"
        ),
        "difficulty": 2,
        "topic": "linear-equations",
        "answers": [
            ("Multiply both sides by a", True),
            ("Divide both sides by 2",   False),
            ("Add m to both sides",      False),
            ("Subtract x from both sides", False),
        ],
        "source": "ACER Set03 Q49",
    },
]

DATA_INTERP = [
    {
        "text": (
            "The mean of the data set {11, 8, 6, 16, 12, 6, 17, 12} is:"
        ),
        "difficulty": 1,
        "topic": "data-interpretation",
        "answers": [
            ("11", True),
            ("6",  False),
            ("10", False),
            ("8",  False),
        ],
        "source": "ACER Set03 Q44",
    },
]

ALGEBRA_LINEAR_EXTRA = [
    {
        "text": "Solve for x: 2(5x + 1) = 8x − 12.",
        "difficulty": 2,
        "topic": "linear-equations",
        "answers": [
            ("−7",  True),
            ("−14", False),
            ("12",  False),
            ("8",   False),
        ],
        "source": "ACER Set03 Q45",
    },
]

RATIOS = [
    {
        "text": (
            "Which option gives the best value on carrots?\n"
            "A. 5 kg at $19.30\n"
            "B. 600 g at $2.70\n"
            "C. 2 kg at $8.60\n"
            "D. 750 g at $3.75"
        ),
        "difficulty": 2,
        "topic": "ratios",
        "answers": [
            ("5 kg at $19.30 ($3.86/kg)",   True),
            ("2 kg at $8.60 ($4.30/kg)",    False),
            ("600 g at $2.70 ($4.50/kg)",   False),
            ("750 g at $3.75 ($5.00/kg)",   False),
        ],
        "source": "ACER Set03 Q18",
    },
    {
        "text": (
            "Five boys and four girls need to fold 144 paper planes together. "
            "If everyone folds an equal amount, how many planes do the boys fold as a group?"
        ),
        "difficulty": 1,
        "topic": "ratios",
        "answers": [
            ("80 paper planes", True),
            ("60 paper planes", False),
            ("40 paper planes", False),
            ("30 paper planes", False),
        ],
        "source": "ACER Set03 Q19",
    },
]

INTEGERS = [
    {
        "text": (
            "Which of the following statements is true?\n"
            "A. 6² + 8² = 10²\n"
            "B. √225 > 4²\n"
            "C. (20/5) × 21 ≠ 4 × 15\n"
            "D. 5 × 8 + 91 = 11²"
        ),
        "difficulty": 2,
        "topic": "integers",
        "answers": [
            ("6² + 8² = 10² (both equal 100)", True),
            ("√225 > 4² (15 is not greater than 16)", False),
            ("(20/5) × 21 ≠ 4 × 15 (both equal 84 and 60, so they ARE ≠)", False),
            ("5 × 8 + 91 = 11² (131 ≠ 121)", False),
        ],
        "source": "ACER Set03 Q29",
    },
]

# ---------------------------------------------------------------------------
# AMC 2019 Senior questions (Q1–Q16, diagram-free)
# ---------------------------------------------------------------------------

AMC_INTEGERS = [
    {
        "text": "What is the value of 201 × 9?",
        "difficulty": 1,
        "topic": "integers",
        "answers": [
            ("1809", True),
            ("189",  False),
            ("1818", False),
            ("2019", False),
        ],
        "source": "AMC 2019 Senior Q1",
    },
]

AMC_PERCENTAGES = [
    {
        "text": "What is 19% of $20?",
        "difficulty": 1,
        "topic": "percentages",
        "answers": [
            ("$3.80",  True),
            ("$20.19", False),
            ("$1.90",  False),
            ("$0.19",  False),
        ],
        "source": "AMC 2019 Senior Q3",
    },
]

AMC_INDICES = [
    {
        "text": "The value of 2⁰ + 1⁹ is:",
        "difficulty": 1,
        "topic": "indices-and-powers",
        "answers": [
            ("2",  True),
            ("1",  False),
            ("3",  False),
            ("10", False),
        ],
        "source": "AMC 2019 Senior Q5",
    },
    {
        "text": (
            "Let f(x) = 3x² − 2x. "
            "Then f(−2) = ?"
        ),
        "difficulty": 2,
        "topic": "indices-and-powers",
        "answers": [
            ("16",  True),
            ("−32", False),
            ("−8",  False),
            ("32",  False),
        ],
        "source": "AMC 2019 Senior Q6",
    },
    {
        "text": (
            "Evaluate: (1¹ + 2² + 3³ + 4⁴) / (1¹ + 2² + 3³)"
        ),
        "difficulty": 3,
        "topic": "indices-and-powers",
        "answers": [
            ("9",  True),
            ("23", False),
            ("32", False),
            ("43", False),
        ],
        "source": "AMC 2019 Senior Q10",
    },
]

AMC_ANGLES = [
    {
        "text": (
            "A kite has four angles: three of them equal θ and one equals θ/3. "
            "What is the size of angle θ?"
        ),
        "difficulty": 2,
        "topic": "angles",
        "answers": [
            ("108°", True),
            ("120°", False),
            ("105°", False),
            ("90°",  False),
        ],
        "source": "AMC 2019 Senior Q7",
    },
]

AMC_LOGIC = [
    {
        "text": (
            "Consider the repeating sequence 1, 4, 7, 4, 1, 4, 7, 4, … (repeats every 4 terms). "
            "The running total of the first 3 terms is 12 and the first 7 terms is 28. "
            "Which of the following is also a possible running total of this sequence?"
        ),
        "difficulty": 2,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("65", True),
            ("61", False),
            ("62", False),
            ("66", False),
        ],
        "source": "AMC 2019 Senior Q8",
    },
    {
        "text": (
            "Mia walks at 1.5 m/s and her friend Crystal walks at 2 m/s. "
            "They walk in opposite directions around a bush track, starting from the same point. "
            "They first meet again after 20 minutes. How long, in kilometres, is the track?"
        ),
        "difficulty": 2,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("4.2 km", True),
            ("3.5 km", False),
            ("6 km",   False),
            ("7 km",   False),
        ],
        "source": "AMC 2019 Senior Q9",
    },
    {
        "text": (
            "In a box of apples, 3/7 of the apples are red and the rest are green. "
            "Five more green apples are added to the box. Now 5/8 of the apples are green. "
            "How many apples are there now in the box?"
        ),
        "difficulty": 3,
        "topic": "fractions",
        "answers": [
            ("40", True),
            ("32", False),
            ("33", False),
            ("48", False),
        ],
        "source": "AMC 2019 Senior Q13",
    },
    {
        "text": (
            "Which number exceeds its own square by the greatest possible amount?"
        ),
        "difficulty": 3,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("1/2",      True),
            ("2/3",      False),
            ("1/4",      False),
            ("3/4",      False),
        ],
        "source": "AMC 2019 Senior Q14",
    },
]

AMC_NUMBER_SYSTEMS = [
    {
        "text": (
            "The 5-digit number P679Q is divisible by 72. The digit P equals:"
        ),
        "difficulty": 3,
        "topic": "number-systems",
        "answers": [
            ("3", True),
            ("1", False),
            ("2", False),
            ("4", False),
        ],
        "source": "AMC 2019 Senior Q11",
    },
]

AMC_SEQUENCES = [
    {
        "text": (
            "Two sequences each have 900 terms:\n"
            "  Sequence 1: 5, 8, 11, 14, … (increasing by 3)\n"
            "  Sequence 2: 3, 7, 11, 15, … (increasing by 4)\n"
            "How many terms do these two sequences have in common?"
        ),
        "difficulty": 3,
        "topic": "logic-and-problem-solving",
        "answers": [
            ("225", True),
            ("400", False),
            ("300", False),
            ("275", False),
        ],
        "source": "AMC 2019 Senior Q16",
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

    # Build the combined slug → question list mapping
    all_groups = (
        PROBABILITY
        + NUMBER_SYSTEMS
        + PERCENTAGES
        + EXPANDING_FACTORISING
        + PYTHAGORAS
        + SIMULTANEOUS_EQNS
        + LOGIC
        + FINANCE
        + MEASUREMENT
        + AREA
        + FRACTIONS
        + ANGLES
        + LINEAR_EQNS
        + ALGEBRA_LINEAR_EXTRA
        + DATA_INTERP
        + RATIOS
        + INTEGERS
        + AMC_INTEGERS
        + AMC_PERCENTAGES
        + AMC_INDICES
        + AMC_ANGLES
        + AMC_LOGIC
        + AMC_NUMBER_SYSTEMS
        + AMC_SEQUENCES
    )

    # Group by topic slug
    from collections import defaultdict
    by_slug = defaultdict(list)
    for q in all_groups:
        by_slug[q['topic']].append(q)

    for slug, q_list in by_slug.items():
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

    all_texts = [
        q['text'] for q in (
            PROBABILITY
            + NUMBER_SYSTEMS
            + PERCENTAGES
            + EXPANDING_FACTORISING
            + PYTHAGORAS
            + SIMULTANEOUS_EQNS
            + LOGIC
            + FINANCE
            + MEASUREMENT
            + AREA
            + FRACTIONS
            + ANGLES
            + LINEAR_EQNS
            + ALGEBRA_LINEAR_EXTRA
            + DATA_INTERP
            + RATIOS
            + INTEGERS
            + AMC_INTEGERS
            + AMC_PERCENTAGES
            + AMC_INDICES
            + AMC_ANGLES
            + AMC_LOGIC
            + AMC_NUMBER_SYSTEMS
            + AMC_SEQUENCES
        )
    ]
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0026_seed_year8_acer_set02'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
