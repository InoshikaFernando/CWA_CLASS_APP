"""
Generate number puzzles and store them in the database.

Usage:
    python manage.py generate_puzzles --level 1 --count 500
    python manage.py generate_puzzles --all --count 500
    python manage.py generate_puzzles --all --count 500 --clear
    python manage.py generate_puzzles --all --dry-run
"""
import hashlib
import itertools
import json
import random

from django.core.management.base import BaseCommand, CommandError

from number_puzzles.models import NumberPuzzle, NumberPuzzleLevel

OPERATORS = ['+', '-', '*', '/']


def safe_eval(expr):
    """
    Evaluate a mathematical expression safely using recursive-descent parsing.
    Supports +, -, *, / and parentheses. Returns a float or None on error.
    """
    pos = [0]
    s = expr.replace(' ', '')

    def peek():
        if pos[0] < len(s):
            return s[pos[0]]
        return None

    def consume(expected=None):
        ch = s[pos[0]]
        if expected and ch != expected:
            return None
        pos[0] += 1
        return ch

    def parse_number():
        start = pos[0]
        if pos[0] < len(s) and s[pos[0]] == '-':
            pos[0] += 1
        while pos[0] < len(s) and s[pos[0]].isdigit():
            pos[0] += 1
        if pos[0] == start:
            return None
        return float(s[start:pos[0]])

    def parse_atom():
        if peek() == '(':
            consume('(')
            val = parse_expr()
            if peek() != ')':
                return None
            consume(')')
            return val
        return parse_number()

    def parse_term():
        left = parse_atom()
        if left is None:
            return None
        while peek() in ('*', '/'):
            op = consume()
            right = parse_atom()
            if right is None:
                return None
            if op == '*':
                left = left * right
            else:
                if right == 0:
                    return None
                left = left / right
        return left

    def parse_expr():
        left = parse_term()
        if left is None:
            return None
        while peek() in ('+', '-'):
            op = consume()
            right = parse_term()
            if right is None:
                return None
            if op == '+':
                left = left + right
            else:
                left = left - right
        return left

    try:
        result = parse_expr()
        if result is None or pos[0] != len(s):
            return None
        return result
    except (IndexError, ValueError, ZeroDivisionError):
        return None


def is_non_negative_integer(val):
    """Check if a value is a non-negative integer."""
    if val is None:
        return False
    return val >= 0 and val == int(val)


def build_puzzle_dict(level, operands, target, display_template, solution,
                      has_multiple_solutions=False):
    """Build a puzzle dict ready for bulk_create."""
    operands_hash = hashlib.md5(
        json.dumps(operands, sort_keys=False).encode()
    ).hexdigest()
    return {
        'level': level,
        'operands': operands,
        'operands_hash': operands_hash,
        'target': int(target),
        'display_template': display_template,
        'solution': solution,
        'has_multiple_solutions': has_multiple_solutions,
    }


def generate_level_1(level, count):
    """Level 1: Two single-digit operands, + or - only."""
    ops = ['+', '-']
    puzzles = []
    seen = set()

    for a in range(level.min_operand, level.max_operand + 1):
        for b in range(level.min_operand, level.max_operand + 1):
            for op in ops:
                expr = f"{a}{op}{b}"
                result = safe_eval(expr)
                if not is_non_negative_integer(result):
                    continue
                if int(result) > level.max_result:
                    continue
                key = (a, b, int(result))
                if key in seen:
                    continue
                seen.add(key)
                target = int(result)
                display = f"{a} _ {b} = {target}"
                # Use x for display in solution
                solution_display = expr.replace('*', 'x')
                puzzles.append(build_puzzle_dict(
                    level, [a, b], target, display,
                    f"{solution_display}={target}"
                ))
                if len(puzzles) >= count:
                    return puzzles

    random.shuffle(puzzles)
    return puzzles[:count]


