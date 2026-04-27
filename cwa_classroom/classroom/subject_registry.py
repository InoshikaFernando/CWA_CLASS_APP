"""
Subject plugin registry — single source of truth for subject-aware behavior.

Phase 1 goal: stop hard-coding `mathematics`, `coding`, `coding_problem` across
the codebase. Every subject registers one ``SubjectPlugin`` at app-ready time;
cross-cutting code (upload, homework, dashboards) reads the registry instead
of branching on slug strings.

Phase 1 surface:
  - ``upload_parser()``            replaces classroom.upload_services._PARSERS
  - ``display_name`` / ``order``   replaces classroom.upload_services.AVAILABLE_SUBJECTS

Later phases will add ``topics_with_content``, ``pick_items``,
``render_attempt_url``, ``grade`` etc. — extending the same registry without
touching the call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .upload_services import BaseQuestionParser


class SubjectPlugin:
    """Base class — one concrete subclass per subject.

    ``slug`` is the only binding to the database: it matches
    ``classroom.Subject.slug`` for subjects that have a global Subject row
    (Mathematics, Coding). Plugins that don't map to a global Subject
    (e.g. the ``coding_problem`` variant, which writes to the same coding
    app but via a different parser) still have a unique slug used as a
    routing key in the upload form.
    """

    slug: str = ''
    display_name: str = ''
    order: int = 100
    supports_homework: bool = False

    # ------------------------------------------------------------------
    # Upload  (Phase 1)
    # ------------------------------------------------------------------

    def upload_parser(self) -> 'BaseQuestionParser':
        """Return the parser that processes this subject's upload files."""
        raise NotImplementedError(
            f'{type(self).__name__} must implement upload_parser()'
        )

    # ------------------------------------------------------------------
    # Homework  (Phase 2)
    #
    # Plugins with ``supports_homework=True`` MUST implement every method in
    # this block. Plugins with ``supports_homework=False`` won't be called
    # by the homework flow, so they can leave these as the stubs below.
    # ------------------------------------------------------------------

    def homework_topic_tree(self, classroom) -> list:
        """Return the topic selector used on the teacher-create page.

        Shape: ``[(strand, [(mid, [leaf, ...]), ...]), ...]`` — the same
        3-level grouping the existing template expects. Each strand/mid/leaf
        must have ``.pk`` and ``.name`` attributes; ``leaves`` may be empty.
        """
        raise NotImplementedError

    def homework_topic_field_name(self) -> str:
        """Name of the POST field that carries selected topic ids.

        Default is ``'topics'`` (matches the maths M2M field on Homework).
        Coding uses ``'coding_topics'``.
        """
        return 'topics'

    def pick_homework_items(self, classroom, selected_topic_ids, n: int) -> list[int]:
        """Return up to n content ids drawn from the selected topics.

        The plugin owns the selection strategy (stratified random, weighted,
        ...). Returns a list of pks into the plugin's own content table:
        ``maths.Question.id`` for maths, ``coding.CodingExercise.id`` for
        coding, etc. Empty list means "no content available".
        """
        raise NotImplementedError

    def save_homework_topics(self, homework, selected_topic_ids) -> None:
        """Persist the selected topics onto the homework.

        Default implementation writes to ``homework.topics`` (maths M2M).
        Plugins for other subjects override to write their own M2M.
        """
        from classroom.models import Topic
        homework.topics.set(Topic.objects.filter(pk__in=selected_topic_ids))

    def take_item_template(self) -> str:
        """Template partial path for rendering one item on the student take page."""
        raise NotImplementedError

    def take_item_context(self, content_id) -> dict:
        """Context dict for ``take_item_template`` given a content_id."""
        raise NotImplementedError

    def grade_answer(self, content_id, post_data) -> dict:
        """Grade a student's answer and return the fields to persist.

        Returns a dict that will be merged into ``HomeworkStudentAnswer``.
        Expected keys::

            {
                'is_correct': bool,
                'points_earned': float,
                'text_answer': str,                 # optional legacy echo
                'selected_answer_id': int | None,   # optional legacy echo
                'answer_data': dict,                # plugin-specific blob
            }
        """
        raise NotImplementedError

    def result_item_template(self) -> str:
        """Template partial path for one answer-review block on the result page."""
        raise NotImplementedError

    def result_item_context(self, answer) -> dict:
        """Context dict for ``result_item_template`` given a HomeworkStudentAnswer."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # UI / routing  (Phase 3)
    #
    # Phase 3 replaces the hard-coded subject branches in the request
    # context processor and template-level sidebar selection. Plugins
    # declare which URL prefixes belong to them and which sidebar partial
    # to render when the user is browsing the subject.
    # ------------------------------------------------------------------

    #: Path prefixes that identify this subject at the URL level. The
    #: context processor iterates registered plugins and picks the first
    #: whose prefix matches ``request.path``. Keep prefixes ending in ``/``.
    url_prefixes: tuple[str, ...] = ()

    def sidebar_template(self) -> str | None:
        """Return the sidebar partial to include for this subject.

        None means "use the default (role-based) sidebar" — appropriate for
        subjects that don't have their own subject hub (e.g. Coding Problems
        which is just an upload variant).
        """
        return None

    def has_content(self, classroom=None) -> bool:
        """Return True when this subject has any student-facing content.

        Used by the context processor + landing pages to decide whether to
        show quiz / start-learning CTAs. ``classroom=None`` means "check
        globally". Default: True (plugins override when content is gated).
        """
        return True

    def classroom_subject_id(self) -> int | None:
        """Return the pk of the global ``classroom.Subject`` row this plugin
        binds to, or ``None`` if the plugin has no backing Subject row."""
        from classroom.models import Subject
        return (
            Subject.objects.filter(slug=self.slug, school__isnull=True)
            .values_list('id', flat=True)
            .first()
        )

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f'<{type(self).__name__} slug={self.slug!r}>'


# ──────────────────────────────────────────────────────────────────────────────
# Module-level registry
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, SubjectPlugin] = {}


def register(plugin: SubjectPlugin) -> None:
    """Add a plugin to the registry.

    Safe to call multiple times with the same slug — later calls replace
    earlier ones.  That makes app reload (runserver, test worker respawn)
    resilient.
    """
    if not plugin.slug:
        raise ValueError(f'{plugin!r} is missing a slug')
    _REGISTRY[plugin.slug] = plugin


def unregister(slug: str) -> None:
    """Remove a plugin — primarily for tests."""
    _REGISTRY.pop(slug, None)


def get(slug: str) -> SubjectPlugin | None:
    """Return the plugin for *slug*, or None if unknown."""
    return _REGISTRY.get(slug)


def all_plugins() -> list[SubjectPlugin]:
    """Return every registered plugin, sorted by (order, slug)."""
    return sorted(_REGISTRY.values(), key=lambda p: (p.order, p.slug))


def slugs() -> Iterable[str]:
    """Return the registered slugs, in display order."""
    return [p.slug for p in all_plugins()]


# ──────────────────────────────────────────────────────────────────────────────
# Upload helpers  (Phase 1 — used by classroom.upload_services)
# ──────────────────────────────────────────────────────────────────────────────

def available_subjects() -> list[dict]:
    """Return ``[{slug, name}, ...]`` for the upload-form subject selector."""
    return [{'slug': p.slug, 'name': p.display_name} for p in all_plugins()]


def get_upload_parser(slug: str) -> 'BaseQuestionParser | None':
    """Return the upload parser for *slug*, or None if unknown.

    Drop-in replacement for the removed ``_PARSERS`` dict lookup.
    """
    plugin = get(slug)
    if plugin is None:
        return None
    return plugin.upload_parser()


# ──────────────────────────────────────────────────────────────────────────────
# Homework helpers  (Phase 2 — used by homework views)
# ──────────────────────────────────────────────────────────────────────────────

def homework_plugins() -> list[SubjectPlugin]:
    """Return every registered plugin whose ``supports_homework`` is True."""
    return [p for p in all_plugins() if p.supports_homework]


def homework_subject_choices() -> list[tuple[str, str]]:
    """Return ``[(slug, display_name), ...]`` for the teacher create-form subject dropdown."""
    return [(p.slug, p.display_name) for p in homework_plugins()]


# ──────────────────────────────────────────────────────────────────────────────
# URL / sidebar helpers  (Phase 3 — used by classroom.context_processors)
# ──────────────────────────────────────────────────────────────────────────────

def plugin_for_path(path: str) -> SubjectPlugin | None:
    """Return the plugin whose ``url_prefixes`` match *path*, or None."""
    for plugin in all_plugins():
        for prefix in plugin.url_prefixes:
            if path.startswith(prefix):
                return plugin
    return None
