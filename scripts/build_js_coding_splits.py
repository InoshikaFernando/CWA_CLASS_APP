#!/usr/bin/env python3
"""
build_js_coding_splits.py
=========================
Generates the JavaScript coding-exercise seed files from the hand-translated
Python originals.  These exercises were ported 1:1 from the existing Python
coding bank (CodingLanguage 'python') into JavaScript idioms:

  * print(...)            -> console.log(...)
  * f"..."               -> `...${ }` template literals
  * True / False          -> true / false
  * type(x) -> <class..>  -> typeof x -> "number" / "string" / "boolean"
  * lists                 -> arrays   (Lists topic -> JS 'arrays' topic)
  * dict-style printing   -> JSON.stringify for whole-array output
  * // (floor div)        -> Math.floor(a / b)
  * range(...)            -> C-style for / for...of loops
  * global / nonlocal     -> JS scope rules (shadowing, closures, by-ref args)

expected_output values are written to match Node.js console.log output exactly,
because the grader compares stdout with == after rstrip() (coding/scoring.py
evaluate_exercise_output). Where Python's repr differs from Node's (arrays,
booleans, types), the exercise was redesigned to produce clean, deterministic
output (e.g. arrays printed with JSON.stringify).

The 29 empty Python multiple_choice stubs (no description / answers — several
duplicate a real write_code exercise of the same title) are intentionally NOT
ported. See EXCLUDED_PY_IDS below.

Run:
    python scripts/build_js_coding_splits.py
Writes one JSON file per (topic, level) into:
    cwa_classroom/coding/management/commands/upload_splits_js/
"""
from __future__ import annotations

import json
import os

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'cwa_classroom', 'coding', 'management', 'commands', 'upload_splits_js',
)

# Python exercise ids that were deliberately dropped: empty multiple_choice
# stubs with no description, starter, expected output or answers.
EXCLUDED_PY_IDS = [
    118, 120, 121, 122, 123, 96, 98, 99, 100, 101, 108, 110, 111, 112, 113,
    90, 92, 93, 94, 95, 102, 104, 105, 106, 107, 114, 115, 116, 117,
]

# Each block: (topic_slug, level, [exercise dicts])
# An exercise dict mirrors the extended seed format consumed by seed_coding_js.
BLOCKS: list[tuple[str, str, list[dict]]] = []


def block(topic, level, exercises):
    BLOCKS.append((topic, level, exercises))


def wc(title, instructions, starter, expected, hints, order,
       required_patterns=None):
    """write_code exercise."""
    d = {
        'title': title,
        'question_type': 'write_code',
        'instructions': instructions,
        'starter_code': starter,
        'expected_output': expected,
        'hints': hints,
        'display_order': order,
    }
    if required_patterns:
        d['required_code_patterns'] = required_patterns
    return d


def mcq(title, options, order, instructions=''):
    """options: list of (text, is_correct)."""
    return {
        'title': title,
        'question_type': 'multiple_choice',
        'instructions': instructions,
        'display_order': order,
        'answers': [{'text': t, 'is_correct': c} for t, c in options],
    }


def tf(title, correct_value, order, instructions=''):
    """correct_value: True or False."""
    return {
        'title': title,
        'question_type': 'true_false',
        'instructions': instructions,
        'display_order': order,
        'answers': [
            {'text': 'True', 'is_correct': correct_value is True},
            {'text': 'False', 'is_correct': correct_value is False},
        ],
    }


def sa(title, answer, order, instructions='', qt='short_answer'):
    return {
        'title': title,
        'question_type': qt,
        'instructions': instructions or title,
        'display_order': order,
        'correct_short_answer': answer,
    }


# ===========================================================================
# VARIABLES & DATA TYPES
# ===========================================================================

