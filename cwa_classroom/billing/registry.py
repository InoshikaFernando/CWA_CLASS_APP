"""What each module owns, declared in one place.

Until now "which feature is paid for" was answered by whether somebody
remembered to write ``required_module`` on a view. That is opt-in, so it fails
open: a new view, a new app, or a capability rebuilt in a different module
ships free, and nothing anywhere reports it. Two real examples, both found by
reading the resolved URL table rather than the code:

* the CPP-388 progress-report rebuild, readable by any school on any plan;
* seven absence-token routes served out of ``attendance/`` — an app that is
  not in ``INSTALLED_APPS``, whose view modules ``classroom/urls.py`` imports
  directly, so it was invisible to every check that looked at settings.

This registry inverts that. It states, per module, the routes and API
basenames it owns, and states the base product explicitly. Anything that
matches neither is a build failure (``tests_module_registry.py``), so a new
route has to make an entitlement decision to merge at all.

Two rules keep this from becoming a second, drifting copy of the truth:

1. **The view marker wins.** ``required_module`` on a view class is read
   first, so the 48 views that already declare one are not re-listed here and
   cannot disagree with this file.
2. **Only what a marker cannot reach is declared here** — function-based
   views, DRF viewsets, and whole namespaces.

``enforcement`` records where a module can actually be enforced, which is not
a detail: two of them have no request to hang a gate off at all.
"""

from dataclasses import dataclass

# How a module is enforced. A module is not "route" just because it has pages.
ROUTE = 'route'      # a URL the middleware/mixin sees
API = 'api'          # a DRF viewset, gated by permission or queryset filter
SERVICE = 'service'  # no request exists — cron, signal or service call

# Who can buy it.
INSTITUTE = 'institute'
INDIVIDUAL = 'individual'
BOTH = 'both'


@dataclass(frozen=True)
class Module:
    slug: str
    name: str
    audience: str = INSTITUTE
    enforcement: tuple = (ROUTE,)
    #: URL namespaces owned outright (``brainbuzz:*``).
    namespaces: tuple = ()
    #: Exact url names, un-namespaced.
    route_names: tuple = ()
    #: Url-name prefixes, un-namespaced.
    route_prefixes: tuple = ()
    #: View modules owned outright (``classroom.views_invoicing``), matched on
    #: the dotted path of the view's own module.
    #:
    #: This exists for a module that lives *inside* a base app, where claiming
    #: by url name is unsafe. ``classroom`` cannot leave ``BASE_APPS`` — it
    #: also holds classes, enrolment and the timetable — so an invoicing route
    #: nobody claimed falls through to base and ships free, and the build stays
    #: green because the route *is* accounted for. Claiming the view module
    #: instead means a new view in that file is owned the moment it exists,
    #: which is the only version of this that survives someone adding a page in
    #: six months without reading this file.
    view_modules: tuple = ()
    #: DRF router basenames, as registered in ``api/urls.py``.
    api_basenames: tuple = ()
    #: Tier family this module belongs to, e.g. ``ai_import``. Blank for a
    #: module that stands alone.
    #:
    #: A family is a set of slugs a school holds exactly *one* of, where the
    #: tier decides an allowance rather than which pages open. Holding any of
    #: them must therefore open all of the family's routes, and that is not
    #: automatic: :func:`module_for_route` returns the *first* registry entry
    #: whose namespace or prefix matches, so without this an ``ai_import``
    #: route resolves to ``ai_import_starter`` for everyone and a school on
    #: Enterprise is denied a page it has paid more for. Shadow mode is the
    #: only reason that has not been seen in production.
    #:
    #: Use :func:`satisfied_by` to turn a requirement into the set of slugs
    #: that meet it; never compare a resolved module slug directly against a
    #: school's entitlements.
    family: str = ''
    #: Free-text note for the module the sales page will need.
    note: str = ''


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# Slugs must match billing.ModuleSubscription.MODULE_CHOICES exactly; a test
# holds the two together, so a module you can buy but cannot enforce — or
# enforce but cannot buy — fails the build.