def generate_level_2(level, count):
    """Level 2: Two operands (1-99), all four operators."""
    ops = ['+', '-', '*', '/']
    puzzles = []
    seen = set()
    attempts = 0
    max_attempts = count * 50

    while len(puzzles) < count and attempts < max_attempts:
        attempts += 1
        a = random.randint(level.min_operand, level.max_operand)
        b = random.randint(level.min_operand, level.max_operand)
        op = random.choice(ops)

        if op == '/' and (b == 0 or a % b != 0):
            continue

        expr = f"{a}{op}{b}"
        result = safe_eval(expr)
        if not is_non_negative_integer(result):
            continue
        if int(result) > level.max_result:
            continue

        target = int(result)
        key = (a, b, target)
        if key in seen:
            continue
        seen.add(key)

        display = f"{a} _ {b} = {target}"
        solution_display = expr.replace('*', 'x')
        puzzles.append(build_puzzle_dict(
            level, [a, b], target, display,
            f"{solution_display}={target}"
        ))

    return puzzles[:count]


def generate_level_3(level, count):
    """Level 3: Three operands (1-20), two operators. Unique solution required."""
    ops = ['+', '-', '*', '/']
    puzzles = []
    seen = set()
    attempts = 0
    max_attempts = count * 100

    while len(puzzles) < count and attempts < max_attempts:
        attempts += 1
        a = random.randint(level.min_operand, level.max_operand)
        b = random.randint(level.min_operand, level.max_operand)
        c = random.randint(level.min_operand, level.max_operand)
        op1 = random.choice(ops)
        op2 = random.choice(ops)

        # Check division validity
        expr = f"{a}{op1}{b}{op2}{c}"
        result = safe_eval(expr)
        if not is_non_negative_integer(result):
            continue
        target = int(result)
        if target > level.max_result:
            continue

        # Check uniqueness: only one operator combination should produce this target
        valid_combos = 0
        for o1, o2 in itertools.product(ops, repeat=2):
            test_expr = f"{a}{o1}{b}{o2}{c}"
            test_result = safe_eval(test_expr)
            if test_result is not None and is_non_negative_integer(test_result) and int(test_result) == target:
                valid_combos += 1
                if valid_combos > 1:
                    break

        if valid_combos != 1:
            continue

        key = (a, b, c, target)
        if key in seen:
            continue
        seen.add(key)

        display = f"{a} _ {b} _ {c} = {target}"
        solution_display = expr.replace('*', 'x')
        puzzles.append(build_puzzle_dict(
            level, [a, b, c], target, display,
            f"{solution_display}={target}"
        ))

    return puzzles[:count]


def generate_level_4(level, count):
    """Level 4: Three operands, brackets shown, find operators."""
    ops = ['+', '-', '*', '/']
    bracket_patterns = [
        # (a op1 b) op2 c
        lambda a, o1, b, o2, c: (f"({a}{o1}{b}){o2}{c}", f"({a} _ {b}) _ {c}"),
        # a op1 (b op2 c)
        lambda a, o1, b, o2, c: (f"{a}{o1}({b}{o2}{c})", f"{a} _ ({b} _ {c})"),
    ]
    puzzles = []
    seen = set()
    attempts = 0
    max_attempts = count * 100

    while len(puzzles) < count and attempts < max_attempts:
        attempts += 1
        a = random.randint(level.min_operand, level.max_operand)
        b = random.randint(level.min_operand, level.max_operand)
        c = random.randint(level.min_operand, level.max_operand)
        op1 = random.choice(ops)
        op2 = random.choice(ops)
        pattern = random.choice(bracket_patterns)

        expr, display_tpl = pattern(a, op1, b, op2, c)
        result = safe_eval(expr)
        if not is_non_negative_integer(result):
            continue
        target = int(result)
        if target > level.max_result:
            continue

        # Brackets must matter: evaluate without brackets
        flat_expr = f"{a}{op1}{b}{op2}{c}"
        flat_result = safe_eval(flat_expr)
        if flat_result is not None and is_non_negative_integer(flat_result) and int(flat_result) == target:
            continue  # brackets don't change the result

        key = (a, b, c, target, display_tpl.replace(str(a), 'A').replace(str(b), 'B').replace(str(c), 'C'))
        if (a, b, c, target) in seen:
            continue
        seen.add((a, b, c, target))

        display = f"{display_tpl} = {target}"
        solution_display = expr.replace('*', 'x')
        puzzles.append(build_puzzle_dict(
            level, [a, b, c], target, display,
            f"{solution_display}={target}"
        ))

    return puzzles[:count]