block('variables-data-types', 'beginner', [
    wc('Hello, World!',
       'Write a JavaScript program that prints exactly:\nHello, World!',
       '// Write your code below\n',
       'Hello, World!',
       'Use console.log().', 1),
    wc('Store Your Name',
       'Create a variable called name and assign "Test" into it.\nThen print: Hello, <name>!',
       '// Create a variable called name\nlet name = ;\n\n// Print the greeting\n',
       'Hello, Test!',
       'Use a template literal: console.log(`Hello, ${name}!`)', 2),
    wc('Variable: Store and Print a Name',
       "Create a variable called 'name' holding the string 'Ada' and print it.",
       'let name = ?;\nconsole.log(?);\n',
       'Ada',
       'Strings go in quotes: "Ada" or \'Ada\'', 3,
       required_patterns=r'console\.log\s*\(\s*name\s*\)'),
    wc('Variable: Store a Number',
       "Create a variable called 'age' holding the number 12 and print it.",
       'let age = ?;\nconsole.log(?);\n',
       '12',
       'Numbers have no quotes around them', 4),
    wc('Variable: A Decimal Number',
       "Create a variable called 'price' holding the number 9.5 and print it.",
       'let price = ?;\nconsole.log(?);\n',
       '9.5',
       'Decimals are numbers with a decimal point', 5),
    wc('Simple Math',
       'Create two variables x = 10 and y = 3.\n'
       'Print the result of: x + y, x - y, x * y, and x / y (each on a new line).',
       'let x = 10;\nlet y = 3;\n\n// Print the four operations\n',
       '13\n7\n30\n3.3333333333333335',
       'Use console.log() for each operation.', 6),
    wc('Variable: A Boolean',
       "Create a variable 'isStudent' set to true and print it.",
       'let isStudent = ?;\nconsole.log(?);\n',
       'true',
       'Booleans are true or false — lowercase, no quotes', 7),
    wc('Variable: Add Two Numbers',
       'Create a = 3 and b = 4, then print their sum.',
       'let a = 3;\nlet b = 4;\nconsole.log(? + ?);\n',
       '7',
       'Use the + operator between the two variable names', 8),
    wc('Variable: Greeting String',
       "Create name = 'Sam' and print 'Hello, Sam' using string concatenation.",
       'let name = "Sam";\nconsole.log("Hello, " + ?);\n',
       'Hello, Sam',
       'Use + to join two strings together', 9),
    wc('Variable: Type of a Value',
       'Create x = 5 and print its type using typeof.',
       'let x = 5;\nconsole.log(typeof ?);\n',
       'number',
       'typeof returns the type of a value as a string', 10),
    wc('Variable: Reassign',
       'Set x = 10, then reassign x = 20, and print x.',
       'let x = 10;\nx = ?;\nconsole.log(?);\n',
       '20',
       'A variable keeps the last value assigned to it', 11),
])

block('variables-data-types', 'intermediate', [
    wc('Conversion: String to Number',
       "Given s = '42', convert it to a number, add 8, and print the result.",
       'let s = "42";\nlet n = Number(?);\nconsole.log(n + ?);\n',
       '50',
       'Number(s) converts a numeric string to a number', 1),
    wc('Conversion: Number to String',
       "Given age = 15, print 'Age: 15' by converting age to a string and concatenating.",
       'let age = 15;\nconsole.log("Age: " + String(?));\n',
       'Age: 15',
       'String(age) converts the number to text', 2),
    wc('Type Inspector',
       'Create four variables:\n'
       '- a number called age (value: 16)\n'
       '- a number called height (value: 1.75)\n'
       '- a string called city (value: "Auckland")\n'
       '- a boolean called isStudent (value: true)\n\n'
       'Print the type of each variable (using typeof) on a separate line.',
       '// Create your variables here\n\n\n// Print each type with typeof\n',
       'number\nnumber\nstring\nboolean',
       'Use typeof: console.log(typeof age). JavaScript has one number type for ints and decimals.', 3),
    wc('Conversion: Decimal to Integer',
       'Given price = 9.8, convert to an integer (truncate toward zero) and print it.',
       'let price = 9.8;\nconsole.log(Math.trunc(?));\n',
       '9',
       'Math.trunc() drops the decimal part', 4),
    wc('Operator: Integer Division',
       'Given a = 17 and b = 5, print the integer (floor) division of a by b.',
       'let a = 17;\nlet b = 5;\nconsole.log(Math.floor(a ? b));\n',
       '3',
       'JavaScript has no // operator — use Math.floor(a / b)', 5),
    wc('Operator: Modulo',
       'Given a = 17 and b = 5, print the remainder of a divided by b.',
       'let a = 17;\nlet b = 5;\nconsole.log(a ? b);\n',
       '2',
       '% returns the remainder', 6),
    wc('Temperature Converter',
       'Given celsius = 25, convert it to Fahrenheit using the formula: F = (C * 9/5) + 32.\n'
       'Print the result as: 25°C is 77.0°F',
       'let celsius = 25;\n\n// Calculate and print\n',
       '25°C is 77.0°F',
       'Use a template literal and .toFixed(1) to show one decimal place.', 7),
    wc('String Formatting: Template Literal',
       "Given name = 'Mia' and score = 95, print 'Mia scored 95' using a template literal.",
       'let name = "Mia";\nlet score = 95;\nconsole.log(`${?} scored ${?}`);\n',
       'Mia scored 95',
       'Inside a template literal (backticks), put variables inside ${ }', 8),
    wc('Multiple Assignment',
       'Assign a, b, c = 1, 2, 3 in a single line using array destructuring, then print their sum.',
       'let [a, b, c] = [?, ?, ?];\nconsole.log(a + b + c);\n',
       '6',
       'JavaScript unpacks the array [1, 2, 3] into a, b, c via destructuring', 9),
    wc('Swap Two Variables',
       "Given a = 1 and b = 2, swap them using array destructuring and print 'a=2 b=1'.",
       'let a = 1;\nlet b = 2;\n[a, b] = [?, ?];\nconsole.log(`a=${a} b=${b}`);\n',
       'a=2 b=1',
       'Write [a, b] = [b, a] — swaps without a temp variable', 10),
    wc('Augmented Assignment',
       'Start with total = 10 and add 5 using +=, then print total.',
       'let total = 10;\ntotal ?= 5;\nconsole.log(total);\n',
       '15',
       '+= adds the right-hand side in place', 11),
])

