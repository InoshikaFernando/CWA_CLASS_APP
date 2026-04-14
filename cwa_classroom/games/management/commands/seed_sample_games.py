"""
Management command: seed_sample_games

Creates three Game objects (Maths Cross Number, English Crossword, Science Crossword),
each with one Stage and one published Level, ready to play.

Safe to re-run — uses get_or_create throughout.
"""

from django.core.management.base import BaseCommand

from games.models import Game, Level, Stage


# ── Verified 3×3 Maths Cross Number ─────────────────────────────────────────
# Grid values:
#   1  2  5      Across: 1A=125, 4A=240, 5A=360
#   2  4  0      Down:   1D=123, 2D=246, 3D=500
#   3  6  0

MATHS_GRID = {
    "rows": 3,
    "cols": 3,
    "blocked": [],
    "clue_numbers": {"1": [0, 0], "2": [0, 1], "3": [0, 2], "4": [1, 0], "5": [2, 0]},
}

MATHS_CLUES = {
    "across": [
        {"number": "1", "text": "Five to the power of three",             "row": 0, "col": 0, "length": 3},
        {"number": "4", "text": "One hundred and twenty multiplied by two", "row": 1, "col": 0, "length": 3},
        {"number": "5", "text": "Degrees in a full turn",                  "row": 2, "col": 0, "length": 3},
    ],
    "down": [
        {"number": "1", "text": "The first three counting numbers in order", "row": 0, "col": 0, "length": 3},
        {"number": "2", "text": "Three consecutive even numbers: 2, 4, ___", "row": 0, "col": 1, "length": 3},
        {"number": "3", "text": "Five hundreds",                             "row": 0, "col": 2, "length": 3},
    ],
}

MATHS_ANSWERS = {
    "across": {"1": "125", "4": "240", "5": "360"},
    "down":   {"1": "123", "2": "246", "3": "500"},
}

# ── Verified 3×3 English Crossword ─────────────────────────────────────────
# Grid values:
#   T  O  N      Across: 1A=TON, 4A=OWE, 5A=PET
#   O  W  E      Down:   1D=TOP, 2D=OWE, 3D=NET
#   P  E  T

ENGLISH_GRID = {
    "rows": 3,
    "cols": 3,
    "blocked": [],
    "clue_numbers": {"1": [0, 0], "2": [0, 1], "3": [0, 2], "4": [1, 0], "5": [2, 0]},
}

ENGLISH_CLUES = {
    "across": [
        {"number": "1", "text": "A unit of weight (2000 pounds)",         "row": 0, "col": 0, "length": 3},
        {"number": "4", "text": "To be in debt to someone",               "row": 1, "col": 0, "length": 3},
        {"number": "5", "text": "A beloved animal companion kept at home", "row": 2, "col": 0, "length": 3},
    ],
    "down": [
        {"number": "1", "text": "The highest point; a spinning toy",       "row": 0, "col": 0, "length": 3},
        {"number": "2", "text": "To be indebted (same as 4 across)",       "row": 0, "col": 1, "length": 3},
        {"number": "3", "text": "Mesh used to catch fish or in tennis",    "row": 0, "col": 2, "length": 3},
    ],
}

ENGLISH_ANSWERS = {
    "across": {"1": "TON", "4": "OWE", "5": "PET"},
    "down":   {"1": "TOP", "2": "OWE", "3": "NET"},
}

# ── Verified 3×3 Science Crossword (same grid, science clues + passage) ─────
# Grid values same as English: TON / OWE / PET
# (Real science levels will be seeded in Sprint 4 via fixtures)

SCIENCE_PASSAGE = (
    "The Sun is a massive star at the centre of our Solar System. "
    "It produces energy through nuclear fusion. "
    "Scientists use units to measure the incredible forces and distances in space. "
    "A telescope is a key tool astronomers use to observe distant objects."
)

SCIENCE_CLUES = {
    "across": [
        {"number": "1", "text": "A metric unit of mass equal to 1000 kg",         "row": 0, "col": 0, "length": 3},
        {"number": "4", "text": "What scientists __ their discoveries to hard work", "row": 1, "col": 0, "length": 3},
        {"number": "5", "text": "An animal kept by a family (not always scientific!)", "row": 2, "col": 0, "length": 3},
    ],
    "down": [
        {"number": "1", "text": "The highest point of a mountain or graph",        "row": 0, "col": 0, "length": 3},
        {"number": "2", "text": "To be indebted (3 letters)",                     "row": 0, "col": 1, "length": 3},
        {"number": "3", "text": "A mesh used to filter or collect specimens",     "row": 0, "col": 2, "length": 3},
    ],
}

