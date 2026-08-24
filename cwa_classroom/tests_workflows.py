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
REPO_ROOT = Path(__file__).resolve().parent.parent


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
    """A push to `test` is the promotion gate and must not be path-filtered.

    PR runs are narrowed to the affected apps to save Actions minutes; the
    safety net is that the merge to `test` runs everything. If that
    `github.event_name == 'push'` escape were dropped, a release could promote
    on a partial matrix.
    """
    jobs = _ci()['jobs']
    gated = {name: job for name, job in jobs.items()
             if 'needs.changes.outputs' in (job.get('if') or '')
             # Release-PR-only: it stands in FOR the suites on that event.
             and name != 'release-already-tested'}
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


# ---------------------------------------------------------------------------
# Coverage: every test file must be run by SOME job, and every UI group must be
# triggered by EVERY app its tests exercise.
#
# Neither is enforced by GitHub, and both had already drifted: nine billing
# suites plus all of notifications/ and usage/ belonged to no job at all, and a
# UI group could be triggered by only one of the several apps it drives.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent


def _pytest_targets():
    """Every path any ci.yml job hands to pytest, matrix entries expanded."""
    targets = set()
    for job in _ci()['jobs'].values():
        for step in job.get('steps') or []:
            for line in (step.get('run') or '').splitlines():
                if 'pytest' not in line:
                    continue
                for token in line.split():
                    if token.startswith('-') or '=' in token:
                        continue
                    if not (token.endswith('.py') or '/' in token):
                        continue
                    token = token.strip('"\'').rstrip('/')
                    if '${{' in token:
                        # `ui_tests/${{ matrix.group }}` — one target per group.
                        prefix = token.split('${{')[0].rstrip('/')
                        if prefix == 'ui_tests':
                            targets.update(f'ui_tests/{g}' for g in _ui_group_dirs())
                        continue
                    targets.add(token)
    return targets


def _all_test_files():
    skip = {'__pycache__', 'node_modules', '.venv', 'staticfiles', 'migrations'}
    found = []
    for path in PROJECT_ROOT.rglob('*.py'):
        if skip & set(path.parts):
            continue
        name = path.name
        if name.startswith('test_') or name == 'tests.py' or name.startswith('tests_'):
            found.append(path.relative_to(PROJECT_ROOT).as_posix())
    return sorted(found)


def test_there_are_test_files_to_check():
    assert _all_test_files(), 'Found no test files — the check below is vacuous'


def test_every_test_file_is_run_by_some_ci_job():
    """A test file no job names never runs — on any PR, or on the release push.

    This does NOT mean every PR runs everything: each job stays path-filtered,
    so a suite runs on the PRs that touch its area and on the push to
    main/test. It means no suite is orphaned.
    """
    targets = _pytest_targets()
    orphans = [
        f for f in _all_test_files()
        if not any(f == t or f.startswith(t + '/') for t in targets)
    ]
    assert not orphans, (
        'Test files that no ci.yml job runs, so they never execute anywhere:\n  '
        + '\n  '.join(orphans)
        + '\n\nPoint a job at the app directory (`pytest <app>/`) rather than '
          'listing files, or add a job for the app.')


def _django_apps():
    return {
        path.name for path in PROJECT_ROOT.iterdir()
        if path.is_dir() and (path / 'models.py').exists()
        and path.name != 'cwa_classroom'
    }


def _url_prefix_owners():
    """Top-level URL prefix -> the local apps served under it.

    A prefix can have more than one owner — `accounts/` is served by both
    accounts.urls and django.contrib.auth.urls — so this collects a set and
    keeps only this project's apps (django.contrib is not one of ours).
    """
    urlconf = (PROJECT_ROOT / 'cwa_classroom' / 'urls.py').read_text()
    apps = _django_apps()
    owners = {}
    for match in re.finditer(
            r"path\(\s*'([^']*)'\s*,\s*include\(\s*'([\w.]+)", urlconf):
        prefix, module = match.group(1).rstrip('/'), match.group(2).split('.')[0]
        if prefix and module in apps:
            owners.setdefault(prefix, set()).add(module)
    return owners


def _apps_used_by(group):
    """Apps a UI group's tests import from, hit a URL of, or reverse against."""
    import ast

    apps = _django_apps()
    owners = _url_prefix_owners()
    used = set()
    for path in sorted((UI_TESTS_DIR / group).glob('*.py')):
        source = path.read_text()
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                head = node.module.split('.')[0]
                if head in apps:
                    used.add(head)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split('.')[0]
                    if head in apps:
                        used.add(head)
        for prefix, prefix_apps in owners.items():
            if re.search(r'''["']/%s[/"']''' % re.escape(prefix), source):
                used |= prefix_apps
        for namespace in re.findall(r"""reverse\(\s*['"](\w+):""", source):
            if namespace in apps:
                used.add(namespace)
    return used


