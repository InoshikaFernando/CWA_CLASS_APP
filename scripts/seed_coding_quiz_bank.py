"""
seed_coding_quiz_bank.py
------------------------
Idempotent seeding pipeline to populate the Coding quiz bank for Flipzo sessions.

Coverage targets per (language, level) pair:
  - ≥ 15 multiple_choice questions
  - ≥ 5 short_answer questions
  - ≥ 5 true_false questions
  Total ≈ 300 questions across 12 pairs (4 languages × 3 levels).

Question flavours:
  1. Syntax recognition   — "Which of these is valid Python?"
  2. Concept understanding — "What does `let` do in JavaScript?"
  3. Debugging             — "What's wrong with this code?"
  4. Output prediction     — "What does `print(2 ** 3)` output?"
  5. True/False            — "`===` checks value only. True or False?"

Idempotency strategy:
  - Uses stable slug-based deduplication: creates slug from question text hash
  - Only top-ups missing questions per (language, level, question_type)
  - Safe to re-run multiple times; no deletes, only creates

Usage (from project root or scripts/ directory):
    python seed_coding_quiz_bank.py [--dry-run]

Add --dry-run to preview all changes without writing to the database.
"""

import os, sys, hashlib, random
from typing import Tuple, List, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
import django
django.setup()

from django.db import transaction
from coding.models import CodingExercise, CodingAnswer, CodingLanguage, CodingTopic, TopicLevel

DRY_RUN = '--dry-run' in sys.argv

# ────────────────────────────────────────────────────────────────────────────
# Configuration: coverage targets
# ────────────────────────────────────────────────────────────────────────────

TARGET_MCQ = 15
TARGET_SHORT_ANSWER = 5
TARGET_TRUE_FALSE = 5

LANGUAGES = ['python', 'javascript', 'html-css', 'scratch']
LEVELS = ['beginner', 'intermediate', 'advanced']

# ────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────

def slug_from_text(text: str) -> str:
    """Generate a stable slug from question text for idempotency checking."""
    h = hashlib.md5(text.encode('utf-8')).hexdigest()[:12]
    # Replace non-alphanumeric with underscores, truncate to avoid column limits
    safe_text = ''.join(c if c.isalnum() else '_' for c in text[:40].lower())
    return f"{safe_text}_{h}"


def get_or_create_topic_level(lang_slug: str, level: str) -> Tuple[TopicLevel, bool]:
    """Get or create a TopicLevel for a language's quiz bank at the given level.
    
    Returns (topic_level, created).
    """
    # Get or create language
    try:
        lang = CodingLanguage.objects.get(slug=lang_slug)
    except CodingLanguage.DoesNotExist:
        if DRY_RUN:
            # Dry-run: create a mock object
            lang = CodingLanguage(slug=lang_slug, name=lang_slug.title(), is_active=True)
        else:
            # Production: fail if language doesn't exist
            raise ValueError(f"CodingLanguage with slug '{lang_slug}' not found. "
                           f"Must be created via migration or upload.")

    # Get or create topic (all quizzes in one "Flipzo Quiz Bank" topic per language)
    topic_name = f"Flipzo Quiz Bank"
    topic_slug = "flipzo-quiz-bank"
    
    if lang.id:  # Only query if the language has an id (not a dry-run mock)
        topic, _ = CodingTopic.objects.get_or_create(
            language=lang,
            slug=topic_slug,
            defaults={'name': topic_name, 'is_active': True, 'order': 0},
        )
    else:
        # Dry-run mock
        topic = CodingTopic(language=lang, slug=topic_slug, name=topic_name, is_active=True)

    # Get or create TopicLevel at the given difficulty
    level_obj, created = TopicLevel.get_or_create_for(topic, level)
    return level_obj, created


def question_exists(topic_level: TopicLevel, slug: str) -> bool:
    """Check if a question with this slug already exists for the given topic_level."""
    if not topic_level.id:
        return False
    return CodingExercise.objects.filter(
        topic_level=topic_level,
        title=slug,  # We store the slug in the title for idempotency tracking
    ).exists()


def count_by_type(topic_level: TopicLevel, question_type: str) -> int:
    """Count questions of a given type in this topic_level."""
    if not topic_level.id:
        return 0
    return CodingExercise.objects.filter(
        topic_level=topic_level,
        question_type=question_type,
    ).count()


def create_mcq_question(topic_level: TopicLevel, title: str, question_text: str,
                        correct_answer: str, wrong_answers: List[str],
                        explanation: str = "") -> Tuple[CodingExercise, bool]:
    """Create or find an MCQ question. Returns (exercise, created)."""
    slug = slug_from_text(question_text)
    
    if question_exists(topic_level, slug):
        ex = CodingExercise.objects.get(topic_level=topic_level, title=slug)
        return ex, False

    if DRY_RUN or not topic_level.id:
        # Dry-run: return a mock
        ex = CodingExercise(
            topic_level=topic_level,
            title=slug,
            description=question_text,
            question_type=CodingExercise.MULTIPLE_CHOICE,
            is_active=True,
        )
        return ex, True

    # Create the exercise
    ex = CodingExercise.objects.create(
        topic_level=topic_level,
        title=slug,
        description=question_text,
        question_type=CodingExercise.MULTIPLE_CHOICE,
        is_active=True,
    )

    # Create 4 answer options: 1 correct + 3 wrong
    # Shuffle order for variety
    options = [correct_answer] + wrong_answers[:3]
    random.shuffle(options)

    for i, opt in enumerate(options):
        CodingAnswer.objects.create(
            exercise=ex,
            answer_text=opt,
            is_correct=(opt == correct_answer),
            order=i,
        )

    return ex, True


def create_tf_question(topic_level: TopicLevel, title: str, question_text: str,
                       correct_answer: bool, explanation: str = "") -> Tuple[CodingExercise, bool]:
    """Create or find a True/False question. Returns (exercise, created)."""
    slug = slug_from_text(question_text)
    
    if question_exists(topic_level, slug):
        ex = CodingExercise.objects.get(topic_level=topic_level, title=slug)
        return ex, False

    if DRY_RUN or not topic_level.id:
        ex = CodingExercise(
            topic_level=topic_level,
            title=slug,
            description=question_text,
            question_type=CodingExercise.TRUE_FALSE,
            is_active=True,
        )
        return ex, True

    ex = CodingExercise.objects.create(
        topic_level=topic_level,
        title=slug,
        description=question_text,
        question_type=CodingExercise.TRUE_FALSE,
        is_active=True,
    )

    # Always create True first, False second (canonical order)
    CodingAnswer.objects.create(
        exercise=ex,
        answer_text="True",
        is_correct=correct_answer,
        order=0,
    )
    CodingAnswer.objects.create(
        exercise=ex,
        answer_text="False",
        is_correct=not correct_answer,
        order=1,
    )

    return ex, True


def create_short_answer(topic_level: TopicLevel, title: str, question_text: str,
                        correct_answer: str, explanation: str = "") -> Tuple[CodingExercise, bool]:
    """Create or find a short-answer question. Returns (exercise, created)."""
    slug = slug_from_text(question_text)
    
    if question_exists(topic_level, slug):
        ex = CodingExercise.objects.get(topic_level=topic_level, title=slug)
        return ex, False

    if DRY_RUN or not topic_level.id:
        ex = CodingExercise(
            topic_level=topic_level,
            title=slug,
            description=question_text,
            question_type=CodingExercise.SHORT_ANSWER,
            correct_short_answer=correct_answer,
            is_active=True,
        )
        return ex, True

    ex = CodingExercise.objects.create(
        topic_level=topic_level,
        title=slug,
        description=question_text,
        question_type=CodingExercise.SHORT_ANSWER,
        correct_short_answer=correct_answer,
        is_active=True,
    )
    return ex, True


# ────────────────────────────────────────────────────────────────────────────
# Question definitions by language and level
# ────────────────────────────────────────────────────────────────────────────