SCIENCE_ANSWERS = {
    "across": {"1": "TON", "4": "OWE", "5": "PET"},
    "down":   {"1": "TOP", "2": "OWE", "3": "NET"},
}


GAMES_DATA = [
    {
        "name": "Maths Cross Number",
        "slug": "maths-crossnumber",
        "game_type": "maths_crossnumber",
        "description": "Fill in the grid using maths clues — addition, subtraction, multiplication and more.",
        "stages": [
            {
                "name": "Number Forest",
                "theme": "forest",
                "order": 1,
                "description": "Start your journey in the Number Forest. Simple maths awaits!",
                "levels": [
                    {
                        "order": 1,
                        "title": "First Steps",
                        "difficulty": "easy",
                        "grid_data": MATHS_GRID,
                        "clues": MATHS_CLUES,
                        "answers": MATHS_ANSWERS,
                        "passage": None,
                        "status": "published",
                    }
                ],
            }
        ],
    },
    {
        "name": "English Crossword",
        "slug": "english-crossword",
        "game_type": "english_crossword",
        "description": "Sharpen your spelling and vocabulary with themed word puzzles and fun clues.",
        "stages": [
            {
                "name": "Word Meadow",
                "theme": "forest",
                "order": 1,
                "description": "A peaceful meadow full of everyday words. Start here!",
                "levels": [
                    {
                        "order": 1,
                        "title": "Everyday Words",
                        "difficulty": "easy",
                        "grid_data": ENGLISH_GRID,
                        "clues": ENGLISH_CLUES,
                        "answers": ENGLISH_ANSWERS,
                        "passage": None,
                        "status": "published",
                    }
                ],
            }
        ],
    },
    {
        "name": "Science Crossword",
        "slug": "science-crossword",
        "game_type": "science_crossword",
        "description": "Read a short passage then answer crossword clues — biology, space, physics and more.",
        "stages": [
            {
                "name": "Space Station",
                "theme": "space",
                "order": 1,
                "description": "Blast off into science! Read a passage and answer clues.",
                "levels": [
                    {
                        "order": 1,
                        "title": "Our Solar System",
                        "difficulty": "easy",
                        "grid_data": ENGLISH_GRID,
                        "clues": SCIENCE_CLUES,
                        "answers": SCIENCE_ANSWERS,
                        "passage": SCIENCE_PASSAGE,
                        "status": "published",
                    }
                ],
            }
        ],
    },
]


class Command(BaseCommand):
    help = "Seed sample games, stages, and levels for development."

    def handle(self, *args, **options):
        for gd in GAMES_DATA:
            game, g_created = Game.objects.get_or_create(
                slug=gd["slug"],
                defaults={
                    "name": gd["name"],
                    "game_type": gd["game_type"],
                    "description": gd["description"],
                    "is_active": True,
                },
            )
            if g_created:
                self.stdout.write(f"  Created game: {game.name}")
            else:
                self.stdout.write(f"  Game exists:  {game.name}")

            for sd in gd["stages"]:
                stage, s_created = Stage.objects.get_or_create(
                    game=game,
                    order=sd["order"],
                    defaults={
                        "name": sd["name"],
                        "theme": sd["theme"],
                        "description": sd["description"],
                        "is_active": True,
                    },
                )
                if s_created:
                    self.stdout.write(f"    Created stage: {stage.name}")

                for ld in sd["levels"]:
                    level, l_created = Level.objects.get_or_create(
                        game=game,
                        stage=stage,
                        order=ld["order"],
                        defaults={
                            "title": ld["title"],
                            "difficulty": ld["difficulty"],
                            "grid_data": ld["grid_data"],
                            "clues": ld["clues"],
                            "answers": ld["answers"],
                            "passage": ld["passage"],
                            "status": ld["status"],
                        },
                    )
                    if l_created:
                        self.stdout.write(f"      Created level: {level}")

        self.stdout.write(self.style.SUCCESS("Done."))