def _eval_with_brackets_3(operands, ops, bracket_type):
    """
    Evaluate 3-operand expression with a specific bracket arrangement.
    bracket_type: 'none', 'left' = (a op b) op c, 'right' = a op (b op c)
    """
    a, b, c = operands
    o1, o2 = ops

    if bracket_type == 'none':
        expr = f"{a}{o1}{b}{o2}{c}"
    elif bracket_type == 'left':
        expr = f"({a}{o1}{b}){o2}{c}"
    elif bracket_type == 'right':
        expr = f"{a}{o1}({b}{o2}{c})"
    else:
        return None, None

    result = safe_eval(expr)
    return result, expr


def generate_level_5(level, count):
    """Level 5: Three operands (1-15), place brackets AND operators."""
    ops = ['+', '-', '*', '/']
    bracket_types = ['left', 'right']
    puzzles = []
    seen = set()

    # Exhaustive enumeration since valid puzzles are rarer
    operand_range = range(level.min_operand, level.max_operand + 1)

    for a in operand_range:
        for b in operand_range:
            for c in operand_range:
                for o1, o2 in itertools.product(ops, repeat=2):
                    for bt in bracket_types:
                        result, expr = _eval_with_brackets_3([a, b, c], [o1, o2], bt)
                        if not is_non_negative_integer(result):
                            continue
                        target = int(result)
                        if target > level.max_result or target <= 0:
                            continue

                        # Brackets must be necessary: flat version must NOT equal target
                        flat_result, _ = _eval_with_brackets_3([a, b, c], [o1, o2], 'none')
                        if flat_result is not None and is_non_negative_integer(flat_result) and int(flat_result) == target:
                            continue

                        key = (a, b, c, target)
                        if key in seen:
                            continue
                        seen.add(key)

                        # Check if multiple solutions exist
                        solutions = []
                        for test_o1, test_o2 in itertools.product(ops, repeat=2):
                            for test_bt in bracket_types:
                                test_result, test_expr = _eval_with_brackets_3(
                                    [a, b, c], [test_o1, test_o2], test_bt
                                )
                                if test_result is not None and is_non_negative_integer(test_result) and int(test_result) == target:
                                    # Verify brackets are necessary for this combo too
                                    flat_r, _ = _eval_with_brackets_3(
                                        [a, b, c], [test_o1, test_o2], 'none'
                                    )
                                    if flat_r is None or not is_non_negative_integer(flat_r) or int(flat_r) != target:
                                        solutions.append(test_expr)

                        display = f"{a}  {b}  {c} = {target}"
                        solution_display = expr.replace('*', 'x')
                        puzzles.append(build_puzzle_dict(
                            level, [a, b, c], target, display,
                            f"{solution_display}={target}",
                            has_multiple_solutions=len(solutions) > 1
                        ))

                        if len(puzzles) >= count:
                            random.shuffle(puzzles)
                            return puzzles[:count]

    random.shuffle(puzzles)
    return puzzles[:count]


