"""
coding.execution
~~~~~~~~~~~~~~~~
Thin client around the Piston code-execution API.

All student code is run inside Piston's sandbox — never via subprocess on
the Django server directly.

Piston API docs: https://github.com/engineer-man/piston
Expected env variable: PISTON_API_URL  (e.g. http://localhost:2000)
"""

import requests
from django.conf import settings

# Default to localhost where Piston is expected to run via Docker.
PISTON_URL = getattr(settings, 'PISTON_API_URL', 'http://localhost:2000')

# Hard timeout so student infinite loops never hang the server.
# Must not exceed Piston's configured run_timeout limit (3000 ms).
EXECUTION_TIMEOUT_SECONDS = 3

# Memory ceiling per execution (bytes). 128 MB is generous for typical student code.
MEMORY_LIMIT_BYTES = 128 * 1024 * 1024  # 128 MB

# Piston runtime versions — language names must match Piston's registry
# Use GET /api/v2/runtimes to see what's installed
RUNTIME_VERSIONS = {
    'python': '3.10.0',
    'javascript': '18.15.0',
}


def run_code(language, code, stdin=''):
    """Execute code via Piston and return a normalised result dict.

    Args:
        language (str): Piston language identifier, e.g. 'python', 'javascript'
        code (str): Source code to execute
        stdin (str): Optional stdin to pipe into the program

    Returns:
        dict with keys:
            stdout    (str)  — program output
            stderr    (str)  — error output
            exit_code (int)  — 0 = success
            error     (str)  — set only if Piston itself failed (network, timeout, etc.)
    """
    if not language:
        return {'stdout': '', 'stderr': '', 'exit_code': 1, 'error': 'Language not supported for server-side execution'}

    version = RUNTIME_VERSIONS.get(language, '*')

    payload = {
        'language': language,
        'version': version,
        'files': [{'content': code}],
        'stdin': stdin or '',
        'run_timeout': EXECUTION_TIMEOUT_SECONDS * 1000,   # Piston expects milliseconds
        'compile_timeout': EXECUTION_TIMEOUT_SECONDS * 1000,
    }

    try:
        response = requests.post(
            f'{PISTON_URL}/api/v2/execute',
            json=payload,
            timeout=EXECUTION_TIMEOUT_SECONDS + 2,  # slightly longer than Piston's own timeout
        )
        response.raise_for_status()
        data = response.json()

        run = data.get('run', {})
        return {
            'stdout': run.get('stdout', ''),
            'stderr': run.get('stderr', ''),
            'exit_code': run.get('code', 1),
        }

    except requests.exceptions.Timeout:
        return {
            'stdout': '',
            'stderr': 'Execution timed out.',
            'exit_code': 1,
            'error': 'timeout',
        }
    except requests.exceptions.ConnectionError:
        return {
            'stdout': '',
            'stderr': 'Code execution service is unavailable. Please try again later.',
            'exit_code': 1,
            'error': 'connection_error',
        }
    except Exception as exc:
        import traceback
        return {
            'stdout': '',
            'stderr': str(exc),
            'exit_code': 1,
            'error': str(exc),
        }


def piston_health_check():
    """Return (ok: bool, detail: str) — used by the admin health view.

    Calls GET /api/v2/runtimes and reports which languages are available.
    """
    try:
        response = requests.get(f'{PISTON_URL}/api/v2/runtimes', timeout=5)
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
