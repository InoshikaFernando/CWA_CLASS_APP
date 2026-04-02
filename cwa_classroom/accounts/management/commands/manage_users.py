"""
Management command to search and delete users.

Usage:
    python manage.py manage_users search jane          # search by name/email/username
    python manage.py manage_users search --role student # search by role
    python manage.py manage_users delete jane.doe       # dry-run delete by username
    python manage.py manage_users delete jane.doe --confirm  # actually delete
    python manage.py manage_users delete --id 42 --confirm   # delete by user ID
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from accounts.models import CustomUser, UserRole


class Command(BaseCommand):
    help = 'Search for users or delete a user by username/ID.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', help='Action to perform')

        # --- search ---
        search_p = sub.add_parser('search', help='Search users by name, email, or username')
        search_p.add_argument('query', nargs='?', default='', help='Search term')
        search_p.add_argument('--role', help='Filter by role name (e.g. student, teacher, parent)')
        search_p.add_argument('--limit', type=int, default=25, help='Max results (default 25)')

        # --- delete ---
        delete_p = sub.add_parser('delete', help='Delete a user by username or ID')
        delete_p.add_argument('username', nargs='?', default='', help='Username to delete')
        delete_p.add_argument('--id', type=int, dest='user_id', help='Delete by user ID instead')
        delete_p.add_argument(
            '--confirm', action='store_true',
            help='Actually delete. Without this flag the command only shows a dry-run.',
        )

    def handle(self, *args, **options):
        action = options.get('action')
        if action == 'search':
            self._search(options)
        elif action == 'delete':
            self._delete(options)
        else:
            self.stdout.write(self.style.ERROR(
                'Specify an action: search or delete\n'
                '  python manage.py manage_users search <query>\n'
                '  python manage.py manage_users delete <username> --confirm'
            ))

    def _search(self, options):
        query = (options.get('query') or '').strip()
        role = (options.get('role') or '').strip()
        limit = options.get('limit') or 25

        qs = CustomUser.objects.all()
        if query:
            qs = qs.filter(
                Q(username__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query)
            )
        if role:
            qs = qs.filter(roles__name__iexact=role).distinct()

        qs = qs.order_by('username')[:limit]
        count = qs.count()

        if not count:
            self.stdout.write(self.style.WARNING('No users found.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nFound {count} user(s):\n'))
        self.stdout.write(f'  {"ID":<6} {"Username":<25} {"Name":<30} {"Email":<35} {"Roles"}')
        self.stdout.write(f'  {"─"*6} {"─"*25} {"─"*30} {"─"*35} {"─"*20}')

        for user in qs:
            roles = ', '.join(
                UserRole.objects.filter(user=user).values_list('role__name', flat=True)
            )
            name = user.get_full_name() or '—'
            self.stdout.write(
                f'  {user.id:<6} {user.username:<25} {name:<30} {user.email:<35} {roles}'
            )

        if count == limit:
            self.stdout.write(self.style.NOTICE(f'\n  (showing first {limit} — use --limit to see more)'))

    def _delete(self, options):
        username = (options.get('username') or '').strip()
        user_id = options.get('user_id')
        confirm = options.get('confirm', False)

        if not username and not user_id:
            self.stdout.write(self.style.ERROR('Provide a username or --id to delete.'))
            return

        if user_id:
            user = CustomUser.objects.filter(id=user_id).first()
        else:
            user = CustomUser.objects.filter(username=username).first()

        if not user:
            self.stdout.write(self.style.ERROR(
                f'User not found: {username or f"ID {user_id}"}'
            ))
            return

        roles = list(UserRole.objects.filter(user=user).values_list('role__name', flat=True))

        self.stdout.write(self.style.WARNING('\n=== User to delete ==='))
        self.stdout.write(f'  ID:       {user.id}')
        self.stdout.write(f'  Username: {user.username}')
        self.stdout.write(f'  Name:     {user.get_full_name() or "—"}')
        self.stdout.write(f'  Email:    {user.email}')
        self.stdout.write(f'  Roles:    {", ".join(roles) or "none"}')
        self.stdout.write(f'  Staff:    {user.is_staff}')
        self.stdout.write(f'  Super:    {user.is_superuser}')

        if user.is_superuser:
            self.stdout.write(self.style.ERROR('\n  Cannot delete a superuser via this command.'))
            return

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                '\n  Dry-run — nothing deleted. Run with --confirm to delete.'
            ))
            return

        with transaction.atomic():
            deleted_count, deleted_detail = user.delete()

        self.stdout.write(self.style.SUCCESS(
            f'\n  Deleted user "{user.username}" and {deleted_count} related records.'
        ))
        for model, count in deleted_detail.items():
            if count:
                self.stdout.write(f'    {model}: {count}')
