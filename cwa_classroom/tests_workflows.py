"""Validate the GitHub Actions workflow files.

CI silently stopped running for two days. A duplicate `ai-import-tests:` job key
made ci.yml invalid, and an invalid workflow does not fail loudly — GitHub
creates a run that dies in zero seconds and reports it by FILE PATH rather than
the workflow's name, so pull requests simply show no checks at all. Nothing goes
red. Everything merged in that window went in unverified.

Duplicate keys are the specific trap: PyYAML's safe_load accepts them silently
(last one wins), so "the YAML parses" proves nothing. GitHub rejects them.

These tests run in the migration-check job, which is deliberately ungated, so
they execute on every push and pull request.
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / '.github' / 'workflows'


class _DuplicateKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of silently
    keeping the last one — which is exactly what GitHub Actions does."""


def _no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(
                f'duplicate key {key!r} at line {key_node.start_mark.line + 1}')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def _workflow_files():
    return sorted(WORKFLOW_DIR.glob('*.yml')) + sorted(WORKFLOW_DIR.glob('*.yaml'))


def test_there_are_workflows_to_check():
    # A glob that matches nothing would make every test below vacuously pass.
    assert _workflow_files(), f'No workflow files found under {WORKFLOW_DIR}'


@pytest.mark.parametrize('path', _workflow_files(), ids=lambda p: p.name)
def test_workflow_has_no_duplicate_keys(path):
    try:
        yaml.load(path.read_text(), Loader=_DuplicateKeyLoader)
    except yaml.YAMLError as exc:
        pytest.fail(
            f'{path.name} is not a valid workflow: {exc}\n'
            f'GitHub rejects the whole file, so NO jobs run and pull requests '
            f'show no checks rather than a failure.')


@pytest.mark.parametrize('path', _workflow_files(), ids=lambda p: p.name)
def test_workflow_declares_name_triggers_and_jobs(path):
    data = yaml.safe_load(path.read_text())
    assert data.get('name'), f'{path.name} has no name:'
    # PyYAML parses the `on:` key as the boolean True.
    assert data.get(True) or data.get('on'), f'{path.name} has no triggers'
    assert data.get('jobs'), f'{path.name} defines no jobs'


@pytest.mark.parametrize('path', _workflow_files(), ids=lambda p: p.name)
def test_every_needs_target_exists(path):
    """A job that `needs:` a job which isn't defined also invalidates the file."""
    data = yaml.safe_load(path.read_text())
    jobs = data.get('jobs') or {}
    for job_name, job in jobs.items():
        needs = job.get('needs') or []
        if isinstance(needs, str):
            needs = [needs]
        for dependency in needs:
            assert dependency in jobs, (
                f'{path.name}: job {job_name!r} needs {dependency!r}, '
                f'which is not defined')


# The one job that is deliberately release-PR-only: it stands in FOR the
# suites on that event, so it must not carry their push escape.
_RELEASE_GUARD_JOB = 'release-already-tested'


def _ci():
    return yaml.safe_load((WORKFLOW_DIR / 'ci.yml').read_text())


def _suite_jobs(data):
    return {name: job for name, job in data['jobs'].items()
            if job.get('if') and name != _RELEASE_GUARD_JOB}


def test_ci_still_runs_every_suite_on_a_push():
    """A push to `test` is the promotion gate and must not be path-filtered.

    PR runs are narrowed to the affected apps to save Actions minutes; the
    safety net is that the merge to `test` runs everything. If that
    `github.event_name == 'push'` escape were dropped, a release could promote
    on a partial matrix.
    """
    gated = _suite_jobs(_ci())
    assert gated, 'Expected the path-filtered jobs to carry an if: condition'
    for name, job in gated.items():
        assert "github.event_name == 'push'" in job['if'], (
            f'ci.yml job {name!r} is path-filtered without the push escape, so '
            f'a merge to test could skip it')


def test_the_full_matrix_still_runs_on_a_push_to_test():
    """`test` is the pre-production gate — dropping it would leave nothing."""
    data = _ci()
    # PyYAML reads a bare `on:` key as the boolean True.
    triggers = data.get('on', data.get(True))
    assert 'test' in triggers['push']['branches']


def test_a_release_pr_does_not_re_run_the_whole_matrix():
    """A release PR's tree is identical to what `test` just validated.

    Re-running ~20 suites and the UI suite over it proved nothing and cost a
    second full matrix per release — which is how the Actions spending limit
    was reached mid-release.
    """
    for name, job in _suite_jobs(_ci()).items():
        assert "needs.changes.outputs.release != 'true'" in job['if'], (
            f'ci.yml job {name!r} would re-run on a release PR over a tree '
            f'that already passed on test')


def test_a_release_pr_still_gets_a_check():
    """Skipping is not the same as not checking.

    A PR showing no checks at all is how a dead CI went unnoticed for four
    days. The release PR must still assert the claim the skip relies on: that
    this exact commit already passed CI on `test`.
    """
    job = _ci()['jobs'][_RELEASE_GUARD_JOB]
    assert "needs.changes.outputs.release == 'true'" in job['if']
    script = '\n'.join(str(step) for step in job['steps'])
    assert 'listWorkflowRuns' in script
    assert 'setFailed' in script


def test_the_ui_suite_is_not_limited_to_the_runner_cpu_count():
    """`-n auto` is one worker per CPU, and a private runner has two.

    1362 browser tests two at a time took ~33 minutes. They are I/O-bound —
    waiting on the browser rather than computing — so the worker count is set
    explicitly above the core count.
    """
    ui = _ci()['jobs']['ui-tests']
    run_step = next(s for s in ui['steps'] if s.get('name') == 'Run UI tests')
    assert '-n auto' not in run_step['run']
    workers = int(run_step['env']['UI_WORKERS'])
    assert workers > 2, 'a private runner has 2 CPUs; this would not help'
