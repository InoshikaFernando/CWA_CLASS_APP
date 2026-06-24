# Running the app locally

Steps to run the Django app on your own machine and exercise the
**Worksheet Builder** (where the pagination fix lives).

## 1. Prerequisites

- **Python 3.11**
- **MySQL or MariaDB** running locally.
  > Do **not** use `DB_ENGINE=sqlite` (the default in `.env.example`). A fresh
  > `migrate` fails on SQLite because `billing/migrations/0029_ai_grading_module`
  > uses MySQL-only `ON DUPLICATE KEY` SQL.
- System libraries for the `mysqlclient` Python package:
  - **macOS:** `brew install mysql pkg-config`
  - **Ubuntu/Debian:** `sudo apt-get install pkg-config default-libmysqlclient-dev build-essential`
  - **Windows:** install MySQL Connector/C, or use WSL with the Ubuntu steps.

## 2. Get the code

```bash
git clone https://github.com/InoshikaFernando/CWA_CLASS_APP.git
cd CWA_CLASS_APP/cwa_classroom
git checkout claude/gracious-ptolemy-hpwzec
```

## 3. Virtualenv + dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Create the database

```bash
mysql -u root -proot -e "CREATE DATABASE cwa_classroom CHARACTER SET utf8mb4;"
```

If `root` has no password, drop `-proot` and leave `DB_PASSWORD` empty in step 5.
If you get `Access denied`, set the password to `root`:

```sql
ALTER USER 'root'@'localhost' IDENTIFIED BY 'root';
FLUSH PRIVILEGES;
```

## 5. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` to use MySQL (overriding the file's `sqlite` default):

```ini
SECRET_KEY=dev-anything-nonempty
DEBUG=True                 # must be exactly "True" — "1"/"true" won't work and forces an HTTPS redirect
ALLOWED_HOSTS=localhost,127.0.0.1
DB_ENGINE=mysql
DB_NAME=cwa_classroom
DB_USER=root
DB_PASSWORD=root
DB_HOST=127.0.0.1          # use 127.0.0.1 (TCP); "localhost" uses the unix socket
DB_PORT=3306
```

## 6. Migrate

```bash
python manage.py migrate
```

This also creates the `mathematics` and `coding` subjects.

## 7. Seed a teacher + coding questions

The builder needs a teacher login and enough questions to paginate. Paste:

```bash
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
        description=f'Practice declaring and using a variable — task #{i+1}.', is_active=True, order=i)
print('login: demo_teacher / pass1234!  | exercises:', CodingExercise.objects.filter(topic_level=tl).count())
PY
```

For the real coding bank instead of dummy exercises, run
`python manage.py seed_coding` (requires the languages/topics to exist first).

## 8. Run

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/>, log in as **`demo_teacher` / `pass1234!`**, then
go to **Worksheets → Worksheet Builder** (`/worksheets/builder/`).

## 9. Verify the pagination fix

1. Set **Subject = Coding**, **Language = Python**, **Concept = Variables**
   → 30 questions, "Page 1 of 2".
2. Click **Next →**.
3. The filters stay on Coding / Python / Variables, the layout stays intact, and
   you see questions 26–30. (Before the fix, paginating reset the filters and
   rendered the whole page inside the question list.)

## Gotchas

- **`DEBUG` must be exactly `True`.** Any other value makes Django treat
  `DEBUG=False`, which triggers `SECURE_SSL_REDIRECT` and 301-redirects every
  request to `https://…`.
- **SortableJS is loaded from a CDN** (`cdn.jsdelivr.net`). If your network
  blocks it, `Sortable` is undefined and the inline builder script throws
  `Sortable is not defined`, which silently disables the filter dropdowns. On a
  normal connection it works fine. (Pre-existing; not part of the pagination fix.)