PYTHON_BEGINNER_MCQ = [
    {
        'title': 'python_beginner_mcq_print_output',
        'question': 'What does print(2 + 3) output?',
        'correct': '5',
        'wrong': ['2 + 3', '5.0', 'Error'],
    },
    {
        'title': 'python_beginner_mcq_variable_syntax',
        'question': 'Which is valid Python to assign 10 to a variable?',
        'correct': 'x = 10',
        'wrong': ['10 = x', 'x := 10', '10 to x'],
    },
    {
        'title': 'python_beginner_mcq_string_quotes',
        'question': 'In Python, are single and double quotes equivalent for strings?',
        'correct': 'Yes, both work the same',
        'wrong': ['No, only double quotes work', 'No, only single quotes work', 'Quotes cannot be used'],
    },
    {
        'title': 'python_beginner_mcq_list_index',
        'question': 'What is the index of the first element in a Python list?',
        'correct': '0',
        'wrong': ['1', '-1', 'undefined'],
    },
    {
        'title': 'python_beginner_mcq_if_syntax',
        'question': 'Which correctly uses an if statement?',
        'correct': 'if x > 5:',
        'wrong': ['if (x > 5)', 'if x > 5 then:', 'if x > 5 {'],
    },
    {
        'title': 'python_beginner_mcq_loop_range',
        'question': 'What does range(5) generate?',
        'correct': '[0, 1, 2, 3, 4]',
        'wrong': ['[1, 2, 3, 4, 5]', '[0, 1, 2, 3, 4, 5]', '[5]'],
    },
    {
        'title': 'python_beginner_mcq_string_length',
        'question': 'How do you get the length of a string s?',
        'correct': 'len(s)',
        'wrong': ['s.length', 'length(s)', 's.size()'],
    },
    {
        'title': 'python_beginner_mcq_power_operator',
        'question': 'What does 2 ** 3 equal?',
        'correct': '8',
        'wrong': ['6', '9', 'Error'],
    },
    {
        'title': 'python_beginner_mcq_modulo_operator',
        'question': 'What is 10 % 3?',
        'correct': '1',
        'wrong': ['3', '0.333...', '10'],
    },
    {
        'title': 'python_beginner_mcq_string_concat',
        'question': 'What does "hello" + " world" produce?',
        'correct': '"hello world"',
        'wrong': ['"hello + world"', 'Error', 'None'],
    },
    {
        'title': 'python_beginner_mcq_input_function',
        'question': 'What does input() do?',
        'correct': 'Reads user input from the keyboard',
        'wrong': ['Prints to the screen', 'Creates a list', 'Defines a function'],
    },
    {
        'title': 'python_beginner_mcq_type_int',
        'question': 'What is the type of 5?',
        'correct': 'int',
        'wrong': ['float', 'str', 'number'],
    },
    {
        'title': 'python_beginner_mcq_type_string',
        'question': 'What is the type of "hello"?',
        'correct': 'str',
        'wrong': ['string', 'int', 'list'],
    },
    {
        'title': 'python_beginner_mcq_comparison_equal',
        'question': 'What does 5 == 5 return?',
        'correct': 'True',
        'wrong': ['False', '1', 'None'],
    },
    {
        'title': 'python_beginner_mcq_list_append',
        'question': 'How do you add an element to the end of a list?',
        'correct': 'list.append(element)',
        'wrong': ['list.add(element)', 'list.insert(element)', 'list.push(element)'],
    },
]

PYTHON_BEGINNER_SHORT_ANSWER = [
    {
        'title': 'python_beginner_short_power',
        'question': 'What does print(3 ** 2) output?',
        'answer': '9',
    },
    {
        'title': 'python_beginner_short_string_index',
        'question': 'What is s[1] if s = "hello"?',
        'answer': 'e',
    },
    {
        'title': 'python_beginner_short_division',
        'question': 'What is 15 // 4?',
        'answer': '3',
    },
    {
        'title': 'python_beginner_short_boolean',
        'question': 'What is 5 > 3?',
        'answer': 'True',
    },
    {
        'title': 'python_beginner_short_list_length',
        'question': 'What is len([1, 2, 3])?',
        'answer': '3',
    },
]

PYTHON_BEGINNER_TRUE_FALSE = [
    {
        'title': 'python_beginner_tf_quotes',
        'question': 'Single quotes and double quotes are equivalent in Python.',
        'correct': True,
    },
    {
        'title': 'python_beginner_tf_index_zero',
        'question': 'The first element of a list has index 0.',
        'correct': True,
    },
    {
        'title': 'python_beginner_tf_range_includes_end',
        'question': 'range(5) includes the number 5.',
        'correct': False,
    },
    {
        'title': 'python_beginner_tf_none_equals_zero',
        'question': 'None and 0 are equal in Python.',
        'correct': False,
    },
    {
        'title': 'python_beginner_tf_string_immutable',
        'question': 'Strings cannot be modified; they are immutable.',
        'correct': True,
    },
]

PYTHON_INTERMEDIATE_MCQ = [
    {
        'title': 'python_inter_mcq_list_slice',
        'question': 'What does [1, 2, 3, 4][1:3] return?',
        'correct': '[2, 3]',
        'wrong': ['[1, 2]', '[2, 3, 4]', '[1, 3]'],
    },
    {
        'title': 'python_inter_mcq_for_loop_list',
        'question': 'What does this code print?\nfor i in [10, 20]:\n    print(i)',
        'correct': '10\n20',
        'wrong': ['0\n1', '10 20', 'Error'],
    },
    {
        'title': 'python_inter_mcq_dict_access',
        'question': 'How do you access the value with key "name" from a dict d?',
        'correct': 'd["name"]',
        'wrong': ['d.name', 'd.get("name")', 'd["name"]()'],
    },
    {
        'title': 'python_inter_mcq_function_def',
        'question': 'Which correctly defines a function?',
        'correct': 'def my_func():\n    pass',
        'wrong': ['function my_func(){}', 'def my_func():', 'def my_func {}'],
    },
    {
        'title': 'python_inter_mcq_return_value',
        'question': 'What does this function return?\ndef f():\n    return 5 * 2',
        'correct': '10',
        'wrong': ['5', '2', 'None'],
    },
    {
        'title': 'python_inter_mcq_default_parameter',
        'question': 'What does this print?\ndef f(x=10):\n    return x\nprint(f())',
        'correct': '10',
        'wrong': ['None', '0', 'Error'],
    },
    {
        'title': 'python_inter_mcq_scope_global',
        'question': 'What is printed?\nx = 5\ndef f():\n    x = 10\n    return x\nprint(f())',
        'correct': '10',
        'wrong': ['5', 'Error', 'None'],
    },
    {
        'title': 'python_inter_mcq_list_in_operator',
        'question': 'What does 2 in [1, 2, 3] return?',
        'correct': 'True',
        'wrong': ['False', '1', 'None'],
    },
    {
        'title': 'python_inter_mcq_string_method',
        'question': 'What does "hello".upper() return?',
        'correct': '"HELLO"',
        'wrong': ['"Hello"', '"hello"', 'Error'],
    },
    {
        'title': 'python_inter_mcq_list_comprehension',
        'question': 'What does [x*2 for x in [1, 2, 3]] produce?',
        'correct': '[2, 4, 6]',
        'wrong': ['[1, 2, 3]', '[2, 4, 6, 8]', 'Error'],
    },
    {
        'title': 'python_inter_mcq_while_loop',
        'question': 'How many times does this loop run?\ni = 0\nwhile i < 3:\n    print(i)\n    i += 1',
        'correct': '3',
        'wrong': ['2', '4', 'Infinite'],
    },
    {
        'title': 'python_inter_mcq_and_operator',
        'question': 'What does True and False return?',
        'correct': 'False',
        'wrong': ['True', 'None', 'Error'],
    },
    {
        'title': 'python_inter_mcq_or_operator',
        'question': 'What does True or False return?',
        'correct': 'True',
        'wrong': ['False', '1', 'None'],
    },
    {
        'title': 'python_inter_mcq_not_operator',
        'question': 'What does not True return?',
        'correct': 'False',
        'wrong': ['True', '0', 'None'],
    },
    {
        'title': 'python_inter_mcq_dict_keys',
        'question': 'What does {"a": 1, "b": 2}.keys() return?',
        'correct': 'dict_keys(["a", "b"])',
        'wrong': ['["a", "b"]', '["1", "2"]', 'Error'],
    },
]

PYTHON_INTERMEDIATE_SHORT_ANSWER = [
    {
        'title': 'python_inter_short_slice',
        'question': 'What is [10, 20, 30, 40][1:3]?',
        'answer': '[20, 30]',
    },
    {
        'title': 'python_inter_short_dict_value',
        'question': 'What is {"x": 5}["x"]?',
        'answer': '5',
    },
    {
        'title': 'python_inter_short_function_call',
        'question': 'What does this return?\ndef add(a, b):\n    return a + b\nadd(3, 4)',
        'answer': '7',
    },
    {
        'title': 'python_inter_short_list_pop',
        'question': 'What does [1, 2, 3].pop() return?',
        'answer': '3',
    },
    {
        'title': 'python_inter_short_string_split',
        'question': 'What does "a,b,c".split(",") return?',
        'answer': "['a', 'b', 'c']",
    },
]

PYTHON_INTERMEDIATE_TRUE_FALSE = [
    {
        'title': 'python_inter_tf_slice_includes_end',
        'question': 'In Python slicing, the end index is included: [1, 2, 3][0:2] returns [1, 2, 3].',
        'correct': False,
    },
    {
        'title': 'python_inter_tf_dict_no_duplicates',
        'question': 'Dictionary keys can have duplicate values.',
        'correct': False,
    },
    {
        'title': 'python_inter_tf_function_returns_none',
        'question': 'A function without a return statement returns None.',
        'correct': True,
    },
    {
        'title': 'python_inter_tf_global_scope',
        'question': 'Variables defined inside a function are accessible outside it.',
        'correct': False,
    },
    {
        'title': 'python_inter_tf_list_mutable',
        'question': 'Lists are mutable; you can change their elements after creation.',
        'correct': True,
    },
]

