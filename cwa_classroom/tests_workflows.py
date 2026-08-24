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
    safety net is that the merge to `test` runs everything. If that escape
    were dropped, a release could promote on a partial matrix.

    The 20 per-app unit jobs are now one job whose targets come from the diff,
    so for those the escape moved from 20 `if:` conditions into the RUN_ALL of
    the step that builds the list. Both forms are checked here — a job that
    still decides for itself must carry it in its `if:`, and the step that
    decides for the rest must carry it in RUN_ALL.
    """
    jobs = _ci()['jobs']
    # These two run INSTEAD OF suites, and only when the tree they cover has
    # already passed elsewhere. Requiring the push escape on them would mean
    # reporting "already tested" on a push that was not.
    stands_in_for_a_suite = {'release-already-tested', 'ui-already-tested'}
    # unit-tests runs whatever `changes` selected for it; the escape that
    # fills that list in full on a push is asserted below instead.
    decided_by_a_step = {'unit-tests'}
    gated = {name: job for name, job in jobs.items()
             if 'needs.changes.outputs' in (job.get('if') or '')
             and name not in stands_in_for_a_suite | decided_by_a_step}
    assert gated, 'Expected the path-filtered jobs to carry an if: condition'
    for name, job in gated.items():
        assert "github.event_name == 'push'" in job['if'], (
            f'ci.yml job {name!r} is path-filtered without the push escape, so '
            f'a merge to main/test could skip it')

    run_all = _unit_step()['env']['RUN_ALL']
    assert "github.event_name == 'push'" in run_all, (
        'ci.yml: the unit suites no longer all run on a push to test. They are '
        'the cheap half of CI and the half that catches one app breaking '
        'another — which a PR narrowed to the changed app cannot see.')
    assert 'shared' in run_all, (
        'ci.yml: a change to the project package, requirements or conftest no '
        'longer runs every unit suite, so it would run only the apps whose '
        'own paths happened to change')


def test_the_unit_job_is_the_only_thing_that_can_orphan_a_suite():
    """One job now decides whether ~20 suites run at all.

    Losing a line from UNIT_SUITES does not fail anything at runtime — the job
    still passes, having quietly run one suite fewer. `classroom` is absent by
    design (it keeps its own job), so it is named here rather than left to
    look like an omission.
    """
    targets = _unit_suite_targets()
    assert 'classroom/' not in targets, (
        'ci.yml: classroom is in UNIT_SUITES as well as its own job, so it '
        'would run twice')
    assert _ci()['jobs'].get('classroom-tests'), (
        'ci.yml: classroom has neither its own job nor a UNIT_SUITES entry'
    )
    assert len(targets) == len(set(targets)), (
        f'ci.yml: UNIT_SUITES repeats a target: {sorted(targets)}')

    job = _ci()['jobs']['unit-tests']
    run_step = next(s for s in job['steps']
                    if str(s.get('name', '')).startswith('Run unit suites'))
    assert '$DIRS' in run_step['run'], (
        'ci.yml: the unit job no longer runs the list `changes` built for it')
    assert "needs.changes.outputs.unit_dirs != ''" in job['if'], (
        'ci.yml: the unit job would run with an empty argument list, which is '
        '`pytest` over the whole tree')


def _unit_step():
    """The step in `changes` that picks the unit suites for this diff."""
    for step in _ci()['jobs']['changes']['steps']:
        if step.get('id') == 'unit':
            return step
    raise AssertionError(
        "ci.yml: the `changes` job has no step id: unit, so unit_dirs is "
        "always empty and NO unit suite runs anywhere")


def _unit_suite_targets():
    """Every pytest target the one unit job can be asked to run.

    The 20 per-app jobs became a single job whose arguments come from this map,
    so it — not a `run:` line — is now what decides whether a suite ever runs.
    """
    env = _unit_step()['env']
    targets = []
    for line in env['UNIT_SUITES'].splitlines():
        line = line.strip()
        if not line:
            continue
        key, _, target = line.partition(':')
        assert target, f'ci.yml: UNIT_SUITES entry {line!r} has no pytest target'
        targets.append(target)
    targets.append(env['UNIT_SHARED_ONLY'])
    return targets


def _ui_matrix_run_all():
    pick = None
    for step in _ci()['jobs']['ui-matrix']['steps']:
        if step.get('id') == 'pick':
            pick = step
    assert pick is not None, 'ci.yml: the ui-matrix job has no step id: pick'
    return pick.get('env', {}).get('RUN_ALL', '')


def test_ui_matrix_is_path_filtered_on_a_push():
    """The UI matrix follows the diff on a push, not the event.

    It used to force all 15 groups on every push to `test`. That is 67 of the
    ~120 billed minutes a full matrix costs, on every merge — and the groups
    are large rather than slow (classroom 231 tests, billing 233, navigation
    223), so the only lever is running fewer of them. At ~8 merges a day it was
    ~$5.75 of a ~$16.50 daily bill, and on 2026-08-24 the account hit its
    Actions spending limit, which stopped every workflow in the repo including
    the production deploy.

    The unit suites stay unfiltered on a push — see the test above. They are
    the cheap half and the half that catches cross-app breakage.
    """
    assert "github.event_name == 'push'" not in _ui_matrix_run_all(), (
        'ci.yml: ui-matrix RUN_ALL forces the whole UI matrix on every push '
        'again. That is the most expensive thing in CI and it is what '
        'exhausted the Actions spending limit.')


def test_ui_matrix_still_runs_everything_for_a_shared_change():
    """The escape that makes the filter safe.

    A change to base templates, the sidebar, shared static or shared fixtures
    can break any page, so those bypass the per-group filter on BOTH events. If
    this went, a `ui_core` change would run only the groups whose own paths
    happened to change and the rest would go quiet.
    """
    run_all = _ui_matrix_run_all()
    for key in ('needs.changes.outputs.shared', 'needs.changes.outputs.ui_core'):
        assert key in run_all, (
            f'ci.yml: ui-matrix RUN_ALL no longer forces the full matrix on a '
            f'{key} change — a change that can break any page would run a subset')


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
                    if token == '$DIRS':
                        # `pytest $DIRS` — the unit job's arguments are built
                        # by the `changes` job, so the map there is the real
                        # list of targets.
                        targets.update(t.rstrip('/')
                                       for t in _unit_suite_targets())
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


# ── The UI matrix is deduped against the PR run, and ONLY the UI matrix ──────
#
# A `pull_request` run tests `refs/pull/N/merge`, not the PR head, so when a
# merge to `test` lands a tree the PR already held, the push re-runs the UI
# groups over byte-identical content. `changes.ui_already_tested` detects that.
#
# The danger is that someone extends it to the unit suites, where the same
# reasoning does NOT hold: PR runs are path-filtered, so a green PR means the
# touched app passed, not that app A's change left app B working. The push run
# is the only thing that checks that, and it must stay unconditional.

_DEDUPE_OUTPUT = 'ui_already_tested'
_DEDUPE_REPORT_JOB = 'ui-already-tested'


def test_only_the_ui_matrix_is_deduped_against_the_pr_run():
    """The unit suites must never skip because a (narrowed) PR run was green.

    They are unfiltered on a push precisely to catch one app breaking another,
    which a PR run scoped to the changed app cannot see. Gating them on
    ui_already_tested would delete that signal while still looking green.
    """
    jobs = _ci_data()['jobs']
    users = {name for name, job in jobs.items()
             if _DEDUPE_OUTPUT in (job.get('if') or '')}
    assert users == {'ui-matrix', _DEDUPE_REPORT_JOB}, (
        f'ci.yml: {_DEDUPE_OUTPUT} gates {sorted(users)}. It is only sound for '
        f'the UI matrix — the unit suites run unfiltered on a push because a '
        f'PR run is narrowed to the apps it touched.')


def test_the_ui_matrix_dedupe_proves_the_tree_is_identical():
    """The skip rests on four claims; none of them may quietly disappear.

    tree equality alone is not enough (the PR must also have been up to date
    with `test`, or `refs/pull/N/merge` tested a different merge), and neither
    is an up-to-date branch without a run that actually passed.
    """
    step = None
    for candidate in _ci_data()['jobs']['changes']['steps']:
        if candidate.get('id') == 'tested':
            step = candidate
    assert step is not None, (
        'ci.yml: the `changes` job has no step id: tested, so '
        f'{_DEDUPE_OUTPUT} can never be true')

    script = step['with']['script']
    for claim, why in (
        ('parents.length !== 2', 'only a merge commit has a PR head to compare'),
        ('tree.sha !== merge.tree.sha', 'the landed tree must be the tested one'),
        ('compareCommitsWithBasehead', 'the PR must have been up to date with test'),
        ('listWorkflowRuns', 'a PR run must actually exist'),
        ("conclusion === 'success'", 'and it must have passed'),
    ):
        assert claim in script, (
            f'ci.yml: the UI dedupe no longer checks {claim!r} — {why}')

    assert step['if'].count('refs/heads/test') == 1, (
        'ci.yml: the UI dedupe must only ever fire on a push to test')


def test_a_deduped_push_still_gets_a_ui_check():
    """Skipping is not the same as not checking.

    A push showing no UI check at all is indistinguishable from a CI that has
    silently stopped running the suite — which went unnoticed here for four
    days once already.
    """
    job = _ci_data()['jobs'][_DEDUPE_REPORT_JOB]
    assert f"needs.changes.outputs.{_DEDUPE_OUTPUT} == 'true'" in job['if']
    assert job.get('name'), 'the report job needs a readable check name'


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

