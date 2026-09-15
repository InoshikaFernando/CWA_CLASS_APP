"""
Management command: create_crossword

Generates a crossword puzzle from a word+clue list and creates a
LanguageExercise of type 'crossword'.

Usage:
    python manage.py create_crossword \\
        --lang en \\
        --topic "Animals" \\
        --level beginner \\
        --title "Animal Kingdom" \\
        --points 10 \\
        --words "CAT=A small domestic pet,DOG=Man's best friend,RAT=A small rodent,BAT=A flying mammal,ANT=A tiny insect"

Word format: WORD=clue  (comma-separated pairs)
"""

import random
import unicodedata
from django.core.management.base import BaseCommand, CommandError
from languages.models import Language, LanguageTopic, LanguageTopicLevel, LanguageExercise


# ---------------------------------------------------------------------------
# Crossword layout generator (greedy backtracker)
# ---------------------------------------------------------------------------

def _nfc(s):
    return unicodedata.normalize('NFC', s)


def _chars(word):
    """Split word into a list of grapheme clusters (handles non-Latin)."""
    return list(_nfc(word))


def _build_grid(width, height):
    return [[None] * width for _ in range(height)]


def _place_word(grid, word_chars, row, col, direction, width, height):
    """Try to place word_chars on grid. Returns True if successful."""
    cells = []
    for i, ch in enumerate(word_chars):
        r = row + (i if direction == 'down' else 0)
        c = col + (i if direction == 'across' else 0)
        if r < 0 or r >= height or c < 0 or c >= width:
            return False
        existing = grid[r][c]
        if existing is not None and existing != ch:
            return False
        cells.append((r, c, ch))
    for r, c, ch in cells:
        grid[r][c] = ch
    return True


def _count_intersections(grid, word_chars, row, col, direction, width, height):
    """Count how many cells of this placement intersect existing letters."""
    count = 0
    for i, ch in enumerate(word_chars):
        r = row + (i if direction == 'down' else 0)
        c = col + (i if direction == 'across' else 0)
        if 0 <= r < height and 0 <= c < width and grid[r][c] == ch:
            count += 1
    return count


def _adjacent_conflict(grid, word_chars, row, col, direction, width, height):
    """Return True if placing the word creates unintended adjacent letter conflicts."""
    length = len(word_chars)
    if direction == 'across':
        # Check left of start and right of end
        if col > 0 and grid[row][col - 1] is not None:
            return True
        if col + length < width and grid[row][col + length] is not None:
            return True
        # Check above/below each cell that isn't an intersection
        for i, ch in enumerate(word_chars):
            c = col + i
            if grid[row][c] is None:  # new cell being placed
                if row > 0 and grid[row - 1][c] is not None:
                    return True
                if row + 1 < height and grid[row + 1][c] is not None:
                    return True
    else:  # down
        if row > 0 and grid[row - 1][col] is not None:
            return True
        if row + length < height and grid[row + length][col] is not None:
            return True
        for i, ch in enumerate(word_chars):
            r = row + i
            if grid[r][col] is None:
                if col > 0 and grid[r][col - 1] is not None:
                    return True
                if col + 1 < width and grid[r][col + 1] is not None:
                    return True
    return False


