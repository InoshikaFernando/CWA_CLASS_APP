"""Ask whether a feature is on, without a query per call.

The public surface is one function:

    from ops.flags import feature_enabled

    if feature_enabled('language', school):
        ...

and one template filter (``ops/templatetags/feature_tags.py``).

Three rules worth knowing before you use it:

**Unknown slugs are off.** A flag that has no row — because the migration has
not run yet, or the slug was mistyped — reads False. Failing open would mean a
typo silently shipped unfinished code to every customer, which is exactly the
accident flags exist to prevent. The miss is logged once per slug so a typo
surfaces rather than sitting there quietly doing nothing.

**A missing table is off too.** Checks can run before the migration has been
applied — a health check on a half-deployed box, a data migration that imports
app code — and the answer there must be "no", never an exception that takes a
request down.

**Environment variables win over the database.** ``FEATURE_FLAGS_OFF`` is the
emergency brake: a comma-separated slug list that forces those features off no
matter what the row says. For when production needs a feature dark right now
and a DB round trip is not the path you want to be on.
"""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Long enough that a page of checks is one query, short enough that flipping a
#: flag in the admin is visible without anyone restarting anything. Flags are
#: read constantly and written about once a week.
CACHE_KEY = 'ops:feature_flags:v1'
CACHE_SECONDS = 30

_warned_unknown = set()


def _forced_off():
    raw = getattr(settings, 'FEATURE_FLAGS_OFF', '') or ''
    return {s.strip() for s in raw.split(',') if s.strip()}


def _load():
    """``{slug: (rollout, {school_id, ...})}`` for every flag, in one query pair."""
    from .models import FeatureFlag

    flags = {}
    try:
        for flag in FeatureFlag.objects.prefetch_related('schools'):
            flags[flag.slug] = (
                flag.rollout,
                {s.pk for s in flag.schools.all()},
            )
    except Exception:  # noqa: BLE001 — a missing table must read as "off"
        logger.warning('feature flags unreadable — treating every flag as off',
                       exc_info=True)
        return {}
    return flags


def all_flags(use_cache=True):
    if not use_cache:
        return _load()
    flags = cache.get(CACHE_KEY)
    if flags is None:
        flags = _load()
        cache.set(CACHE_KEY, flags, CACHE_SECONDS)
    return flags


def invalidate():
    """Drop the cache. Called when a flag is saved, so the admin feels instant."""
    cache.delete(CACHE_KEY)


def feature_enabled(slug, school=None, use_cache=True):
    """Is ``slug`` on for ``school``? Unknown or unreadable means no."""
    if slug in _forced_off():
        return False

    flags = all_flags(use_cache=use_cache)
    entry = flags.get(slug)
    if entry is None:
        if slug not in _warned_unknown:
            _warned_unknown.add(slug)
            logger.warning(
                'feature_enabled("%s") — no such flag, treating as OFF. '
                'Create it in the admin, or fix the slug.', slug,
            )
        return False

    rollout, school_ids = entry
    from .models import FeatureFlag
    if rollout == FeatureFlag.ON:
        return True
    if rollout != FeatureFlag.PILOT or school is None:
        return False
    return getattr(school, 'pk', school) in school_ids
