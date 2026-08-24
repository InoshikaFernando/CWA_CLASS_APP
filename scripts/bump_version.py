"""
bump_version.py — SemVer bumper for CWA School App
====================================================

Usage:
    python scripts/bump_version.py patch    # 1.0.0 → 1.0.1
    python scripts/bump_version.py minor    # 1.0.0 → 1.1.0
    python scripts/bump_version.py major    # 1.0.0 → 2.0.0

What it does:
    1. Refuses to run on `test` or `main` (see below)
    2. Reads the current APP_VERSION from settings.py
    3. Increments the requested part (major/minor/patch)
    4. Writes APP_VERSION and APP_VERSION_DATE back to settings.py
    5. Prints a confirmation summary

Run from the project root directory.

WHY IT REFUSES TO RUN ON `test`
-------------------------------
Bump on the FEATURE BRANCH, before the PR merges — not on `test` afterwards.

A push to `test` runs the full CI matrix (~29 jobs, ~119 billed Actions
minutes; the path filters are deliberately ignored there so the promotion gate
is always the whole suite). Bumping on `test` after a merge therefore means TWO
full matrices per release instead of one — and worse, the second push cancels
the first mid-flight, so the ~25 jobs already running are paid for and thrown
away. On 2026-08-24 that pattern ran three times in one evening and helped
exhaust the Actions spending limit, which stopped every workflow in the repo
including the production deploy.

Bumping on the feature branch makes the merge a single push carrying the
version, so one release costs one matrix. The release gate
("Release tree already tested on test") still finds its green run, because that
run is now the merge itself.

If you genuinely must bump on a protected branch — a hotfix going straight out
— pass --allow-protected and accept the second matrix.
"""

import re
import subprocess
import sys
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SETTINGS_FILE = Path(__file__).resolve().parent.parent / 'cwa_classroom' / 'cwa_classroom' / 'settings.py'

VERSION_RE = re.compile(r"^(APP_VERSION\s*=\s*['\"])(\d+\.\d+\.\d+)(['\"])", re.MULTILINE)
DATE_RE    = re.compile(r"^(APP_VERSION_DATE\s*=\s*['\"])([\d\-]+)(['\"])",   re.MULTILINE)

BUMP_TYPES = ('major', 'minor', 'patch')

# Bumping here costs a second full CI matrix and cancels the one already
# running for the merge (see the module docstring).
PROTECTED_BRANCHES = ('test', 'main')

ALLOW_PROTECTED_FLAG = '--allow-protected'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_branch():
    """The checked-out branch, or None if git cannot say (detached HEAD, no git).

    Returning None rather than raising: an unknown branch must not stop a
    release, it just cannot be checked.
    """
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    name = out.stdout.strip()
    return name or None


def refuse_on_protected_branch(allow_protected):
    """Exit unless this bump is happening somewhere it will not cost a matrix."""
    if allow_protected:
        return
    branch = current_branch()
    if branch not in PROTECTED_BRANCHES:
        return
    sys.exit(
        f"ERROR: refusing to bump the version on '{branch}'.\n"
        f"\n"
        f"A push to 'test' runs the full CI matrix (~119 billed Actions\n"
        f"minutes). Bumping here means a second full matrix for the release,\n"
        f"and it cancels the one already running for the merge — those jobs\n"
        f"are paid for and thrown away.\n"
        f"\n"
        f"Bump on the feature branch instead, before the PR merges:\n"
        f"\n"
        f"    git checkout <your-feature-branch>\n"
        f"    python scripts/bump_version.py {{patch|minor|major}}\n"
        f"    git commit -am 'Release vX.Y.Z' && git push\n"
        f"\n"
        f"The merge to 'test' then carries the version in one push, and the\n"
        f"release gate finds that run.\n"
        f"\n"
        f"Hotfix straight to a protected branch? Re-run with "
        f"{ALLOW_PROTECTED_FLAG}."
    )


def read_settings():
    return SETTINGS_FILE.read_text(encoding='utf-8')


def write_settings(content):
    SETTINGS_FILE.write_text(content, encoding='utf-8')


def parse_version(text):
    match = VERSION_RE.search(text)
    if not match:
        sys.exit(f"ERROR: Could not find APP_VERSION in {SETTINGS_FILE}")
    return match.group(2)


def bump(version_str, bump_type):
    major, minor, patch = map(int, version_str.split('.'))
    if bump_type == 'major':
        return f"{major + 1}.0.0"
    elif bump_type == 'minor':
        return f"{major}.{minor + 1}.0"
    elif bump_type == 'patch':
        return f"{major}.{minor}.{patch + 1}"


def apply(content, new_version, new_date):
    content = VERSION_RE.sub(lambda m: f"{m.group(1)}{new_version}{m.group(3)}", content)
    content = DATE_RE.sub(   lambda m: f"{m.group(1)}{new_date}{m.group(3)}",    content)
    return content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    allow_protected = ALLOW_PROTECTED_FLAG in args
    args = [a for a in args if a != ALLOW_PROTECTED_FLAG]

    if len(args) != 1 or args[0] not in BUMP_TYPES:
        print(f"Usage: python scripts/bump_version.py "
              f"[{' | '.join(BUMP_TYPES)}] [{ALLOW_PROTECTED_FLAG}]")
        sys.exit(1)

    bump_type = args[0]
    refuse_on_protected_branch(allow_protected)
    content   = read_settings()

    old_version = parse_version(content)
    new_version = bump(old_version, bump_type)
    new_date    = datetime.date.today().isoformat()   # e.g. 2026-04-07

    updated = apply(content, new_version, new_date)

    if updated == content:
        sys.exit("ERROR: Nothing was changed — check regex patterns in bump_version.py")

    write_settings(updated)

    print(f"[OK] Version bumped ({bump_type})")
    print(f"     {old_version}  ->  {new_version}")
    print(f"     Date: {new_date}")
    print(f"     File: {SETTINGS_FILE.relative_to(Path.cwd())}")


if __name__ == '__main__':
    main()
