"""
Runtime question generator for Basic Facts.
Questions are never stored in the database.
"""
import random


SUBTOPIC_CONFIG = {
    'Addition':       {'level_range': (100, 106), 'display_levels': 7},
    'Subtraction':    {'level_range': (107, 113), 'display_levels': 7},
    'Multiplication': {'level_range': (114, 120), 'display_levels': 7},
    'Division':       {'level_range': (121, 127), 'display_levels': 7},
    'PlaceValue':     {'level_range': (128, 132), 'display_levels': 5},
}

SUBTOPIC_LABELS = {
    'Addition': 'Addition',
    'Subtraction': 'Subtraction',
    'Multiplication': 'Multiplication',
    'Division': 'Division',
    'PlaceValue': 'Place Value Facts',
}


def get_display_level(subtopic, level_number):
    """Convert internal level_number to display level 1-N."""
    cfg = SUBTOPIC_CONFIG.get(subtopic)
    if not cfg:
        return 1
    return level_number - cfg['level_range'][0] + 1


def generate_questions(subtopic, level_number, count=10):
    """Return a list of question dicts for the given subtopic + level."""
    generators = {
        'Addition':       _addition_question,
        'Subtraction':    _subtraction_question,
        'Multiplication': _multiplication_question,
        'Division':       _division_question,
        'PlaceValue':     _place_value_question,
    }
    gen = generators.get(subtopic)
    if not gen:
        return []
    questions = []
    for i in range(count):
        q = gen(level_number)
        q['id'] = i + 1
        questions.append(q)
    return questions


def check_answer(question, raw_answer):
    """Return True if raw_answer matches the correct answer (with tolerance for numerics)."""
    from django.conf import settings
    tolerance = getattr(settings, 'ANSWER_NUMERIC_TOLERANCE', 0.05)
    correct = str(question['answer']).strip()
    given = str(raw_answer).strip()
    # Try exact string match first
    if given.lower() == correct.lower():
        return True
    # Try numeric comparison
    try:
        return abs(float(given) - float(correct)) <= tolerance
    except (ValueError, TypeError):
        return False


# ── Addition ────────────────────────────────────────────────────────────────

