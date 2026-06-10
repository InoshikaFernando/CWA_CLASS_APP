#!/usr/bin/env bash
#
# One-command local runner for the Worksheet Builder.
#
#   ./scripts/run_local.sh
#
# Creates the MySQL database, applies migrations, seeds a demo teacher plus
# 30 Python/Variables coding questions, and starts the dev server on
# http://127.0.0.1:8000/  (log in as demo_teacher / pass1234!).
#
# Override any DB setting via env vars, e.g.:
#   DB_PASSWORD=secret DB_HOST=127.0.0.1 ./scripts/run_local.sh
#
set -euo pipefail
cd "$(dirname "$0")/../cwa_classroom"

# --- Config (defaults match a local MySQL root/root install) ---------------
export DB_ENGINE=mysql
export DB_NAME=${DB_NAME:-cwa_classroom}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-root}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}
export DEBUG=True                       # MUST be exactly "True"
export SECRET_KEY=${SECRET_KEY:-dev-local-secret-change-me}
export ALLOWED_HOSTS=${ALLOWED_HOSTS:-localhost,127.0.0.1}
PORT=${PORT:-8000}

# --- 1. Create database (no-op if it already exists) -----------------------
echo "==> Ensuring database '$DB_NAME' exists"
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" ${DB_PASSWORD:+-p"$DB_PASSWORD"} \
  -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4;"

# --- 2. Migrate ------------------------------------------------------------
echo "==> Applying migrations"
python manage.py migrate --noinput

# --- 3. Seed demo teacher + coding questions -------------------------------
echo "==> Seeding demo data"
python manage.py shell <<'PY'
from django.contrib.auth import get_user_model
from accounts.models import Role
from classroom.models import School, SchoolTeacher, Level
from coding.models import CodingLanguage, CodingTopic, TopicLevel, CodingExercise
U = get_user_model()
tr, _  = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
orr, _ = Role.objects.get_or_create(name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
owner, _ = U.objects.get_or_create(username='demo_owner', defaults={'email': 'demo_owner@example.com'})
owner.set_password('pass1234!'); owner.profile_completed = True; owner.must_change_password = False; owner.save(); owner.roles.add(orr)
school, _ = School.objects.get_or_create(slug='demo-school', defaults={'name': 'Demo School', 'admin': owner})
t, _ = U.objects.get_or_create(username='demo_teacher', defaults={'email': 'demo_teacher@example.com'})
t.set_password('pass1234!'); t.profile_completed = True; t.must_change_password = False; t.save(); t.roles.add(tr)
SchoolTeacher.objects.get_or_create(school=school, teacher=t)
for n in range(1, 13):
    Level.objects.get_or_create(level_number=n)
py, _ = CodingLanguage.objects.get_or_create(slug='python', defaults={'name': 'Python', 'is_active': True, 'order': 1})
var, _ = CodingTopic.objects.get_or_create(language=py, slug='variables', defaults={'name': 'Variables', 'is_active': True, 'order': 1})
tl, _ = TopicLevel.objects.get_or_create(topic=var, level_choice='beginner', defaults={'is_active': True})
have = CodingExercise.objects.filter(topic_level=tl).count()
for i in range(have, 30):
    CodingExercise.objects.create(topic_level=tl, title=f'Variables Exercise {i+1:02d}',
        description=f'Practice declaring and using a variable - task #{i+1}.', is_active=True, order=i)
print('   login: demo_teacher / pass1234!  | Python/Variables exercises:', CodingExercise.objects.filter(topic_level=tl).count())
PY

# --- 4. Run ----------------------------------------------------------------
echo "==> Starting server on http://127.0.0.1:${PORT}/  (Ctrl+C to stop)"
echo "    Log in as demo_teacher / pass1234! then open /worksheets/builder/"
exec python manage.py runserver "127.0.0.1:${PORT}"
