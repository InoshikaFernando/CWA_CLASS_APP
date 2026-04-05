"""
Test settings — imports everything from main settings then forces SQLite.
Usage: python manage.py test --settings=cwa_classroom.settings_test
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'TEST': {
            'NAME': ':memory:',
            'MIGRATE': False,
        },
    },
}
