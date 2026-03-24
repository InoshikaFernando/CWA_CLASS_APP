# MySQL Commands Reference

Quick reference for connecting to and managing the CWA Classroom databases.

---

## Connection Details

| | Local | Test | Production |
|---|---|---|---|
| **Host** | `127.0.0.1` | `avinesh.mysql.pythonanywhere-services.com` | `avinesh.mysql.pythonanywhere-services.com` |
| **Port** | `3306` | `3306` | `3306` |
| **Database** | `cwa_classroom` | `avinesh$cwa_classroom_test` | `avinesh$cwa_classroom` |
| **User** | `root` | `avinesh` | `avinesh` |
| **Password** | `root` | `wenuskala!1` | `wenuskala!1` |
| **URL** | — | `test-cwa-class-avinesh.pythonanywhere.com` | `wizardslearninghub.co.nz` |

---

## Connect to MySQL

### Local

```bash
mysql -u root -proot -h 127.0.0.1 -P 3306 cwa_classroom
```

### Test

```bash
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com -P 3306 avinesh\$cwa_classroom_test
```

### Production

```bash
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com -P 3306 avinesh\$cwa_classroom
```

> **Note:** On PythonAnywhere, you can also use the MySQL console from the **Databases** tab in the dashboard.

---

## Database Backup (mysqldump)

> **Note:** PythonAnywhere requires `--no-tablespaces` flag (no PROCESS privilege).

### Local

```bash
mysqldump -u root -proot -h 127.0.0.1 cwa_classroom > backup_local_$(date +%Y%m%d).sql
```

### Test

```bash
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom_test > backup_test_$(date +%Y%m%d).sql
```

### Production

```bash
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom > backup_prod_$(date +%Y%m%d).sql
```

### Backup a single table

```bash
# Example: backup the quiz_quizattempt table from production
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom quiz_quizattempt > quiz_attempt_backup.sql
```

### Backup structure only (no data)

```bash
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com --no-data avinesh\$cwa_classroom > schema_only.sql
```

---

## Restore Database

### Restore to local

```bash
mysql -u root -proot -h 127.0.0.1 cwa_classroom < backup_file.sql
```

### Restore to test

```bash
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom_test < backup_file.sql
```

### Restore to production

```bash
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom < backup_file.sql
```

---

## Copy Between Environments

### Production -> Local

```bash
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom > prod_dump.sql
mysql -u root -proot -h 127.0.0.1 cwa_classroom < prod_dump.sql
```

### Production -> Test

```bash
mysqldump --no-tablespaces -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom > prod_dump.sql
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom_test < prod_dump.sql
```

### Local -> Test

```bash
mysqldump -u root -proot -h 127.0.0.1 cwa_classroom > local_dump.sql
mysql -u avinesh -p'wenuskala!1' -h avinesh.mysql.pythonanywhere-services.com avinesh\$cwa_classroom_test < local_dump.sql
```

---

## Common Queries

### Show all tables

```sql
SHOW TABLES;
```

### Check table row counts

```sql
SELECT table_name, table_rows
FROM information_schema.tables
WHERE table_schema = 'cwa_classroom'
ORDER BY table_rows DESC;
```

### List all users

```sql
SELECT id, email, first_name, last_name, role, is_active
FROM accounts_user
ORDER BY id;
```

### Check database size

```sql
SELECT table_schema AS 'Database',
       ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)'
FROM information_schema.tables
WHERE table_schema = 'cwa_classroom'
GROUP BY table_schema;
```

### Check individual table sizes

```sql
SELECT table_name,
       ROUND((data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)',
       table_rows AS 'Rows'
FROM information_schema.tables
WHERE table_schema = 'cwa_classroom'
ORDER BY (data_length + index_length) DESC;
```

---

## Django Management Commands

### Run migrations

```bash
python manage.py migrate
```

### Show migration status

```bash
python manage.py showmigrations
```

### Create a new migration

```bash
python manage.py makemigrations
```

### Reset dev passwords after restoring a prod backup

```bash
python manage.py reset_users_for_dev
```

### Seed initial data (roles, levels, subjects, packages)

```bash
python manage.py setup_data
```

### Full local dev setup (seed data + test users)

```bash
python manage.py setup_dev
```

### Import from legacy CWA_SCHOOL database

```bash
python manage.py migrate_from_cwa_school
```

### Generate number puzzles

```bash
python manage.py generate_puzzles
```

---

## Useful Admin Queries

### Reset a user password (via Django shell)

```bash
python manage.py shell -c "
from accounts.models import User
u = User.objects.get(email='user@example.com')
u.set_password('newpassword')
u.save()
print('Password reset for', u.email)
"
```

### Check active student count

```sql
SELECT COUNT(*) AS active_students
FROM accounts_user
WHERE role = 'student' AND is_active = 1;
```

### List classes with student counts

```sql
SELECT c.name, c.code, COUNT(cs.id) AS students
FROM classroom_class c
LEFT JOIN classroom_classstudent cs ON cs.class_field_id = c.id
GROUP BY c.id
ORDER BY students DESC;
```

### Check recent quiz attempts

```sql
SELECT u.email, q.title, qa.score, qa.completed_at
FROM quiz_quizattempt qa
JOIN accounts_user u ON u.id = qa.student_id
JOIN quiz_quiz q ON q.id = qa.quiz_id
ORDER BY qa.completed_at DESC
LIMIT 20;
```

---

## Troubleshooting

### Can't connect to local MySQL

```bash
# Check if MySQL is running
sudo service mysql status

# Start MySQL
sudo service mysql start
```

### Access denied errors on PythonAnywhere

- Verify credentials in the **Databases** tab on PythonAnywhere dashboard
- Database names on PythonAnywhere are prefixed with your username (`avinesh$`)
- The `$` must be escaped in bash: `avinesh\$cwa_classroom`

### Character encoding issues

The project uses `utf8mb4`. To verify:

```sql
SHOW VARIABLES LIKE 'character_set%';
```

### Check current connections

```sql
SHOW PROCESSLIST;
```
