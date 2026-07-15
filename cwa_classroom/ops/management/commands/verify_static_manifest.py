"""
Management command: verify_static_manifest
==========================================
Fail-fast guard that every literal ``{% static 'path' %}`` reference in the
project's own templates actually resolves through the active staticfiles
storage. Under production's ``ManifestStaticFilesStorage`` an unknown path makes
``{% static %}`` raise ``ValueError: Missing staticfiles manifest entry`` *at
render time* — a 500 on a live page — so this turns that latent failure into a
loud, pre-restart deploy error instead.

This exists because a real outage: a new ``js/number_line.js`` shipped in a
template but the deploy skipped ``collectstatic``, so the manifest had no entry
and every homework "take" page 500'd. ``scripts/deploy.sh`` runs this straight
after ``collectstatic`` (fatal on failure, before the service restart), and CI
can run it too to catch a template that references an uncommitted asset before
it ever merges.

What it checks
--------------
* Scans only the project's OWN templates (settings ``TEMPLATES['DIRS']`` plus
  app ``templates/`` dirs under ``BASE_DIR``) — third-party/site-packages
  templates are skipped so their assets can't produce false failures.
* Collects every literal ``{% static '...' %}`` / ``{% static "..." %}`` path.
  References built from variables (``{% static var %}``) can't be checked
  statically and are skipped.
* Manifest storage (prod/deploy): the path must be present in the compiled
  manifest — i.e. ``collectstatic`` has run and included it.
* Non-manifest storage (dev/CI): the path must have a source file the
  staticfiles finders can locate.

Usage
-----
python manage.py verify_static_manifest          # exit 1 (CommandError) if any missing
python manage.py verify_static_manifest --list    # also print every reference checked
"""
import os
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management.base import BaseCommand, CommandError
from django.template.utils import get_app_template_dirs

# {% static 'x' %} or {% static "x" %} — single capture of the quoted literal.
STATIC_RE = re.compile(r"""\{%\s*static\s+(['"])(?P<path>[^'"]+)\1\s*%\}""")


class Command(BaseCommand):
    help = "Verify every literal {% static '...' %} template reference resolves."

    def add_arguments(self, parser):
        parser.add_argument(
            '--list', action='store_true',
            help='Print every static reference checked, not just failures.',
        )

    def _project_template_dirs(self):
        """Template dirs owned by this repo — excludes site-packages templates."""
        base = str(getattr(settings, 'BASE_DIR', ''))
        dirs = []
        for cfg in settings.TEMPLATES:
            dirs.extend(str(d) for d in cfg.get('DIRS', []))
        dirs.extend(str(d) for d in get_app_template_dirs('templates'))
        # De-dupe, keep only dirs inside the repo (if BASE_DIR is known).
        seen, kept = set(), []
        for d in dirs:
            if d in seen:
                continue
            seen.add(d)
            if base and not d.startswith(base):
                continue
            kept.append(d)
        return kept

    def _collect_references(self):
        """Map each literal static path → sorted list of templates referencing it."""
        refs = {}
        for d in self._project_template_dirs():
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    if not fn.endswith(('.html', '.svg', '.txt', '.xml')):
                        continue
                    full = os.path.join(root, fn)
                    try:
                        with open(full, encoding='utf-8') as fh:
                            text = fh.read()
                    except (OSError, UnicodeDecodeError):
                        continue
                    for m in STATIC_RE.finditer(text):
                        path = m.group('path')
                        # Skip anything that isn't a plain literal (e.g. a nested
                        # template var/tag inside the quotes) — can't verify it.
                        if '{' in path or '}' in path:
                            continue
                        refs.setdefault(path, set()).add(full)
        return {p: sorted(t) for p, t in refs.items()}

    def handle(self, *args, **options):
        refs = self._collect_references()
        # Accessing hashed_files lazily loads the manifest; its presence tells us
        # whether the active storage is manifest-backed (prod) or not (dev/CI).
        has_manifest = hasattr(staticfiles_storage, 'hashed_files')

        missing = []
        for path, templates in sorted(refs.items()):
            if has_manifest:
                if path not in staticfiles_storage.hashed_files:
                    missing.append((path, 'not in manifest (collectstatic did not include it)', templates))
            elif finders.find(path) is None:
                missing.append((path, 'no source file found by staticfiles finders', templates))

        if options['list']:
            for path in sorted(refs):
                self.stdout.write(f'  static: {path}')

        if missing:
            for path, reason, templates in missing:
                self.stderr.write(self.style.ERROR(f'MISSING static: {path} — {reason}'))
                for t in templates:
                    self.stderr.write(f'    referenced in {t}')
            raise CommandError(
                f'{len(missing)} template static reference(s) do not resolve. '
                'Run collectstatic (and commit the source file); a deploy must '
                'not ship a template that references an uncollected asset.'
            )

        storage_kind = 'manifest' if has_manifest else 'finders'
        self.stdout.write(self.style.SUCCESS(
            f'OK — all {len(refs)} literal {{% static %}} reference(s) resolve '
            f'via {storage_kind} storage.'
        ))