block('variables-data-types', 'advanced', [
    wc('Type Casting',
       'You are given:\n  x = "42"\n  y = "3.14"\n\n'
       'Convert x to a number and y to a number.\nPrint their sum.',
       'let x = "42";\nlet y = "3.14";\n\n// Convert and print the sum\n',
       '45.14',
       'Use parseInt() and parseFloat() (or Number()) to convert. The result should be 45.14.', 1),
    wc('Local Variable: Shadows Outer',
       'The outer x is 10. Inside show(), declare a LOCAL x so that 5 prints when show() is called.',
       'let x = 10;\n\nfunction show() {\n  let ? = ?;\n  console.log(x);\n}\n\nshow();\n',
       '5',
       'Declaring `let x` inside the function creates a new LOCAL variable that hides the outer one', 2),
    wc('Read an Outer Variable',
       'A function can READ an outer variable without redeclaring it. Print the outer counter from inside show().',
       'let counter = 42;\n\nfunction show() {\n  console.log(?);\n}\n\nshow();\n',
       '42',
       "Reading a name JavaScript doesn't find locally falls back to the enclosing/outer scope", 3),
    wc('Mutate an Outer Variable',
       'Update the OUTER count inside increment() (assign without `let`, which would make a new local).\n'
       'Print count after two calls.',
       'let count = 0;\n\nfunction increment() {\n  ? += 1;\n}\n\nincrement();\nincrement();\nconsole.log(count);\n',
       '2',
       'Using `let count` inside the function makes a new local; assigning without `let` updates the outer one', 4),
    wc('Scope Trap: Read the Outer Variable',
       'Fix the function so it prints the outer value 7. Just READ the outer variable — do not redeclare it with let.',
       'let value = 7;\n\nfunction show() {\n  // Do NOT redeclare value here — just print the outer one\n  console.log(?);\n}\n\nshow();\n',
       '7',
       'Declaring `let value` inside would shadow the outer one for the whole function (temporal dead zone)', 5,
       required_patterns=r'console\.log\s*\(\s*value\s*\)'),
    wc('Closure: Update an Enclosing Variable',
       'Inside inner(), update x in the enclosing outer() scope so that outer() returns 99. (Assign without let.)',
       'function outer() {\n  let x = 1;\n  function inner() {\n    ? = 99;\n  }\n  inner();\n  return x;\n}\n\nconsole.log(outer());\n',
       '99',
       "A nested function can assign to a variable in its enclosing scope — just don't redeclare it with let", 6),
    wc('Mutability: Mutate an Array Argument',
       'Arrays are passed by reference. Append 99 to the array inside modify() so the outer array ends as [1,2,3,99].',
       'let nums = [1, 2, 3];\n\nfunction modify(lst) {\n  lst.?(99);\n}\n\nmodify(nums);\nconsole.log(JSON.stringify(nums));\n',
       '[1,2,3,99]',
       'lst refers to the same array object as nums — .push() mutates it in place', 7),
    wc('Mutability: Reassigning vs Mutating',
       'Reassigning a parameter (lst = [...]) does NOT affect the caller. Print the unchanged array after rebind() runs.',
       'let nums = [1, 2, 3];\n\nfunction rebind(lst) {\n  lst = [9, 9, 9];\n}\n\nrebind(nums);\nconsole.log(JSON.stringify(?));\n',
       '[1,2,3]',
       '`lst = [...]` points the local name at a NEW array — the caller\'s array is untouched', 8),
    wc('Numbers Are Passed by Value',
       'Reassigning a number parameter inside a function does not touch the caller. Print the unchanged outer value.',
       'let n = 5;\n\nfunction change(x) {\n  x = 100;\n}\n\nchange(n);\nconsole.log(?);\n',
       '5',
       'Only the local name x is reassigned; n is a separate binding in the outer scope', 9,
       required_patterns=r'console\.log\s*\(\s*n\s*\)'),
    mcq('What is a variable?',
        [('A named container that stores a value in memory', True),
         ('A fixed constant value that cannot change', False),
         ('A function that performs operations', False),
         ('A comment in the code', False)], 10),
])

# ===========================================================================
# IF CONDITIONS
# ===========================================================================

