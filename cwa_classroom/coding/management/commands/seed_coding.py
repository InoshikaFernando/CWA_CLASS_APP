"""
Management command: seed_coding
================================
Creates the initial CodingLanguage, CodingTopic, CodingExercise,
CodingProblem, and ProblemTestCase records.

Usage:
    python manage.py seed_coding            # create missing records only
    python manage.py seed_coding --reset    # wipe all coding data first, then seed
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from coding.models import (
    CodingLanguage,
    CodingTopic,
    CodingExercise,
    CodingProblem,
    ProblemTestCase,
)


# ---------------------------------------------------------------------------
# Language definitions
# ---------------------------------------------------------------------------

LANGUAGES = [
    {
        'name': 'Python',
        'slug': 'python',
        'description': 'A beginner-friendly, readable language used in data science, automation, and web development.',
        'icon_name': 'code-bracket',
        'color': '#3b82f6',   # blue-500
        'order': 1,
    },
    {
        'name': 'JavaScript',
        'slug': 'javascript',
        'description': 'The language of the web — runs in every browser and powers interactive websites.',
        'icon_name': 'code-bracket',
        'color': '#f59e0b',   # amber-500
        'order': 2,
    },
    {
        'name': 'HTML',
        'slug': 'html',
        'description': 'Build the structure and content of web pages with the markup language of the internet.',
        'icon_name': 'code-bracket',
        'color': '#e34f26',   # HTML orange
        'order': 3,
    },
    {
        'name': 'CSS',
        'slug': 'css',
        'description': 'Style and design web pages with colours, fonts, layouts, and animations.',
        'icon_name': 'code-bracket',
        'color': '#264de4',   # CSS blue
        'order': 4,
    },
    {
        'name': 'Scratch',
        'slug': 'scratch',
        'description': 'A visual block-based language perfect for learning programming fundamentals.',
        'icon_name': 'code-bracket',
        'color': '#f97316',   # orange-500
        'order': 5,
    },
]


# ---------------------------------------------------------------------------
# Topics per language  { lang_slug: [ {name, description, order} ] }
# ---------------------------------------------------------------------------

TOPICS = {
    'python': [
        {'name': 'Variables & Data Types', 'description': 'Store and work with different kinds of data.', 'order': 1},
        {'name': 'If Conditions',           'description': 'Make decisions in your code with if/elif/else.', 'order': 2},
        {'name': 'Loops',                   'description': 'Repeat actions with for and while loops.', 'order': 3},
        {'name': 'Functions',               'description': 'Write reusable blocks of code.', 'order': 4},
        {'name': 'Lists',                   'description': 'Work with ordered collections of items.', 'order': 5},
        {'name': 'Dictionaries',            'description': 'Store and look up data using key-value pairs.', 'order': 6},
        {'name': 'String Manipulation',     'description': 'Slice, format, and transform text.', 'order': 7},
    ],
    'javascript': [
        {'name': 'Variables & Data Types', 'description': 'let, const, and JavaScript data types.', 'order': 1},
        {'name': 'If Conditions',           'description': 'Branching logic with if/else and ternary.', 'order': 2},
        {'name': 'Loops',                   'description': 'for, while, and array iteration.', 'order': 3},
        {'name': 'Functions',               'description': 'Regular functions and arrow functions.', 'order': 4},
        {'name': 'Arrays',                  'description': 'Create and manipulate arrays.', 'order': 5},
        {'name': 'Objects',                 'description': 'Work with JavaScript objects and properties.', 'order': 6},
        {'name': 'DOM Basics',              'description': 'Select and update elements on a web page.', 'order': 7},
    ],
    'html': [
        {'name': 'HTML Structure',   'description': 'Tags, elements, and building a page skeleton.', 'order': 1},
        {'name': 'Text & Links',     'description': 'Headings, paragraphs, and anchor tags.', 'order': 2},
        {'name': 'Images & Media',   'description': 'Embed images, video, and audio.', 'order': 3},
        {'name': 'Forms',            'description': 'Build HTML forms with inputs, labels, and buttons.', 'order': 4},
        {'name': 'Tables',           'description': 'Create structured data with HTML tables.', 'order': 5},
    ],
    'css': [
        {'name': 'CSS Basics',        'description': 'Selectors, colours, fonts, and spacing.', 'order': 1},
        {'name': 'CSS Layout',        'description': 'Flexbox and Grid for page layout.', 'order': 2},
        {'name': 'CSS Animations',    'description': 'Add motion and transitions to elements.', 'order': 3},
        {'name': 'Responsive Design', 'description': 'Make pages look great on all screen sizes with media queries.', 'order': 4},
    ],
    'scratch': [
        {'name': 'Motion & Looks',   'description': 'Move sprites and change how they look.', 'order': 1},
        {'name': 'Events',           'description': 'Trigger scripts with key presses and clicks.', 'order': 2},
        {'name': 'Control',          'description': 'Loops, waits, and if/else blocks.', 'order': 3},
        {'name': 'Variables',        'description': 'Store and change values.', 'order': 4},
        {'name': 'Sound',            'description': 'Play sounds and music in your project.', 'order': 5},
    ],
}


# ---------------------------------------------------------------------------
# Exercises per topic  { (lang_slug, topic_name): [ exercise dict ] }
# ---------------------------------------------------------------------------

EXERCISES = {

    # ── Python — Variables & Data Types ────────────────────────────────────
    ('python', 'Variables & Data Types'): [
        {
            'level': 'beginner',
            'title': 'Hello, World!',
            'description': 'Write a Python program that prints exactly:\nHello, World!',
            'starter_code': '# Write your code below\n',
            'expected_output': 'Hello, World!',
            'hints': 'Use the print() function.',
            'order': 1,
        },
        {
            'level': 'beginner',
            'title': 'Store Your Name',
            'description': 'Create a variable called name and assign it your first name.\nThen print: Hello, <name>!',
            'starter_code': '# Create a variable called name\nname = \n\n# Print the greeting\n',
            'expected_output': '',
            'hints': 'Use an f-string: print(f"Hello, {name}!")',
            'order': 2,
        },
        {
            'level': 'intermediate',
            'title': 'Type Inspector',
            'description': 'Create four variables:\n- an integer called age (value: 16)\n- a float called height (value: 1.75)\n- a string called city (value: "Auckland")\n- a boolean called is_student (value: True)\n\nPrint the type of each variable on a separate line.',
            'starter_code': '# Create your variables here\n\n\n# Print each type\n',
            'expected_output': "<class 'int'>\n<class 'float'>\n<class 'str'>\n<class 'bool'>",
            'hints': 'Use the type() function: print(type(age))',
            'order': 3,
        },
        {
            'level': 'advanced',
            'title': 'Type Casting',
            'description': 'You are given:\n  x = "42"\n  y = "3.14"\n\nConvert x to an integer and y to a float.\nPrint their sum as a float.',
            'starter_code': 'x = "42"\ny = "3.14"\n\n# Convert and print the sum\n',
            'expected_output': '45.14',
            'hints': 'Use int() and float() to cast. The result should be 45.14.',
            'order': 4,
        },
    ],

    # ── Python — If Conditions ───────────────────────────────────────────────
    ('python', 'If Conditions'): [
        {
            'level': 'beginner',
            'title': 'Positive or Negative',
            'description': 'Write a program that checks if the number 7 is positive or negative.\nPrint "Positive" if it is greater than 0, otherwise print "Negative".',
            'starter_code': 'number = 7\n\n# Check and print\n',
            'expected_output': 'Positive',
            'hints': 'Use if number > 0:',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'Grade Calculator',
            'description': 'Given score = 72, print the grade using this scale:\n90-100 → A\n80-89  → B\n70-79  → C\n60-69  → D\nBelow 60 → F',
            'starter_code': 'score = 72\n\n# Determine and print the grade\n',
            'expected_output': 'C',
            'hints': 'Use elif for each range. Check from highest to lowest.',
            'order': 2,
        },
        {
            'level': 'advanced',
            'title': 'Leap Year',
            'description': 'Given year = 2024, determine if it is a leap year.\nA year is a leap year if:\n- It is divisible by 4 AND\n- It is NOT divisible by 100, OR it IS divisible by 400\n\nPrint "Leap year" or "Not a leap year".',
            'starter_code': 'year = 2024\n\n# Check and print\n',
            'expected_output': 'Leap year',
            'hints': 'Use the % (modulo) operator. Combine conditions with and/or.',
            'order': 3,
        },
    ],

    # ── Python — Loops ──────────────────────────────────────────────────────
    ('python', 'Loops'): [
        {
            'level': 'beginner',
            'title': 'Count to 5',
            'description': 'Use a for loop to print the numbers 1 to 5, each on a new line.',
            'starter_code': '# Use a for loop\n',
            'expected_output': '1\n2\n3\n4\n5',
            'hints': 'Use range(1, 6) to get numbers 1 through 5.',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'Sum of a List',
            'description': 'Given numbers = [4, 8, 15, 16, 23, 42], use a loop to calculate the total.\nPrint the total.',
            'starter_code': 'numbers = [4, 8, 15, 16, 23, 42]\ntotal = 0\n\n# Loop and sum\n\nprint(total)\n',
            'expected_output': '108',
            'hints': 'Add each number to total inside the loop.',
            'order': 2,
        },
        {
            'level': 'advanced',
            'title': 'FizzBuzz',
            'description': 'Print numbers 1 to 20.\n- If divisible by 3, print "Fizz" instead.\n- If divisible by 5, print "Buzz" instead.\n- If divisible by both 3 and 5, print "FizzBuzz".',
            'starter_code': '# FizzBuzz from 1 to 20\n',
            'expected_output': '1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n16\n17\nFizz\n19\nBuzz',
            'hints': 'Check the FizzBuzz condition first (divisible by both), then Fizz, then Buzz.',
            'order': 3,
        },
    ],

    # ── Python — Functions ──────────────────────────────────────────────────
    ('python', 'Functions'): [
        {
            'level': 'beginner',
            'title': 'Greet Function',
            'description': 'Define a function called greet that takes a name as a parameter.\nIt should print: Hello, <name>!\n\nCall it with greet("Alex").',
            'starter_code': 'def greet(name):\n    # Write your code here\n    pass\n\ngreet("Alex")\n',
            'expected_output': 'Hello, Alex!',
            'hints': 'Use print(f"Hello, {name}!") inside the function.',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'Square Function',
            'description': 'Write a function called square that takes a number and returns its square.\nPrint the result of square(9).',
            'starter_code': 'def square(n):\n    # Return the square of n\n    pass\n\nprint(square(9))\n',
            'expected_output': '81',
            'hints': 'Use return n * n or return n ** 2',
            'order': 2,
        },
        {
            'level': 'advanced',
            'title': 'Factorial',
            'description': 'Write a recursive function called factorial(n) that returns n!\n\nPrint factorial(5).',
            'starter_code': 'def factorial(n):\n    # Base case: factorial(0) = 1\n    # Recursive case\n    pass\n\nprint(factorial(5))\n',
            'expected_output': '120',
            'hints': 'Base case: if n == 0, return 1. Recursive: return n * factorial(n - 1)',
            'order': 3,
        },
    ],

    # ── JavaScript — Variables & Data Types ─────────────────────────────────
    ('javascript', 'Variables & Data Types'): [
        {
            'level': 'beginner',
            'title': 'Hello from JS',
            'description': 'Write a JavaScript program that prints:\nHello from JavaScript!',
            'starter_code': '// Write your code below\n',
            'expected_output': 'Hello from JavaScript!',
            'hints': 'Use console.log()',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'const vs let',
            'description': 'Create:\n- A const called PI with value 3.14159\n- A let called radius with value 5\n\nPrint the area of the circle (PI * radius * radius).\nRound to 2 decimal places.',
            'starter_code': '// Declare your variables\n\n\n// Print the area\n',
            'expected_output': '78.54',
            'hints': 'Use (PI * radius * radius).toFixed(2) to round.',
            'order': 2,
        },
    ],

    # ── JavaScript — Loops ──────────────────────────────────────────────────
    ('javascript', 'Loops'): [
        {
            'level': 'beginner',
            'title': 'Count to 5',
            'description': 'Use a for loop to print numbers 1 to 5, each on a new line.',
            'starter_code': '// Use a for loop\n',
            'expected_output': '1\n2\n3\n4\n5',
            'hints': 'for (let i = 1; i <= 5; i++)',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'Array Sum',
            'description': 'Given const numbers = [4, 8, 15, 16, 23, 42];\nUse a loop to calculate and print the total.',
            'starter_code': 'const numbers = [4, 8, 15, 16, 23, 42];\nlet total = 0;\n\n// Loop and sum\n\nconsole.log(total);\n',
            'expected_output': '108',
            'hints': 'Use a for...of loop or a standard for loop.',
            'order': 2,
        },
    ],

    # ── HTML — HTML Structure ────────────────────────────────────────────────
    ('html', 'HTML Structure'): [
        {
            'level': 'beginner',
            'title': 'My First Page',
            'description': 'Create a basic HTML page with:\n- A proper <!DOCTYPE html> declaration\n- <html>, <head>, and <body> tags\n- A <title> of "My Page"\n- An <h1> heading: Welcome to My Page',
            'starter_code': '<!DOCTYPE html>\n<html>\n  <head>\n    <!-- Add your title here -->\n  </head>\n  <body>\n    <!-- Add your heading here -->\n  </body>\n</html>\n',
            'expected_output': '',
            'hints': 'Use <title>My Page</title> in the head. Use <h1>Welcome to My Page</h1> in the body.',
            'order': 1,
        },
        {
            'level': 'intermediate',
            'title': 'Semantic Layout',
            'description': 'Build a page using semantic HTML5 tags:\n- <header> containing a <nav>\n- <main> containing an <article> with a heading and paragraph\n- <footer> with copyright text',
            'starter_code': '<!DOCTYPE html>\n<html>\n<head><title>Semantic Page</title></head>\n<body>\n  <!-- Build your layout here -->\n</body>\n</html>\n',
            'expected_output': '',
            'hints': 'Semantic tags: header, nav, main, article, section, footer.',
            'order': 2,
        },
    ],

    # ── CSS — CSS Basics ────────────────────────────────────────────────────
    ('css', 'CSS Basics'): [
        {
            'level': 'beginner',
            'title': 'Style a Heading',
            'description': 'Create an h1 that says "Hello CSS!" and style it so it:\n- Has colour: #7c3aed (violet)\n- Is centre-aligned\n- Has font-size: 2rem',
            'starter_code': '<!DOCTYPE html>\n<html>\n<head>\n  <style>\n    /* Write your CSS here */\n  </style>\n</head>\n<body>\n  <h1>Hello CSS!</h1>\n</body>\n</html>\n',
            'expected_output': '',
            'hints': 'Target the h1 element: h1 { color: #7c3aed; text-align: center; font-size: 2rem; }',
            'order': 1,
        },
    ],
}


# ---------------------------------------------------------------------------
# Algorithm problems  (with test cases)
# ---------------------------------------------------------------------------

PROBLEMS = [

    # ── Python Problems ─────────────────────────────────────────────────────
    {
        'language': 'python',
        'title': 'Reverse a String',
        'description': (
            'Write a Python program that reads a single line of input and prints it reversed.\n\n'
            'Input: A single string\n'
            'Output: The string reversed\n\n'
            'Example:\n  Input:  hello\n  Output: olleh'
        ),
        'starter_code': 's = input()\n# Print the reversed string\n',
        'difficulty': 1,
        'test_cases': [
            {'input': 'hello',    'expected': 'olleh',     'visible': True,  'description': 'Basic word'},
            {'input': 'Python',   'expected': 'nohtyP',    'visible': True,  'description': 'Mixed case'},
            {'input': 'racecar',  'expected': 'racecar',   'visible': False, 'description': 'Palindrome'},
            {'input': 'a',        'expected': 'a',         'visible': False, 'description': 'Single character'},
            {'input': '12345',    'expected': '54321',     'visible': False, 'description': 'Digits only'},
        ],
    },
    {
        'language': 'python',
        'title': 'Sum of Digits',
        'description': (
            'Read a positive integer and print the sum of its digits.\n\n'
            'Example:\n  Input:  1234\n  Output: 10'
        ),
        'starter_code': 'n = input()\n# Print the sum of digits\n',
        'difficulty': 1,
        'test_cases': [
            {'input': '1234',  'expected': '10',  'visible': True,  'description': 'Four digits'},
            {'input': '99',    'expected': '18',  'visible': True,  'description': 'Two nines'},
            {'input': '0',     'expected': '0',   'visible': False, 'description': 'Zero'},
            {'input': '100',   'expected': '1',   'visible': False, 'description': 'Trailing zeros'},
            {'input': '9999',  'expected': '36',  'visible': False, 'description': 'All nines'},
        ],
    },
    {
        'language': 'python',
        'title': 'Count Vowels',
        'description': (
            'Read a word and print the number of vowels it contains (a, e, i, o, u — case-insensitive).\n\n'
            'Example:\n  Input:  Education\n  Output: 5'
        ),
        'starter_code': 'word = input()\n# Print the number of vowels\n',
        'difficulty': 2,
        'test_cases': [
            {'input': 'Education', 'expected': '5',  'visible': True,  'description': 'Mixed case word'},
            {'input': 'hello',     'expected': '2',  'visible': True,  'description': 'Lowercase'},
            {'input': 'rhythm',    'expected': '0',  'visible': False, 'description': 'No vowels'},
            {'input': 'AEIOU',     'expected': '5',  'visible': False, 'description': 'All uppercase vowels'},
            {'input': 'a',         'expected': '1',  'visible': False, 'description': 'Single vowel'},
        ],
    },
    {
        'language': 'python',
        'title': 'Fibonacci Sequence',
        'description': (
            'Read a number n and print the first n numbers of the Fibonacci sequence, space-separated.\n\n'
            'The sequence starts: 0 1 1 2 3 5 8 13 …\n\n'
            'Example:\n  Input:  7\n  Output: 0 1 1 2 3 5 8'
        ),
        'starter_code': 'n = int(input())\n# Print first n Fibonacci numbers, space-separated\n',
        'difficulty': 3,
        'test_cases': [
            {'input': '7',  'expected': '0 1 1 2 3 5 8',       'visible': True,  'description': 'First 7'},
            {'input': '1',  'expected': '0',                   'visible': True,  'description': 'Only first'},
            {'input': '2',  'expected': '0 1',                 'visible': False, 'description': 'First two'},
            {'input': '10', 'expected': '0 1 1 2 3 5 8 13 21 34', 'visible': False, 'description': 'First ten'},
        ],
    },
    {
        'language': 'python',
        'title': 'Find the Maximum',
        'description': (
            'Read a line of space-separated integers and print the largest one.\n\n'
            'Example:\n  Input:  3 1 4 1 5 9 2 6\n  Output: 9'
        ),
        'starter_code': 'numbers = list(map(int, input().split()))\n# Print the maximum\n',
        'difficulty': 2,
        'test_cases': [
            {'input': '3 1 4 1 5 9 2 6',  'expected': '9',   'visible': True,  'description': 'Mixed numbers'},
            {'input': '10 20 30',          'expected': '30',  'visible': True,  'description': 'Ascending'},
            {'input': '-5 -1 -10',         'expected': '-1',  'visible': False, 'description': 'All negatives'},
            {'input': '42',                'expected': '42',  'visible': False, 'description': 'Single number'},
            {'input': '0 0 0',             'expected': '0',   'visible': False, 'description': 'All zeros'},
        ],
    },
    {
        'language': 'python',
        'title': 'Is Palindrome',
        'description': (
            'Read a word and print "Yes" if it is a palindrome, "No" otherwise.\n'
            'Ignore case.\n\n'
            'Example:\n  Input:  Racecar\n  Output: Yes'
        ),
        'starter_code': 'word = input()\n# Print Yes or No\n',
        'difficulty': 2,
        'test_cases': [
            {'input': 'Racecar',  'expected': 'Yes', 'visible': True,  'description': 'Mixed case palindrome'},
            {'input': 'hello',    'expected': 'No',  'visible': True,  'description': 'Not palindrome'},
            {'input': 'a',        'expected': 'Yes', 'visible': False, 'description': 'Single char'},
            {'input': 'Madam',    'expected': 'Yes', 'visible': False, 'description': 'Classic palindrome'},
            {'input': 'Python',   'expected': 'No',  'visible': False, 'description': 'Not palindrome'},
        ],
    },
    {
        'language': 'python',
        'title': 'Two Sum',
        'description': (
            'Given a list of integers and a target value, find the indices of the two numbers '
            'that add up to the target.\n\n'
            'Read the first line as space-separated integers, the second line as the target.\n'
            'Print the two indices (0-based), space-separated, smaller index first.\n\n'
            'Example:\n  Input:  2 7 11 15\n          9\n  Output: 0 1'
        ),
        'starter_code': 'numbers = list(map(int, input().split()))\ntarget = int(input())\n# Print the two indices\n',
        'difficulty': 4,
        'test_cases': [
            {'input': '2 7 11 15\n9',   'expected': '0 1', 'visible': True,  'description': 'Basic case'},
            {'input': '3 2 4\n6',       'expected': '1 2', 'visible': True,  'description': 'Non-zero start'},
            {'input': '0 4 3 0\n0',     'expected': '0 3', 'visible': False, 'description': 'Zeros'},
            {'input': '1 2 3 4 5\n9',   'expected': '3 4', 'visible': False, 'description': 'Last two'},
            {'input': '-1 -2 -3 -4\n-6','expected': '1 3', 'visible': False, 'description': 'Negatives'},
        ],
    },
    {
        'language': 'python',
        'title': 'Bubble Sort',
        'description': (
            'Implement bubble sort.\n\n'
            'Read a line of space-separated integers and print them sorted ascending.\n\n'
            'Example:\n  Input:  5 3 8 1 9 2\n  Output: 1 2 3 5 8 9'
        ),
        'starter_code': 'numbers = list(map(int, input().split()))\n\n# Implement bubble sort (do NOT use .sort() or sorted())\n\nprint(*numbers)\n',
        'difficulty': 5,
        'test_cases': [
            {'input': '5 3 8 1 9 2',   'expected': '1 2 3 5 8 9', 'visible': True,  'description': 'Random order'},
            {'input': '1 2 3',         'expected': '1 2 3',       'visible': True,  'description': 'Already sorted'},
            {'input': '3 2 1',         'expected': '1 2 3',       'visible': False, 'description': 'Reverse order'},
            {'input': '4 4 4',         'expected': '4 4 4',       'visible': False, 'description': 'All same'},
            {'input': '-3 1 -1 0 2',   'expected': '-3 -1 0 1 2', 'visible': False, 'description': 'Negatives mixed'},
        ],
    },

    # ── JavaScript Problems ──────────────────────────────────────────────────
    {
        'language': 'javascript',
        'title': 'Reverse a String',
        'description': (
            'Read a single line of input and print it reversed.\n\n'
            'Example:\n  Input:  hello\n  Output: olleh'
        ),
        'starter_code': 'const readline = require("readline");\nconst rl = readline.createInterface({ input: process.stdin });\nrl.on("line", line => {\n  // Print the reversed string\n  rl.close();\n});\n',
        'difficulty': 1,
        'test_cases': [
            {'input': 'hello',   'expected': 'olleh',  'visible': True,  'description': 'Basic word'},
            {'input': 'JavaScript', 'expected': 'tpircSavaJ', 'visible': True, 'description': 'Mixed case'},
            {'input': 'a',       'expected': 'a',      'visible': False, 'description': 'Single char'},
            {'input': '12345',   'expected': '54321',  'visible': False, 'description': 'Digits'},
        ],
    },
    {
        'language': 'javascript',
        'title': 'FizzBuzz',
        'description': (
            'Read a number n and print FizzBuzz from 1 to n.\n'
            '- Divisible by 3 → Fizz\n'
            '- Divisible by 5 → Buzz\n'
            '- Divisible by both → FizzBuzz\n'
            '- Otherwise → the number\n\n'
            'Example (n=5):\n  1\n  2\n  Fizz\n  4\n  Buzz'
        ),
        'starter_code': 'const n = parseInt(require("fs").readFileSync("/dev/stdin","utf8").trim());\nfor (let i = 1; i <= n; i++) {\n  // Print FizzBuzz\n}\n',
        'difficulty': 2,
        'test_cases': [
            {'input': '5',  'expected': '1\n2\nFizz\n4\nBuzz',           'visible': True,  'description': 'n=5'},
            {'input': '15', 'expected': '1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz', 'visible': True, 'description': 'n=15'},
            {'input': '1',  'expected': '1',                             'visible': False, 'description': 'n=1'},
            {'input': '3',  'expected': '1\n2\nFizz',                   'visible': False, 'description': 'n=3'},
        ],
    },
]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Seed initial CodingLanguage, CodingTopic, CodingExercise, and CodingProblem records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete ALL coding data before seeding.',
        )

    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write(self.style.WARNING('Deleting all coding data…'))
            ProblemTestCase.objects.all().delete()
            CodingProblem.objects.all().delete()
            CodingExercise.objects.all().delete()
            CodingTopic.objects.all().delete()
            CodingLanguage.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Deleted.'))

        # ── Languages ────────────────────────────────────────────────────────
        lang_objects = {}
        for lang_data in LANGUAGES:
            lang, created = CodingLanguage.objects.update_or_create(
                slug=lang_data['slug'],
                defaults=lang_data,
            )
            lang_objects[lang.slug] = lang
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} language: {lang.name}')

        # ── Topics ───────────────────────────────────────────────────────────
        topic_objects = {}   # (lang_slug, topic_name) → CodingTopic
        for lang_slug, topics in TOPICS.items():
            language = lang_objects.get(lang_slug)
            if not language:
                continue
            for t in topics:
                topic, created = CodingTopic.objects.update_or_create(
                    language=language,
                    slug=slugify(t['name']),
                    defaults={
                        'name': t['name'],
                        'description': t['description'],
                        'order': t['order'],
                        'is_active': True,
                    },
                )
                topic_objects[(lang_slug, t['name'])] = topic
                status = 'Created' if created else 'Updated'
                self.stdout.write(f'    {status} topic: {language.name} / {topic.name}')

        # ── Exercises ─────────────────────────────────────────────────────────
        ex_count = 0
        for (lang_slug, topic_name), exercises in EXERCISES.items():
            topic = topic_objects.get((lang_slug, topic_name))
            if not topic:
                self.stdout.write(self.style.WARNING(f'  Topic not found: {lang_slug} / {topic_name} — skipping'))
                continue
            for ex in exercises:
                _, created = CodingExercise.objects.update_or_create(
                    topic=topic,
                    title=ex['title'],
                    defaults={
                        'level':           ex['level'],
                        'description':     ex['description'],
                        'starter_code':    ex['starter_code'],
                        'expected_output': ex.get('expected_output', ''),
                        'hints':           ex.get('hints', ''),
                        'order':           ex.get('order', 0),
                        'is_active':       True,
                    },
                )
                if created:
                    ex_count += 1

        self.stdout.write(f'  Exercises created/updated: {ex_count}')

        # ── Problems ──────────────────────────────────────────────────────────
        prob_count = 0
        tc_count   = 0
        for prob_data in PROBLEMS:
            language = lang_objects.get(prob_data['language'])
            if not language:
                continue
            problem, created = CodingProblem.objects.update_or_create(
                language=language,
                title=prob_data['title'],
                defaults={
                    'description':   prob_data['description'],
                    'starter_code':  prob_data['starter_code'],
                    'difficulty':    prob_data['difficulty'],
                    'is_active':     True,
                },
            )
            if created:
                prob_count += 1

            # Re-seed test cases only when freshly created
            # (to avoid duplicate test cases on re-run without --reset)
            if created:
                for order, tc in enumerate(prob_data['test_cases'], start=1):
                    ProblemTestCase.objects.create(
                        problem=problem,
                        input_data=tc['input'],
                        expected_output=tc['expected'],
                        is_visible=tc['visible'],
                        description=tc.get('description', ''),
                        order=order,
                    )
                    tc_count += 1

        self.stdout.write(f'  Problems created: {prob_count}')
        self.stdout.write(f'  Test cases created: {tc_count}')
        self.stdout.write(self.style.SUCCESS('Coding seed complete.'))