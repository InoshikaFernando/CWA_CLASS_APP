"""
seed_fill_blank_demo
~~~~~~~~~~~~~~~~~~~~
Build a runnable BEFORE/AFTER demo of the fill-in-the-blank question type, so
the change can be seen in the actual UI rather than described.

It seeds a demo school, class, teacher and student, then creates each sample
question TWICE:

  BEFORE — exactly how these questions sit in the database today: a typed
           question whose text carries "___" gaps, answered through one box for
           the whole sentence.
  AFTER  — the same question, converted by the same code path the bulk command
           uses (``Question.rebuild_blank_spec``), so the per-blank answers are
           genuinely derived from the answer rows the BEFORE copy already has.

Both go into their own homework, so the two pages can be opened side by side.
The AFTER questions keep their original answer rows, exactly as a real
conversion does.

Intended for a scratch database. It refuses to touch a database that already
holds real questions unless you pass --force, because it creates users with
known passwords.

Usage:
    python manage.py seed_fill_blank_demo            # seed + print the URLs
    python manage.py seed_fill_blank_demo --report   # also print the answer mapping
    python manage.py seed_fill_blank_demo --reset    # rebuild the demo from scratch
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from maths.blank_grading import describe_blank_spec

DEMO_TAG = 'fbdemo'
PASSWORD = 'DemoPass123!'
TEACHER = f'{DEMO_TAG}_teacher'
STUDENT = f'{DEMO_TAG}_student'
ADMIN = f'{DEMO_TAG}_admin'

# Real-shaped samples, one per mapping rule the converter supports. The answer
# text is stored the way the database already stores it — that is the point of
# the demo: nothing here is authored specially for the new format.
SAMPLES = [
    {
        'text': (
            'Out of 100 000 births, 99 231 females are expected to survive to '
            'the age of ___. From that age, the survivors are expected to ___ '
            'for another 67.0 years.'
        ),
        'answers': ['15; live|survive'],
        'note': 'one answer row, split on ";" — and "|" gives the 2nd gap two wordings',
    },
    {
        'text': 'A triangle has ___ sides and ___ angles.',
        'answers': ['3', '3'],
        'note': 'one answer row per gap, in order',
    },
    {
        'text': 'The value of 5531 - 4414 is ___.',
        'answers': ['1117', '1,117'],
        'note': 'a single gap — every row becomes an accepted spelling of it',
    },
    {
        'text': 'Water boils at ___ °C and freezes at ___ °C.',
        'answers': ['100, 0'],
        'note': 'one answer row, split on "," when there is no ";"',
    },
    # The shapes a real conversion run over the production bank turned up, which
    # the first pass mapped onto the wrong gaps. Each stays a working single box
    # and is reported, rather than being guessed at.
    {
        'text': 'Complete the pattern: 30, ___, 60, 75, ___, ___. What is the rule?',
        'answers': ['+15', 'add 15', '+ 15'],
        'note': 'REFUSED — 3 rows spelling the RULE, not one value per gap',
    },
    {
        'text': 'Write the sum: 3 + 3 + 3 = ______, then the product: 3 x 3 = ______',
        'answers': ['9', '9 and 9'],
        'note': 'REFUSED — one answer written twice over, not one per gap',
    },
    {
        'text': 'Convert to millilitres: 5.3 L = _____ mL',
        'answers': ['5300 mL'],
        'note': 'REFUSED — the answer repeats the "mL" already after the gap',
    },
    {
        'text': 'Fill in the missing numbers of this sequence: 14, 17, 20, 23, ___, ___',
        'answers': ['26, 29', '26 and 29'],
        'note': 'every row lists both values, so they become alternatives per gap',
    },
]


class Command(BaseCommand):
    help = 'Seed a BEFORE/AFTER fill-in-the-blank demo (demo database only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete the previous demo data and rebuild it.')
        parser.add_argument(
            '--report', action='store_true',
            help='Also print how each stored answer maps onto the gaps.')
        parser.add_argument(
            '--force', action='store_true',
            help='Seed even when the database already holds questions. The demo '
                 'creates users with a known password — never pass this on a '
                 'database anyone real logs into.')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        from maths.models import Question

        existing = Question.objects.exclude(
            question_text__startswith='[demo]').count()
        if existing and not opts['force']:
            raise CommandError(
                f'This database already holds {existing} question(s). '
                f'seed_fill_blank_demo creates users with a known password and '
                f'is meant for a scratch database — re-run with --force only if '
                f'this is one.'
            )

        if opts['reset']:
            self._teardown()

        with transaction.atomic():
            ctx = self._seed()

        self._print_urls(ctx)
        if opts['report']:
            self._print_report(ctx)

    # ------------------------------------------------------------------
    def _teardown(self):
        from accounts.models import CustomUser
        from classroom.models import School
        from maths.models import Question

        School.objects.filter(slug=f'{DEMO_TAG}-school').delete()
        CustomUser.objects.filter(username__startswith=DEMO_TAG).delete()
        Question.objects.filter(question_text__startswith='[demo]').delete()
        self.stdout.write(self.style.WARNING('Previous demo data removed.'))

    # ------------------------------------------------------------------
    def _user(self, username, role_name, **extra):
        from accounts.models import CustomUser, Role

        user = CustomUser.objects.filter(username=username).first()
        if user is None:
            user = CustomUser.objects.create_user(
                username=username, password=PASSWORD,
                email=f'{username}@demo.local',
                first_name=username.replace('_', ' ').title(),
                profile_completed=True, must_change_password=False,
                **extra,
            )
        role, _ = Role.objects.get_or_create(
            name=role_name, defaults={'display_name': role_name.replace('_', ' ').title()})
        user.roles.add(role)
        return user

    def _seed(self):
        from datetime import time

        from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
        from classroom.models import (
            ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentSubject,
            DepartmentTeacher, Level, School, SchoolStudent, SchoolTeacher, Subject,
            Topic,
        )
        from accounts.models import Role
        from homework.models import Homework, HomeworkQuestion
        from maths.models import Answer, Question

        admin = self._user(ADMIN, Role.INSTITUTE_OWNER, is_staff=True)
        teacher = self._user(TEACHER, Role.TEACHER)
        student = self._user(STUDENT, Role.STUDENT)

        school, _ = School.objects.get_or_create(
            slug=f'{DEMO_TAG}-school',
            defaults={'name': 'Fill-Blank Demo School', 'admin': admin, 'is_active': True},
        )
        plan, _ = InstitutePlan.objects.get_or_create(
            slug=f'{DEMO_TAG}-plan',
            defaults={'name': 'Demo Plan', 'price': 0, 'stripe_price_id': 'price_demo',
                      'class_limit': 50, 'student_limit': 500,
                      'invoice_limit_yearly': 500, 'extra_invoice_rate': 0},
        )
        sub, created = SchoolSubscription.objects.get_or_create(
            school=school, defaults={'plan': plan, 'status': 'active'})
        if created:
            for module_key, _label in ModuleSubscription.MODULE_CHOICES:
                ModuleSubscription.objects.create(
                    school_subscription=sub, module=module_key, is_active=True)

        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        level, _ = Level.objects.get_or_create(
            level_number=10, defaults={'display_name': 'Year 10'})
        topic, _ = Topic.objects.get_or_create(
            subject=subject, name='Fill-Blank Demo',
            defaults={'slug': f'{DEMO_TAG}-topic', 'is_active': True})
        topic.levels.add(level)

        dept, _ = Department.objects.get_or_create(
            school=school, slug=f'{DEMO_TAG}-dept',
            defaults={'name': 'Mathematics', 'head': teacher})
        DepartmentSubject.objects.get_or_create(department=dept, subject=subject)
        DepartmentTeacher.objects.get_or_create(department=dept, teacher=teacher)
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=admin, defaults={'role': 'head_of_institute'})
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=teacher, defaults={'role': 'teacher'})

        room, _ = ClassRoom.objects.get_or_create(
            school=school, name='Year 10 Maths (demo)',
            defaults={'department': dept, 'subject': subject, 'day': 'monday',
                      'start_time': time(9, 0), 'end_time': time(10, 0)},
        )
        room.levels.add(level)
        ClassTeacher.objects.get_or_create(classroom=room, teacher=teacher)
        SchoolStudent.objects.get_or_create(school=school, student=student)
        ClassStudent.objects.get_or_create(
            classroom=room, student=student, defaults={'is_active': True})

        before_qs, after_qs, mapping = [], [], []
        for i, sample in enumerate(SAMPLES, start=1):
            # BEFORE — stored exactly as these questions are stored today.
            before = Question.objects.create(
                level=level, topic=topic, school=school,
                question_text=f'[demo] {sample["text"]}',
                question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
            )
            for order, text in enumerate(sample['answers'], start=1):
                Answer.objects.create(question=before, answer_text=text,
                                      is_correct=True, order=order)
            before_qs.append(before)

            # AFTER — the same question, converted by the same code path the
            # bulk command uses, from the answer rows above.
            after = Question.objects.create(
                level=level, topic=topic, school=school,
                question_text=before.question_text,
                question_type=Question.SHORT_ANSWER, difficulty=1, points=1,
            )
            for order, text in enumerate(sample['answers'], start=1):
                Answer.objects.create(question=after, answer_text=text,
                                      is_correct=True, order=order)
            applied, reason = after.rebuild_blank_spec()
            if applied:
                after.question_type = Question.FILL_BLANK
                after.save(update_fields=['question_type', 'blank_spec'])
            after_qs.append(after)
            mapping.append((i, sample, after, applied, reason))

        homeworks = {}
        for label, questions in (('BEFORE — one box', before_qs),
                                 ('AFTER — a gap per blank', after_qs)):
            hw = Homework.objects.create(
                classroom=room, created_by=teacher,
                title=f'Fill-in-the-blank demo · {label}',
                homework_type='topic', num_questions=len(questions),
                due_date=timezone.now() + timedelta(days=14), max_attempts=99,
            )
            hw.topics.add(topic)
            for order, q in enumerate(questions):
                HomeworkQuestion.objects.create(homework=hw, question=q, order=order)
            homeworks[label] = hw

        return {'homeworks': homeworks, 'mapping': mapping,
                'teacher': teacher, 'student': student}

    # ------------------------------------------------------------------
    def _print_urls(self, ctx):
        w = self.stdout.write
        w('')
        w(self.style.SUCCESS('Demo seeded.'))
        w('')
        w('Start the server:   python manage.py runserver 0.0.0.0:8000')
        w('')
        w(self.style.HTTP_INFO('Log in as the STUDENT to answer the questions:'))
        w(f'    username  {ctx["student"].username}')
        w(f'    password  {PASSWORD}')
        for label, hw in ctx['homeworks'].items():
            w(f'    {label:<28} http://localhost:8000/homework/{hw.pk}/take/')
        w('')
        w(self.style.HTTP_INFO('Log in as the TEACHER to see the answer key:'))
        w(f'    username  {ctx["teacher"].username}')
        w(f'    password  {PASSWORD}')
        w('')
        w('Answer the BEFORE homework and the AFTER homework, then open each')
        w('result page — the same questions, the same stored answers, graded')
        w('through one box on one and through a gap per blank on the other.')

    def _print_report(self, ctx):
        w = self.stdout.write
        w('')
        w(self.style.HTTP_INFO('How each stored answer maps onto the gaps'))
        w('')
        for i, sample, after, applied, reason in ctx['mapping']:
            w(self.style.SUCCESS(f'{i}. {sample["note"]}'))
            w(f'   text     {sample["text"][:100]}')
            w(f'   stored   {sample["answers"]}')
            if applied:
                w(f'   becomes  {describe_blank_spec(after.blank_spec)}')
                w(f'   spec     {after.blank_spec}')
            else:
                w(self.style.WARNING(f'   NOT converted — {reason}'))
            w('')