def _addition_question(level_number):
    display = level_number - 100 + 1  # 1-7
    if display == 1:
        a, b = random.randint(1, 5), random.randint(1, 5)
    elif display == 2:
        a, b = random.randint(0, 9), random.randint(0, 9)
    elif display == 3:
        a = random.randint(10, 90)
        b = random.randint(1, 99 - a % 10) if a % 10 < 9 else random.randint(10, 89)
        # No carry: ensure units don't exceed 9
        a = (a // 10) * 10 + random.randint(1, 8)
        b = random.randint(1, 9 - (a % 10))
        a += random.randint(10, 50)
    elif display == 4:
        a = random.randint(15, 85)
        b = random.randint(15, 99 - a)
    elif display == 5:
        a = random.randint(100, 999)
        b = random.randint(100, 999 - a) if a < 900 else random.randint(10, 99)
    elif display == 6:
        a = random.randint(1000, 9000)
        b = random.randint(1000, 9999 - a)
    else:
        a = random.randint(10000, 90000)
        b = random.randint(1000, 99999 - a)
    answer = a + b
    return {'question': f'{a} + {b} = ?', 'answer': answer, 'display_answer': str(answer)}


# ── Subtraction ─────────────────────────────────────────────────────────────

def _subtraction_question(level_number):
    display = level_number - 107 + 1
    if display == 1:
        a = random.randint(1, 9)
        b = random.randint(0, a)
    elif display == 2:
        tens = random.randint(1, 9) * 10
        b = random.randint(1, tens % 10 if tens % 10 else 9)
        a = tens + random.randint(b, 9)
    elif display == 3:
        a = random.randint(11, 99)
        b = random.randint(1, 9)
    elif display == 4:
        a = random.randint(20, 99)
        b = random.randint(10, a)
    elif display == 5:
        a = random.randint(20, 99)
        b = random.randint(1, 99)
    elif display == 6:
        a = random.randint(100, 999)
        b = random.randint(100, a)
    else:
        a = random.randint(1000, 9999)
        b = random.randint(100, a)
    answer = a - b
    return {'question': f'{a} − {b} = ?', 'answer': answer, 'display_answer': str(answer)}


# ── Multiplication ──────────────────────────────────────────────────────────

def _multiplication_question(level_number):
    display = level_number - 114 + 1
    if display == 1:
        tables = [1, 10]
    elif display == 2:
        tables = [1, 10, 100]
    elif display == 3:
        tables = [5, 10]
    elif display == 4:
        tables = [2, 3, 5, 10]
    elif display == 5:
        b = random.choice([2, 3, 4, 5, 10])
        a = random.randint(10, 99)
        answer = a * b
        return {'question': f'{a} × {b} = ?', 'answer': answer, 'display_answer': str(answer)}
    elif display == 6:
        b = random.choice([2, 3, 4, 5, 6, 7, 10])
        a = random.randint(10, 99)
        answer = a * b
        return {'question': f'{a} × {b} = ?', 'answer': answer, 'display_answer': str(answer)}
    else:
        b = random.choice(range(2, 11))
        a = random.randint(100, 999)
        answer = a * b
        return {'question': f'{a} × {b} = ?', 'answer': answer, 'display_answer': str(answer)}
    b = random.choice(tables)
    a = random.randint(1, 12)
    answer = a * b
    return {'question': f'{a} × {b} = ?', 'answer': answer, 'display_answer': str(answer)}


# ── Division ────────────────────────────────────────────────────────────────

def _division_question(level_number):
    display = level_number - 121 + 1
    if display == 1:
        divisors = [1, 10]
        quotient = random.randint(1, 12)
    elif display == 2:
        divisors = [1, 10, 100]
        quotient = random.randint(2, 12)
    elif display == 3:
        divisors = [5, 10]
        quotient = random.randint(2, 12)
    elif display == 4:
        divisors = [2, 3, 5, 10]
        quotient = random.randint(3, 12)
    elif display == 5:
        divisor = random.choice([2, 3, 4, 5, 10])
        quotient = random.randint(10, 99)
        dividend = divisor * quotient
        return {'question': f'{dividend} ÷ {divisor} = ?', 'answer': quotient, 'display_answer': str(quotient)}
    elif display == 6:
        divisor = random.choice([2, 3, 4, 5, 6, 7, 10])
        quotient = random.randint(10, 99)
        dividend = divisor * quotient
        return {'question': f'{dividend} ÷ {divisor} = ?', 'answer': quotient, 'display_answer': str(quotient)}
    else:
        divisor = random.choice(range(2, 12))
        quotient = random.randint(100, 999)
        dividend = divisor * quotient
        return {'question': f'{dividend} ÷ {divisor} = ?', 'answer': quotient, 'display_answer': str(quotient)}
    divisor = random.choice(divisors)
    dividend = divisor * quotient
    return {'question': f'{dividend} ÷ {divisor} = ?', 'answer': quotient, 'display_answer': str(quotient)}


# ── Place Value Facts ────────────────────────────────────────────────────────

def _place_value_question(level_number):
    display = level_number - 128 + 1
    targets = {1: 10, 2: 100, 3: 1000, 4: 10000, 5: 100000}
    target = targets.get(display, 10)

    a = random.randint(1, target - 1)
    b = target - a

    # Randomly pick question format
    fmt = random.choice(['ab', 'a_blank', 'blank_b'])
    if fmt == 'ab':
        question = f'{a} + {b} = ?'
        answer = target
    elif fmt == 'a_blank':
        question = f'{a} + ? = {target}'
        answer = b
    else:
        question = f'? + {b} = {target}'
        answer = a

    return {'question': question, 'answer': answer, 'display_answer': str(answer)}
