"""
coding.execution
~~~~~~~~~~~~~~~~
Thin client around the Piston code-execution API.

All student code is run inside Piston's sandbox — never via subprocess on
the Django server directly.

Piston API docs: https://github.com/engineer-man/piston
Expected env variable: PISTON_API_URL  (e.g. http://localhost:2000)
"""

import time

import requests
from django.conf import settings

# Default to localhost where Piston is expected to run via Docker.
PISTON_URL = getattr(settings, 'PISTON_API_URL', 'http://localhost:2000')
PISTON_TOKEN = getattr(settings, 'PISTON_API_TOKEN', '')


def _auth_headers():
    """Build Authorization header for Piston requests.

    Returns an empty dict when no token is configured so the client
    still works against a local unauthenticated Piston (for dev).
    """
    return {'Authorization': f'Bearer {PISTON_TOKEN}'} if PISTON_TOKEN else {}

# Hard timeout so student infinite loops never hang the server.
# Set high enough to honour per-problem time_limit_seconds values (e.g. 10 s for
# N-Queens, 8 s for LIS).  The per-problem limit is always applied first; this
# constant is only the absolute maximum the runner will ever grant.
EXECUTION_TIMEOUT_SECONDS = 15

# Memory ceiling per execution (bytes).  256 MB matches the per-problem default
# declared in problem JSON files.  The per-problem value is applied first; this
# constant is the absolute maximum.
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB

# Piston runtime versions — language names must match Piston's registry
# Use GET /api/v2/runtimes to see what's installed
RUNTIME_VERSIONS = {
    'python': '3.10.0',
    'javascript': '18.15.0',
}


def run_code(language, code, stdin='', timeout_seconds=None, memory_limit_mb=None):
    """Execute code via Piston and return a normalised result dict.

    Args:
        language (str):         Piston language identifier, e.g. 'python', 'javascript'
        code (str):             Source code to execute
        stdin (str):            Optional stdin to pipe into the program
        timeout_seconds (int):  Per-execution wall-clock limit; falls back to
                                EXECUTION_TIMEOUT_SECONDS if not provided.
        memory_limit_mb (int):  Per-execution memory ceiling in MB; converted to bytes
                                and falls back to MEMORY_LIMIT_BYTES if not provided.

    Returns:
        dict with keys:
            stdout    (str)  — program output
            stderr    (str)  — error output
            exit_code (int)  — 0 = success
            error     (str)  — set only if Piston itself failed (network, timeout, etc.)
    """
    if not language:
        return {'stdout': '', 'stderr': '', 'exit_code': 1, 'error': 'Language not supported for server-side execution'}

    # Per-problem limits are advisory but must never exceed the runner's
    # configured hard caps, otherwise Piston can reject execution requests.
    try:
        requested_timeout = int(timeout_seconds) if timeout_seconds is not None else EXECUTION_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        requested_timeout = EXECUTION_TIMEOUT_SECONDS
    effective_timeout = max(1, min(requested_timeout, EXECUTION_TIMEOUT_SECONDS))

    try:
        requested_memory_bytes = (
            int(memory_limit_mb) * 1024 * 1024
            if memory_limit_mb is not None else MEMORY_LIMIT_BYTES
        )
    except (TypeError, ValueError):
        requested_memory_bytes = MEMORY_LIMIT_BYTES
    effective_memory = max(16 * 1024 * 1024, min(requested_memory_bytes, MEMORY_LIMIT_BYTES))

    version = RUNTIME_VERSIONS.get(language, '*')

    payload = {
        'language': language,
        'version': version,
        'files': [{'content': code}],
        'stdin': stdin or '',
        'run_timeout': effective_timeout * 1000,     # Piston expects milliseconds
        'compile_timeout': effective_timeout * 1000,
        'run_memory_limit': effective_memory,         # bytes — enforced by Piston runner
    }

    try:
        _t0 = time.monotonic()
        response = requests.post(
            f'{PISTON_URL}/api/v2/execute',
            json=payload,
            headers=_auth_headers(),
            timeout=effective_timeout + 2,  # slightly longer than Piston's own timeout
        )
        response.raise_for_status()
        data = response.json()
        _elapsed = time.monotonic() - _t0

        # Piston returns {"message": "..."} (no "run" key) when a configuration
        # limit is exceeded (e.g. run_timeout > Piston's configured cap).
        # Surface this as a clear stderr message rather than silent empty output.
        if 'message' in data and 'run' not in data:
            return {
                'stdout': '',
                'stderr': f'Piston rejected execution: {data["message"]}',
                'exit_code': 1,
                'run_time_seconds': _elapsed,
                'error': data['message'],
            }

        run = data.get('run', {})
        # Be tolerant to schema variations across executor versions.
        # Standard Piston v2 uses run.stdout / run.stderr / run.code, but
        # some installations expose run.output or top-level stdout/stderr/code.
        # Always coerce to str so callers never receive None.
        stdout = run.get('stdout')
        if stdout is None:
            stdout = run.get('output')
        if stdout is None:
            stdout = data.get('stdout')
        stdout = stdout if stdout is not None else ''

        stderr = run.get('stderr')
        if stderr is None:
            stderr = data.get('stderr')
        stderr = stderr if stderr is not None else ''

        exit_code = run.get('code')
        if exit_code is None:
            exit_code = run.get('exit_code')
        if exit_code is None:
            exit_code = data.get('code')
        # If Piston returns null for the exit code (process killed by signal),
        # treat it as a failure (non-zero) so the test case is marked failed.
        if exit_code is None:
            exit_code = 1

        return {
            'stdout': stdout,
            'stderr': stderr,
            'exit_code': exit_code,
            # Server-measured wall time (monotonic clock) for the full round-trip
            # to the Piston sandbox.  The standard Piston v2 API does not expose
            # per-execution timing, so we measure it here.  Network latency to the
            # local Docker container is constant across submissions and fair.
            'run_time_seconds': _elapsed,
        }

    except requests.exceptions.Timeout:
        return {
            'stdout': '',
            'stderr': 'Execution timed out.',
            'exit_code': 1,
            'run_time_seconds': float(effective_timeout + 2),
            'error': 'timeout',
        }
    except requests.exceptions.ConnectionError:
        return {
            'stdout': '',
            'stderr': 'Code execution service is unavailable. Please try again later.',
            'exit_code': 1,
            'run_time_seconds': float(effective_timeout + 2),
            'error': 'connection_error',
        }
    except Exception as exc:
        import traceback
        return {
            'stdout': '',
            'stderr': str(exc),
            'exit_code': 1,
            'run_time_seconds': float(effective_timeout + 2),
            'error': str(exc),
        }


def piston_health_check():
    """Return (ok: bool, detail: str) — used by the admin health view.

    Calls GET /api/v2/runtimes and reports which languages are available.
    """
    try:
        response = requests.get(f'{PISTON_URL}/api/v2/runtimes', headers=_auth_headers(), timeout=5)
        response.raise_for_status()
        runtimes = response.json()
        available = {r['language'] for r in runtimes}
        needed = set(RUNTIME_VERSIONS.keys())  # {'python', 'node'}
        missing = needed - available
        if missing:
            return False, f'Piston up but missing runtimes: {", ".join(missing)}'
        return True, f'Piston OK — runtimes: {", ".join(sorted(available))}'
    except requests.exceptions.ConnectionError:
        return False, f'Cannot connect to Piston at {PISTON_URL}'
    except Exception as exc:
        return False, str(exc)