PYTHON_ADVANCED_MCQ = [
    {
        'title': 'python_adv_mcq_generator',
        'question': 'What does this code create?\ndef gen():\n    yield 1\n    yield 2',
        'correct': 'A generator',
        'wrong': ['A list', 'A tuple', 'An iterator object'],
    },
    {
        'title': 'python_adv_mcq_lambda',
        'question': 'What does lambda x: x * 2 do?',
        'correct': 'Creates an anonymous function that doubles its input',
        'wrong': ['Creates a variable', 'Creates a class', 'Causes an error'],
    },
    {
        'title': 'python_adv_mcq_decorator',
        'question': 'What is a decorator?',
        'correct': 'A function that modifies another function or class',
        'wrong': ['A type of variable', 'A loop statement', 'A comment marker'],
    },
    {
        'title': 'python_adv_mcq_exception_try',
        'question': 'What does try...except do?',
        'correct': 'Catches and handles errors',
        'wrong': ['Prevents errors', 'Logs errors', 'Causes errors'],
    },
    {
        'title': 'python_adv_mcq_closure',
        'question': 'What is a closure?',
        'correct': 'A function that captures variables from its enclosing scope',
        'wrong': ['A loop that ends', 'A finished program', 'A class method'],
    },
    {
        'title': 'python_adv_mcq_list_vs_tuple',
        'question': 'What is the key difference between list and tuple?',
        'correct': 'Lists are mutable; tuples are immutable',
        'wrong': ['Tuples are faster', 'Lists cannot contain duplicates', 'Tuples cannot be indexed'],
    },
    {
        'title': 'python_adv_mcq_args_kwargs',
        'question': 'What does *args do in a function definition?',
        'correct': 'Allows the function to accept a variable number of positional arguments',
        'wrong': ['Multiplies arguments', 'Unpacks a list', 'Creates keyword arguments'],
    },
    {
        'title': 'python_adv_mcq_deepcopy',
        'question': 'What is the difference between copy and deepcopy?',
        'correct': 'copy makes a shallow copy; deepcopy makes a recursive copy',
        'wrong': ['No difference', 'deepcopy is faster', 'copy is for lists only'],
    },
    {
        'title': 'python_adv_mcq_property_decorator',
        'question': 'What does the @property decorator do?',
        'correct': 'Allows a method to be accessed as an attribute',
        'wrong': ['Creates a class variable', 'Makes a method private', 'Caches method results'],
    },
    {
        'title': 'python_adv_mcq_context_manager',
        'question': 'What is the purpose of with statement?',
        'correct': 'Ensures proper resource cleanup (e.g., file closing)',
        'wrong': ['Declares a scope', 'Creates a context variable', 'Imports a module'],
    },
    {
        'title': 'python_adv_mcq_metaclass',
        'question': 'What is a metaclass?',
        'correct': 'A class whose instances are classes',
        'wrong': ['A class method', 'A static method', 'A parent class'],
    },
    {
        'title': 'python_adv_mcq_map_function',
        'question': 'What does map(lambda x: x**2, [1, 2, 3]) return?',
        'correct': 'A map object; convert with list() for [1, 4, 9]',
        'wrong': ['[1, 4, 9]', '[1, 2, 3]', 'Error'],
    },
    {
        'title': 'python_adv_mcq_filter_function',
        'question': 'What does filter(lambda x: x > 2, [1, 2, 3]) return?',
        'correct': 'A filter object that yields [3] when converted',
        'wrong': ['[1, 2, 3]', '[3]', '[1, 2]'],
    },
    {
        'title': 'python_adv_mcq_virtual_env',
        'question': 'What is a virtual environment?',
        'correct': 'An isolated Python environment with its own dependencies',
        'wrong': ['A simulated computer', 'A Python interpreter', 'A code editor'],
    },
    {
        'title': 'python_adv_mcq_import_star',
        'question': 'What does "from module import *" do?',
        'correct': 'Imports all public names from the module',
        'wrong': ['Imports only functions', 'Creates a wildcard variable', 'Causes an error'],
    },
]

PYTHON_ADVANCED_SHORT_ANSWER = [
    {
        'title': 'python_adv_short_slice_negative',
        'question': 'What is [1, 2, 3, 4][-1]?',
        'answer': '4',
    },
    {
        'title': 'python_adv_short_dict_get',
        'question': 'What does {"a": 1}.get("b") return (not found)?',
        'answer': 'None',
    },
    {
        'title': 'python_adv_short_exception_type',
        'question': 'What exception is raised by 1 / 0?',
        'answer': 'ZeroDivisionError',
    },
    {
        'title': 'python_adv_short_inheritance',
        'question': 'How do you call a parent class method from a subclass?',
        'answer': 'super()',
    },
    {
        'title': 'python_adv_short_enumerate',
        'question': 'What does list(enumerate(["a", "b"])) return?',
        'answer': '[(0, "a"), (1, "b")]',
    },
]

PYTHON_ADVANCED_TRUE_FALSE = [
    {
        'title': 'python_adv_tf_generator_lazy',
        'question': 'Generators evaluate all values immediately when created.',
        'correct': False,
    },
    {
        'title': 'python_adv_tf_args_unpacking',
        'question': '*args allows you to pass a variable number of arguments to a function.',
        'correct': True,
    },
    {
        'title': 'python_adv_tf_keyword_only',
        'question': 'You can define keyword-only arguments in Python.',
        'correct': True,
    },
    {
        'title': 'python_adv_tf_private_name_mangling',
        'question': 'Attributes starting with double underscore are truly private in Python.',
        'correct': False,
    },
    {
        'title': 'python_adv_tf_none_singleton',
        'question': 'None is a singleton; there is only one None object in Python.',
        'correct': True,
    },
]

# ────────────────────────────────────────────────────────────────────────────
# JavaScript questions
# ────────────────────────────────────────────────────────────────────────────

JAVASCRIPT_BEGINNER_MCQ = [
    {
        'title': 'js_beginner_mcq_console_log',
        'question': 'What does console.log("hello") do?',
        'correct': 'Prints "hello" to the console',
        'wrong': ['Logs in to the console', 'Creates a variable', 'Causes an error'],
    },
    {
        'title': 'js_beginner_mcq_var_let_const',
        'question': 'Which is NOT a way to declare a variable?',
        'correct': 'variable x = 5',
        'wrong': ['var x = 5', 'let x = 5', 'const x = 5'],
    },
    {
        'title': 'js_beginner_mcq_string_quotes',
        'question': 'In JavaScript, are "hello" and \'hello\' the same?',
        'correct': 'Yes, both are strings',
        'wrong': ['No, only double quotes work', 'No, only single quotes work', 'They are different types'],
    },
    {
        'title': 'js_beginner_mcq_array_index',
        'question': 'What is the index of the first element in an array?',
        'correct': '0',
        'wrong': ['1', '-1', 'undefined'],
    },
    {
        'title': 'js_beginner_mcq_function_syntax',
        'question': 'Which is valid JavaScript function syntax?',
        'correct': 'function myFunc() { }',
        'wrong': ['def myFunc():', 'func myFunc() { }', 'myFunc() function { }'],
    },
    {
        'title': 'js_beginner_mcq_if_statement',
        'question': 'Which is correct?',
        'correct': 'if (x > 5) { }',
        'wrong': ['if x > 5 { }', 'if x > 5:', 'if (x > 5)'],
    },
    {
        'title': 'js_beginner_mcq_typeof',
        'question': 'What does typeof "hello" return?',
        'correct': '"string"',
        'wrong': ['"String"', 'string', 'null'],
    },
    {
        'title': 'js_beginner_mcq_addition',
        'question': 'What is 5 + 3?',
        'correct': '8',
        'wrong': ['53', '15', '8.0'],
    },
    {
        'title': 'js_beginner_mcq_string_concat',
        'question': 'What does "hello" + " " + "world" produce?',
        'correct': '"hello world"',
        'wrong': ['"hello + world"', 'Error', 'undefined'],
    },
    {
        'title': 'js_beginner_mcq_array_length',
        'question': 'How do you get the length of an array arr?',
        'correct': 'arr.length',
        'wrong': ['arr.size', 'length(arr)', 'arr.count()'],
    },
    {
        'title': 'js_beginner_mcq_undefined_vs_null',
        'question': 'What is the difference between undefined and null?',
        'correct': 'undefined is uninitialized; null is intentionally empty',
        'wrong': ['No difference', 'null is a number', 'undefined is an error'],
    },
    {
        'title': 'js_beginner_mcq_for_loop',
        'question': 'Which is a for loop?',
        'correct': 'for (let i = 0; i < 5; i++) { }',
        'wrong': ['for i in range(5):', 'for i := 0; i < 5; i++', 'for (let i: 0 to 5)'],
    },
    {
        'title': 'js_beginner_mcq_const_reassign',
        'question': 'Can you reassign a const variable?',
        'correct': 'No, const cannot be reassigned',
        'wrong': ['Yes, it can be reassigned', 'Only once', 'It depends on the browser'],
    },
    {
        'title': 'js_beginner_mcq_object_property',
        'question': 'How do you access a property "name" from an object obj?',
        'correct': 'obj.name or obj["name"]',
        'wrong': ['obj->name', 'obj:name', 'obj.getName()'],
    },
    {
        'title': 'js_beginner_mcq_array_push',
        'question': 'What does arr.push(5) do?',
        'correct': 'Adds 5 to the end of the array',
        'wrong': ['Creates a new array', 'Removes 5 from the array', 'Pushes arr to output'],
    },
]

JAVASCRIPT_BEGINNER_SHORT_ANSWER = [
    {
        'title': 'js_beginner_short_arithmetic',
        'question': 'What is 10 - 3?',
        'answer': '7',
    },
    {
        'title': 'js_beginner_short_modulo',
        'question': 'What is 10 % 3?',
        'answer': '1',
    },
    {
        'title': 'js_beginner_short_array_access',
        'question': 'What is [10, 20, 30][1]?',
        'answer': '20',
    },
    {
        'title': 'js_beginner_short_typeof_number',
        'question': 'What does typeof 42 return?',
        'answer': '"number"',
    },
    {
        'title': 'js_beginner_short_equality',
        'question': 'What is 5 == "5"?',
        'answer': 'true',
    },
]