block('if-conditions', 'beginner', [
    wc('Positive or Negative',
       'Write a program that checks if the number 7 is positive or negative.\n'
       'Print "Positive" if it is greater than 0, otherwise print "Negative".',
       'let number = 7;\n\n// Check and print\n',
       'Positive',
       'Use if (number > 0) { ... }', 1),
    wc('If: Positive Number',
       "Check if the number is greater than 0 and print 'Positive' when it is.",
       'let num = 7;\nif (num ? 0) {\n  console.log(?);\n}\n',
       'Positive',
       'Use the > operator to compare num with 0', 2),
    wc('If: Is Even',
       "If the number is divisible by 2, print 'Even'.",
       'let num = 4;\nif (num % 2 === ?) {\n  console.log(?);\n}\n',
       'Even',
       'A number is even when num % 2 equals 0', 3),
    wc('Even or Odd',
       'Given number = 17, check if it is even or odd.\n'
       'Print "Even" if divisible by 2, otherwise print "Odd".',
       'let number = 17;\n\n// Check and print\n',
       'Odd',
       'Use the modulo operator % to check divisibility.', 4),
    wc('If: Big Enough',
       "If the age is 18 or more, print 'Adult'.",
       'let age = 21;\nif (age ? 18) {\n  console.log(?);\n}\n',
       'Adult',
       'Use the >= operator to include 18', 5),
    wc('If: Exact Match',
       "If the colour is 'red', print 'Stop'.",
       'let colour = "red";\nif (colour === ?) {\n  console.log(?);\n}\n',
       'Stop',
       'Use === to compare strings', 6),
    wc('If: Passing Mark',
       "If the score is 50 or above, print 'Pass'.",
       'let score = 72;\nif (score ? 50) {\n  console.log(?);\n}\n',
       'Pass',
       'Use >= so a score of exactly 50 still passes', 7),
    wc('If: Empty Array',
       "If the array has 0 items, print 'Empty'.",
       'let items = [];\nif (items.length === ?) {\n  console.log(?);\n}\n',
       'Empty',
       'items.length returns the number of items in the array', 8),
    wc('If: Member Check',
       "If the letter 'a' is in the word 'banana', print 'Found'.",
       'let word = "banana";\nif (word.includes(?)) {\n  console.log(?);\n}\n',
       'Found',
       'Use .includes() to check if the letter is in the word', 9),
    wc('If: Boolean Flag',
       "If isRaining is true, print 'Take an umbrella'.",
       'let isRaining = true;\nif (?) {\n  console.log(?);\n}\n',
       'Take an umbrella',
       'A boolean variable can be used directly as the condition', 10),
])

block('if-conditions', 'intermediate', [
    wc('If/Else: Even or Odd',
       "Print 'Even' if the number is divisible by 2, otherwise print 'Odd'.",
       'let num = 7;\nif (num % 2 === 0) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'Odd',
       'The else branch runs when the if condition is false', 1),
    wc('Grade Calculator',
       'Given score = 72, print the grade using this scale:\n'
       '90-100 -> A\n80-89  -> B\n70-79  -> C\n60-69  -> D\nBelow 60 -> F',
       'let score = 72;\n\n// Determine and print the grade\n',
       'C',
       'Use else if for each range. Check from highest to lowest.', 2),
    wc('If/Else: Adult or Minor',
       "Print 'Adult' if age is 18 or more, otherwise 'Minor'.",
       'let age = 16;\nif (age >= 18) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'Minor',
       'Use >= to include exactly 18 as an adult', 3),
    wc('If/Else: Larger Number',
       'Given a = 12 and b = 9, print the larger number.',
       'let a = 12;\nlet b = 9;\nif (a ? b) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       '12',
       'Compare with > and print whichever is bigger', 4),
    wc('Number Range Check',
       'Given number = 42, check if it\'s within range 1-100.\n'
       'Print "In range" or "Out of range".',
       'let number = 42;\n\n// Check and print\n',
       'In range',
       'Use && to combine two conditions: number >= 1 && number <= 100', 5),
    wc('If/Else: Positive or Non-Positive',
       "If num is greater than 0 print 'Positive', otherwise print 'Non-positive'.",
       'let num = -3;\nif (num > 0) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'Non-positive',
       'The else branch handles 0 and negatives together', 6),
    wc('If/Else If/Else: Sign of a Number',
       "Given num = 0, print 'Positive' if > 0, 'Negative' if < 0, otherwise 'Zero'.",
       'let num = 0;\nif (num > 0) {\n  console.log(?);\n} else if (num ? 0) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'Zero',
       'else if is checked only if the first if is false', 7),
    wc('If/Else If/Else: Grade Letter',
       "Given score = 75, print 'A' if >= 90, 'B' if >= 75, 'C' if >= 50, otherwise 'F'.",
       'let score = 75;\nif (score >= 90) {\n  console.log("A");\n} else if (score >= ?) {\n  console.log(?);\n} else if (score >= 50) {\n  console.log("C");\n} else {\n  console.log(?);\n}\n',
       'B',
       'The first matching branch wins — order matters', 8),
    wc('If/Else with AND: In Range',
       "Given x = 15, print 'In range' if x is between 10 and 20 inclusive, otherwise 'Out of range'.",
       'let x = 15;\nif (x >= 10 ? x <= 20) {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'In range',
       'Combine two conditions with the && operator', 9),
    wc('If/Else with OR: Weekend',
       "Given day = 'Sun', print 'Weekend' if day is 'Sat' or 'Sun', otherwise 'Weekday'.",
       'let day = "Sun";\nif (day === "Sat" ? day === "Sun") {\n  console.log(?);\n} else {\n  console.log(?);\n}\n',
       'Weekend',
       'Use the || operator between the two equality checks', 10),
])