def _get_bracket_arrangements_4():
    """
    Return bracket arrangement functions for 4 operands.
    Each takes (a, b, c, d, o1, o2, o3) and returns an expression string.
    """
    return [
        # ((a o1 b) o2 c) o3 d
        lambda a, b, c, d, o1, o2, o3: f"(({a}{o1}{b}){o2}{c}){o3}{d}",
        # (a o1 (b o2 c)) o3 d
        lambda a, b, c, d, o1, o2, o3: f"({a}{o1}({b}{o2}{c})){o3}{d}",
        # (a o1 b) o2 (c o3 d)
        lambda a, b, c, d, o1, o2, o3: f"({a}{o1}{b}){o2}({c}{o3}{d})",
        # a o1 ((b o2 c) o3 d)
        lambda a, b, c, d, o1, o2, o3: f"{a}{o1}(({b}{o2}{c}){o3}{d})",
        # a o1 (b o2 (c o3 d))
        lambda a, b, c, d, o1, o2, o3: f"{a}{o1}({b}{o2}({c}{o3}{d}))",
    ]


def _get_simple_bracket_arrangements_4():
    """
    Return single-level bracket arrangements for 4 operands (non-nested).
    """
    return [
        # (a o1 b) o2 c o3 d
        lambda a, b, c, d, o1, o2, o3: f"({a}{o1}{b}){o2}{c}{o3}{d}",
        # a o1 (b o2 c) o3 d
        lambda a, b, c, d, o1, o2, o3: f"{a}{o1}({b}{o2}{c}){o3}{d}",
        # a o1 b o2 (c o3 d)
        lambda a, b, c, d, o1, o2, o3: f"{a}{o1}{b}{o2}({c}{o3}{d})",
        # (a o1 b) o2 (c o3 d)
        lambda a, b, c, d, o1, o2, o3: f"({a}{o1}{b}){o2}({c}{o3}{d})",
    ]


def generate_level_6(level, count):
    """Level 6: Four operands (1-15), nested brackets + operators."""
    ops = ['+', '-', '*', '/']
    nested_arrangements = _get_bracket_arrangements_4()
    simple_arrangements = _get_simple_bracket_arrangements_4()
    puzzles = []
    seen = set()
    attempts = 0
    max_attempts = count * 500

    while len(puzzles) < count and attempts < max_attempts:
        attempts += 1
        a = random.randint(level.min_operand, level.max_operand)
        b = random.randint(level.min_operand, level.max_operand)
        c = random.randint(level.min_operand, level.max_operand)
        d = random.randint(level.min_operand, level.max_operand)
        o1, o2, o3 = [random.choice(ops) for _ in range(3)]
        arrangement = random.choice(nested_arrangements)

        expr = arrangement(a, b, c, d, o1, o2, o3)
        result = safe_eval(expr)
        if not is_non_negative_integer(result):
            continue
        target = int(result)
        if target > level.max_result or target <= 0:
            continue

        # Flat expression must NOT produce the same result
        flat_expr = f"{a}{o1}{b}{o2}{c}{o3}{d}"
        flat_result = safe_eval(flat_expr)
        if flat_result is not None and is_non_negative_integer(flat_result) and int(flat_result) == target:
            continue

        # Single-level brackets must NOT produce the same result (nested must be needed)
        simple_match = False
        for simple_arr in simple_arrangements:
            simple_expr = simple_arr(a, b, c, d, o1, o2, o3)
            simple_result = safe_eval(simple_expr)
            if simple_result is not None and is_non_negative_integer(simple_result) and int(simple_result) == target:
                simple_match = True
                break
        if simple_match:
            continue

        key = (a, b, c, d, target)
        if key in seen:
            continue
        seen.add(key)

        display = f"{a}  {b}  {c}  {d} = {target}"
        solution_display = expr.replace('*', 'x')
        puzzles.append(build_puzzle_dict(
            level, [a, b, c, d], target, display,
            f"{solution_display}={target}",
            has_multiple_solutions=True  # Assume multiple at this level
        ))

    return puzzles[:count]


GENERATORS = {
    1: generate_level_1,
    2: generate_level_2,
    3: generate_level_3,
    4: generate_level_4,
    5: generate_level_5,
    6: generate_level_6,
}


