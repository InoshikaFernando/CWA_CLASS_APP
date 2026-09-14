# Runbook — Reference/seed data must ship in a migration

**When to use it:** whenever you add or change data the app needs to *exist in
the database* to work — a language, a subject, a currency, a question type, a
SubjectApp hub card, default settings rows. Also when someone reports "the
feature merged but I can't see it on dev/test/prod".

---

## 1. The rule

> **A deploy runs `migrate`. It never runs a management command.**
> Seed data that only a management command creates does not exist on any server.

`scripts/deploy.sh` — the script both `deploy-test.yml` and `deploy-prod.yml`
(and `deploy-dev.yml`) run over SSH — does exactly this:

```
git reset --hard origin/<branch>
pip install -r requirements.txt
python manage.py migrate --noinput        # <- the only thing that writes data
python manage.py collectstatic --noinput --clear
python manage.py check --deploy
systemctl restart <service>
```

There is no step that runs `seed_*`, `create_*`, `import_*` or any other
management command, and there should not be — a deploy has to be repeatable and
unattended. So:

- **A management command is a convenience for a human at a shell.** Useful for
  re-seeding, topping up, or fixing one server by hand.
- **A data migration is the only thing that reaches every environment.**

If you write one without the other, you have shipped code nothing executes.

## 2. What this looked like the time we got it wrong

Three separate symptoms, one cause. Worth reading because the symptom points
away from the cause every time.

**September 2026 — the Languages module.** French, Mandarin, Japanese and Korean
were added to `languages/management/commands/seed_language_exercises.py` and to
nothing else. The PR merged to `dev`, `deploy-dev.yml` ran, migrations
`0011`/`0012`/`0013` applied cleanly, and the deploy went green. `0012` and
`0013` even widened `Language.script_type` to accept `cjk`/`kana`/`hangul`, so
the schema was ready and waiting. The hub still showed English, Sinhala and
Tamil only.

The obvious reading — "the dev deploy must not be running migrations" — was
wrong, and cost an afternoon. The deploy log said:

```
==> Running migrations...
  Applying languages.0012_alter_language_script_type... OK
  Applying languages.0013_alter_language_script_type... OK
```

Migrations ran. There was simply no migration that created the rows.

**The same bug, quieter, since June.** `0010_seed_language_exercises` froze its
own copy of English/Sinhala/Tamil. Everything added to those three afterwards
went only into the command: an English *Vowels (intermediate)* topic, a Sinhala
*Consonants (advanced)* topic, 22 further English consonant prompts, and **seven
entire Tamil topics** (short vowels, long vowels, diphthongs, hard/soft/medium
consonants, the special character) that no server had ever had. Nobody noticed,
because a topic that does not exist does not render an error — it renders
nothing.

**The collation variant.** Even with a migration, MySQL's default collation is
accent- and case-insensitive, so `get_or_create` treated `e` == `é` == `è` and
`A` == `a`. French lost three of four `e` variants and Sinhala lost every
lowercase vowel — on the server only, with SQLite tests green throughout. That
is what `languages/migrations/0011_case_accent_sensitive_prompt_collation.py`
fixes, and it is why **any seeding migration must be ordered after it.**

## 3. Why CI could not catch any of it

`cwa_classroom/conftest.py`:

```python
def django_db_use_migrations():
    """Skip migrations on SQLite (tables created from models). Run on MySQL."""
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite" in engine:
        return False
    return True
```

CI runs on SQLite. The test database is built **straight from the models**, so
**no `RunPython` in this repository has ever executed under pytest.** Every unit
suite verifies what the models can do; none verifies what a deployed database
actually contains. A data migration that seeds nothing is green everywhere and
fails only on the droplet — where nothing checks it either.

The `fresh-db-migrate` job in `ci.yml` exists to close exactly that gap. It
brings up MySQL 8 (the production backend, and the only one the raw-SQL
migrations in `billing/`, `homework/` and `classroom/` can run on at all),
migrates from zero, and then asserts the data landed. It is the only place the
migration chain runs end to end.