JAVASCRIPT_BEGINNER_TRUE_FALSE = [
    {
        'title': 'js_beginner_tf_semicolons_required',
        'question': 'Semicolons are required at the end of every statement in JavaScript.',
        'correct': False,
    },
    {
        'title': 'js_beginner_tf_case_sensitive',
        'question': 'JavaScript is case-sensitive.',
        'correct': True,
    },
    {
        'title': 'js_beginner_tf_arrays_zero_indexed',
        'question': 'Arrays are zero-indexed in JavaScript.',
        'correct': True,
    },
    {
        'title': 'js_beginner_tf_null_object',
        'question': 'typeof null returns "object".',
        'correct': True,
    },
    {
        'title': 'js_beginner_tf_var_block_scoped',
        'question': 'Variables declared with var are block-scoped.',
        'correct': False,
    },
]

JAVASCRIPT_INTERMEDIATE_MCQ = [
    {
        'title': 'js_inter_mcq_strict_equality',
        'question': 'What is the difference between == and ===?',
        'correct': '=== is strict equality (no type coercion)',
        'wrong': ['No difference', '== is faster', '=== only works for numbers'],
    },
    {
        'title': 'js_inter_mcq_arrow_function',
        'question': 'What is an arrow function?',
        'correct': '() => { } is a shorthand for function syntax',
        'wrong': ['A comment', 'A comparison operator', 'A loop structure'],
    },
    {
        'title': 'js_inter_mcq_callback',
        'question': 'What is a callback function?',
        'correct': 'A function passed as an argument to another function',
        'wrong': ['A function that calls itself', 'An error handler', 'A return value'],
    },
    {
        'title': 'js_inter_mcq_promise',
        'question': 'What is a Promise?',
        'correct': 'An object representing a value that may be available later',
        'wrong': ['A variable declaration', 'A loop', 'A type of string'],
    },
    {
        'title': 'js_inter_mcq_async_await',
        'question': 'What does async before a function do?',
        'correct': 'Allows use of await and always returns a Promise',
        'wrong': ['Makes the function synchronous', 'Runs it immediately', 'Caches the result'],
    },
    {
        'title': 'js_inter_mcq_this_context',
        'question': 'What does "this" refer to in a method?',
        'correct': 'The object the method belongs to',
        'wrong': ['The function itself', 'The global object', 'undefined'],
    },
    {
        'title': 'js_inter_mcq_closure',
        'question': 'What is a closure?',
        'correct': 'A function that captures variables from its outer scope',
        'wrong': ['A loop that ends', 'A finished program', 'A type error'],
    },
    {
        'title': 'js_inter_mcq_map_array',
        'question': 'What does [1, 2, 3].map(x => x * 2) return?',
        'correct': '[2, 4, 6]',
        'wrong': ['[1, 2, 3]', '[2, 4, 6, 8]', 'Error'],
    },
    {
        'title': 'js_inter_mcq_filter_array',
        'question': 'What does [1, 2, 3].filter(x => x > 1) return?',
        'correct': '[2, 3]',
        'wrong': ['[1, 2, 3]', '[2]', '[3]'],
    },
    {
        'title': 'js_inter_mcq_reduce',
        'question': 'What does [1, 2, 3].reduce((a, b) => a + b) return?',
        'correct': '6',
        'wrong': ['[1, 2, 3]', '[6]', 'undefined'],
    },
    {
        'title': 'js_inter_mcq_spread_operator',
        'question': 'What does ...arr do?',
        'correct': 'Spreads array elements as individual arguments',
        'wrong': ['Multiplies elements', 'Creates a copy', 'Causes an error'],
    },
    {
        'title': 'js_inter_mcq_destructuring',
        'question': 'What does const {x, y} = {x: 1, y: 2} do?',
        'correct': 'Extracts x and y from the object',
        'wrong': ['Creates a new object', 'Causes an error', 'Deletes x and y'],
    },
    {
        'title': 'js_inter_mcq_try_catch',
        'question': 'What is try...catch used for?',
        'correct': 'Catching and handling errors',
        'wrong': ['Preventing errors', 'Logging errors', 'Retrying code'],
    },
    {
        'title': 'js_inter_mcq_event_listener',
        'question': 'How do you add a click listener?',
        'correct': 'element.addEventListener("click", callback)',
        'wrong': ['element.onClick = callback', 'element.click(callback)', 'element.on("click", callback)'],
    },
    {
        'title': 'js_inter_mcq_json_stringify',
        'question': 'What does JSON.stringify({x: 1}) return?',
        'correct': '"{\\"x\\":1}"',
        'wrong': ['{x: 1}', '[1]', 'Error'],
    },
]

JAVASCRIPT_INTERMEDIATE_SHORT_ANSWER = [
    {
        'title': 'js_inter_short_array_slice',
        'question': 'What does [1, 2, 3, 4].slice(1, 3) return?',
        'answer': '[2, 3]',
    },
    {
        'title': 'js_inter_short_includes',
        'question': 'What does [1, 2, 3].includes(2) return?',
        'answer': 'true',
    },
    {
        'title': 'js_inter_short_find',
        'question': 'What does [1, 2, 3].find(x => x > 2) return?',
        'answer': '3',
    },
    {
        'title': 'js_inter_short_object_keys',
        'question': 'What does Object.keys({a: 1, b: 2}) return?',
        'answer': '["a", "b"]',
    },
    {
        'title': 'js_inter_short_number_methods',
        'question': 'What does (3.14).toFixed(1) return?',
        'answer': '"3.1"',
    },
]

JAVASCRIPT_INTERMEDIATE_TRUE_FALSE = [
    {
        'title': 'js_inter_tf_equality_coercion',
        'question': '"" == 0 is true due to type coercion.',
        'correct': True,
    },
    {
        'title': 'js_inter_tf_arrow_function_this',
        'question': 'Arrow functions have their own "this" binding.',
        'correct': False,
    },
    {
        'title': 'js_inter_tf_promise_return_value',
        'question': 'A Promise can only resolve once.',
        'correct': True,
    },
    {
        'title': 'js_inter_tf_async_implicit_promise',
        'question': 'An async function always returns a Promise.',
        'correct': True,
    },
    {
        'title': 'js_inter_tf_var_hoisting',
        'question': 'Variables declared with var are hoisted to the top of their scope.',
        'correct': True,
    },
]

JAVASCRIPT_ADVANCED_MCQ = [
    {
        'title': 'js_adv_mcq_prototype',
        'question': 'What is prototypal inheritance?',
        'correct': 'Objects inherit from other objects via their prototype chain',
        'wrong': ['Inheritance via classes only', 'Inheritance via interfaces', 'No inheritance in JS'],
    },
    {
        'title': 'js_adv_mcq_this_binding',
        'question': 'How many ways can "this" be bound?',
        'correct': 'Four: default, implicit, explicit, and new',
        'wrong': ['One', 'Two', 'Three'],
    },
    {
        'title': 'js_adv_mcq_event_bubbling',
        'question': 'What is event bubbling?',
        'correct': 'Events propagate from child to parent elements',
        'wrong': ['Events propagate from parent to child', 'Events trigger twice', 'Events trigger only once'],
    },
    {
        'title': 'js_adv_mcq_module_pattern',
        'question': 'What is the module pattern used for?',
        'correct': 'Creating private and public members in JavaScript',
        'wrong': ['Loading external files', 'Creating classes', 'Organizing imports'],
    },
    {
        'title': 'js_adv_mcq_higher_order_function',
        'question': 'What is a higher-order function?',
        'correct': 'A function that takes or returns another function',
        'wrong': ['A function with more parameters', 'A nested function', 'A recursive function'],
    },
    {
        'title': 'js_adv_mcq_composition',
        'question': 'What is function composition?',
        'correct': 'Combining functions so output of one is input to another',
        'wrong': ['Writing multiple functions', 'Nesting functions', 'Calling functions in sequence'],
    },
    {
        'title': 'js_adv_mcq_memoization',
        'question': 'What is memoization?',
        'correct': 'Caching function results to avoid recomputation',
        'wrong': ['Recording memory usage', 'Storing objects', 'Deleting variables'],
    },
    {
        'title': 'js_adv_mcq_event_delegation',
        'question': 'What is event delegation?',
        'correct': 'Attaching listeners to parent to handle child events',
        'wrong': ['Delegating tasks to other functions', 'Preventing event propagation', 'Creating new events'],
    },
    {
        'title': 'js_adv_mcq_proxy_object',
        'question': 'What is a Proxy?',
        'correct': 'An object that intercepts and customizes operations',
        'wrong': ['A network intermediary', 'A backup object', 'A temporary variable'],
    },
    {
        'title': 'js_adv_mcq_reflect_api',
        'question': 'What is the Reflect API used for?',
        'correct': 'Intercepting object operations at a meta level',
        'wrong': ['Reflecting light', 'Creating mirrors', 'Debugging code'],
    },
    {
        'title': 'js_adv_mcq_strict_mode',
        'question': 'What does "use strict" do?',
        'correct': 'Enables strict mode, enforcing stricter parsing and error handling',
        'wrong': ['Makes the code strict typing', 'Prevents all errors', 'Requires semicolons'],
    },
    {
        'title': 'js_adv_mcq_web_worker',
        'question': 'What is a Web Worker?',
        'correct': 'A script that runs in the background without blocking the UI',
        'wrong': ['A person who builds websites', 'A function that works', 'A server-side process'],
    },
    {
        'title': 'js_adv_mcq_throttle_debounce',
        'question': 'What is the difference between throttle and debounce?',
        'correct': 'Throttle limits frequency; debounce delays until activity stops',
        'wrong': ['No difference', 'Opposite effects', 'Only throttle exists'],
    },
    {
        'title': 'js_adv_mcq_optional_chaining',
        'question': 'What does obj?.prop do?',
        'correct': 'Safely accesses nested properties, returning undefined if null/undefined',
        'wrong': ['Deletes the property', 'Creates a new property', 'Causes an error'],
    },
    {
        'title': 'js_adv_mcq_nullish_coalescing',
        'question': 'What does a ?? b do?',
        'correct': 'Returns b only if a is null or undefined',
        'wrong': ['Returns b if a is falsy', 'Returns a and b', 'Causes an error'],
    },
]