block('if-conditions', 'advanced', [
    wc('Nested If: Admin Panel',
       "If the user is logged in AND also an admin, print 'Admin panel'. Use nested ifs (not &&).",
       'let loggedIn = true;\nlet isAdmin = true;\nif (loggedIn) {\n  if (?) {\n    console.log(?);\n  }\n}\n',
       'Admin panel',
       "Place the second if inside the first if's block", 1),
    wc('Nested If: Positive and Even',
       "Given num = 8, first check that num is positive; if so, check whether it is even and print 'Positive even' or 'Positive odd'.",
       'let num = 8;\nif (num > 0) {\n  if (num % 2 === 0) {\n    console.log(?);\n  } else {\n    console.log(?);\n  }\n}\n',
       'Positive even',
       'The inner if/else only runs when the outer condition is true', 2),
    wc('Nested If: Login Flow',
       "Given username = 'admin' and password = 'secret', print 'Welcome admin' only when both match. Otherwise print 'Access denied'. Use nested ifs.",
       'let username = "admin";\nlet password = "secret";\nif (username === "admin") {\n  if (password === ?) {\n    console.log(?);\n  } else {\n    console.log(?);\n  }\n} else {\n  console.log("Access denied");\n}\n',
       'Welcome admin',
       'Check username in the outer if, then password in the inner if', 3),
    wc('Nested If: Ticket Pricing',
       "Given age = 30 and isMember = true, print 10 if adult member, 15 if adult non-member, 5 if child member, 7 if child non-member. 'Adult' means age >= 18.",
       'let age = 30;\nlet isMember = true;\nif (age >= 18) {\n  if (isMember) {\n    console.log(?);\n  } else {\n    console.log(?);\n  }\n} else {\n  if (isMember) {\n    console.log(?);\n  } else {\n    console.log(?);\n  }\n}\n',
       '10',
       'Outer if splits adult/child, inner if splits member/non-member', 4),
    wc('Nested If: Triangle Classifier',
       "Given a = 5, b = 5, c = 5, first check the triangle is valid (a+b>c and a+c>b and b+c>a). If valid, classify it as 'Equilateral', 'Isosceles', or 'Scalene' with nested ifs.",
       'let a = 5, b = 5, c = 5;\nif (a + b > c && a + c > b && b + c > a) {\n  if (a === b && b === c) {\n    console.log(?);\n  } else {\n    if (a === b || b === c || a === c) {\n      console.log(?);\n    } else {\n      console.log(?);\n    }\n  }\n} else {\n  console.log("Not a triangle");\n}\n',
       'Equilateral',
       'The innermost if handles Isosceles vs Scalene', 5),
    wc('Nested If: Leap Year',
       "Given year = 2000, print 'Leap' if it is a leap year, otherwise 'Not leap'. Rule: divisible by 4; if divisible by 100 it must also be divisible by 400. Use nested ifs (no &&).",
       'let year = 2000;\nif (year % 4 === 0) {\n  if (year % 100 === 0) {\n    if (year % 400 === 0) {\n      console.log(?);\n    } else {\n      console.log(?);\n    }\n  } else {\n    console.log("Leap");\n  }\n} else {\n  console.log("Not leap");\n}\n',
       'Leap',
       'Three levels of nesting handle the /4, /100, /400 rules in order', 6),
    wc('Leap Year',
       'Given year = 2024, determine if it is a leap year.\n'
       'A year is a leap year if:\n'
       '- It is divisible by 4 AND\n'
       '- It is NOT divisible by 100, OR it IS divisible by 400\n\n'
       'Print "Leap year" or "Not a leap year".',
       'let year = 2024;\n\n// Check and print\n',
       'Leap year',
       'Use the % (modulo) operator. Combine conditions with && and ||.', 7),
    mcq('What is the JavaScript ternary (conditional) expression syntax?',
        [('condition ? valueIfTrue : valueIfFalse', True),
         ('valueIfTrue if condition else valueIfFalse', False),
         ('if condition then valueIfTrue else valueIfFalse', False),
         ('condition && valueIfTrue || valueIfFalse only', False)], 8),
])

# ===========================================================================
# LOOPS
# ===========================================================================