## 4. Checklist — adding seed data

1. **Put the data in a plain module, not in the command.** The Languages app
   uses `languages/seed_data.py`: data only, no Django imports, so both a
   management command and a migration can read it. One copy or they drift.
2. **Write the data migration.** `RunPython`, `get_or_create` throughout so it
   is safe to replay (every deploy re-runs `migrate`), reverse `noop` unless
   you are certain a rollback should delete rows — cascading a delete off a
   parent can take real student work with it.
   Model on `languages/migrations/0014_seed_all_languages.py`.
3. **Use historical models**, `apps.get_model('app', 'Model')` — never
   `from app.models import Model` inside the migration function.
4. **Order it after any collation/schema migration it depends on.** On MySQL,
   seeding text before the column is case/accent-sensitive silently drops rows.
5. **Reconcile, don't just add the new thing.** An earlier frozen migration plus
   later command-only edits means existing languages/subjects are short too.
   Iterating the whole seed source costs one pass and fixes both.
6. **Extend the verification command** so CI's `fresh-db-migrate` job proves the
   data landed — see `languages/management/commands/check_language_seed.py`.
   Count rows against what the seed source declares, not just `> 0`: a
   partially-seeded language passes a non-zero check.
7. **Check the path filter.** `ci.yml`'s `migrations` filter is what makes
   `fresh-db-migrate` run. Get it wrong and the job goes quiet, not red.

## 5. Diagnosing "it merged but it isn't there"

Work in this order. Do **not** start by assuming the deploy is broken.

```bash
# 1. Did the deploy run at all, and did migrate run inside it?
#    GitHub → Actions → "Deploy to Dev"/"Deploy to Test" → the run for that merge.
#    Look for "==> Running migrations..." and the "Applying ..." lines.
#    A deploy that took ~40s and shows no Applying lines had nothing to apply —
#    that is the signal, and it means the code has no migration.

# 2. Is there actually a migration that creates the data?
git log --oneline -- cwa_classroom/<app>/migrations/
grep -rl "RunPython" cwa_classroom/<app>/migrations/

# 3. Ask the database directly, on the server.
sudo -u cwa /home/cwa/CWA_CLASS_APP_DEV/venv/bin/python \
    /home/cwa/CWA_CLASS_APP_DEV/cwa_classroom/manage.py check_language_seed
#    prod: CWA_CLASS_APP  |  test: CWA_CLASS_APP_TEST  |  dev: CWA_CLASS_APP_DEV
```

Also check the deploy did not silently no-op: `deploy-dev.yml`/`deploy-test.yml`
skip the deploy step entirely when `DEV_DEPLOY_HOST`/`TEST_DEPLOY_HOST` is unset,
and the run still reports **success**. A green run whose Deploy step was skipped
looks identical to a green run that deployed.

## 6. Unblocking a server right now

The management command is idempotent (`get_or_create` throughout), so it is safe
to run on a live server to restore missing data while the proper migration goes
through review:

```bash
sudo -u cwa /home/cwa/CWA_CLASS_APP_DEV/venv/bin/python \
    /home/cwa/CWA_CLASS_APP_DEV/cwa_classroom/manage.py seed_language_exercises
```

**This is a stopgap, not the fix.** It repairs one database. The next
environment, the next fresh build and the next restore-from-prod all start
missing the data again. The migration is what makes it permanent — and because
the migration also uses `get_or_create`, running it afterwards over a database
you already seeded by hand is a no-op.

## 7. Related

- [`production-deployment.md`](production-deployment.md) — what a deploy runs,
  and how to verify one went green.
- [`test-env-db-refresh.md`](test-env-db-refresh.md) — a refresh from a prod
  snapshot inherits prod's missing seed data; re-run `migrate` afterwards.
- `cwa_classroom/tests_migrations.py` — migration-graph health (conflicting
  leaves, missing migrations).
- `cwa_classroom/tests_workflows.py` — guards that `fresh-db-migrate` still
  exists and still checks the seed data.