JAVASCRIPT_ADVANCED_SHORT_ANSWER = [
    {
        'title': 'js_adv_short_closure_value',
        'question': 'What does this return?\nfunction outer() {\n  let x = 10;\n  return () => x;\n}\nouter()()',
        'answer': '10',
    },
    {
        'title': 'js_adv_short_bind_this',
        'question': 'What does func.bind(obj) return?',
        'answer': 'A new function with "this" permanently bound to obj',
    },
    {
        'title': 'js_adv_short_promise_then',
        'question': 'What does Promise.resolve(5).then(x => x * 2) return?',
        'answer': 'A Promise that resolves to 10',
    },
    {
        'title': 'js_adv_short_async_await_result',
        'question': 'What does await Promise.resolve(42) return?',
        'answer': '42',
    },
    {
        'title': 'js_adv_short_symbol',
        'question': 'What does typeof Symbol("id") return?',
        'answer': '"symbol"',
    },
]

JAVASCRIPT_ADVANCED_TRUE_FALSE = [
    {
        'title': 'js_adv_tf_prototype_chain',
        'question': 'All JavaScript objects inherit from Object.prototype.',
        'correct': True,
    },
    {
        'title': 'js_adv_tf_call_vs_apply',
        'question': 'call() and apply() are identical except for argument passing.',
        'correct': True,
    },
    {
        'title': 'js_adv_tf_promise_rejection',
        'question': 'An unhandled Promise rejection will crash the program.',
        'correct': False,
    },
    {
        'title': 'js_adv_tf_generator_one_shot',
        'question': 'Generators can only be iterated once.',
        'correct': True,
    },
    {
        'title': 'js_adv_tf_symbols_unique',
        'question': 'Two Symbols with the same description are equal.',
        'correct': False,
    },
]

# ────────────────────────────────────────────────────────────────────────────
# HTML/CSS questions
# ────────────────────────────────────────────────────────────────────────────

HTML_CSS_BEGINNER_MCQ = [
    {
        'title': 'html_beginner_mcq_doctype',
        'question': 'What is the <!DOCTYPE html> tag used for?',
        'correct': 'Declares the document type as HTML5',
        'wrong': ['Imports a library', 'Defines a variable', 'Creates a comment'],
    },
    {
        'title': 'html_beginner_mcq_structure',
        'question': 'Which is the correct HTML structure?',
        'correct': '<html><head></head><body></body></html>',
        'wrong': ['<html><body><head></head></body></html>', '<head><body></body><html></html>', '<body><head></head></body>'],
    },
    {
        'title': 'html_beginner_mcq_meta_charset',
        'question': 'What does <meta charset="UTF-8"> do?',
        'correct': 'Specifies the character encoding for the document',
        'wrong': ['Imports an external file', 'Creates metadata', 'Displays text'],
    },
    {
        'title': 'html_beginner_mcq_heading_tags',
        'question': 'What is the largest heading tag?',
        'correct': '<h1>',
        'wrong': ['<h2>', '<heading>', '<title>'],
    },
    {
        'title': 'html_beginner_mcq_paragraph_tag',
        'question': 'Which tag creates a paragraph?',
        'correct': '<p>',
        'wrong': ['<para>', '<text>', '<div>'],
    },
    {
        'title': 'html_beginner_mcq_link_tag',
        'question': 'How do you create a hyperlink?',
        'correct': '<a href="url">link</a>',
        'wrong': ['<link url>', '<href>link</href>', '<url>link</url>'],
    },
    {
        'title': 'html_beginner_mcq_image_tag',
        'question': 'Which is correct for images?',
        'correct': '<img src="image.jpg" alt="description">',
        'wrong': ['<image src="image.jpg">', '<img href="image.jpg">', '<image url="image.jpg">'],
    },
    {
        'title': 'html_beginner_mcq_list_ordered',
        'question': 'Which tag creates an ordered list?',
        'correct': '<ol>',
        'wrong': ['<ul>', '<list>', '<ol-list>'],
    },
    {
        'title': 'html_beginner_mcq_list_unordered',
        'question': 'Which tag creates an unordered list?',
        'correct': '<ul>',
        'wrong': ['<ol>', '<list>', '<ul-list>'],
    },
    {
        'title': 'html_beginner_mcq_list_item',
        'question': 'What tag is used for list items?',
        'correct': '<li>',
        'wrong': ['<item>', '<li-item>', '<list-item>'],
    },
    {
        'title': 'html_beginner_mcq_form_tag',
        'question': 'Which tag creates a form?',
        'correct': '<form>',
        'wrong': ['<input-form>', '<fields>', '<form-control>'],
    },
    {
        'title': 'html_beginner_mcq_input_tag',
        'question': 'Which creates a text input?',
        'correct': '<input type="text">',
        'wrong': ['<text>', '<input text>', '<textarea type="text">'],
    },
    {
        'title': 'html_beginner_mcq_button_tag',
        'question': 'How do you create a button?',
        'correct': '<button>Click me</button>',
        'wrong': ['<btn>', '<input button>', '<push>'],
    },
    {
        'title': 'html_beginner_mcq_semantic_header',
        'question': 'Which tag represents a header?',
        'correct': '<header>',
        'wrong': ['<head>', '<title>', '<nav>'],
    },
    {
        'title': 'css_beginner_mcq_selector_element',
        'question': 'How do you select all p elements with CSS?',
        'correct': 'p { }',
        'wrong': ['p() { }', '.p { }', '#p { }'],
    },
]

HTML_CSS_BEGINNER_SHORT_ANSWER = [
    {
        'title': 'html_beginner_short_h1_tag',
        'question': 'What HTML tag displays the largest heading?',
        'answer': '<h1>',
    },
    {
        'title': 'html_beginner_short_em_tag',
        'question': 'What HTML tag makes text emphasized?',
        'answer': '<em>',
    },
    {
        'title': 'html_beginner_short_strong_tag',
        'question': 'What HTML tag makes text strong/bold?',
        'answer': '<strong>',
    },
    {
        'title': 'css_beginner_short_color',
        'question': 'What CSS property changes text color?',
        'answer': 'color',
    },
    {
        'title': 'css_beginner_short_font_size',
        'question': 'What CSS property sets the font size?',
        'answer': 'font-size',
    },
]

HTML_CSS_BEGINNER_TRUE_FALSE = [
    {
        'title': 'html_beginner_tf_closing_tag',
        'question': 'All HTML tags must have a closing tag.',
        'correct': False,
    },
    {
        'title': 'html_beginner_tf_attributes',
        'question': 'HTML attributes provide additional information about elements.',
        'correct': True,
    },
    {
        'title': 'css_beginner_tf_case_sensitive',
        'question': 'CSS property names are case-sensitive.',
        'correct': False,
    },
    {
        'title': 'css_beginner_tf_inline_style',
        'question': 'You can apply CSS inline using the style attribute.',
        'correct': True,
    },
    {
        'title': 'html_beginner_tf_nested_elements',
        'question': 'HTML elements can be nested inside other elements.',
        'correct': True,
    },
]