block('loops', 'beginner', [
    wc('Count to 5',
       'Use a for loop to print the numbers 1 to 5, each on a new line.',
       '// Use a for loop\n',
       '1\n2\n3\n4\n5',
       'Use a for loop: for (let i = 1; i <= 5; i++)', 1),
    wc('For Loop: Print 1-10',
       'Use a for loop to print numbers 1 through 10, each on a new line.',
       '// Use a for loop\nfor (let i = ?; i <= ?; i++) {\n  console.log(?);\n}\n',
       '1\n2\n3\n4\n5\n6\n7\n8\n9\n10',
       'Loop from 1 while i <= 10', 2),
    wc('For Loop: Even Numbers',
       'Use a for loop to print all even numbers from 2 to 10, each on a new line.',
       '// Use a for loop with a step\nfor (let i = ?; i <= ?; i += ?) {\n  console.log(?);\n}\n',
       '2\n4\n6\n8\n10',
       'Start at 2 and step by 2 with i += 2', 3),
    wc('For Loop: Sum 1 to 5',
       'Use a for loop to calculate the sum of numbers from 1 to 5 and print the result.',
       'let total = 0;\nfor (let i = ?; i <= ?; i++) {\n  total += ?;\n}\nconsole.log(total);\n',
       '15',
       'Add each i to total inside the loop, then print total after the loop', 4),
    wc('Multiply Table',
       "Print the 5 times table (5*1 through 5*10), each on a new line.\nFormat: 5 x 1 = 5",
       '// Print 5 times table\n',
       '5 x 1 = 5\n5 x 2 = 10\n5 x 3 = 15\n5 x 4 = 20\n5 x 5 = 25\n5 x 6 = 30\n5 x 7 = 35\n5 x 8 = 40\n5 x 9 = 45\n5 x 10 = 50',
       'Use a for loop with range 1..10 and a template literal.', 5),
    wc('For Loop: Multiplication Table',
       "Print the 3 times table from 3x1 to 3x5 in the format '3 x 1 = 3'.",
       'for (let i = ?; i <= ?; i++) {\n  console.log(`3 x ${i} = ${?}`);\n}\n',
       '3 x 1 = 3\n3 x 2 = 6\n3 x 3 = 9\n3 x 4 = 12\n3 x 5 = 15',
       'Multiply 3 by i inside the template literal', 6),
    wc('While Loop: Countdown from 10',
       'Use a while loop to count down from 10 to 1.',
       'let count = 10;\nwhile (count > 0) {\n  // Print count and decrease it\n}\n',
       '10\n9\n8\n7\n6\n5\n4\n3\n2\n1',
       'Print count, then use count-- to decrease it', 7),
    wc('While Loop: Double Until 100',
       'Start with 1 and keep doubling it while it is less than 100. Print each value.',
       'let num = 1;\nwhile (num < ?) {\n  console.log(?);\n  num = ?;\n}\n',
       '1\n2\n4\n8\n16\n32\n64',
       'Use num = num * 2 to double the value each iteration', 8),
    wc('For...of: Loop Through an Array',
       'Loop through the array of fruits and print each one.',
       'let fruits = ["apple", "banana", "cherry"];\nfor (let ? of ?) {\n  console.log(?);\n}\n',
       'apple\nbanana\ncherry',
       'Use for (let fruit of fruits) to iterate through each item', 9),
    wc('For Loop: Count Vowels',
       "Count how many vowels (a, e, i, o, u) are in the word 'education' and print the count.",
       'let word = "education";\nlet vowels = "aeiou";\nlet count = 0;\nfor (let letter of ?) {\n  if (vowels.includes(?)) {\n    count++;\n  }\n}\nconsole.log(count);\n',
       '5',
       "Loop through each letter of word and check if it's in the vowels string with .includes()", 10),
    wc('While Loop: Sum Until 50',
       'Keep adding numbers starting from 1 until the total reaches or exceeds 50. Print the final total.',
       'let total = 0;\nlet n = 1;\nwhile (total < ?) {\n  total += ?;\n  n++;\n}\nconsole.log(total);\n',
       '55',
       '1+2+3+...+10 = 55, which is the first sum >= 50', 11),
    wc('For Loop: Reverse Countdown',
       'Use a for loop to print numbers from 5 down to 1.',
       'for (let i = ?; i >= ?; i--) {\n  console.log(i);\n}\n',
       '5\n4\n3\n2\n1',
       'Start at 5 and decrease with i-- while i >= 1', 12),
    wc('Nested Loop: Square Pattern',
       'Use nested loops to print a 3x3 grid of stars (*).',
       'for (let i = 0; i < ?; i++) {\n  let row = "";\n  for (let j = 0; j < ?; j++) {\n    row += "*";\n  }\n  console.log(row);\n}\n',
       '***\n***\n***',
       'Build each row as a string in the inner loop, then console.log the row', 13),
    wc('For Loop: Find Maximum',
       'Find the largest number in the array [4, 7, 2, 9, 5, 1] and print it.',
       'let numbers = [4, 7, 2, 9, 5, 1];\nlet largest = numbers[0];\nfor (let num of ?) {\n  if (num > ?) {\n    largest = ?;\n  }\n}\nconsole.log(largest);\n',
       '9',
       'Compare each number to largest, and update largest if the current number is bigger', 14),
    mcq('What is the output of:\nfor (let i = 0; i < 3; i++) {\n  console.log(i);\n}',
        [('0\n1\n2', True), ('1\n2\n3', False), ('0\n1\n2\n3', False), ('3', False)], 15),
    mcq('How many times does this loop run?\nfor (let i = 1; i < 6; i++) {\n  console.log(i);\n}',
        [('4', False), ('5', True), ('6', False), ('1', False)], 16),
    mcq('Which keyword starts a counting loop in JavaScript?',
        [('loop', False), ('foreach', False), ('for', True), ('iterate', False)], 17),
    tf('The loop `for (let i = 0; i < 5; i++)` sets i to 1, 2, 3, 4, 5.', False, 18),
    mcq('What is the output of:\nlet total = 0;\nfor (const n of [1, 2, 3, 4]) {\n  total += n;\n}\nconsole.log(total);',
        [('4', False), ('6', False), ('10', True), ('24', False)], 19),
    mcq('What values does `for (let i = 2; i < 10; i += 2)` give i?',
        [('2, 4, 6, 8, 10', False), ('2, 4, 6, 8', True),
         ('2, 3, 4, 5, 6, 7, 8, 9', False), ('0, 2, 4, 6, 8', False)], 20),
    sa("Fill in the blank so the loop prints each character of the word 'cat' on its own line:\nfor (const letter ___ 'cat') {\n  console.log(letter);\n}",
       'of', 21, qt='fill_blank'),
    tf('A for...of loop in JavaScript can iterate over a string character by character.', True, 22),
    sa('What is the output of:\nfor (let i = 0; i < 3; i++) {\n  if (i === 1) break;\n  console.log(i);\n}',
       '0', 23, qt='short_answer'),
    mcq('What is the output of:\nfor (let i = 0; i < 4; i++) {\n  if (i === 2) continue;\n  console.log(i);\n}',
        [('0\n1\n2\n3', False), ('0\n1\n3', True), ('0\n1', False), ('1\n3', False)], 24),
])

