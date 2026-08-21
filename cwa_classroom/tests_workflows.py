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


def _ci():
    return yaml.safe_load((WORKFLOW_DIR / 'ci.yml').read_text())


def _ci_filters():
    """The `changes` job's paths-filter config, parsed out of its YAML string."""
    for step in _ci()['jobs']['changes']['steps']:
        if step.get('id') == 'filter':
            return yaml.safe_load(step['with']['filters'])
    raise AssertionError("ci.yml: the `changes` job has no step id: filter")


def test_ci_still_runs_every_suite_on_a_push():
    """A push to main/test is the promotion gate and must not be path-filtered.

    PR runs are narrowed to the affected apps to save Actions minutes; the
    safety net is that a merge runs everything. If that `github.event_name ==
    'push'` escape were dropped, a release could promote on a partial matrix.
    """
    jobs = _ci()['jobs']
    gated = {name: job for name, job in jobs.items()
             if 'needs.changes.outputs' in (job.get('if') or '')}
    assert gated, 'Expected the path-filtered jobs to carry an if: condition'
    for name, job in gated.items():
        assert "github.event_name == 'push'" in job['if'], (
            f'ci.yml job {name!r} is path-filtered without the push escape, so '
            f'a merge to main/test could skip it')


def test_ui_matrix_runs_every_group_on_a_push():
    """Same promotion gate, for the UI suite's dynamic matrix.

    ui-tests is gated on the matrix the ui-matrix job emits rather than on the
    filters directly, so the rule above cannot see it. The full-suite escape
    lives in ui-matrix's RUN_ALL expression instead — if that lost its `push`
    arm, a merge to `test` would deploy on a partial UI matrix.
    """
    pick = None
    for step in _ci()['jobs']['ui-matrix']['steps']:
        if step.get('id') == 'pick':
            pick = step
    assert pick is not None, 'ci.yml: the ui-matrix job has no step id: pick'
    run_all = pick.get('env', {}).get('RUN_ALL', '')
    assert "github.event_name == 'push'" in run_all, (
        'ci.yml: ui-matrix RUN_ALL no longer forces the full UI matrix on a '
        'push, so the pre-production gate on `test` could run a subset')


# ---------------------------------------------------------------------------
# UI suites are split per app area (cwa_classroom/ui_tests/<group>/) and each
# group gets its own path filter + matrix entry. Nothing in GitHub Actions ties
# those two together, so a new group directory with no matching filter would
# simply never run — the tests would go quiet rather than red. These tests are
# that tie.
# ---------------------------------------------------------------------------
UI_TESTS_DIR = Path(__file__).resolve().parent / 'ui_tests'


def _ui_group_dirs():
    return sorted(
        d.name for d in UI_TESTS_DIR.iterdir()
        if d.is_dir() and (d / '__init__.py').exists()
    )


def _ui_filter_groups():
    return sorted(
        name[len('ui_'):] for name in _ci_filters()
        if name.startswith('ui_') and name != 'ui_core'
    )


def test_ui_gate_job_is_stable_and_always_runs():
    """Branch protection hangs off one check name that must not move.

    The matrix jobs are named per group, so that set changes whenever a group
    is added. `ui-tests-gate` keeps the stable name, and it only gates anything
    if it runs unconditionally and actually depends on the matrix jobs.
    """
    jobs = _ci()['jobs']
    gate = jobs.get('ui-tests-gate')
    assert gate is not None, (
        'ci.yml has no ui-tests-gate job — branch protection would have '
        'nothing stable to require')
    assert gate['name'] == 'UI Tests (Playwright)', (
        f"ui-tests-gate is named {gate['name']!r}; branch protection requires "
        f"'UI Tests (Playwright)', so renaming it silently stops the gate")
    assert 'always()' in (gate.get('if') or ''), (
        'ui-tests-gate must run with if: always(), or a failed UI group would '
        'skip the gate instead of failing it')
    needs = gate.get('needs') or []
    for dependency in ('changes', 'ui-matrix', 'ui-tests'):
        assert dependency in needs, (
            f'ui-tests-gate does not need {dependency!r}, so it cannot report '
            f'that job\'s result')


def test_ui_test_groups_exist():
    # A mapping between two empty sets would make the tests below vacuous.
    assert _ui_group_dirs(), f'No UI group packages found under {UI_TESTS_DIR}'


def test_every_ui_group_has_a_path_filter():
    """A group directory with no `ui_<group>:` filter never enters the matrix."""
    missing = sorted(set(_ui_group_dirs()) - set(_ui_filter_groups()))
    assert not missing, (
        f'ui_tests/ groups with no ui_<group> filter in ci.yml: {missing}. '
        f'Those suites would silently stop running on every PR and on the '
        f'push to `test`.')


def test_every_ui_path_filter_has_a_group():
    """A `ui_<group>:` filter with no directory fails the whole matrix entry."""
    orphans = sorted(set(_ui_filter_groups()) - set(_ui_group_dirs()))
    assert not orphans, (
        f'ci.yml declares ui_<group> filters with no matching '
        f'cwa_classroom/ui_tests/<group>/ package: {orphans}')


def test_every_ui_group_filter_watches_its_own_tests():
    """Editing a UI test must at minimum run that test's own group."""
    filters = _ci_filters()
    for group in _ui_group_dirs():
        paths = filters[f'ui_{group}']
        assert f'cwa_classroom/ui_tests/{group}/**' in paths, (
            f'ci.yml filter ui_{group} does not watch '
            f'cwa_classroom/ui_tests/{group}/**, so editing one of its tests '
            f'would not run it')


def test_no_ui_tests_outside_a_group():
    """A test file left at the ui_tests/ root belongs to no group, so no job
    would ever run it. Move it into the package for its app area."""
    strays = sorted(p.name for p in UI_TESTS_DIR.glob('test_*.py'))
    assert not strays, (
        f'UI test files sitting directly in cwa_classroom/ui_tests/: {strays}. '
        f'CI runs `pytest ui_tests/<group>` per app area, so these would never '
        f'run. Move each into the group package for its area.')


def test_ui_relative_imports_resolve():
    """Every relative import inside a group package must point at a real module.

    Moving the suites down a directory changed what `from .conftest import …`
    means, and pytest only surfaces the mistake for imports at module scope —
    one inside a function body collects fine and explodes mid-run, in whichever
    group happens to be running. This resolves them statically instead.
    """
    import ast

    broken = []
    for group in _ui_group_dirs():
        package = UI_TESTS_DIR / group
        for path in sorted(package.glob('*.py')):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.level:
                    continue
                # level 1 → the group package, level 2 → ui_tests/, and so on.
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                target = node.module or ''
                if target:
                    candidate = base.joinpath(*target.split('.'))
                    if not (candidate.with_suffix('.py').exists()
                            or (candidate / '__init__.py').exists()):
                        broken.append(
                            f'{path.relative_to(UI_TESTS_DIR.parent)}:'
                            f'{node.lineno} → '
                            f'{"." * node.level}{target}')
    assert not broken, (
        'Relative imports in ui_tests group packages that do not resolve:\n  '
        + '\n  '.join(broken)
        + '\n(after the per-area split, shared modules live one level up: '
          'use `from ..conftest import …`)')
