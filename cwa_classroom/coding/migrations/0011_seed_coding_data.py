"""
Migration: seed CodingTopic records for all languages.

Languages are already seeded by 0003_seed_coding_languages.
This migration adds only topics — no exercises or problems.
Safe to re-run: uses update_or_create throughout.
"""
from django.db import migrations
from django.utils.text import slugify

TOPICS = [
    # Python
    {'language_slug': 'python', 'name': 'Variables & Data Types', 'description': 'Store and work with different kinds of data.', 'order': 1},
    {'language_slug': 'python', 'name': 'If Conditions',          'description': 'Make decisions in your code with if/elif/else.', 'order': 2},
    {'language_slug': 'python', 'name': 'Loops',                  'description': 'Repeat actions with for and while loops.', 'order': 3},
    {'language_slug': 'python', 'name': 'Functions',              'description': 'Write reusable blocks of code.', 'order': 4},
    {'language_slug': 'python', 'name': 'Lists',                  'description': 'Work with ordered collections of items.', 'order': 5},
    {'language_slug': 'python', 'name': 'Dictionaries',           'description': 'Store and look up data using key-value pairs.', 'order': 6},
    {'language_slug': 'python', 'name': 'String Manipulation',    'description': 'Slice, format, and transform text.', 'order': 7},
    # JavaScript
    {'language_slug': 'javascript', 'name': 'Variables & Data Types', 'description': 'let, const, and JavaScript data types.', 'order': 1},
    {'language_slug': 'javascript', 'name': 'If Conditions',          'description': 'Branching logic with if/else and ternary.', 'order': 2},
    {'language_slug': 'javascript', 'name': 'Loops',                  'description': 'for, while, and array iteration.', 'order': 3},
    {'language_slug': 'javascript', 'name': 'Functions',              'description': 'Regular functions and arrow functions.', 'order': 4},
    {'language_slug': 'javascript', 'name': 'Arrays',                 'description': 'Create and manipulate arrays.', 'order': 5},
    {'language_slug': 'javascript', 'name': 'Objects',                'description': 'Work with JavaScript objects and properties.', 'order': 6},
    {'language_slug': 'javascript', 'name': 'DOM Basics',             'description': 'Select and update elements on a web page.', 'order': 7},
    # HTML
    {'language_slug': 'html', 'name': 'HTML Structure', 'description': 'Tags, elements, and building a page skeleton.', 'order': 1},
    {'language_slug': 'html', 'name': 'Text & Links',   'description': 'Headings, paragraphs, and anchor tags.', 'order': 2},
    {'language_slug': 'html', 'name': 'Images & Media', 'description': 'Embed images, video, and audio.', 'order': 3},
    {'language_slug': 'html', 'name': 'Forms',          'description': 'Build HTML forms with inputs, labels, and buttons.', 'order': 4},
    {'language_slug': 'html', 'name': 'Tables',         'description': 'Create structured data with HTML tables.', 'order': 5},
    # CSS
    {'language_slug': 'css', 'name': 'CSS Basics',        'description': 'Selectors, colours, fonts, and spacing.', 'order': 1},
    {'language_slug': 'css', 'name': 'CSS Layout',        'description': 'Flexbox and Grid for page layout.', 'order': 2},
    {'language_slug': 'css', 'name': 'CSS Animations',    'description': 'Add motion and transitions to elements.', 'order': 3},
    {'language_slug': 'css', 'name': 'Responsive Design', 'description': 'Make pages look great on all screen sizes with media queries.', 'order': 4},
    # Scratch
    {'language_slug': 'scratch', 'name': 'Motion & Looks', 'description': 'Move sprites and change how they look.', 'order': 1},
    {'language_slug': 'scratch', 'name': 'Events',         'description': 'Trigger scripts with key presses and clicks.', 'order': 2},
    {'language_slug': 'scratch', 'name': 'Control',        'description': 'Loops, waits, and if/else blocks.', 'order': 3},
    {'language_slug': 'scratch', 'name': 'Variables',      'description': 'Store and change values.', 'order': 4},
    {'language_slug': 'scratch', 'name': 'Sound',          'description': 'Play sounds and music in your project.', 'order': 5},
]


def seed_topics(apps, schema_editor):
    CodingLanguage = apps.get_model('coding', 'CodingLanguage')
    CodingTopic    = apps.get_model('coding', 'CodingTopic')

    for t in TOPICS:
        try:
            language = CodingLanguage.objects.get(slug=t['language_slug'])
        except CodingLanguage.DoesNotExist:
            continue
        CodingTopic.objects.update_or_create(
            language=language,
            slug=slugify(t['name']),
            defaults={
                'name':        t['name'],
                'description': t['description'],
                'order':       t['order'],
                'is_active':   True,
            },
        )


def unseed_topics(apps, schema_editor):
    CodingTopic = apps.get_model('coding', 'CodingTopic')
    CodingTopic.objects.filter(
        slug__in=[slugify(t['name']) for t in TOPICS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0010_add_topiclevel_restructure_exercise'),
    ]

    operations = [
        migrations.RunPython(seed_topics, unseed_topics),
    ]
