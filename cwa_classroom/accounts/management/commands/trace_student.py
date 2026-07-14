"""
Read-only diagnostic: trace every account matching a query and show, for each,
the things that decide whether a child can actually reach a paid subscription —
roles, parent<->student links, school enrolment (Student ID), class enrolments,
and the subscription/package. Also flags likely duplicate student accounts
(same name) so support can spot a self-registered account sitting next to the
institute-created one.

Nothing is written — safe to run against production.

Usage:
    python manage.py trace_student Herath
    python manage.py trace_student ratnayakehimali        # matches +saduni too
    python manage.py trace_student "Sanduli"
    python manage.py trace_student STU-001-0042           # by Student ID code
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Q

from accounts.models import CustomUser, UserRole


class Command(BaseCommand):
    help = 'Trace accounts (roles, parent links, enrolment, subscription) and flag duplicates.'

    def add_arguments(self, parser):
        parser.add_argument(
            'query',
            help='Name, email, username, or Student ID code to search for.',
        )
        parser.add_argument('--limit', type=int, default=25, help='Max accounts (default 25)')

    def handle(self, *args, **options):
        from classroom.models import SchoolStudent, ClassStudent, ParentStudent

        query = (options.get('query') or '').strip()
        limit = options.get('limit') or 25
        if not query:
            self.stdout.write(self.style.ERROR('Provide a search query.'))
            return

        # Match users directly, or via a matching Student ID code on SchoolStudent.
        student_ids_by_code = set(
            SchoolStudent.objects
            .filter(student_id_code__icontains=query)
            .values_list('student_id', flat=True)
        )
        users = list(
            CustomUser.objects.filter(
                Q(username__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query) |
                Q(id__in=student_ids_by_code)
            ).order_by('last_name', 'first_name', 'id')[:limit]
        )

        if not users:
            self.stdout.write(self.style.WARNING('No accounts found.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nFound {len(users)} account(s) matching "{query}":'))

        # Track (first,last) -> student user ids to flag duplicate children.
        name_groups = defaultdict(list)

        for u in users:
            roles = list(UserRole.objects.filter(user=u).values_list('role__name', flat=True))
            self.stdout.write(self.style.HTTP_INFO(
                f'\n─── #{u.id}  {u.username}  ({u.get_full_name() or "—"}) ───'
            ))
            self.stdout.write(f'  email:    {u.email or "—"}')
            self.stdout.write(f'  active:   {u.is_active}    roles: {", ".join(roles) or "—"}')

            # Subscription / package
            self._show_subscription(u)

            # Enrolment as a student: Student ID + classes
            school_rows = list(
                SchoolStudent.objects.filter(student=u).select_related('school')
            )
            if school_rows:
                for ss in school_rows:
                    flag = '' if ss.is_active else '  (INACTIVE)'
                    self.stdout.write(
                        f'  school:   {ss.school.name} — Student ID: '
                        f'{ss.student_id_code or "—"}{flag}'
                    )
            class_rows = list(
                ClassStudent.objects.filter(student=u)
                .select_related('classroom', 'classroom__school')
            )
            for cs in class_rows:
                c = cs.classroom
                when = f'{c.get_day_display() if c.day else "—"} {self._time(c)}'.strip()
                flag = '' if cs.is_active else '  (INACTIVE)'
                self.stdout.write(f'  class:    {c.name} [{when}] @ {c.school.name}{flag}')

            # Parent links — as a student (who are their parents)
            as_child = list(
                ParentStudent.objects.filter(student=u)
                .select_related('parent', 'school')
            )
            for ps in as_child:
                flag = '' if ps.is_active else '  (INACTIVE)'
                sch = ps.school.name if ps.school else 'no school'
                self.stdout.write(
                    f'  parent:   #{ps.parent_id} {ps.parent.get_full_name() or ps.parent.username} '
                    f'({ps.parent.email or "—"}) — {ps.get_relationship_display()} @ {sch}{flag}'
                )

            # Parent links — as a parent (who are their children)
            as_parent = list(
                ParentStudent.objects.filter(parent=u)
                .select_related('student', 'school')
            )
            for ps in as_parent:
                flag = '' if ps.is_active else '  (INACTIVE)'
                sch = ps.school.name if ps.school else 'no school'
                self.stdout.write(
                    f'  child:    #{ps.student_id} {ps.student.get_full_name() or ps.student.username} '
                    f'({ps.student.email or "—"}) @ {sch}{flag}'
                )

            # Record for duplicate detection only if this account looks like a student.
            if school_rows or class_rows or as_child or 'student' in roles:
                key = (
                    (u.first_name or '').strip().lower(),
                    (u.last_name or '').strip().lower(),
                )
                if key != ('', ''):
                    name_groups[key].append(u.id)

        # Flag potential duplicate children
        dups = {k: v for k, v in name_groups.items() if len(v) > 1}
        if dups:
            self.stdout.write(self.style.WARNING('\n⚠  Possible duplicate student accounts (same name):'))
            for (first, last), ids in dups.items():
                self.stdout.write(
                    f'   {first.title()} {last.title()}: account IDs {", ".join(map(str, ids))}'
                )
            self.stdout.write(self.style.NOTICE(
                '   Review in the admin "Merge Students" tool if these are one child.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('\nNo same-name duplicate student accounts detected.'))

    def _time(self, classroom):
        st, et = classroom.start_time, classroom.end_time
        if st and et:
            return f'{st.strftime("%H:%M")}-{et.strftime("%H:%M")}'
        if st:
            return st.strftime('%H:%M')
        return ''

    def _show_subscription(self, user):
        try:
            from billing.models import Subscription
        except Exception:
            return
        sub = Subscription.objects.filter(user=user).select_related('package').first()
        if sub:
            pkg = sub.package.name if sub.package else '—'
            self.stdout.write(f'  sub:      {sub.get_status_display()} — package: {pkg}')
        elif getattr(user, 'package_id', None):
            self.stdout.write(f'  sub:      (no Subscription row) — user.package: {user.package}')
        else:
            self.stdout.write('  sub:      none')
