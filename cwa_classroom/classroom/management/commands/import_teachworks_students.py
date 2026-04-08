"""
Management command to import students from a Teachworks CSV export into a school.

Usage:
    python manage.py import_teachworks_students <csv_path> <school_id> [--dry-run]

Example:
    python manage.py import_teachworks_students Students-All-Active.csv 4 --dry-run
    python manage.py import_teachworks_students Students-All-Active.csv 4
"""

import csv
import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Import students from a Teachworks CSV export into a school'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='Path to the Teachworks CSV file')
        parser.add_argument('school_id', type=int, help='School ID to import students into')
        parser.add_argument('--dry-run', action='store_true', help='Preview only, no DB changes')

    def handle(self, *args, **options):
        from classroom.models import School
        from classroom.import_services import apply_preset, validate_and_preview, execute_import

        csv_path = options['csv_path']
        school_id = options['school_id']
        dry_run = options['dry_run']

        if not os.path.isfile(csv_path):
            raise CommandError(f'File not found: {csv_path}')

        school = School.objects.filter(id=school_id).first()
        if not school:
            raise CommandError(f'School with id={school_id} not found')

        self.stdout.write(f'School: {school.name}')
        self.stdout.write(f'File:   {csv_path}')
        self.stdout.write(f'Mode:   {"DRY RUN" if dry_run else "LIVE IMPORT"}')
        self.stdout.write('')

        # Read CSV
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            data_rows = list(reader)

        self.stdout.write(f'Rows in CSV: {len(data_rows)}')

        # Apply Teachworks preset
        column_mapping = apply_preset('teachworks', headers)
        if not column_mapping:
            raise CommandError('Could not apply Teachworks preset — check CSV headers')

        self.stdout.write(f'Column mapping: {column_mapping}')
        self.stdout.write('')

        # Get a superuser to act as uploader
        uploader = User.objects.filter(is_superuser=True).first()
        if not uploader:
            raise CommandError('No superuser found to act as uploader')

        # Validate and preview
        self.stdout.write('Running validation and preview...')
        preview = validate_and_preview(data_rows, column_mapping, school)

        errors = preview.get('errors', [])
        warnings = preview.get('warnings', [])
        students_new = preview.get('students_new', [])
        students_existing = preview.get('students_existing', [])

        self.stdout.write(f'  New students:      {len(students_new)}')
        self.stdout.write(f'  Existing students: {len(students_existing)}')
        self.stdout.write(f'  Warnings:          {len(warnings)}')
        self.stdout.write(f'  Errors:            {len(errors)}')

        if warnings:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Warnings:'))
            for w in warnings[:20]:
                self.stdout.write(f'  {w}')
            if len(warnings) > 20:
                self.stdout.write(f'  ... and {len(warnings) - 20} more')

        if errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('Errors:'))
            for e in errors[:20]:
                self.stdout.write(f'  {e}')
            if len(errors) > 20:
                self.stdout.write(f'  ... and {len(errors) - 20} more')

        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Dry run complete — no changes made.'))
            return

        if not students_new and not students_existing:
            self.stdout.write(self.style.WARNING('Nothing to import.'))
            return

        # Execute import
        self.stdout.write('')
        self.stdout.write('Importing...')
        result = execute_import(preview, school, uploader)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Import complete!'))
        self.stdout.write(f'  Students created:    {result["counts"]["students_created"]}')
        self.stdout.write(f'  Students enrolled:   {result["counts"]["students_enrolled"]}')
        self.stdout.write(f'  Classes created:     {result["counts"]["classes_created"]}')
        self.stdout.write(f'  Departments created: {result["counts"]["departments_created"]}')
        self.stdout.write(f'  Guardians created:   {result["counts"]["guardians_created"]}')
        self.stdout.write(f'  Parents created:     {result["counts"]["parents_created"]}')

        if result['counts'].get('errors'):
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('Import errors:'))
            for e in result['counts']['errors']:
                self.stdout.write(f'  {e}')

        # Save credentials to file
        credentials = result.get('credentials', [])
        parent_credentials = result.get('parent_credentials', [])
        all_creds = credentials + parent_credentials
        if all_creds:
            creds_path = csv_path.replace('.csv', '_credentials.csv')
            with open(creds_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Role', 'Name', 'Username', 'Password', 'Email'])
                for c in credentials:
                    writer.writerow(['Student', c.get('name', ''), c.get('username', ''), c.get('password', ''), c.get('email', '')])
                for c in parent_credentials:
                    writer.writerow(['Parent', c.get('name', ''), c.get('username', ''), c.get('password', ''), c.get('email', '')])
            self.stdout.write('')
            self.stdout.write(f'Credentials saved to: {creds_path}')