HTML_CSS_INTERMEDIATE_MCQ = [
    {
        'title': 'css_inter_mcq_box_model',
        'question': 'What does the CSS box model include?',
        'correct': 'Content, padding, border, and margin',
        'wrong': ['Only padding and margin', 'Only border and content', 'Width and height only'],
    },
    {
        'title': 'css_inter_mcq_display_block',
        'question': 'What does display: block do?',
        'correct': 'Makes an element take up a full line (100% width)',
        'wrong': ['Hides the element', 'Centers the element', 'Makes it transparent'],
    },
    {
        'title': 'css_inter_mcq_display_inline',
        'question': 'What does display: inline do?',
        'correct': 'Makes an element flow inline with text',
        'wrong': ['Makes it a full line', 'Hides it', 'Makes it centered'],
    },
    {
        'title': 'css_inter_mcq_display_flex',
        'question': 'What does display: flex do?',
        'correct': 'Enables flexbox layout for flexible child alignment',
        'wrong': ['Makes elements flexible width', 'Creates a fixed width', 'Hides overflow'],
    },
    {
        'title': 'css_inter_mcq_position_static',
        'question': 'What is the default position value?',
        'correct': 'static',
        'wrong': ['relative', 'absolute', 'fixed'],
    },
    {
        'title': 'css_inter_mcq_position_relative',
        'question': 'What does position: relative do?',
        'correct': 'Positions relative to its normal position',
        'wrong': ['Positions relative to parent', 'Removes from document flow', 'Fixes to viewport'],
    },
    {
        'title': 'css_inter_mcq_position_absolute',
        'question': 'What does position: absolute do?',
        'correct': 'Positions relative to the nearest positioned parent',
        'wrong': ['Positions relative to viewport', 'Normal positioning', 'Relative to body'],
    },
    {
        'title': 'html_inter_mcq_semantic_article',
        'question': 'What does <article> represent?',
        'correct': 'A self-contained piece of content',
        'wrong': ['The main content area', 'A section of navigation', 'A footer'],
    },
    {
        'title': 'html_inter_mcq_semantic_section',
        'question': 'What does <section> represent?',
        'correct': 'A thematic grouping of content',
        'wrong': ['A paragraph', 'A division (like div)', 'A header'],
    },
    {
        'title': 'html_inter_mcq_input_checkbox',
        'question': 'What does <input type="checkbox"> create?',
        'correct': 'A checkbox for multiple selections',
        'wrong': ['A radio button', 'A text field', 'A button'],
    },
    {
        'title': 'css_inter_mcq_margin_collapse',
        'question': 'What is margin collapsing?',
        'correct': 'Adjacent margins combine into one larger margin',
        'wrong': ['Margins disappear', 'Margins double', 'Margins are ignored'],
    },
    {
        'title': 'css_inter_mcq_z_index',
        'question': 'What does z-index control?',
        'correct': 'The stacking order of positioned elements',
        'wrong': ['Horizontal positioning', 'Vertical positioning', 'Element opacity'],
    },
    {
        'title': 'css_inter_mcq_pseudo_class',
        'question': 'What is a pseudo-class?',
        'correct': 'A keyword added to a selector to define element state',
        'wrong': ['A fake class in CSS', 'An error in CSS', 'A JavaScript class'],
    },
    {
        'title': 'css_inter_mcq_pseudo_element',
        'question': 'Which is a pseudo-element?',
        'correct': '::before',
        'wrong': [':hover', ':focus', ':active'],
    },
    {
        'title': 'html_inter_mcq_data_attribute',
        'question': 'How do you create a custom data attribute?',
        'correct': '<div data-id="123">',
        'wrong': ['<div custom-id="123">', '<div id-data="123">', '<div dataattr="123">'],
    },
]

HTML_CSS_INTERMEDIATE_SHORT_ANSWER = [
    {
        'title': 'css_inter_short_padding_vs_margin',
        'question': 'What is the difference between padding and margin?',
        'answer': 'Padding is inside the border; margin is outside',
    },
    {
        'title': 'css_inter_short_flex_direction',
        'question': 'What does flex-direction: column do?',
        'answer': 'Arranges flex items vertically',
    },
    {
        'title': 'html_inter_short_label_for',
        'question': 'What attribute links a label to an input?',
        'answer': 'for',
    },
    {
        'title': 'css_inter_short_hover_selector',
        'question': 'How do you style an element on hover?',
        'answer': ':hover',
    },
    {
        'title': 'css_inter_short_opacity_range',
        'question': 'What is the range for opacity values?',
        'answer': '0 to 1',
    },
]

HTML_CSS_INTERMEDIATE_TRUE_FALSE = [
    {
        'title': 'css_inter_tf_margin_negative',
        'question': 'Margins can be negative.',
        'correct': True,
    },
    {
        'title': 'css_inter_tf_padding_negative',
        'question': 'Padding can be negative.',
        'correct': False,
    },
    {
        'title': 'css_inter_tf_z_index_negative',
        'question': 'z-index can have negative values.',
        'correct': True,
    },
    {
        'title': 'css_inter_tf_float_removed',
        'question': 'Float is completely replaced by flexbox and grid.',
        'correct': False,
    },
    {
        'title': 'html_inter_tf_svg_scalable',
        'question': '<svg> images scale without losing quality.',
        'correct': True,
    },
]

HTML_CSS_ADVANCED_MCQ = [
    {
        'title': 'css_adv_mcq_css_grid',
        'question': 'What does CSS Grid allow?',
        'correct': '2D layout control with rows and columns',
        'wrong': ['Only 1D layouts', 'Only row layouts', 'No alignment control'],
    },
    {
        'title': 'css_adv_mcq_grid_auto_fit',
        'question': 'What is the difference between auto-fit and auto-fill?',
        'correct': 'auto-fit collapses empty tracks; auto-fill preserves them',
        'wrong': ['No difference', 'Opposite effects', 'auto-fill is deprecated'],
    },
    {
        'title': 'css_adv_mcq_transform',
        'question': 'What does CSS transform do?',
        'correct': 'Applies 2D or 3D transformations without affecting layout',
        'wrong': ['Changes the element type', 'Modifies layout', 'Animates the element'],
    },
    {
        'title': 'css_adv_mcq_transition',
        'question': 'What does CSS transition do?',
        'correct': 'Smoothly animates property changes over time',
        'wrong': ['Changes element type', 'Moves elements', 'Creates new elements'],
    },
    {
        'title': 'css_adv_mcq_animation',
        'question': 'What is the difference between transition and animation?',
        'correct': 'Animation can loop and has keyframes; transition is one-time',
        'wrong': ['No difference', 'Animation is faster', 'Transition is more advanced'],
    },
    {
        'title': 'css_adv_mcq_calc_function',
        'question': 'What does calc() do in CSS?',
        'correct': 'Performs calculations for values (e.g., width: calc(100% - 20px))',
        'wrong': ['Calculates element size', 'Performs math on JavaScript', 'Optimizes performance'],
    },
    {
        'title': 'css_adv_mcq_custom_properties',
        'question': 'What are CSS custom properties (variables)?',
        'correct': 'Reusable values defined with -- prefix',
        'wrong': ['JavaScript variables', 'Conditional properties', 'Pseudo-elements'],
    },
    {
        'title': 'css_adv_mcq_specificity',
        'question': 'What is CSS specificity?',
        'correct': 'A measure of how specific a selector is (IDs, classes, elements)',
        'wrong': ['How accurate CSS is', 'The speed of CSS', 'Browser support'],
    },
    {
        'title': 'css_adv_mcq_cascade',
        'question': 'What is the CSS cascade?',
        'correct': 'The process of determining which styles apply when multiple selectors match',
        'wrong': ['Water flowing down', 'Style inheritance only', 'Browser defaults'],
    },
    {
        'title': 'css_adv_mcq_media_query',
        'question': 'What are media queries used for?',
        'correct': 'Applying styles based on device characteristics (screen size, etc.)',
        'wrong': ['Loading external CSS', 'Creating responsive layouts only', 'Browser detection'],
    },
    {
        'title': 'css_adv_mcq_stacking_context',
        'question': 'What is a stacking context?',
        'correct': 'A layer created by certain CSS properties that affects z-index stacking',
        'wrong': ['A bug in CSS', 'A browser feature', 'An HTML element'],
    },
    {
        'title': 'css_adv_mcq_bfc',
        'question': 'What is Block Formatting Context (BFC)?',
        'correct': 'A layout region where floats, margins, and overflow are isolated',
        'wrong': ['A browser format', 'A CSS property', 'A layout mode'],
    },
    {
        'title': 'html_adv_mcq_canvas',
        'question': 'What is <canvas> used for?',
        'correct': 'Drawing graphics with JavaScript',
        'wrong': ['Creating text areas', 'Displaying images', 'Creating forms'],
    },
    {
        'title': 'html_adv_mcq_svg_vs_canvas',
        'question': 'What is the key difference between SVG and Canvas?',
        'correct': 'SVG is vector-based and DOM-queryable; Canvas is raster and pixel-based',
        'wrong': ['No difference', 'SVG is faster', 'Canvas is scalable'],
    },
    {
        'title': 'css_adv_mcq_will_change',
        'question': 'What does will-change property do?',
        'correct': 'Hints to the browser about future transformations for optimization',
        'wrong': ['Changes element style', 'Predicts future sizes', 'Animates automatically'],
    },
]

HTML_CSS_ADVANCED_SHORT_ANSWER = [
    {
        'title': 'css_adv_short_grid_template_columns',
        'question': 'What does grid-template-columns: 1fr 2fr 1fr create?',
        'answer': '3 columns with 1:2:1 width ratio',
    },
    {
        'title': 'css_adv_short_flexbox_gap',
        'question': 'What does gap: 10px do in flexbox?',
        'answer': 'Adds 10px space between flex items',
    },
    {
        'title': 'css_adv_short_transform_rotate',
        'question': 'What does transform: rotate(45deg) do?',
        'answer': 'Rotates the element 45 degrees clockwise',
    },
    {
        'title': 'html_adv_short_accessibility_role',
        'question': 'What attribute defines an element\'s accessibility role?',
        'answer': 'role',
    },
    {
        'title': 'html_adv_short_aria_label',
        'question': 'What is the ARIA attribute for screen reader text?',
        'answer': 'aria-label',
    },
]