block('loops', 'intermediate', [
    wc('Sum of an Array',
       'Given numbers = [4, 8, 15, 16, 23, 42], use a loop to calculate the total.\nPrint the total.',
       'let numbers = [4, 8, 15, 16, 23, 42];\nlet total = 0;\n\n// Loop and sum\n\nconsole.log(total);\n',
       '108',
       'Add each number to total inside the loop.', 1),
    wc('Countdown Loop',
       'Print a countdown from 10 to 1, each on a new line.',
       '// Print countdown\n',
       '10\n9\n8\n7\n6\n5\n4\n3\n2\n1',
       'Use a for loop: for (let i = 10; i >= 1; i--)', 2),
])

block('loops', 'advanced', [
    wc('FizzBuzz',
       'Print numbers 1 to 20.\n'
       '- If divisible by 3, print "Fizz" instead.\n'
       '- If divisible by 5, print "Buzz" instead.\n'
       '- If divisible by both 3 and 5, print "FizzBuzz".',
       '// FizzBuzz from 1 to 20\n',
       '1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n16\n17\nFizz\n19\nBuzz',
       'Check the FizzBuzz condition first (divisible by both), then Fizz, then Buzz.', 1),
    mcq('What does the array map() method do?',
        [('Creates a new array by transforming each element', True),
         ('Sorts the array in place', False),
         ('Removes elements from the array', False),
         ('Joins the array into a single string', False)], 2),
])

# ===========================================================================
# FUNCTIONS
# ===========================================================================

block('functions', 'beginner', [
    wc('Greet Function',
       'Define a function called greet that takes a name as a parameter.\n'
       'It should print: Hello, <name>!\n\n'
       'Call it with greet("Alex").',
       'function greet(name) {\n  // Write your code here\n}\n\ngreet("Alex");\n',
       'Hello, Alex!',
       'Use console.log(`Hello, ${name}!`) inside the function.', 1),
    wc('Add Function',
       'Write a function called add(a, b) that returns the sum of two numbers.\n'
       'Call it with add(15, 27) and print the result.',
       'function add(a, b) {\n  // Return the sum\n}\n\nconsole.log(add(15, 27));\n',
       '42',
       'Use return a + b', 2),
])

block('functions', 'intermediate', [
    wc('Square Function',
       'Write a function called square that takes a number and returns its square.\n'
       'Print the result of square(9).',
       'function square(n) {\n  // Return the square of n\n}\n\nconsole.log(square(9));\n',
       '81',
       'Use return n * n or return n ** 2', 1),
    wc('Check Prime',
       'Write a function called isPrime(n) that returns true if n is prime, false otherwise.\n'
       'Test with isPrime(7) and isPrime(10).',
       'function isPrime(n) {\n  // Check if n is prime\n}\n\nconsole.log(isPrime(7));\nconsole.log(isPrime(10));\n',
       'true\nfalse',
       'A prime number has no divisors other than 1 and itself.', 2),
])

