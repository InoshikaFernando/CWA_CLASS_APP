"""Seed a demo teacher + 30 Python/Variables coding questions for the
Worksheet Builder. Run via:  python manage.py shell -c "exec(open('scripts/seed_demo.py').read())"
(invoked automatically by scripts/run_local.sh and scripts/run_local.ps1)."""
from django.contrib.auth import get_user_model
from accounts.models import Role
from classroom.models import School, SchoolTeacher, Level
from coding.models import CodingLanguage, CodingTopic, TopicLevel, CodingExercise

U = get_user_model()
tr, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
orr, _ = Role.objects.get_or_create(name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})

owner, _ = U.objects.get_or_create(username='demo_owner', defaults={'email': 'demo_owner@example.com'})
owner.set_password('pass1234!'); owner.profile_completed = True; owner.must_change_password = False; owner.save()
owner.roles.add(orr)

school, _ = School.objects.get_or_create(slug='demo-school', defaults={'name': 'Demo School', 'admin': owner})

t, _ = U.objects.get_or_create(username='demo_teacher', defaults={'email': 'demo_teacher@example.com'})
t.set_password('pass1234!'); t.profile_completed = True; t.must_change_password = False; t.save()
t.roles.add(tr)
SchoolTeacher.objects.get_or_create(school=school, teacher=t)

for n in range(1, 13):
    Level.objects.get_or_create(level_number=n)

py, _ = CodingLanguage.objects.get_or_create(slug='python', defaults={'name': 'Python', 'is_active': True, 'order': 1})
var, _ = CodingTopic.objects.get_or_create(language=py, slug='variables', defaults={'name': 'Variables', 'is_active': True, 'order': 1})
tl, _ = TopicLevel.objects.get_or_create(topic=var, level_choice='beginner', defaults={'is_active': True})

have = CodingExercise.objects.filter(topic_level=tl).count()
for i in range(have, 30):
    CodingExercise.objects.create(
        topic_level=tl,
        title='Variables Exercise %02d' % (i + 1),
        description='Practice declaring and using a variable - task #%d.' % (i + 1),
        is_active=True,
        order=i,
    )

print('   login: demo_teacher / pass1234!  | Python/Variables exercises:',
      CodingExercise.objects.filter(topic_level=tl).count())