HTML_CSS_ADVANCED_TRUE_FALSE = [
    {
        'title': 'css_adv_tf_transform_layout',
        'question': 'Transform does not affect the document layout.',
        'correct': True,
    },
    {
        'title': 'css_adv_tf_will_change_performance',
        'question': 'Using will-change always improves performance.',
        'correct': False,
    },
    {
        'title': 'css_adv_tf_grid_auto_placement',
        'question': 'Grid automatically places items if grid-auto-flow is set.',
        'correct': True,
    },
    {
        'title': 'css_adv_tf_focus_visible',
        'question': 'focus-visible targets keyboard focus only, not mouse click.',
        'correct': True,
    },
    {
        'title': 'html_adv_tf_web_components',
        'question': 'Web Components are fully supported in all browsers.',
        'correct': False,
    },
]

# ────────────────────────────────────────────────────────────────────────────
# Scratch questions (simplified, beginner/intermediate only)
# ────────────────────────────────────────────────────────────────────────────

SCRATCH_BEGINNER_MCQ = [
    {
        'title': 'scratch_beginner_mcq_sprite',
        'question': 'What is a sprite in Scratch?',
        'correct': 'A character or object you can control',
        'wrong': ['A type of block', 'A code editor', 'A sound effect'],
    },
    {
        'title': 'scratch_beginner_mcq_block_event',
        'question': 'What is an event block?',
        'correct': 'A block that triggers when something happens',
        'wrong': ['A bug in code', 'A loop', 'A variable'],
    },
    {
        'title': 'scratch_beginner_mcq_green_flag',
        'question': 'What does clicking the green flag do?',
        'correct': 'Starts the script',
        'wrong': ['Stops the script', 'Resets the script', 'Creates a new sprite'],
    },
    {
        'title': 'scratch_beginner_mcq_move_steps',
        'question': 'What does "move 10 steps" do?',
        'correct': 'Moves the sprite forward 10 pixels',
        'wrong': ['Moves 10 times', 'Moves backward', 'Changes size by 10'],
    },
    {
        'title': 'scratch_beginner_mcq_repeat_block',
        'question': 'What is a repeat block?',
        'correct': 'A loop that runs code multiple times',
        'wrong': ['A backup of code', 'A variable', 'A function'],
    },
    {
        'title': 'scratch_beginner_mcq_if_block',
        'question': 'What is an if block?',
        'correct': 'A conditional that runs code if a condition is true',
        'wrong': ['A loop', 'A variable', 'A sprite'],
    },
    {
        'title': 'scratch_beginner_mcq_variable',
        'question': 'What is a variable in Scratch?',
        'correct': 'A container to store and change values',
        'wrong': ['A sprite', 'A block type', 'A script'],
    },
    {
        'title': 'scratch_beginner_mcq_broadcast',
        'question': 'What does broadcast do?',
        'correct': 'Sends a message to all sprites',
        'wrong': ['Plays a sound', 'Changes the backdrop', 'Creates a sprite'],
    },
    {
        'title': 'scratch_beginner_mcq_costume',
        'question': 'What is a costume?',
        'correct': 'An image that makes the sprite look different',
        'wrong': ['A sprite behavior', 'A type of sound', 'A block'],
    },
    {
        'title': 'scratch_beginner_mcq_wait_block',
        'question': 'What does "wait 1 seconds" do?',
        'correct': 'Pauses the script for 1 second',
        'wrong': ['Moves the sprite', 'Creates a delay loop', 'Plays a sound'],
    },
    {
        'title': 'scratch_beginner_mcq_say_block',
        'question': 'What does "say" block do?',
        'correct': 'Makes the sprite display text',
        'wrong': ['Plays sound', 'Prints to console', 'Creates a variable'],
    },
    {
        'title': 'scratch_beginner_mcq_point_direction',
        'question': 'What does "point in direction 90" do?',
        'correct': 'Makes the sprite face right',
        'wrong': ['Moves the sprite right', 'Rotates the sprite 90 times', 'Points to a sprite'],
    },
    {
        'title': 'scratch_beginner_mcq_touching_sensor',
        'question': 'What does "touching mouse-pointer" check?',
        'correct': 'Whether the sprite is touching the cursor',
        'wrong': ['If the mouse is moving', 'If the mouse is clicked', 'If the sprite exists'],
    },
    {
        'title': 'scratch_beginner_mcq_color_sensor',
        'question': 'What does "color is touching" check?',
        'correct': 'Whether the sprite\'s color is touching another color',
        'wrong': ['If the sprite is visible', 'If the stage is colored', 'If a sound is playing'],
    },
    {
        'title': 'scratch_beginner_mcq_parallel_scripts',
        'question': 'Can multiple scripts run at the same time in Scratch?',
        'correct': 'Yes, they run in parallel',
        'wrong': ['No, only one script runs', 'Only if they share variables', 'Only on different sprites'],
    },
]

SCRATCH_BEGINNER_SHORT_ANSWER = [
    {
        'title': 'scratch_beginner_short_project_file',
        'question': 'What file extension is used for Scratch projects?',
        'answer': '.sb3',
    },
    {
        'title': 'scratch_beginner_short_default_sprite',
        'question': 'What is the default sprite in Scratch?',
        'answer': 'Scratch Cat',
    },
    {
        'title': 'scratch_beginner_short_stage_size',
        'question': 'What are the default dimensions of the Scratch stage?',
        'answer': '480 x 360',
    },
    {
        'title': 'scratch_beginner_short_backdrop_definition',
        'question': 'What is a backdrop?',
        'answer': 'The background of the stage',
    },
    {
        'title': 'scratch_beginner_short_clone',
        'question': 'What does a clone in Scratch do?',
        'answer': 'Creates a duplicate of the sprite',
    },
]

SCRATCH_BEGINNER_TRUE_FALSE = [
    {
        'title': 'scratch_beginner_tf_scripts_run_parallel',
        'question': 'In Scratch, multiple scripts on the same sprite run at the same time.',
        'correct': True,
    },
    {
        'title': 'scratch_beginner_tf_variables_sprite_specific',
        'question': 'Variables created in Scratch are specific to one sprite.',
        'correct': False,
    },
    {
        'title': 'scratch_beginner_tf_internet_required',
        'question': 'Scratch requires an internet connection to run projects.',
        'correct': False,
    },
    {
        'title': 'scratch_beginner_tf_blocks_draggable',
        'question': 'Scratch blocks can be dragged to any position on the workspace.',
        'correct': True,
    },
    {
        'title': 'scratch_beginner_tf_collision_detection',
        'question': 'Scratch has built-in collision detection blocks.',
        'correct': True,
    },
]

SCRATCH_INTERMEDIATE_MCQ = [
    {
        'title': 'scratch_inter_mcq_custom_block',
        'question': 'What are custom blocks in Scratch?',
        'correct': 'User-defined blocks that group code for reuse',
        'wrong': ['Built-in blocks', 'Extension blocks', 'Loop blocks'],
    },
    {
        'title': 'scratch_inter_mcq_list_variable',
        'question': 'What is a list in Scratch?',
        'correct': 'A variable that stores multiple values',
        'wrong': ['A type of sprite', 'A block category', 'A data type'],
    },
    {
        'title': 'scratch_inter_mcq_clone_performance',
        'question': 'What happens if you create too many clones?',
        'correct': 'The project may slow down or crash',
        'wrong': ['Clones are automatically deleted', 'No effect', 'Clones merge automatically'],
    },
    {
        'title': 'scratch_inter_mcq_extension_blocks',
        'question': 'What are extensions in Scratch?',
        'correct': 'Add-ons that provide additional blocks (e.g., music, AI)',
        'wrong': ['Built-in blocks', 'Costumes', 'Backdrops'],
    },
    {
        'title': 'scratch_inter_mcq_pen_extension',
        'question': 'What can the Pen extension do?',
        'correct': 'Draw lines and shapes on the stage',
        'wrong': ['Change sprite color', 'Play sounds', 'Create sprites'],
    },
    {
        'title': 'scratch_inter_mcq_random_number',
        'question': 'How do you generate a random number?',
        'correct': 'Use "pick random 1 to 10"',
        'wrong': ['Use "random variable"', 'Use "generate number"', 'Use "number block"'],
    },
    {
        'title': 'scratch_inter_mcq_join_text',
        'question': 'What does "join" block do with strings?',
        'correct': 'Combines two strings together',
        'wrong': ['Splits strings', 'Reverses strings', 'Deletes strings'],
    },
    {
        'title': 'scratch_inter_mcq_string_length',
        'question': 'How do you get the length of a string?',
        'correct': 'Use "length of" block',
        'wrong': ['Use "size of"', 'Use "count"', 'Use "measure"'],
    },
    {
        'title': 'scratch_inter_mcq_forever_loop',
        'question': 'What does a "forever" loop do?',
        'correct': 'Repeats code endlessly until stopped',
        'wrong': ['Repeats code once', 'Repeats until a condition', 'Repeats 100 times'],
    },
    {
        'title': 'scratch_inter_mcq_repeat_until_loop',
        'question': 'What does "repeat until" do?',
        'correct': 'Repeats code until a condition becomes true',
        'wrong': ['Repeats while condition is true', 'Repeats a fixed number of times', 'Repeats once'],
    },
    {
        'title': 'scratch_inter_mcq_if_else_block',
        'question': 'What does "if-else" block do?',
        'correct': 'Runs one code block if condition is true, another if false',
        'wrong': ['Runs both blocks', 'Runs only if condition is true', 'Runs no blocks'],
    },
    {
        'title': 'scratch_inter_mcq_and_or_operators',
        'question': 'What is the difference between AND and OR?',
        'correct': 'AND: both must be true; OR: at least one must be true',
        'wrong': ['No difference', 'OR is faster', 'AND is for numbers'],
    },
    {
        'title': 'scratch_inter_mcq_not_operator',
        'question': 'What does NOT do in Scratch?',
        'correct': 'Reverses a true/false value',
        'wrong': ['Deletes a block', 'Creates a variable', 'Stops a script'],
    },
    {
        'title': 'scratch_inter_mcq_broadcast_receive',
        'question': 'How do you receive a broadcast message?',
        'correct': 'Use "when I receive" event block',
        'wrong': ['Use "on message"', 'Use "listen"', 'Use "subscribe"'],
    },
    {
        'title': 'scratch_inter_mcq_go_to_layer',
        'question': 'What does "go to front layer" do?',
        'correct': 'Brings the sprite to the front (above other sprites)',
        'wrong': ['Moves the sprite up', 'Changes the sprite size', 'Changes the costume'],
    },
]

