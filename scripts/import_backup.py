"""
import_backup.py
===============
Loads the CWA_SCHOOL backup.sql into the cwa_classroom MySQL database
under a `src_` prefix (src_maths_*, etc.) so the migrate_from_cwa_school
management command can read from them.

Run from the project root:
    python import_backup.py

After this, run:
    cd cwa_classroom
    python manage.py migrate_from_cwa_school
"""

import MySQLdb
import re
import sys

# ── Connection settings ───────────────────────────────────────────────────────
HOST     = '192.168.240.1'
PORT     = 3306
USER     = 'root'
PASSWORD = 'root'
DB       = 'cwa_classroom'          # the only DB we can write to
BACKUP   = r'C:\Source\CWA_CLASS_APP\backup.sql'
PREFIX   = 'src_'                   # added in front of every maths_ table

# Tables we want to migrate (skip Django system tables)
MATHS_TABLES = {
    'maths_customuser',
    'maths_customuser_groups',
    'maths_customuser_user_permissions',
    'maths_topic',
    'maths_level',
    'maths_level_topics',
    'maths_classroom',
    'maths_classroom_levels',
    'maths_enrollment',
    'maths_question',
    'maths_answer',
    'maths_studentanswer',
    'maths_basicfactsresult',
    'maths_timelog',
    'maths_topiclevelstatistics',
    'maths_studentfinalanswer',
}


def rename(name):
    """maths_foo  →  src_maths_foo"""
    if name in MATHS_TABLES:
        return PREFIX + name
    return None   # skip this table


def preprocess_sql(raw_sql):
    """
    Walk the dump line-by-line and:
    - Keep CREATE TABLE / DROP TABLE / INSERT INTO for maths_ tables only
    - Rename every `maths_foo` reference to `src_maths_foo`
    - Skip auth / django system tables and their statements
    """
    def sub_tables(text):
        """Replace every backtick-quoted maths_ table name."""
        return re.sub(
            r'`(maths_\w+)`',
            lambda m: '`' + PREFIX + m.group(1) + '`',
            text
        )

    lines = raw_sql.splitlines()
    output = []
    in_create = False
    skip_create = False
    create_block = []   # collects lines for the current CREATE TABLE body

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- DROP TABLE ---
        m = re.match(r'DROP TABLE IF EXISTS `(\w+)`', stripped)
        if m:
            tbl = m.group(1)
            if tbl in MATHS_TABLES:
                output.append(f'DROP TABLE IF EXISTS `{PREFIX}{tbl}`;')
            i += 1
            continue

        # --- START CREATE TABLE ---
        m = re.match(r'CREATE TABLE `(\w+)`', stripped)
        if m:
            tbl = m.group(1)
            if tbl in MATHS_TABLES:
                in_create = True
                skip_create = False
                create_block = [sub_tables(line)]
            else:
                in_create = True
                skip_create = True
                create_block = []
            i += 1
            continue

        # --- INSIDE CREATE TABLE ---
        if in_create:
            if stripped.startswith(') ENGINE'):
                in_create = False
                if not skip_create:
                    # Strip KEY / CONSTRAINT lines to avoid long-identifier errors.
                    # These staging tables are read-only for migration; we don't
                    # need FK constraints or secondary indexes.
                    filtered = []
                    for cl in create_block:
                        cs = cl.strip()
                        if cs.startswith(('KEY ', 'UNIQUE KEY ', 'CONSTRAINT ')):
                            continue
                        filtered.append(cl)
                    # Remove trailing comma from the last kept definition line
                    for j in range(len(filtered) - 1, -1, -1):
                        if filtered[j].strip():
                            filtered[j] = filtered[j].rstrip().rstrip(',')
                            break
                    output.extend(filtered)
                    output.append(sub_tables(line))   # ) ENGINE=... line
                create_block = []
            elif not skip_create:
                create_block.append(sub_tables(line))
            i += 1
            continue

        # --- INSERT INTO ---
        m = re.match(r'INSERT INTO `(\w+)`', stripped)
        if m:
            tbl = m.group(1)
            if tbl in MATHS_TABLES:
                output.append(sub_tables(line))
            i += 1
            continue

        # --- LOCK TABLES / UNLOCK TABLES ---
        # Skip entirely: they cause "table not locked" errors when interleaved
        # with DROP/CREATE for other tables. Not needed for a single-user import.
        if stripped.startswith('LOCK TABLES') or stripped.startswith('UNLOCK TABLES'):
            i += 1
            continue

        # --- ALTER TABLE (only for maths tables) ---
        m = re.match(r'ALTER TABLE `(\w+)`', stripped)
        if m:
            tbl = m.group(1)
            if tbl in MATHS_TABLES:
                output.append(sub_tables(line))
            i += 1
            continue

        # Skip everything else (session vars, comments, etc.)
        i += 1

    return '\n'.join(output)


def split_statements(sql):
    """
    Split preprocessed SQL into individual statements on ';' boundaries,
    being careful inside string literals.
    """
    statements = []
    current = []
    in_string = False
    string_char = ''
    escape_next = False

    for char in sql:
        if escape_next:
            current.append(char)
            escape_next = False
            continue

        if char == '\\' and in_string:
            current.append(char)
            escape_next = True
            continue

        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            current.append(char)
            continue

        if char == string_char and in_string:
            in_string = False
            current.append(char)
            continue

        if char == ';' and not in_string:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            continue

        current.append(char)

    # Last statement (if no trailing semicolon)
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def main():
    print(f"Reading {BACKUP} ...")
    with open(BACKUP, 'r', encoding='utf-8') as f:
        raw = f.read()

    print("Preprocessing SQL (keeping only maths_* tables with src_ prefix) ...")
    processed = preprocess_sql(raw)

    print("Splitting into statements ...")
    statements = split_statements(processed)
    print(f"  -> {len(statements)} statements to execute")

    print(f"Connecting to MySQL {HOST}:{PORT}/{DB} ...")
    conn = MySQLdb.connect(
        host=HOST, port=PORT, user=USER, passwd=PASSWORD,
        db=DB, charset='utf8mb4',
    )
    conn.autocommit(False)
    cur = conn.cursor()

    # Temporarily disable FK checks so we can drop/create in any order
    cur.execute('SET FOREIGN_KEY_CHECKS=0')
    cur.execute("SET NAMES utf8mb4")
    conn.commit()

    ok = 0
    errors = 0
    for i, stmt in enumerate(statements, 1):
        try:
            cur.execute(stmt)
            ok += 1
        except MySQLdb.Error as e:
            print(f"  [WARN] stmt {i}: {e}")
            print(f"         SQL: {stmt[:120]}...")
            errors += 1

    conn.commit()
    cur.execute('SET FOREIGN_KEY_CHECKS=1')
    conn.commit()
    conn.close()

    print(f"\nDone. {ok} ok, {errors} errors.")

    # Verify tables exist
    conn2 = MySQLdb.connect(host=HOST, port=PORT, user=USER, passwd=PASSWORD, db=DB)
    cur2 = conn2.cursor()
    cur2.execute(f"SHOW TABLES LIKE '{PREFIX}maths_%'")
    tables = [r[0] for r in cur2.fetchall()]
    conn2.close()
    print(f"\nTables created in {DB}:")
    for t in sorted(tables):
        print(f"  {t}")


if __name__ == '__main__':
    main()
