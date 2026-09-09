"""Guard the operational shell scripts in ``scripts/``.

These are not covered by any app's unit suite, and two of the ways they go
wrong are silent:

1. **A credential written into the file.** ``restore_prod_to_test.sh`` and its
   sanitiser both carried the production MySQL password as a literal shell
   default for the life of the PythonAnywhere era. Nothing failed; the secret
   simply sat in git.

2. **A prod→test copy that leaves test unable to take payments.** A prod dump
   carries prod's LIVE Stripe price ids. Restored onto a test site running
   ``sk_test_`` keys, Stripe answers "No such price" and the app shows its
   generic "contact support" — nothing goes red, and you find out from a
   tester's screenshot a day later. That is a real September 2026 incident.
   The restore script has to blank those ids, mint test-mode replacements, and
   then *prove* the result is chargeable.

Runs in the ungated migration-check job, so it executes on every push and PR.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / 'scripts'

# Defaults that are obviously a local-development placeholder rather than a
# real secret. Anything else appearing as a password default is a leak.
PLACEHOLDER_PASSWORDS = {'root', 'password', 'changeme', 'local', 'test', ''}
PLACEHOLDER_MARKERS = ('dev', 'local', 'change', 'example', 'placeholder',
                       'test', 'dummy')

# The one-off that carried the data off PythonAnywhere. It names that host by
# definition; every other script must not.
PA_MIGRATION_SCRIPT = 'migrate_db_pa_to_do.sh'

# The host itself, not the word. Prose explaining that the app *left*
# PythonAnywhere is exactly what we want in these files.
PA_HOSTS = re.compile(r'[\w.-]*pythonanywhere(?:-services)?\.com')


def _looks_like_a_placeholder(value):
    v = value.lower()
    return v in PLACEHOLDER_PASSWORDS or any(m in v for m in PLACEHOLDER_MARKERS)

RESTORE_TO_TEST = SCRIPTS / 'restore_prod_to_test.sh'


def _shell_scripts():
    return sorted(SCRIPTS.glob('*.sh'))


def test_there_are_scripts_to_check():
    assert _shell_scripts(), 'Found no shell scripts — the checks below are vacuous'


@pytest.mark.parametrize('path', _shell_scripts(), ids=lambda p: p.name)
def test_shell_script_parses(path):
    """``bash -n`` — a syntax error in an ops script surfaces mid-restore."""
    result = subprocess.run(['bash', '-n', str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f'{path.name} is not valid bash:\n{result.stderr}')


@pytest.mark.parametrize('path', _shell_scripts(), ids=lambda p: p.name)
def test_no_credential_baked_into_a_script(path):
    """No real password may appear as a literal default in a committed script.

    Catches the two shapes we actually had:
        DB_PASS="${DB_PASS:-hunter2}"
        mysql -phunter2 ...
    """
    text = path.read_text()
    offences = []

    for match in re.finditer(
            r'^\s*(?:export\s+)?([A-Z_]*(?:PASS|PASSWORD|SECRET|TOKEN|KEY)[A-Z_]*)'
            r'\s*=\s*"?\$\{\1:-([^}]*)\}',
            text, re.MULTILINE):
        var, default = match.group(1), match.group(2).strip().strip('"\'')
        if not _looks_like_a_placeholder(default):
            offences.append(f'{var} defaults to a literal value')

    # `-p<literal>` on a mysql/mysqldump invocation. A variable reference is
    # fine; a bare word is the password itself.
    for match in re.finditer(r'\b(?:mysql|mysqldump)\b[^\n]*?\s-p(?!["\']?\$)(\S+)',
                             text):
        offences.append(f'mysql invoked with a literal password: -p{match.group(1)}')

    assert not offences, (
        f'{path.name} appears to contain a credential:\n  '
        + '\n  '.join(offences)
        + '\n\nRead it from the systemd env files in /etc/cwa/ (see '
          'restore_prod_to_test.sh) or from the caller\'s environment.')


@pytest.mark.parametrize(
    'path',
    [p for p in _shell_scripts() if p.name != PA_MIGRATION_SCRIPT],
    ids=lambda p: p.name)
def test_no_script_still_points_at_pythonanywhere(path):
    """Both sites run on DigitalOcean. A PythonAnywhere host is a dead default.

    A script that silently defaults to an unreachable host does not fail
    honestly — it fails at connect time with a message that reads like a
    network problem.
    """
    hosts = sorted(set(PA_HOSTS.findall(path.read_text().lower())))
    assert not hosts, (
        f'{path.name} still points at a PythonAnywhere host ({", ".join(hosts)}), '
        f'which the app left for DigitalOcean. Only {PA_MIGRATION_SCRIPT} (the '
        f'one-off migration) may name it. A script defaulting to an unreachable '
        f'host fails at connect time with what looks like a network problem.')


# ── restore_prod_to_test.sh specifically ─────────────────────────────────────

def test_the_restore_script_exists():
    assert RESTORE_TO_TEST.exists(), 'scripts/restore_prod_to_test.sh is missing'


def test_restore_reads_credentials_from_the_droplet_env_files():
    text = RESTORE_TO_TEST.read_text()
    assert '/etc/cwa/cwa.env' in text, 'prod credentials must come from /etc/cwa/cwa.env'
    assert '/etc/cwa/cwa-test.env' in text, 'test credentials must come from /etc/cwa/cwa-test.env'


def test_restore_refuses_a_target_that_is_not_test():
    """The guard that stands between this script and the production database."""
    text = RESTORE_TO_TEST.read_text()
    assert '*test*' in text, (
        'restore_prod_to_test.sh must refuse a destination DB name that does '
        'not contain "test" — it DROPs that database.')
    assert 'DROP DATABASE' in text and 'exit 1' in text


def test_restore_refuses_a_live_stripe_key():
    """Re-pointing Stripe against sk_live_ would bill a tester's real card."""
    text = RESTORE_TO_TEST.read_text()
    assert 'sk_live_' in text, (
        'restore_prod_to_test.sh must abort when the test env still holds a '
        'live Stripe secret key.')