REGISTRY: dict[str, Module] = {}


def _add(module: Module) -> Module:
    REGISTRY[module.slug] = module
    return module


_add(Module(
    slug='students_attendance',
    name='Students Attendance',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    route_prefixes=(
        'attendance_', 'class_attendance', 'session_attendance',
        'student_attendance_', 'student_mark_attendance', 'student_absence_',
        'student_available_makeup_sessions', 'student_redeem_absence_token',
        'student_request_absence_token', 'absence_token_',
        'start_session', 'create_session', 'complete_session',
        'cancel_session', 'delete_session',
        'parent_attendance', 'hod_attendance_report',
    ),
    api_basenames=('attendance', 'session'),
))

_add(Module(
    slug='teachers_attendance',
    name='Teachers Attendance',
    audience=INSTITUTE,
    route_names=('teacher_self_attendance',),
))

_add(Module(
    slug='student_progress_reports',
    name='Student Progress Reports',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    namespaces=('progress',),
    route_prefixes=('student_report', 'period_report', 'report_preview',
                    'report_settings'),
    api_basenames=('report',),
))

_add(Module(
    slug='invoicing',
    name='Student Invoicing',
    audience=INSTITUTE,
    enforcement=(ROUTE,),
    # Claimed by view module, not by url name. The 29 staff routes are named
    # inconsistently enough (`zero_balances`, `csv_upload`, `student_search_api`,
    # `reference_mappings`, `invoicing_scope_classes`) that a prefix list would
    # be a guessing game, and a missed name here does not fail the build — it
    # falls through to `classroom`, which is base. Owning the module is exact.
    view_modules=('classroom.views_invoicing',),
    # The stragglers, which live in other view modules and so must be named.
    # The four parent routes are the family-facing half: a parent has no school
    # of their own, so the gate follows the *student's* school, exactly as the
    # progress-report gate does.
    route_names=(
        'parent_invoices', 'parent_invoice_detail',
        'parent_invoice_pay', 'parent_invoice_pay_success',
        'update_student_fee', 'admin_department_update_fee',
    ),
    note=('Fee schedules, invoice numbering, line items, part-payments and '
          'reversals, plus parent card checkout. Base product until 1.36.0.'),
))

_add(Module(
    slug='report_automation',
    name='Student Report Automation',
    audience=INSTITUTE,
    # No routes of its own: it is a *mode* on a setting the reports module
    # already sells, read by the nightly generate_progress_reports command.
    # Enforced in progress.report_settings.enabled_classrooms().
    enforcement=(SERVICE,),
    note='Scheduled, unattended sending. Manual sending stays in the base reports module.',
))

for _slug, _label in (
    ('question_automation_starter', 'Question Automation — Starter'),
    ('question_automation_professional', 'Question Automation — Professional'),
    ('question_automation_unlimited', 'Question Automation — Unlimited'),
):
    _add(Module(
        slug=_slug, name=_label, audience=INSTITUTE,
        # Pages AND cron: schedule_services.due_weeks() runs with no request.
        enforcement=(ROUTE, SERVICE),
        route_prefixes=('schedule_',),
        family='question_automation',
        note=('Teaching plan scheduled across a term or year, built '
              'unattended. Tiered by concurrently running schedules.'),
    ))

for _slug, _label, _pages in (
    ('ai_import_starter', 'AI Question Import — Starter', 300),
    ('ai_import_professional', 'AI Question Import — Professional', None),
    ('ai_import_enterprise', 'AI Question Import — Enterprise', None),
):
    _add(Module(
        slug=_slug, name=_label, audience=INSTITUTE,
        # One namespace, three tiers: whichever tier is held opens the same
        # pages, and the tier decides the monthly page quota.
        namespaces=('ai_import',),
        family='ai_import',
        note='Tiered by pages/month.',
    ))

