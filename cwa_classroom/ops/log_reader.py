"""Read the tail of the application log files for the in-app viewer.

The reason this exists: on 2026-09-07 a student's checkout failed eleven times
with a precise Stripe message — *The price specified is inactive* — and that
message existed only in ``/var/log/cwa/django-error.log``. Finding it took an
SSH session and a grep, two weeks later. The audit log records business events;
there was nowhere in the app to read an application error.

Three things this deliberately does NOT do:

* **Never read a whole file.** They rotate at 10 MB. Only the last
  ``MAX_TAIL_BYTES`` are read, seeking from the end.
* **Never accept a path from the request.** The caller passes a key from
  ``LOG_FILES``; anything else is refused. A log viewer that takes a filename
  is a file-disclosure bug wearing a hat.
* **Never split a traceback.** A Python traceback is a dozen lines after one
  log header, and one line of it is useless. Continuation lines are folded into
  the entry they belong to.
"""
import os
import re
from pathlib import Path

from django.conf import settings

#: Files the viewer may read, by key. The request never names a path.
LOG_FILES = {
    'error': {
        'name': 'django-error.log',
        'label': 'Errors',
        'help': 'ERROR and above — exceptions, failed checkouts, anything that broke.',
    },
    'app': {
        'name': 'django-app.log',
        'label': 'Application',
        'help': 'WARNING and above — the errors plus everything worth noticing.',
    },
    'slow': {
        'name': 'slow-queries.log',
        'label': 'Slow queries',
        'help': 'Queries over the threshold, and requests issuing too many.',
    },
}

DEFAULT_FILE = 'error'

#: How far back from the end of the file to read. Enough for a few thousand
#: lines; small enough that a 10 MB log costs nothing to open.
MAX_TAIL_BYTES = 512 * 1024

#: Levels offered as a filter, most severe first.
LEVELS = ['ERROR', 'WARNING', 'INFO', 'DEBUG']

# [2026-09-08 15:04:04,769] ERROR accounts.views views:1082 — the message
_ENTRY_RE = re.compile(
    r'^\[(?P<ts>[^\]]+)\]\s+(?P<level>[A-Z]+)\s+(?P<logger>\S+)\s+'
    r'(?P<location>\S+)\s+[—-]\s+(?P<message>.*)$'
)


def log_dir():
    return Path(getattr(settings, 'LOG_DIR', '/var/log/cwa'))


def _candidate_paths(key):
    """The live file then its rotated backups, newest first.

    ``RotatingFileHandler`` names them ``.log``, ``.log.1``, ``.log.2`` … so a
    failure from before the last rotation is still reachable — which matters,
    since the incident that prompted this was two weeks old.
    """
    name = LOG_FILES[key]['name']
    base = log_dir() / name
    paths = [base]
    for i in range(1, 6):
        paths.append(log_dir() / f'{name}.{i}')
    return paths


def _tail_bytes(path, max_bytes=MAX_TAIL_BYTES):
    """Return the last ``max_bytes`` of a file as text, or '' if unreadable."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # discard the partial first line
            return fh.read().decode('utf-8', errors='replace')
    except (OSError, ValueError):
        return ''


def _parse(text):
    """Split raw log text into entries, folding continuation lines in.

    A traceback follows its header line, so anything that does not start a new
    entry belongs to the one before it.
    """
    entries = []
    for line in text.splitlines():
        match = _ENTRY_RE.match(line)
        if match:
            entries.append({
                'timestamp': match.group('ts'),
                'level': match.group('level'),
                'logger': match.group('logger'),
                'location': match.group('location'),
                'message': match.group('message'),
                'detail': '',
            })
        elif entries:
            entries[-1]['detail'] += ('\n' if entries[-1]['detail'] else '') + line
        # A continuation with no preceding header (the tail cut mid-entry) is
        # dropped: half a traceback with no timestamp is noise.
    return entries


def read_log(key=DEFAULT_FILE, level='', search='', limit=200):
    """Return recent log entries, newest first.

    Returns ``(entries, meta)``. ``meta`` explains itself when there is nothing
    to show — an empty list because the directory does not exist is a very
    different answer from an empty list because nothing has gone wrong, and the
    page must not present them identically.
    """
    if key not in LOG_FILES:
        key = DEFAULT_FILE

    meta = {
        'key': key,
        'file': LOG_FILES[key]['name'],
        'label': LOG_FILES[key]['label'],
        'help': LOG_FILES[key]['help'],
        'dir': str(log_dir()),
        'available': True,
        'note': '',
        'files_read': [],
        'truncated': False,
    }

    if not log_dir().exists():
        meta['available'] = False
        meta['note'] = (
            f'No log directory at {log_dir()} — logging goes to the console on '
            f'this server, so there is nothing to read here.'
        )
        return [], meta

    level = (level or '').upper()
    needle = (search or '').strip().lower()

    entries = []
    for path in _candidate_paths(key):
        if not path.exists():
            continue
        meta['files_read'].append(path.name)
        for entry in _parse(_tail_bytes(path)):
            if level and entry['level'] != level:
                continue
            if needle and needle not in (
                    entry['message'] + entry['detail'] + entry['logger']).lower():
                continue
            entries.append(entry)
        # Newest first: the live file usually satisfies the limit on its own,
        # so a rotated backup is only opened when it does not.
        if len(entries) >= limit:
            meta['truncated'] = True
            break

    entries.reverse()  # file order is oldest-first; show newest at the top

    if not entries and not meta['note']:
        if not meta['files_read']:
            meta['available'] = False
            meta['note'] = (
                f'No {LOG_FILES[key]["name"]} in {log_dir()} yet — nothing has '
                f'been written to it.'
            )
        elif level or needle:
            meta['note'] = 'No entries match this filter.'
        else:
            meta['note'] = 'Nothing logged — this file is empty.'

    return entries[:limit], meta
