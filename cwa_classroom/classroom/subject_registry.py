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

    def pick_homework_items(self, classroom, selected_topic_ids, n: int,
                            question_type=None, exclude_content_ids=None) -> list[int]:
        """Return up to n content ids drawn from the selected topics.

        The plugin owns the selection strategy (stratified random, weighted,
        ...). Returns a list of pks into the plugin's own content table:
        ``maths.Question.id`` for maths, ``coding.CodingExercise.id`` for
        coding, etc. Empty list means "no content available".

        ``question_type`` optionally constrains selection to a single
        ``question_type`` value (e.g. 'write_code'); ``None`` means "any type".

        ``exclude_content_ids`` is an optional iterable of ids to leave out —
        used by the question-automation schedule (CPP-399) so a class does not
        get the same questions two weeks running. Selection is the plugin's
        job, so the exclusion belongs here rather than being applied to the
        returned list: filtering afterwards would hand back fewer than ``n``
        items even when the bank had plenty left. ``None`` (the default) is
        exactly the pre-CPP-399 behaviour, so every existing caller is
        unaffected.

        Callers that must have ``n`` items are responsible for topping up:
        excluding can legitimately empty a small bank, and the schedule
        generator re-asks without the exclusion rather than shipping a short
        set (see ``homework.schedule_services.pick_items_for_week``).
        """
        raise NotImplementedError

    def homework_question_type_choices(self) -> list:
        """Return ``[(value, label), ...]`` for the homework question-type filter.

        Empty list (the default) hides the filter for subjects that don't
        distinguish question types.
        """
        return []

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

    def answer_field_names(self, content_id) -> tuple:
        """The POST/draft field names that carry this item's answer.

        Used to work out how far through a paper a student is *without*
        grading anything — the progress-art panel on the take page needs the
        count, and a saved draft is just a flat ``{field_name: value}`` map.

        The default is the maths convention (``answer_<content_id>``), which is
        also what a new plugin should follow unless it has a reason not to.
        """
        return (f'answer_{content_id}',)

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

    # ------------------------------------------------------------------
    # BrainBuzz  (Phase 4)
    #
    # Plugins that want to appear in the BrainBuzz session-creation form
    # MUST set ``brainbuzz_subject_key`` to the string stored in
    # ``BrainBuzzSession.subject`` (e.g. ``'maths'``, ``'coding'``).
    # They SHOULD override ``brainbuzz_topic_choices()`` to return the
    # context dict the create-form template needs.
    # ------------------------------------------------------------------

    #: Key stored in ``BrainBuzzSession.subject``.  Empty string = opt out.
    brainbuzz_subject_key: str = ''

    def content_topic_names(self, content_ids) -> dict:
        """Map content id -> topic name, for the progress report breakdown.

        Bulk rather than one call per id: the breakdown covers every answer in
        a period, and a term report would otherwise issue a query per answer.

        Ids this plugin does not recognise are simply absent from the result —
        the caller decides what to call them. The default returns nothing, so a
        plugin with no topics degrades to "Unclassified" exactly as before
        rather than raising on a code path that renders a parent's report.
        """
        return {}

    def content_topic_paths(self, content_ids) -> dict:
        """Map content id -> ``(group, topic name)`` for the report breakdown.

        The group is the heading a reader would file the topic under — the
        curriculum strand in maths, the language in coding. It exists because
        the report's chart plots one bar per topic, and after the topic tree
        was tidied there were still ~29 sub-topics in a term: forty bars at 6pt
        is a wall, not a picture. So the chart plots groups and the table below
        keeps every sub-topic.

        Defaults to the plugin's topic names with no group, so a plugin that
        has no grouping to offer still charts exactly what it charted before
        rather than vanishing from the chart. Returning an empty group is the
        way to say "this topic is its own heading".
        """
        return {content_id: ('', name)
                for content_id, name in self.content_topic_names(content_ids).items()}

    def topic_content_counts(self, classroom, topic_ids, question_type=None,
                             exclude_content_ids=None) -> dict:
        """Map plugin topic id -> how many items this class could draw from it.

        The counterpart to ``pick_homework_items``: same pool, same class
        scoping, same ``question_type`` and ``exclude_content_ids`` filters —
        counted instead of sampled. It has to be the same filters or the number
        shown to a teacher would be a number the generator does not honour,
        which is worse than showing nothing.

        Used by the question-automation schedule to tell a teacher, while they
        are planning, whether a topic can actually cover the set size they
        asked for — rather than letting them find out weeks later when a set
        comes out padded with repeats.

        An item belongs to exactly one topic in both maths (``Question.topic``)
        and coding (``CodingExercise.topic_level``), so counts across topics do
        not overlap and a caller may sum them for a multi-topic week.

        Topics with no items are simply absent from the result.
        """
        return {}

    def topic_labels(self, topic_ids) -> dict:
        """Map plugin topic id -> human label, for ids from ``homework_topic_tree``.

        The inverse of the tree: the tree hands out selectable leaves, this
        turns a stored selection back into names. The question-automation
        schedule (CPP-399) stores raw plugin topic ids — the only shape that
        round-trips both maths ``Topic`` pks and coding ``TopicLevel`` pks —
        and needs their names to render a plan and to denormalise labels so a
        plan still reads correctly after a topic is renamed or deleted.

        Ids this plugin does not recognise are simply absent from the result,
        so the caller can tell a stale selection from a live one rather than
        being handed a plausible-looking blank.
        """
        return {}

    def practice_section(self, student, begin, finish):
        """Practice this subject's students did OUTSIDE homework, in a window.

        Maths has had this since CPP-388 as times tables and basic facts, read
        directly by the report. Every other subject was invisible: a student
        who spent a week on coding exercises got a report saying they had done
        nothing, which is the exact complaint that added the maths strands.

        Return ``None`` (the default) when a subject has no practice of its own
        — the report then omits the section rather than showing an empty one.
        Otherwise return::

            {'label': str, 'items': int, 'attempts': int,
             'avg_first_pct': int, 'avg_best_pct': int,
             'improvement_pct': int, 'rows': [...]}

        where each row is ``{name, attempts, first_pct, best_pct, gain_pct}``.
        """
        return None

    def brainbuzz_topic_choices(self) -> dict:
        """Context variables injected into the BrainBuzz create-form template.

        Shape is plugin-specific (e.g. maths returns ``maths_topics`` and
        ``maths_levels``; coding returns ``coding_topic_levels``). The dict
        is merged directly into the view context, so key names must not
        clash across plugins.  Default: empty dict (opt-out).
        """
        return {}

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


def brainbuzz_plugins() -> list[SubjectPlugin]:
    """Return every registered plugin that participates in BrainBuzz sessions."""
    return [p for p in all_plugins() if p.brainbuzz_subject_key]


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