class Command(BaseCommand):
    help = 'Pre-generate number puzzles and store them in the database'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '--level', type=int,
            help='Level number (1-6) to generate puzzles for'
        )
        group.add_argument(
            '--all', action='store_true', dest='all_levels',
            help='Generate puzzles for all 6 levels'
        )
        parser.add_argument(
            '--count', type=int, default=500,
            help='Target number of puzzles to generate per level (default: 500)'
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete existing unreferenced puzzles before generating'
        )
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run',
            help='Show expected counts without writing to the database'
        )

    def handle(self, *args, **options):
        level_num = options.get('level')
        all_levels = options.get('all_levels')
        count = options['count']
        clear = options['clear']
        dry_run = options['dry_run']
        verbosity = options['verbosity']

        if not level_num and not all_levels:
            raise CommandError(
                'You must specify --level <number> or --all. '
                'Run with --help for usage.'
            )

        levels = NumberPuzzleLevel.objects.all()
        if not levels.exists():
            raise CommandError(
                'No puzzle levels found. Run: '
                'python manage.py loaddata puzzle_levels'
            )

        if level_num:
            if level_num < 1 or level_num > 6:
                raise CommandError(f'Invalid level: {level_num}. Must be 1-6')
            levels = levels.filter(number=level_num)
            if not levels.exists():
                raise CommandError(
                    f'Level {level_num} not found. Run: '
                    'python manage.py loaddata puzzle_levels'
                )

        total_generated = 0
        total_in_db = 0

        for level in levels:
            generator = GENERATORS.get(level.number)
            if not generator:
                self.stderr.write(f'No generator for level {level.number}, skipping.')
                continue

            existing_count = NumberPuzzle.objects.filter(level=level).count()

            if clear and not dry_run:
                # Only delete puzzles not referenced by attempts or session assignments
                unreferenced = NumberPuzzle.objects.filter(
                    level=level
                ).exclude(
                    attempts__isnull=False
                ).exclude(
                    session_assignments__isnull=False
                )
                deleted_count = unreferenced.count()
                unreferenced.delete()
                if verbosity >= 1:
                    self.stdout.write(
                        f'Level {level.number} ({level.name}): '
                        f'cleared {deleted_count} unreferenced puzzles'
                    )
                existing_count = NumberPuzzle.objects.filter(level=level).count()

            if existing_count >= count and not clear:
                if verbosity >= 1:
                    self.stdout.write(
                        f'Level {level.number} ({level.name}): '
                        f'already has {existing_count} puzzles (>= {count}), skipping'
                    )
                total_in_db += existing_count
                continue

            if dry_run:
                self.stdout.write(
                    f'Level {level.number} ({level.name}): '
                    f'would generate up to {count} puzzles '
                    f'({existing_count} already exist)'
                )
                continue

            if verbosity >= 1:
                self.stdout.write(
                    f'Level {level.number} ({level.name}): generating...'
                )

            puzzle_dicts = generator(level, count)

            if not puzzle_dicts:
                self.stdout.write(
                    self.style.WARNING(
                        f'Level {level.number} ({level.name}): '
                        f'no valid puzzles could be generated'
                    )
                )
                continue

            # Build model instances (without calling save() to skip per-row hash)
            puzzle_objects = [
                NumberPuzzle(**p) for p in puzzle_dicts
            ]

            created = NumberPuzzle.objects.bulk_create(
                puzzle_objects, ignore_conflicts=True
            )
            num_created = len(created)
            num_skipped = len(puzzle_dicts) - num_created

            final_count = NumberPuzzle.objects.filter(level=level).count()
            total_generated += num_created
            total_in_db += final_count

            if len(puzzle_dicts) < count:
                self.stdout.write(
                    self.style.WARNING(
                        f'Level {level.number} ({level.name}): '
                        f'only {len(puzzle_dicts)} valid puzzles possible, '
                        f'generated {num_created}'
                    )
                )
            elif verbosity >= 1:
                self.stdout.write(
                    f'Level {level.number} ({level.name}): '
                    f'{num_created} generated, {num_skipped} duplicates skipped, '
                    f'{final_count} total in DB'
                )

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Done. Total puzzles in database: {total_in_db}'
            ))
