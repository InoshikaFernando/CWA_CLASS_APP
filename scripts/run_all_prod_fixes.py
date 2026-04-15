"""
run_all_prod_fixes.py
---------------------
Master script: runs all one-off data fixes in the correct order.
Safe to run multiple times — every step is idempotent.

Steps
-----
  1. Rename BODMAS/PEMDAS -> BODMAS and fix orphaned topic parents
  2. Merge duplicate BODMAS topics
  3. Fix unsimplified fraction answers
  4. Seed missing times-table topics and questions
  5. Consolidate duplicate parent records (merge Guardian -> ParentStudent)

Usage (run from the scripts/ directory or project root):
    python run_all_prod_fixes.py [--dry-run]

Add --dry-run to preview all changes without writing to the database.
"""

import os, sys, subprocess

DRY_RUN = '--dry-run' in sys.argv
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

def run_script(name, extra_args=None):
    path = os.path.join(SCRIPTS_DIR, name)
    args = [sys.executable, path]
    if DRY_RUN:
        args.append('--dry-run')
    if extra_args:
        args.extend(extra_args)
    print(f"\n{'='*60}")
    print(f"Running: {name}")
    print('='*60)
    result = subprocess.run(args, cwd=SCRIPTS_DIR)
    if result.returncode != 0:
        print(f"\nERROR: {name} exited with code {result.returncode}")
        sys.exit(result.returncode)

if __name__ == '__main__':
    mode = '[DRY RUN] ' if DRY_RUN else ''
    print(f"{mode}Running all production data fixes...\n")

    run_script('fix_topic_parents.py')
    run_script('fix_unsimplified_fraction_answers.py')
    run_script('seed_times_tables.py')
    run_script('fix_parent_duplicates.py')

    print(f"\n{'='*60}")
    print(f"{mode}All fixes complete.")