block('functions', 'advanced', [
    wc('Factorial',
       'Write a recursive function called factorial(n) that returns n!\n\nPrint factorial(5).',
       'function factorial(n) {\n  // Base case: factorial(0) = 1\n  // Recursive case\n}\n\nconsole.log(factorial(5));\n',
       '120',
       'Base case: if (n === 0) return 1; Recursive: return n * factorial(n - 1)', 1),
    mcq('What is a higher-order function in JavaScript?',
        [('A function that takes or returns another function', True),
         ('A method defined inside a class', False),
         ('A variable that holds a number', False),
         ('A type annotation', False)], 2),
])

# ===========================================================================
# LISTS -> ARRAYS
# ===========================================================================

block('arrays', 'beginner', [
    wc('Create and Print an Array',
       'Create an array called fruits containing these 5 items, in order:\n'
       '"apple", "banana", "cherry", "date", "elder".\n'
       'Then print it using JSON.stringify().',
       'let fruits = [];\n\n// Add the fruits and print with JSON.stringify\n',
       '["apple","banana","cherry","date","elder"]',
       'Build the array, then console.log(JSON.stringify(fruits)).', 1),
    wc('Access Array Elements',
       'Given numbers = [10, 20, 30, 40, 50], print the first, third, and last elements.',
       'let numbers = [10, 20, 30, 40, 50];\n\n// Print first, third, and last\n',
       '10\n30\n50',
       'Use indices: numbers[0], numbers[2], numbers[numbers.length - 1]', 2),
])

block('arrays', 'intermediate', [
    wc('Array Length and Sum',
       'Given scores = [85, 92, 78, 95, 88], print the length and sum of the array.',
       'let scores = [85, 92, 78, 95, 88];\n\n// Print length and sum\n',
       '5\n438',
       'Use scores.length and scores.reduce((a, b) => a + b, 0)', 1),
    wc('Double Each Item',
       'Given numbers = [1, 2, 3, 4, 5], create a new array with each number doubled.\n'
       'Print the new array using JSON.stringify().',
       'let numbers = [1, 2, 3, 4, 5];\n\n// Create doubled array and print with JSON.stringify\n',
       '[2,4,6,8,10]',
       'Use .map(): numbers.map(x => x * 2), then JSON.stringify the result.', 2),
])

block('arrays', 'advanced', [
    wc('Filter Even Numbers',
       'Given numbers = [1..10], create a new array containing only even numbers.\n'
       'Print it using JSON.stringify().',
       'let numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];\n\n// Filter even numbers and print with JSON.stringify\n',
       '[2,4,6,8,10]',
       'Use .filter(): numbers.filter(x => x % 2 === 0), then JSON.stringify the result.', 1),
    mcq('What is the output of [3, 1, 2].sort((a, b) => b - a)?',
        [('[3, 2, 1]', True), ('[1, 2, 3]', False), ('[2, 1, 3]', False), ('Error', False)], 2),
])

# ===========================================================================
# STRING MANIPULATION -> new JS 'strings' topic
# ===========================================================================

block('strings', 'beginner', [
    wc('String Length',
       'Given text = "Hello World", print the length of the string.',
       'let text = "Hello World";\n\n// Print the length\n',
       '11',
       'Use .length', 1),
    wc('String Uppercase and Lowercase',
       'Given word = "JavaScript", print it in uppercase and lowercase.',
       'let word = "JavaScript";\n\n// Print uppercase and lowercase\n',
       'JAVASCRIPT\njavascript',
       'Use .toUpperCase() and .toLowerCase() methods.', 2),
])

block('strings', 'intermediate', [
    wc('String Replace',
       'Given sentence = "I love cats", replace "cats" with "dogs" and print the result.',
       'let sentence = "I love cats";\n\n// Replace and print\n',
       'I love dogs',
       'Use the .replace() method.', 1),
    wc('String Split and Join',
       'Given text = "apple,banana,cherry", split by comma, then print each fruit on a new line.',
       'let text = "apple,banana,cherry";\n\n// Split and print each on a new line\n',
       'apple\nbanana\ncherry',
       'Use .split(",") then loop, or join with "\\n".', 2),
])


# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    files = 0
    for topic, level, exercises in BLOCKS:
        payload = {
            'subject': 'coding',
            'language': 'javascript',
            'topic': topic,
            'level': level,
            'exercises': exercises,
        }
        fname = f'javascript_{topic}_{level}.json'
        with open(os.path.join(OUT_DIR, fname), 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write('\n')
        total += len(exercises)
        files += 1
        print(f'  {fname:48s} {len(exercises):2d} exercises')
    print(f'\nWrote {total} exercises across {files} files into {OUT_DIR}')
    print(f'Excluded {len(EXCLUDED_PY_IDS)} empty Python stubs (not ported).')


if __name__ == '__main__':
    main()
