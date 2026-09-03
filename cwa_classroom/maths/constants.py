# Which times tables a year may practise, for both multiplication and division.
#
# THIS IS THE ONLY COPY. There used to be a second one in ``quiz/views.py``, and
# the two had drifted: Year 4 read 1-10 here and 1-15 there, and Year 6 was
# missing from this dict entirely, so it fell through a ``.get(year, 1-15)``
# default and quietly offered a nine-year-old every table up to fifteen. The
# live page read the quiz copy, so editing this one changed nothing — which is
# the sort of edit that looks applied and is not.
#
# Each table generates questions up to X x 12.
TIMES_TABLES_BY_YEAR = {
    1: [1],
    2: [1, 2],
    3: [1, 2, 5, 10],
    4: [1, 2, 3, 4, 5, 6, 7, 10],
    5: list(range(1, 13)),
    6: list(range(1, 13)),
    7: list(range(1, 15)),
    8: list(range(1, 15)),
    9: list(range(1, 15)),
    10: list(range(1, 15)),
}

#: The highest table any year reaches. Derived, not typed: the picker draws a
#: tile per table and greys the locked ones, and a hard-coded ceiling above this
#: puts a tile on every page that no year can ever unlock.
MAX_TIMES_TABLE = max(t for tables in TIMES_TABLES_BY_YEAR.values() for t in tables)


def times_tables_for_year(year):
    """The tables a student in *year* may practise.

    A year the dict does not name falls back to the SENIOR list, not to
    everything. The old default was ``list(range(1, 16))``, which meant an
    unmapped year — Year 6 was one, by omission — silently got more than any
    mapped year above it. Falling back to the top of the ladder is the same
    rule the curriculum states as "Year 7 onwards".
    """
    if year in TIMES_TABLES_BY_YEAR:
        return TIMES_TABLES_BY_YEAR[year]
    return TIMES_TABLES_BY_YEAR[max(TIMES_TABLES_BY_YEAR)]

# Year-to-topics mapping for dashboard display and question loading.
# Maps year number to list of (topic_name, url_name, display_name).
# This is the single source of truth used by views.py and add_questions_from_json.py.
YEAR_TOPICS_MAP = {
    1: [
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
    ],
    2: [
        ("Measurements", "measurements_questions", "Measurements"),
        ("Place Values", "place_values_questions", "Place Values"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
    ],
    3: [
        ("Measurements", "measurements_questions", "Measurements"),
        ("Fractions", "fractions_questions", "Fractions"),
        ("Finance", "finance_questions", "Finance"),
        ("Date and Time", "date_time_questions", "Date and Time"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
    ],
    4: [
        ("Fractions", "fractions_questions", "Fractions"),
        ("Integers", "integers_questions", "Integers"),
        ("Place Values", "place_values_questions", "Place Values"),
        ("Factors", "factors_questions", "Factors"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
        ("Long Division", "long_division_selection", "Long Division"),
    ],
    5: [
        ("Measurements", "measurements_questions", "Measurements"),
        ("BODMAS/PEMDAS", "bodmas_questions", "BODMAS/PEMDAS"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
        ("Long Division", "long_division_selection", "Long Division"),
    ],
    6: [
        ("Measurements", "measurements_questions", "Measurements"),
        ("BODMAS/PEMDAS", "bodmas_questions", "BODMAS/PEMDAS"),
        ("Whole Numbers", "whole_numbers_questions", "Whole Numbers"),
        ("Factors", "factors_questions", "Factors"),
        ("Angles", "angles_questions", "Angles"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
        ("Long Division", "long_division_selection", "Long Division"),
    ],
    7: [
        ("Measurements", "measurements_questions", "Measurements"),
        ("BODMAS/PEMDAS", "bodmas_questions", "BODMAS/PEMDAS"),
        ("Integers", "integers_questions", "Integers"),
        ("Factors", "factors_questions", "Factors"),
        ("Fractions", "fractions_questions", "Fractions"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
        ("Long Division", "long_division_selection", "Long Division"),
    ],
    8: [
        ("Trigonometry", "trigonometry_questions", "Trigonometry"),
        ("Integers", "integers_questions", "Integers"),
        ("Factors", "factors_questions", "Factors"),
        ("Fractions", "fractions_questions", "Fractions"),
        ("Multiplication", "multiplication_selection", "Multiplication"),
        ("Division", "division_selection", "Division"),
        ("Long Division", "long_division_selection", "Long Division"),
    ],
    # Year 10 strands are seeded as placeholders (see classroom migration
    # 0101); question-page topics are added later via the admin.
    10: [],
}
