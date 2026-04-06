"""
bump_version.py — SemVer bumper for CWA School App
====================================================

Usage:
    python scripts/bump_version.py patch    # 1.0.0 → 1.0.1
    python scripts/bump_version.py minor    # 1.0.0 → 1.1.0
    python scripts/bump_version.py major    # 1.0.0 → 2.0.0

What it does:
    1. Reads the current APP_VERSION from settings.py
    2. Increments the requested part (major/minor/patch)
    3. Writes APP_VERSION and APP_VERSION_DATE back to settings.py
    4. Prints a confirmation summary

Run from the project root directory.
"""

import re
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    if len(sys.argv) != 2 or sys.argv[1] not in BUMP_TYPES:
        print(f"Usage: python scripts/bump_version.py [{' | '.join(BUMP_TYPES)}]")
        sys.exit(1)

    bump_type = sys.argv[1]
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
