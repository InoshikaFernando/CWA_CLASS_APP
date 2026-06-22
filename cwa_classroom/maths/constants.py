# Times tables available per year for Multiplication and Division topics.
# Edit this dict to change which times tables are available for each year.
# Each times table generates questions up to X * 12.
TIMES_TABLES_BY_YEAR = {
    1: [1],
    2: [1, 2, 10],
    3: [1, 2, 3, 4, 5, 10],
    4: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    5: list(range(1, 16)),
    7: list(range(1, 16)),
    8: list(range(1, 16)),
    9: list(range(1, 16)),
    10: list(range(1, 16)),
}

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