def test_restore_sanitizes_before_it_finishes():
    text = RESTORE_TO_TEST.read_text()
    assert 'sanitize_test_db.py' in text, (
        'A restored prod dump holds real emails and password hashes. The '
        'restore must sanitise, not leave it to whoever remembers.')


def test_restore_repoints_stripe_at_test_mode_objects():
    """The regression guard for the September 2026 test-site outage.

    Sanitising blanks the live price ids; on its own that leaves every package
    with no price, which fails checkout just as surely. The prices have to be
    re-created in test mode.
    """
    text = RESTORE_TO_TEST.read_text()
    assert 'sync_stripe_prices --create-missing' in text, (
        'restore_prod_to_test.sh must mint/link test-mode Stripe prices after '
        'sanitising, or the test site cannot take a payment.')
    assert 'sync_stripe_coupons' in text, (
        'Discount codes need test-mode coupons too, or a coded checkout '
        'overcharges or fails.')


def test_restore_ends_on_a_hard_payment_gate():
    """Silent success is the failure mode this whole change exists to remove."""
    text = RESTORE_TO_TEST.read_text()
    assert 'check_stripe_prices' in text, (
        'restore_prod_to_test.sh must verify every configured price is '
        'chargeable before declaring the environment ready.')
    gate = text[text.index('check_stripe_prices'):]
    assert 'exit 1' in gate, (
        'check_stripe_prices must be a gate: a broken price has to exit '
        'non-zero, not print a warning into a scrollback nobody reads.')


def test_restore_verifies_no_real_emails_remain():
    text = RESTORE_TO_TEST.read_text()
    assert 'accounts_customuser' in text and 'test.local' in text, (
        'restore_prod_to_test.sh must count unscrubbed emails and fail if any '
        'remain — a half-run sanitiser is a data-protection incident.')


# ── sanitize_test_db.py ──────────────────────────────────────────────────────

def test_sanitizer_covers_every_invariant_the_runbook_claims():
    """The runbook promises passwords, emails, Stripe ids and sessions."""
    text = (SCRIPTS / 'sanitize_test_db.py').read_text()
    for needle, why in [
        ('make_password', 'must reset every password'),
        ('@test.local', 'must rewrite every email'),
        ('stripe_price_id', 'must blank live Stripe price ids'),
        ('EmailQueue', 'must drop prod queued mail, which holds real invoices'),
        ('Session', 'must clear sessions so no prod login carries over'),
    ]:
        assert needle in text, f'sanitize_test_db.py {why} ({needle!r} not found)'


def test_sanitizer_refuses_a_non_test_database():
    text = (SCRIPTS / 'sanitize_test_db.py').read_text()
    assert "('test', 'dev')" in text and 'ABORT' in text, (
        'sanitize_test_db.py must refuse to run against a DB whose name is '
        'neither test nor dev — it rewrites every password in it.')