def test_every_ui_group_filter_covers_the_apps_it_uses():
    """A UI test that drives several apps must run when ANY of them changes.

    ui_tests/parent, for example, drives classroom views through accounts auth
    with homework and maths content — a homework change that breaks the parent
    homework page has to run the parent group, not just the homework one.
    """
    filters = _ci_filters()
    missing = {}
    for group in _ui_group_dirs():
        watched = set(filters[f'ui_{group}'])
        gaps = sorted(
            app for app in _apps_used_by(group)
            if f'cwa_classroom/{app}/**' not in watched
        )
        if gaps:
            missing[group] = gaps
    assert not missing, (
        'UI groups whose filter does not watch every app their tests drive:\n  '
        + '\n  '.join(f'ui_{g}: add {apps}' for g, apps in sorted(missing.items()))
        + '\n\nA change to one of those apps would not run these tests.')


# ---------------------------------------------------------------------------
# Release-PR cost (the Actions spending limit was reached mid-release)
# ---------------------------------------------------------------------------
# The one job that is deliberately release-PR-only: it stands in FOR the suites
# on that event, so it must not carry their push escape.
_RELEASE_GUARD_JOB = 'release-already-tested'


def _ci_data():
    return yaml.safe_load((WORKFLOW_DIR / 'ci.yml').read_text())


def _path_filtered_jobs(data):
    return {name: job for name, job in data['jobs'].items()
            if job.get('if') and "github.event_name == 'push'" in job['if']}


def test_the_full_matrix_still_runs_on_a_push_to_test():
    """`test` is the pre-production gate — dropping it would leave nothing."""
    data = _ci_data()
    # PyYAML reads a bare `on:` key as the boolean True.
    triggers = data.get('on', data.get(True))
    assert 'test' in triggers['push']['branches']


def test_a_push_to_main_does_not_re_run_the_matrix():
    """A release merge lands the identical tree that just passed on `test`."""
    data = _ci_data()
    triggers = data.get('on', data.get(True))
    assert 'main' not in triggers['push']['branches'], (
        'a push to main re-runs every suite over a tree that already passed')


def test_a_release_pr_does_not_re_run_the_whole_matrix():
    """A release PR's tree is identical to what `test` just validated."""
    for name, job in _path_filtered_jobs(_ci_data()).items():
        assert "needs.changes.outputs.release != 'true'" in job['if'], (
            f'ci.yml job {name!r} would re-run on a release PR over a tree '
            f'that already passed on test')


def test_a_release_pr_still_gets_a_check():
    """Skipping is not the same as not checking.

    A PR showing no checks is how a dead CI went unnoticed here for four days.
    The release PR must still assert the claim the skip relies on: that this
    exact commit already passed CI on `test`.
    """
    job = _ci_data()['jobs'][_RELEASE_GUARD_JOB]
    assert "needs.changes.outputs.release == 'true'" in job['if']
    script = '\n'.join(str(step) for step in job['steps'])
    assert 'listWorkflowRuns' in script
    assert 'setFailed' in script


def test_the_ui_groups_are_not_limited_to_the_runner_cpu_count():
    """`-n auto` is one worker per CPU, and a private runner has two.

    Splitting the suite by app area bounds the wall clock by the slowest
    group — but each group still ran two browsers at a time. These tests wait
    on the browser rather than computing, so the worker count is set above the
    core count.
    """
    ui = _ci_data()['jobs']['ui-tests']
    run_step = next(s for s in ui['steps']
                    if str(s.get('name', '')).startswith('Run UI tests'))
    assert '-n auto' not in run_step['run']
    assert int(run_step['env']['UI_WORKERS']) > 2, (
        'a private runner has 2 CPUs; this would not help'
    )


# ── Release hygiene: one CI matrix per release ───────────────────────────────
#
# A push to `test` runs the full matrix (~29 jobs, ~119 billed Actions
# minutes) — the path filters are deliberately ignored there so the promotion
# gate is always the whole suite. Bumping APP_VERSION on `test` AFTER a merge
# therefore buys a second full matrix per release, and the second push cancels
# the first mid-flight so ~25 already-running jobs are paid for and discarded.
#
# On 2026-08-24 that happened three times in one evening and helped exhaust the
# Actions spending limit, which stopped every workflow in the repo — including
# the production deploy. bump_version.py refuses to run on a protected branch
# so the bump lands in the feature PR and the merge is a single push.
#
# These live here because this file runs in the ungated migration-check job, so
# a change that quietly removes the guard cannot slip through on a path filter.

def _bump_script():
    return (REPO_ROOT / 'scripts' / 'bump_version.py').read_text(encoding='utf-8')


def test_bump_version_refuses_to_run_on_a_protected_branch():
    src = _bump_script()
    assert 'PROTECTED_BRANCHES' in src, (
        'bump_version.py must refuse to bump on test/main — bumping there costs '
        'a second full CI matrix per release and cancels the first one.'
    )
    assert "'test'" in src and "'main'" in src, (
        'both protected branches must be named in PROTECTED_BRANCHES'
    )


def test_bump_version_keeps_an_escape_hatch():
    # A hotfix straight to a protected branch must still be possible; the guard
    # is there to stop the accident, not to block a deliberate release.
    assert '--allow-protected' in _bump_script()


def test_bump_version_says_why_it_refused():
    # A bare "refused" teaches people to reach for the escape hatch. The cost
    # and the alternative have to be in the message.
    src = _bump_script()
    for phrase in ('feature branch', 'matrix'):
        assert phrase in src, f'the refusal message should mention {phrase!r}'