for _slug, _label in (
    ('ai_grading_starter', 'AI Grading — Starter'),
    ('ai_grading_professional', 'AI Grading — Professional'),
    ('ai_grading_enterprise', 'AI Grading — Enterprise'),
):
    _add(Module(
        slug=_slug, name=_label, audience=INSTITUTE,
        # Enforced inside worksheets.grading_service, not on a URL: grading
        # happens on submission and in background jobs.
        enforcement=(SERVICE,),
        family='ai_grading',
        note='Tiered by AI-graded answers/month.',
    ))


# --- Modules that exist as features today but are not yet sold -------------
# Declared so the registry is a complete map of the product and so shadow mode
# can measure who would be affected. They are only *enforced* when
# MODULE_ENFORCEMENT is switched on — see billing.middleware.

_add(Module(
    slug='brainbuzz',
    name='BrainBuzz Live Quiz',
    audience=INSTITUTE,
    namespaces=('brainbuzz',),
    note='Live in-class quiz sessions with join codes and leaderboards.',
))

_add(Module(
    slug='worksheets',
    name='Worksheets',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    namespaces=('worksheets',),
    api_basenames=('worksheet-assignment', 'worksheet-submission'),
    note='AI grading is sold separately on top of this.',
))

_add(Module(
    slug='whatsapp_notifications',
    name='WhatsApp Parent Notifications',
    audience=INSTITUTE,
    # Signals and RQ tasks; there is no request anywhere in the send path.
    enforcement=(SERVICE,),
    note='Enforced at the send path in whatsapp.services.',
))


# ---------------------------------------------------------------------------
# The base product
# ---------------------------------------------------------------------------
# Everything in every plan. Stated positively, so a new app is unclassified
# (a build failure) rather than silently free.

BASE_NAMESPACES = frozenset({
    'homework',      # question_automation carves its schedule_* routes out
    'help',
    'feedback',
    'taskqueue',
    'sprints',
    'maths',         # subject content — see SUBJECT_PACKS below
    'coding',
    'music',
    'science',
})

#: Top-level view-module packages whose routes are base unless a module rule
#: above claims them. Ordered as they appear in INSTALLED_APPS.
BASE_APPS = frozenset({
    'accounts',      # auth, registration, profile
    'classroom',     # classes, enrolment, subjects, timetable
    'billing',       # plans, checkout, invoices — you must be able to pay us
    'quiz',
    'progress',      # the un-namespaced student dashboard, not the reports
    'audit',
    'usage',
    'ops',
    'api',           # auth + schema endpoints
    'number_puzzles',
    'maths',
    'coding',
    'music',
    'science',
    'homework',
    'help',
    'feedback',
    'taskqueue',
    'sprints',
    'cwa_classroom',  # health check, sitemap, static pages
    'notifications',
    # Points and the global leaderboard, free for every student on every plan.
    # This one is a deliberate commercial choice rather than an oversight, so
    # it is stated here rather than left to fall through: the leaderboard is
    # what makes a student do the next piece of work. It is the first thing
    # they see — hub/home.html renders the board, and should_show_daily_popup()
    # puts "Top Wizards" in front of them once a day on their first hub load.
    # Charging for the thing that drives the engagement every other paid
    # module is measured by would be charging for our own retention.
    #
    # It is also the one module that could not have been gated cleanly: the
    # enforcement middleware only reaches the API, while the hub card is
    # rendered server-side by classroom/views.py. Enforcing it would have left
    # the board on screen with the API refusing to fill it.
    'rewards',
})

#: Apps that are wholly a paid module. Deliberately absent from BASE_APPS: a
#: route here that no module rule claims must fail the build rather than fall
#: through to "base", which is how the attendance routes stayed free.
FULLY_MODULAR_APPS = frozenset({
    'attendance', 'brainbuzz', 'worksheets', 'ai_import',
})