SCRATCH_INTERMEDIATE_SHORT_ANSWER = [
    {
        'title': 'scratch_inter_short_list_length',
        'question': 'How do you get the length of a list?',
        'answer': 'length of [list]',
    },
    {
        'title': 'scratch_inter_short_list_access',
        'question': 'How do you access the first item in a list?',
        'answer': 'item 1 of [list]',
    },
    {
        'title': 'scratch_inter_short_change_variable',
        'question': 'How do you increase a variable by 5?',
        'answer': 'change [variable] by 5',
    },
    {
        'title': 'scratch_inter_short_modulo_operator',
        'question': 'What is the modulo (mod) operator?',
        'answer': 'Returns the remainder of division',
    },
    {
        'title': 'scratch_inter_short_clone_delete',
        'question': 'How do you delete a clone in Scratch?',
        'answer': 'delete this clone',
    },
]

SCRATCH_INTERMEDIATE_TRUE_FALSE = [
    {
        'title': 'scratch_inter_tf_variables_global',
        'question': 'Variables created at the sprite level are available to all sprites.',
        'correct': False,
    },
    {
        'title': 'scratch_inter_tf_lists_ordered',
        'question': 'List items maintain their order in Scratch.',
        'correct': True,
    },
    {
        'title': 'scratch_inter_tf_broadcast_delay',
        'question': 'Broadcast messages are instantaneous across all sprites.',
        'correct': True,
    },
    {
        'title': 'scratch_inter_tf_operators_precedence',
        'question': 'Scratch respects mathematical operator precedence.',
        'correct': True,
    },
    {
        'title': 'scratch_inter_tf_nested_conditions',
        'question': 'You can nest if blocks inside if blocks in Scratch.',
        'correct': True,
    },
]

# ────────────────────────────────────────────────────────────────────────────
# Master question catalog
# ────────────────────────────────────────────────────────────────────────────

QUESTION_DATA = {
    ('python', 'beginner'): {
        'mcq': PYTHON_BEGINNER_MCQ,
        'short_answer': PYTHON_BEGINNER_SHORT_ANSWER,
        'true_false': PYTHON_BEGINNER_TRUE_FALSE,
    },
    ('python', 'intermediate'): {
        'mcq': PYTHON_INTERMEDIATE_MCQ,
        'short_answer': PYTHON_INTERMEDIATE_SHORT_ANSWER,
        'true_false': PYTHON_INTERMEDIATE_TRUE_FALSE,
    },
    ('python', 'advanced'): {
        'mcq': PYTHON_ADVANCED_MCQ,
        'short_answer': PYTHON_ADVANCED_SHORT_ANSWER,
        'true_false': PYTHON_ADVANCED_TRUE_FALSE,
    },
    ('javascript', 'beginner'): {
        'mcq': JAVASCRIPT_BEGINNER_MCQ,
        'short_answer': JAVASCRIPT_BEGINNER_SHORT_ANSWER,
        'true_false': JAVASCRIPT_BEGINNER_TRUE_FALSE,
    },
    ('javascript', 'intermediate'): {
        'mcq': JAVASCRIPT_INTERMEDIATE_MCQ,
        'short_answer': JAVASCRIPT_INTERMEDIATE_SHORT_ANSWER,
        'true_false': JAVASCRIPT_INTERMEDIATE_TRUE_FALSE,
    },
    ('javascript', 'advanced'): {
        'mcq': JAVASCRIPT_ADVANCED_MCQ,
        'short_answer': JAVASCRIPT_ADVANCED_SHORT_ANSWER,
        'true_false': JAVASCRIPT_ADVANCED_TRUE_FALSE,
    },
    ('html-css', 'beginner'): {
        'mcq': HTML_CSS_BEGINNER_MCQ,
        'short_answer': HTML_CSS_BEGINNER_SHORT_ANSWER,
        'true_false': HTML_CSS_BEGINNER_TRUE_FALSE,
    },
    ('html-css', 'intermediate'): {
        'mcq': HTML_CSS_INTERMEDIATE_MCQ,
        'short_answer': HTML_CSS_INTERMEDIATE_SHORT_ANSWER,
        'true_false': HTML_CSS_INTERMEDIATE_TRUE_FALSE,
    },
    ('html-css', 'advanced'): {
        'mcq': HTML_CSS_ADVANCED_MCQ,
        'short_answer': HTML_CSS_ADVANCED_SHORT_ANSWER,
        'true_false': HTML_CSS_ADVANCED_TRUE_FALSE,
    },
    ('scratch', 'beginner'): {
        'mcq': SCRATCH_BEGINNER_MCQ,
        'short_answer': SCRATCH_BEGINNER_SHORT_ANSWER,
        'true_false': SCRATCH_BEGINNER_TRUE_FALSE,
    },
    ('scratch', 'intermediate'): {
        'mcq': SCRATCH_INTERMEDIATE_MCQ,
        'short_answer': SCRATCH_INTERMEDIATE_SHORT_ANSWER,
        'true_false': SCRATCH_INTERMEDIATE_TRUE_FALSE,
    },
}


# ────────────────────────────────────────────────────────────────────────────
# Seeding orchestration
# ────────────────────────────────────────────────────────────────────────────

def seed_language_level(lang: str, level: str) -> Dict[str, int]:
    """Seed a single (language, level) pair. Returns counts of created items."""
    topic_level, _ = get_or_create_topic_level(lang, level)
    
    counts = {'mcq_created': 0, 'short_answer_created': 0, 'true_false_created': 0}

    data = QUESTION_DATA.get((lang, level))
    if not data:
        return counts

    # Count existing questions by type
    mcq_count = count_by_type(topic_level, CodingExercise.MULTIPLE_CHOICE)
    sa_count = count_by_type(topic_level, CodingExercise.SHORT_ANSWER)
    tf_count = count_by_type(topic_level, CodingExercise.TRUE_FALSE)

    # Top up MCQ questions
    mcq_needed = max(0, TARGET_MCQ - mcq_count)
    for q_data in data['mcq'][:mcq_needed]:
        _, created = create_mcq_question(
            topic_level,
            q_data['title'],
            q_data['question'],
            q_data['correct'],
            q_data['wrong'],
        )
        if created:
            counts['mcq_created'] += 1

    # Top up short-answer questions
    sa_needed = max(0, TARGET_SHORT_ANSWER - sa_count)
    for q_data in data['short_answer'][:sa_needed]:
        _, created = create_short_answer(
            topic_level,
            q_data['title'],
            q_data['question'],
            q_data['answer'],
        )
        if created:
            counts['short_answer_created'] += 1

    # Top up true/false questions
    tf_needed = max(0, TARGET_TRUE_FALSE - tf_count)
    for q_data in data['true_false'][:tf_needed]:
        _, created = create_tf_question(
            topic_level,
            q_data['title'],
            q_data['question'],
            q_data['correct'],
        )
        if created:
            counts['true_false_created'] += 1

    return counts


def main():
    """Main seeding orchestration."""
    print("\n" + "=" * 80)
    print("SEED CODING QUIZ BANK FOR FLIPZO")
    print("=" * 80)
    if DRY_RUN:
        print("[DRY RUN] — no changes will be written to the database")
    print()

    total_counts = {'mcq': 0, 'short_answer': 0, 'true_false': 0}

    with transaction.atomic():
        for lang in LANGUAGES:
            for level in LEVELS:
                print(f"Seeding {lang.title()} — {level.title()}...")
                try:
                    counts = seed_language_level(lang, level)
                    total_counts['mcq'] += counts['mcq_created']
                    total_counts['short_answer'] += counts['short_answer_created']
                    total_counts['true_false'] += counts['true_false_created']
                    print(f"  ✓ Created: {counts['mcq_created']} MCQ, "
                          f"{counts['short_answer_created']} short-answer, "
                          f"{counts['true_false_created']} true/false")
                except Exception as e:
                    print(f"  ✗ Error: {e}")
                    if not DRY_RUN:
                        raise

    print()
    print(f"Total created:")
    print(f"  MCQ:           {total_counts['mcq']:3d}")
    print(f"  Short-answer:  {total_counts['short_answer']:3d}")
    print(f"  True/False:    {total_counts['true_false']:3d}")
    print(f"  TOTAL:         {sum(total_counts.values()):3d}")
    print()
    print("=" * 80)
    if DRY_RUN:
        print("[DRY RUN] Completed. No changes written.")
    else:
        print("Seeding complete. All questions committed to database.")
    print("=" * 80)
    print()


if __name__ == '__main__':
    main()