def generate_crossword(word_clue_pairs, max_tries=800):
    """
    Given [(word, clue), ...], return puzzle_data dict or None if layout fails.
    Words are uppercased for Latin scripts; NFC-normalized for all scripts.
    """
    if not word_clue_pairs:
        return None

    # Normalize words
    pairs = [(_nfc(w.upper() if w.isascii() else w), c) for w, c in word_clue_pairs]
    pairs.sort(key=lambda p: len(_chars(p[0])), reverse=True)

    best = None
    best_placed = 0

    for attempt in range(max_tries):
        # Shuffle all but the first (longest) word
        shuffled = [pairs[0]] + random.sample(pairs[1:], len(pairs) - 1)
        first_chars = _chars(shuffled[0][0])

        # Grid is generous: 2× longest word in each dimension
        size = max(20, len(first_chars) * 2 + 4)
        width = height = size
        grid = _build_grid(width, height)
        placed = []

        # Place first word horizontally at centre
        start_r = height // 2
        start_c = (width - len(first_chars)) // 2
        _place_word(grid, first_chars, start_r, start_c, 'across', width, height)
        placed.append({
            'index': 0,
            'word': shuffled[0][0],
            'clue': shuffled[0][1],
            'direction': 'across',
            'row': start_r,
            'col': start_c,
        })

        for word_str, clue in shuffled[1:]:
            wchars = _chars(word_str)
            candidates = []

            for placed_info in placed:
                pw      = placed_info['word']
                pchars  = _chars(pw)
                pd      = placed_info['direction']
                pr      = placed_info['row']
                pc      = placed_info['col']
                new_dir = 'down' if pd == 'across' else 'across'

                for pi, pch in enumerate(pchars):
                    for wi, wch in enumerate(wchars):
                        if pch != wch:
                            continue
                        if new_dir == 'down':
                            r = pr - wi
                            c = pc + pi
                        else:
                            r = pr + pi
                            c = pc - wi

                        if (r < 1 or r + len(wchars) > height - 1 or
                                c < 1 or c + len(wchars) > width - 1):
                            continue

                        intersections = _count_intersections(
                            grid, wchars, r, c, new_dir, width, height)
                        if intersections == 0:
                            continue

                        test_grid = [row[:] for row in grid]
                        if not _place_word(test_grid, wchars, r, c, new_dir, width, height):
                            continue
                        if _adjacent_conflict(grid, wchars, r, c, new_dir, width, height):
                            continue

                        candidates.append((intersections, r, c, new_dir))

            if not candidates:
                continue

            candidates.sort(key=lambda x: -x[0])
            _, best_r, best_c, best_dir = candidates[0]
            _place_word(grid, wchars, best_r, best_c, best_dir, width, height)
            placed.append({
                'index': len(placed),
                'word': word_str,
                'clue': clue,
                'direction': best_dir,
                'row': best_r,
                'col': best_c,
            })

        if len(placed) > best_placed:
            best_placed = len(placed)
            best = (grid, placed, width, height)
            if best_placed == len(pairs):
                break

    if not best:
        return None

    grid, placed, width, height = best

    # Crop grid to bounding box
    used_rows = [p['row'] + len(_chars(p['word'])) - 1
                 if p['direction'] == 'down' else p['row'] for p in placed]
    used_rows += [p['row'] for p in placed]
    used_cols = [p['col'] + len(_chars(p['word'])) - 1
                 if p['direction'] == 'across' else p['col'] for p in placed]
    used_cols += [p['col'] for p in placed]

    min_r = max(0, min(used_rows) - 1)
    max_r = min(height - 1, max(used_rows) + 1)
    min_c = max(0, min(used_cols) - 1)
    max_c = min(width - 1, max(used_cols) + 1)

    new_height = max_r - min_r + 1
    new_width  = max_c - min_c + 1

    # Assign word numbers (top-to-bottom, left-to-right order)
    placed.sort(key=lambda p: (p['row'] - min_r, p['col'] - min_c))
    word_number = 1
    number_map  = {}
    for p in placed:
        coord = (p['row'] - min_r, p['col'] - min_c)
        if coord not in number_map:
            number_map[coord] = word_number
            word_number += 1
        p['number'] = number_map[coord]

    words_out = []
    for i, p in enumerate(placed):
        words_out.append({
            'index':     i,
            'number':    p['number'],
            'direction': p['direction'],
            'row':       p['row'] - min_r,
            'col':       p['col'] - min_c,
            'answer':    p['word'],
            'clue':      p['clue'],
        })

    return {
        'width':  new_width,
        'height': new_height,
        'words':  words_out,
    }


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Create a crossword exercise from a word+clue list'

    def add_arguments(self, parser):
        parser.add_argument('--lang',   required=True, help='Language code (e.g. en, si, ta)')
        parser.add_argument('--topic',  required=True, help='Topic name (created if missing)')
        parser.add_argument('--level',  default='beginner',
                            choices=['beginner', 'intermediate', 'advanced'])
        parser.add_argument('--title',  default='Crossword',
                            help='Exercise prompt / title shown to students')
        parser.add_argument('--points', type=int, default=10)
        parser.add_argument('--words',  required=True,
                            help='Comma-separated WORD=clue pairs')
        parser.add_argument('--tries',  type=int, default=800,
                            help='Max layout attempts (default 800)')

    def handle(self, *args, **options):
        lang_code = options['lang']
        try:
            language = Language.objects.get(code=lang_code)
        except Language.DoesNotExist:
            raise CommandError(f'Language "{lang_code}" not found. Create it via admin first.')

        topic, _ = LanguageTopic.objects.get_or_create(
            language=language,
            name=options['topic'],
            defaults={'order': 99, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic,
            level_choice=options['level'],
        )

        raw_words = options['words']
        pairs = []
        for part in raw_words.split(','):
            part = part.strip()
            if '=' not in part:
                self.stderr.write(f'Skipping malformed entry (no =): {part!r}')
                continue
            word, clue = part.split('=', 1)
            word = word.strip()
            clue = clue.strip()
            if word and clue:
                pairs.append((word, clue))

        if len(pairs) < 2:
            raise CommandError('Need at least 2 valid WORD=clue pairs.')

        self.stdout.write(f'Generating layout for {len(pairs)} words...')
        puzzle_data = generate_crossword(pairs, max_tries=options['tries'])

        if not puzzle_data:
            raise CommandError(
                'Could not generate a valid crossword layout. '
                'Try fewer words, or words with more shared letters.'
            )

        placed = len(puzzle_data['words'])
        if placed < len(pairs):
            self.stdout.write(self.style.WARNING(
                f'Only {placed}/{len(pairs)} words placed. Others had no valid intersection.'
            ))

        exercise = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.CROSSWORD,
            prompt=options['title'],
            points=options['points'],
            puzzle_data=puzzle_data,
            is_active=True,
        )

        self.stdout.write(self.style.SUCCESS(
            f'\nCreated crossword exercise pk={exercise.pk}\n'
            f'  Title:  {exercise.prompt}\n'
            f'  Words:  {placed} placed ({puzzle_data["width"]}×{puzzle_data["height"]} grid)\n'
            f'  URL:    /languages/exercise/{exercise.pk}/\n'
        ))