#: Subject packs are a *future* split: maths and coding are base today. Listed
#: so the intent is on the record and the change is one line, not an audit.
SUBJECT_PACKS_NOT_YET_SOLD = ('maths', 'coding')


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def module_for_view(view_class) -> str | None:
    """The module a view declares for itself, or None.

    Read before any rule in this file so the existing ``required_module``
    markers stay the single source of truth for the views that carry one.
    """
    return getattr(view_class, 'required_module', None) if view_class else None


def module_for_route(namespace: str | None, url_name: str | None) -> str | None:
    """The module owning this route by name, or None for the base product.

    Namespace ownership loses to an explicit name rule, so a module can carve
    routes out of a base namespace — ``question_automation`` owns
    ``homework:schedule_*`` while the rest of ``homework:`` stays base.
    """
    if not url_name:
        return None

    for module in REGISTRY.values():
        if url_name in module.route_names:
            return module.slug
        if any(url_name.startswith(p) for p in module.route_prefixes):
            return module.slug

    if namespace:
        for module in REGISTRY.values():
            if namespace in module.namespaces:
                return module.slug

    return None


def members_of(family: str) -> frozenset:
    """Every slug in *family*, or an empty set if no such family exists."""
    if not family:
        return frozenset()
    return frozenset(m.slug for m in REGISTRY.values() if m.family == family)


def satisfied_by(requirement: str | None) -> frozenset:
    """The slugs that satisfy *requirement* — the set to test entitlements against.

    *requirement* may be a module slug or a family name. A slug in a tier
    family expands to the whole family, because the tiers differ by allowance
    and not by which pages they open: a school on Enterprise must not be
    turned away from a route that happens to resolve to Starter.

    Anything unrecognised comes back as itself, so a caller passing a slug this
    registry has never heard of gets a denial rather than a silent allow.
    """
    if not requirement:
        return frozenset()

    module = REGISTRY.get(requirement)
    if module is not None and module.family:
        return members_of(module.family)

    family = members_of(requirement)
    if family:
        return family

    return frozenset({requirement})


def siblings_of(slug: str | None) -> frozenset:
    """The other tiers in *slug*'s family — the rows that must be retired.

    Empty for a module that stands alone, so a caller can apply this
    unconditionally. A family is pick-one: holding two tiers means being billed
    twice while only one takes effect, and which one takes effect depends on
    the resolver you happen to ask.
    """
    if not slug:
        return frozenset()
    module = REGISTRY.get(slug)
    if module is None or not module.family:
        return frozenset()
    return members_of(module.family) - {slug}


def module_for_view_module(view_module: str | None) -> str | None:
    """The module owning every view in this Python module, or None.

    Checked *after* the name rules so an explicit ``route_names`` entry can
    still carve a single route back out of a claimed file, and *before*
    :func:`is_base`, so a claimed file inside a base app is paid rather than
    silently free.
    """
    if not view_module:
        return None
    for module in REGISTRY.values():
        if view_module in module.view_modules:
            return module.slug
    return None


def module_for_api_basename(basename: str | None) -> str | None:
    """The module owning a DRF router basename, or None."""
    if not basename:
        return None
    for module in REGISTRY.values():
        if basename in module.api_basenames:
            return module.slug
    return None


def is_base(view_module: str | None, namespace: str | None) -> bool:
    """Whether an unclaimed route belongs to the declared base product."""
    if namespace and namespace in BASE_NAMESPACES:
        return True
    if view_module:
        return view_module.split('.')[0] in BASE_APPS
    return False


def slugs() -> frozenset:
    return frozenset(REGISTRY)


def enforced_by(kind: str) -> tuple:
    """Modules enforceable in a given way — ROUTE, API or SERVICE."""
    return tuple(m.slug for m in REGISTRY.values() if kind in m.enforcement)
