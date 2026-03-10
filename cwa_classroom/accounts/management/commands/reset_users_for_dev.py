"""
Reset all user passwords and emails for local/test environments.

Usage:
    python manage.py reset_users_for_dev
    python manage.py reset_users_for_dev --password MyPassword123
    python manage.py reset_users_for_dev --email test@example.com
    python manage.py reset_users_for_dev --password MyPassword123 --email test@example.com
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password


class Command(BaseCommand):
    help = 'Reset all user passwords and emails for local/test development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            default='Password1!',
            help='Password to set for all users (default: Password1!)',
        )
        parser.add_argument(
            '--email',
            default='inoshi.fernando@gmail.com',
            help='Email to set for all users (default: inoshi.fernando@gmail.com)',
        )
        parser.add_argument(
            '--skip-email',
            action='store_true',
            help='Only reset passwords, leave emails unchanged.',
        )

    def handle(self, *args, **options):
        from accounts.models import CustomUser

        password = options['password']
        email = options['email']
        skip_email = options['skip_email']

        password_hash = make_password(password)

        update_fields = {'password': password_hash}
        if not skip_email:
            update_fields['email'] = email

        count = CustomUser.objects.all().update(**update_fields)

        self.stdout.write(self.style.SUCCESS(
            f'Updated {count} users: password="{password}"'
            + (f', email="{email}"' if not skip_email else '')
        ))
