"""The checked-in OpenAPI schema is the contract, so it must stay current.

The mobile client is generated from ``api/schema.yml``. If the file drifts
from the code, the generated client describes an API that no longer exists and
the mismatch shows up as a runtime crash in a shipped build rather than as a
diff in review. This test makes the drift a red build instead.

When it fails, regenerate:

    python manage.py spectacular --file api/schema.yml

and read the diff — that diff IS the API change you are making.
"""

from pathlib import Path

import pytest
import yaml
from django.core.management import call_command

SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'schema.yml'


def _without_version(schema):
    """Compare everything except the version stamp.

    ``info.version`` tracks APP_VERSION, which every release bumps. Comparing
    it would turn a routine version bump into a schema failure and train
    everyone to regenerate without reading the diff — which is the one thing
    this test exists to make people do.
    """
    schema = dict(schema)
    info = dict(schema.get('info', {}))
    info.pop('version', None)
    schema['info'] = info
    return schema


@pytest.fixture
def generated_schema():
    from io import StringIO

    out = StringIO()
    call_command('spectacular', '--format', 'openapi', stdout=out)
    return yaml.safe_load(out.getvalue())


def test_the_checked_in_schema_exists():
    assert SCHEMA_PATH.exists(), (
        'api/schema.yml is missing — the mobile client is generated from it.')


def test_the_checked_in_schema_matches_the_code(generated_schema):
    committed = yaml.safe_load(SCHEMA_PATH.read_text())
    assert _without_version(committed) == _without_version(generated_schema), (
        'api/schema.yml is out of date. Regenerate it with:\n'
        '    python manage.py spectacular --file api/schema.yml\n'
        'and check the diff — it is the API change you are shipping.')


def test_every_endpoint_declares_authentication(generated_schema):
    """A path with no security scheme is a path anyone can call.

    Login and token refresh are the deliberate exceptions: they are how a
    caller gets a token in the first place.
    """
    public = {'/api/v1/auth/login/', '/api/v1/auth/refresh/', '/api/v1/auth/verify/'}
    unsecured = []
    for path, operations in generated_schema['paths'].items():
        if path in public:
            continue
        for method, operation in operations.items():
            if method not in ('get', 'post', 'put', 'patch', 'delete'):
                continue
            if not operation.get('security', True):
                unsecured.append(f'{method.upper()} {path}')
    assert not unsecured, f'Endpoints with no authentication: {unsecured}'


def test_the_schema_advertises_the_bearer_scheme(generated_schema):
    """Without this the generated client never sends the Authorization header
    and every call 401s."""
    schemes = generated_schema['components']['securitySchemes']
    assert schemes['jwtAuth']['scheme'] == 'bearer'
