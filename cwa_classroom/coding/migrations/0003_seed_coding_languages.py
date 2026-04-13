"""
Data migration: seed the five platform CodingLanguage records.

Runs automatically with `python manage.py migrate` — no manual step needed.
Uses update_or_create so it is safe to run on existing databases.

Languages seeded: Python, JavaScript, HTML, CSS, Scratch
"""
from django.db import migrations


# Language data is duplicated here (not imported from seed_coding.py) so the
# migration remains self-contained and will not break if the seed command changes.
LANGUAGES = [
    {
        'name': 'Python',
        'slug': 'python',
        'description': 'A beginner-friendly, readable language used in data science, automation, and web development.',
        'icon_name': 'code-bracket',
        'color': '#3b82f6',
        'order': 1,
        'is_active': True,
    },
    {
        'name': 'JavaScript',
        'slug': 'javascript',
        'description': 'The language of the web — runs in every browser and powers interactive websites.',
        'icon_name': 'code-bracket',
        'color': '#f59e0b',
        'order': 2,
        'is_active': True,
    },
    {
        'name': 'HTML',
        'slug': 'html',
        'description': 'Build the structure and content of web pages with the markup language of the internet.',
        'icon_name': 'code-bracket',
        'color': '#e34f26',
        'order': 3,
        'is_active': True,
    },
    {
        'name': 'CSS',
        'slug': 'css',
        'description': 'Style and design web pages with colours, fonts, layouts, and animations.',
        'icon_name': 'code-bracket',
        'color': '#264de4',
        'order': 4,
        'is_active': True,
    },
    {
        'name': 'Scratch',
        'slug': 'scratch',
        'description': 'A visual block-based language perfect for learning programming fundamentals.',
        'icon_name': 'code-bracket',
        'color': '#f97316',
        'order': 5,
        'is_active': True,
    },
]


def seed_languages(apps, schema_editor):
    CodingLanguage = apps.get_model('coding', 'CodingLanguage')
    for lang in LANGUAGES:
        slug = lang['slug']
        CodingLanguage.objects.update_or_create(
            slug=slug,
            defaults={k: v for k, v in lang.items() if k != 'slug'},
        )


def unseed_languages(apps, schema_editor):
    """Reverse: remove the seeded records (only if they still match the seeded data)."""
    CodingLanguage = apps.get_model('coding', 'CodingLanguage')
    CodingLanguage.objects.filter(slug__in=[l['slug'] for l in LANGUAGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0002_update_language_choices'),
    ]

    operations = [
        migrations.RunPython(seed_languages, unseed_languages),
    ]
