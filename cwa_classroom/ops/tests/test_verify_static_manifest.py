"""Tests for the verify_static_manifest deploy/CI guard."""
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


def _templates_setting(extra_dir):
    return [{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [extra_dir],
        'APP_DIRS': False,
        'OPTIONS': {},
    }]


class VerifyStaticManifestTest(SimpleTestCase):
    def test_passes_on_the_real_templates(self):
        # The project's own templates should all resolve (dev storage → finders).
        out = StringIO()
        call_command('verify_static_manifest', stdout=out)
        self.assertIn('OK', out.getvalue())

    def test_fails_when_a_referenced_asset_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            # BASE_DIR must contain the temp dir or the scanner skips it.
            with open(os.path.join(d, 'probe.html'), 'w', encoding='utf-8') as fh:
                fh.write("{% load static %}"
                         "<script src=\"{% static 'js/nope_missing_9999.js' %}\">"
                         "</script>")
            err = StringIO()
            with override_settings(BASE_DIR=d, TEMPLATES=_templates_setting(d)):
                with self.assertRaises(CommandError) as ctx:
                    call_command('verify_static_manifest', stderr=err)
        # The summary rides on the CommandError; the offending file is named on stderr.
        self.assertIn('do not resolve', str(ctx.exception))
        self.assertIn('nope_missing_9999.js', err.getvalue())

    def test_ignores_non_literal_static_references(self):
        # {% static some_var %} can't be checked statically and must not error.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'probe.html'), 'w', encoding='utf-8') as fh:
                fh.write("{% load static %}<img src=\"{% static logo_path %}\">")
            with override_settings(BASE_DIR=d, TEMPLATES=_templates_setting(d)):
                out = StringIO()
                call_command('verify_static_manifest', stdout=out)   # no raise
        self.assertIn('OK', out.getvalue())
