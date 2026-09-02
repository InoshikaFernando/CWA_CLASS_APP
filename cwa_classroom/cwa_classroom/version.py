"""The app version, on its own, so bumping it does not run the whole test suite.

This is one constant in one file for one reason: **CI cost**.

`APP_VERSION` used to live in ``settings.py``, and ``settings.py`` is inside the
project package, which the `shared` path filter in ``.github/workflows/ci.yml``
watches — rightly, since a change to settings, urls, middleware or the WSGI
entry point can break any app in the repo. `shared` is the filter's "run
everything" escape hatch.

But the runbook requires every feature branch to bump `APP_VERSION` before its
PR merges. So *every* PR touched `settings.py`, *every* PR tripped `shared`,
and the path filtering that the rest of ci.yml is built around never once
narrowed anything. PR #834 is the worked example: it changed three files under
``maths/`` plus this one line, and CI ran all 20 unit suites, the classroom
suite and all 15 Playwright groups on 5 runners — and then did it again on the
merge to ``test``.

Moving the constant here fixes that at the source. ``ci.yml`` lists the project
package file by file, this file deliberately absent, so a version bump selects
the suites the *rest* of the diff needs and nothing more. A settings change
still runs everything, exactly as before.

The classification is enforced, not trusted: ``tests_workflows.py`` fails the
build if any file in the project package is neither watched by `shared` nor
named as the version file, so a new module cannot quietly go unwatched.

Bump it with ``python scripts/bump_version.py patch`` — never by hand, and
never on ``test`` or ``main`` (see that script for why).
"""

APP_VERSION = '1.28.1'        # MAJOR.MINOR.PATCH
APP_VERSION_DATE = '2026-09-02'     # ISO date of this release
